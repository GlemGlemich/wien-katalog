"""Shopping-list estimates from saved catalogue prices, without retailer requests."""
import itertools
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP

from quantities import package_size
from sources import STORES

MAX_ITEMS = 30


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).casefold())
                   if not unicodedata.combining(c)).strip()


def decimal(value):
    if isinstance(value, bool):
        raise ValueError('Invalid quantity')
    try:
        result = Decimal(str(value).replace(',', '.'))
    except InvalidOperation as error:
        raise ValueError('Invalid quantity') from error
    if not result.is_finite() or not 0 < result <= 10000:
        raise ValueError('Invalid quantity')
    return result


def validate_items(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ITEMS:
        raise ValueError('Invalid shopping list')
    result, ids = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError('Invalid item')
        ident, query = entry.get('id'), entry.get('query')
        unit = entry.get('unit')
        if not isinstance(ident, str) or not 1 <= len(ident) <= 80 or ident in ids:
            raise ValueError('Invalid item ID')
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 160:
            raise ValueError('Invalid product search')
        if unit not in ('pack', 'kg', 'l', 'pcs'):
            raise ValueError('Invalid unit')
        amount = decimal(entry.get('amount'))
        if amount < Decimal('.001') or (unit in ('pack', 'pcs') and amount != amount.to_integral_value()):
            raise ValueError('Invalid quantity')
        product = entry.get('product')
        if product is not None:
            if not isinstance(product, dict) or product.get('store') not in STORES or not isinstance(product.get('id'), str) or not 1 <= len(product['id']) <= 240:
                raise ValueError('Invalid product reference')
            product = {key: product[key] for key in ('store', 'id')}
        result.append({'id': ident, 'query': query.strip(), 'unit': unit,
                       'amount': float(amount), 'product': product})
        ids.add(ident)
    return result


def criteria(query):
    """Known generic foods use existing classification; other searches use names."""
    query = normalized(query)
    presets = {
        'milk': ('milk', ''), 'milch': ('milk', ''), 'молоко': ('milk', ''),
        'lactose-free milk': ('milk_free', ''), 'laktosefreie milch': ('milk_free', ''),
        'молоко без лактозы': ('milk_free', ''), 'безлактозное молоко': ('milk_free', ''),
        'яйца': ('eggs', ''), 'eggs': ('eggs', ''), 'eier': ('eggs', ''),
        'кола': ('cola', ''), 'cola': ('cola', ''), 'кола зеро': ('cola', 'zero'),
        'cola zero': ('cola', 'zero'),
        'куриное филе': ('chicken', 'filet'), 'chicken fillet': ('chicken', 'filet'),
    }
    return {normalized(key): value for key, value in presets.items()}.get(query, ('search', query))


def candidates(db, item, today):
    where = ['active=1', '(valid_from IS NULL OR valid_from<=?)', '(valid_to IS NULL OR valid_to>=?)']
    args = [today, today]
    kind, query = criteria(item['query'])
    if item['product']:
        where += ['store=?', 'id=?']
        args += [item['product']['store'], item['product']['id']]
        kind, query = 'exact', ''
    elif kind.startswith('milk'):
        where += ["(selection_flags & 4) != 0", "json_extract(details,'$.milk_kind')='plain'"]
        if kind == 'milk_free':
            where += ["json_extract(details,'$.milk_lactose')='free'"]
    elif kind == 'eggs':
        where += ["group_id='dairy'", "search LIKE '%eier%'"]
    elif kind == 'cola':
        where += ["group_id='drinks'", "search LIKE '%cola%'"]
    elif kind == 'chicken':
        where += ["json_extract(details,'$.meat_kind')='chicken'", "json_extract(details,'$.meat_form')='cuts'"]
    if query:
        # Search SQL narrows candidates; the name-only check below avoids
        # matching a broad department that merely mentions the search term.
        for word in query.split():
            where.append("search LIKE ? ESCAPE '\\'")
            args.append('%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    for row in db.execute('SELECT payload,quantity,checked_at FROM products WHERE ' + ' AND '.join(where), args):
        product = json.loads(row['payload'])
        name = normalized(product['name'])
        if query and any(word not in name for word in query.split()):
            continue
        if kind == 'eggs' and (not re.search(r'eier\b', name) or re.search(r'salat|aufstrich|nudel|likor|schoko|pulver|farb|mayonnaise', name)):
            continue
        if kind == 'cola' and (not re.search(r'\bcola\b', name) or 'sirup' in name):
            continue
        yield product, json.loads(row['quantity']), row['checked_at']


def price_options(product):
    """Only explicit quantity rules are calculated. Unknown terms need review."""
    if product.get('membership_required'):
        return []
    conditions = product.get('conditions') or []
    minimum, multiple, uncertain = 1, 1, False
    for condition in conditions:
        text = normalized(condition)
        if re.search(r'lidl plus|\bjo\b|jö|купон|карт|coupon|gutschein|app|treue|mitglied', text):
            return []
        rule = re.fullmatch(r'(\d+)\s*\+\s*(\d+)\s*(?:gratis|kostenlos)?', text)
        threshold = re.fullmatch(r'(?:ab|bei|от)\s+(\d+)\s*(?:stk\.?|stuck|stuck\.|шт\.?|packungen?)(?:\s*(?:je|, цена за одну))?', text)
        if rule:
            multiple = int(rule[1]) + int(rule[2])
            minimum = max(minimum, multiple)
        elif threshold:
            minimum = max(minimum, int(threshold[1]))
        elif (not text or re.match(r'^\+?\s*pfand\b', text)
              or text in ('пока товар есть в наличии', 'solange der vorrat reicht')
              or text.startswith(normalized('весовой товар'))
              or re.fullmatch(r'-?\d+\s*%\s*(?:billiger|rabatt)?', text)
              or (re.fullmatch(r'je\s+[\d.,x×\s]+(?:g|kg|ml|l|liter)', text))):
            continue
        else:
            uncertain = True
    options = []
    # An explicit single price is valid even when the bulk rule is ambiguous.
    if product.get('single_price'):
        options.append((decimal(product['single_price']), 1, 1, True))
        if minimum == 1:
            uncertain = True
    if not uncertain and minimum <= 1000 and 1 <= multiple <= 1000:
        options.append((decimal(product['price']), minimum, multiple, False))
    return options


def pieces(unit):
    match = re.fullmatch(r'\s*(\d+)\s*(?:stk\.?|stuck|stuck\.|pieces?|pcs\.?|шт\.?)(?:\s*)', normalized(unit))
    return Decimal(match[1]) if match and int(match[1]) > 0 else None


def quote(product, quantity, checked_at, item):
    wanted = decimal(item['amount'])
    unit = item['unit']
    options = price_options(product)
    if not options:
        return None
    variable = quantity.get('variable_weight', False)
    size = package_size(product.get('unit'))
    pack_amount = None
    if unit == 'pack' and not variable:
        pack_amount = Decimal(1)
    elif unit == 'pcs' and not variable:
        pack_amount = pieces(product.get('unit', ''))
    elif size and not variable and size[1] == unit:
        pack_amount = size[0]
    possible = []
    for price, minimum, multiple, single in options:
        if variable:
            if unit != 'kg' or quantity.get('measure') != 'kg' or not quantity.get('unit_price') or minimum != 1 or single:
                continue
            cost = decimal(quantity['unit_price']) * wanted
            bought, packs = wanted, None
        elif pack_amount:
            packs = max(int((wanted / pack_amount).to_integral_value(rounding=ROUND_CEILING)), minimum)
            packs = ((packs + multiple - 1) // multiple) * multiple
            cost, bought = price * packs, pack_amount * packs
        else:
            continue
        possible.append({'cost_cents': int((cost * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
                         'packs': packs, 'bought': float(bought), 'single_price': single})
    if not possible:
        return None
    best = min(possible, key=lambda option: (option['cost_cents'], option['bought']))
    return {**best, 'store': product['store'], 'id': str(product['id']), 'name': product['name'],
            'unit': product.get('unit') or '', 'url': product.get('url') or '',
            'checked_at': checked_at, 'variable': variable, 'conditions': product.get('conditions') or [],
            'valid_from': product.get('valid_from'), 'valid_to': product.get('valid_to')}


def calculate(db, raw_items, today):
    items = validate_items(raw_items)
    choices, stats = {}, {}
    for item in items:
        cheapest, matched, excluded = {}, 0, 0
        for product, quantity, stamp in candidates(db, item, today):
            matched += 1
            try:
                candidate = quote(product, quantity, stamp, item)
            except (ValueError, InvalidOperation, TypeError):
                candidate = None
            if candidate is None:
                excluded += 1
                continue
            previous = cheapest.get(candidate['store'])
            if previous is None or (candidate['cost_cents'], candidate['bought'], candidate['id']) < (previous['cost_cents'], previous['bought'], previous['id']):
                cheapest[candidate['store']] = candidate
        choices[item['id']] = cheapest
        stats[item['id']] = {'matched': matched, 'excluded': excluded}

    def plan(stores):
        lines, subtotal, used = [], 0, set()
        for item in items:
            available = [choices[item['id']][store] for store in stores if store in choices[item['id']]]
            chosen = min(available, key=lambda option: (option['cost_cents'], option['bought'], option['store'])) if available else None
            if chosen:
                subtotal += chosen['cost_cents']
                used.add(chosen['store'])
            lines.append({'item_id': item['id'], 'choice': chosen})
        covered = sum(line['choice'] is not None for line in lines)
        return {'stores': list(stores), 'used_stores': sorted(used), 'lines': lines,
                'covered': covered, 'complete': covered == len(items), 'subtotal_cents': subtotal,
                'total_cents': subtotal if covered == len(items) else None}

    singles = [plan((store,)) for store in STORES]
    plans = singles + [plan(pair) for pair in itertools.combinations(STORES, 2)]
    rank = lambda p: (p['subtotal_cents'], len(p['used_stores']), p['stores'])
    best_single = min((p for p in singles if p['complete']), key=rank, default=None)
    best_two = min((p for p in plans if p['complete']), key=rank, default=None)
    return {'today': today, 'items': [{**item, **stats[item['id']]} for item in items],
            'stores': sorted(singles, key=lambda p: (not p['complete'], -p['covered'], p['subtotal_cents'], p['stores'])),
            'best_single': best_single, 'best_two': best_two,
            'saving_cents': best_single['total_cents'] - best_two['total_cents'] if best_single and best_two else None}
