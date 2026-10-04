"""Normalisation and arithmetic for prices printed in a leaflet."""
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

from categories import classify

DRINKS = [('all', 'Все напитки'), ('cola', 'Кола'), ('soft', 'Лимонады и сладкие напитки'),
          ('juice', 'Соки и нектары'), ('energy', 'Энергетики'), ('water', 'Вода'),
          ('syrup', 'Сиропы'), ('alcohol', 'Алкоголь')]


def clean(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text).replace('\xad', '')).strip()


def cents(value):
    return int((Decimal(str(value).replace(',', '.')) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def drink_kind(name):
    text = clean(name).casefold()
    if re.search(r'sirup', text):
        return 'syrup'
    if re.search(r'cola|pepsi|coke', text):
        return 'cola'
    if re.search(r'\bsaft\b|\bsäfte\b|nektar|happy day|smoothie|multivitamin', text):
        return 'juice'
    if re.search(r'red bull|energy|energydrink|nocco|monster', text):
        return 'energy'
    if re.search(r'limonad|fanta|sprite|schweppes|almdudler|eistee|flavours|vitaminwasser|vitamin well|vitamingetränk|sportgetränk|dreh.*trink|fruchtsaftgetränk', text):
        return 'soft'
    if re.search(r'mineralwasser|quellwasser|sodawasser', text):
        return 'water'
    if re.search(r'\bbier\b|märzen|wieselburger|gösser|heineken|desperados|stiegl|budweiser|zwettler|ottakringer|kozel|prosecco|riesling|ouzo|\bwein\b|veltliner|\bsekt\b|vodka|wodka|whisk|campari|aperol|\bgin\b|ramazzotti|tullamore|gurktaler|frizzante', text):
        return 'alcohol'
    return ''


def measure(text):
    """Only an unambiguous package size; ranges and mixed sizes stay unranked."""
    text = clean(text)
    # Parentheses contain reference prices, not package sizes.
    size_text = re.sub(r'\([^)]*\)', '', text)
    size_text = re.sub(r'(?:zzgl\.?\s*)?Pfand\s*(?:€\s*)?\d+[.,]\d{2}', '', size_text, flags=re.I)
    size_text = re.split(r'\b(?:1\s*(?:kg|l|Liter)\s*=|Mit Lidl Plus|Preis exkl|Einzeln)', size_text, flags=re.I)[0]
    if re.search(r'\d\s*(?:[/–—-]|bis)\s*\d', size_text):
        return None, None, size_text.strip()
    pattern = r'(?<![\w.,])(\d+(?:[.,]\d+)?)\s*[- ]?\s*(ml|cl|Liter|liter|l\b|kg\b|Kilo\b|g\b)'
    matches = list(re.finditer(pattern, size_text))
    # More than one distinct size means that variants cannot safely share a unit price.
    amounts = []
    for m in matches:
        number = Decimal(m[1].replace(',', '.'))
        u = m[2].lower()
        factor = Decimal('0.001') if u in ('ml', 'g') else Decimal('0.01') if u == 'cl' else Decimal(1)
        unit = 'kg' if u in ('kg', 'g', 'kilo') else 'l'
        prefix = size_text[max(0, m.start()-20):m.start()]
        multi = re.search(r'(\d+)\s*[x×]\s*$', prefix)
        amount = number * factor * (int(multi[1]) if multi else 1)
        amounts.append((amount, unit, m.group(0)))
    unique = {(v, u) for v, u, _ in amounts}
    if len(unique) == 1 and not re.search(r'\bca\.', size_text):
        amount, unit, label = amounts[0]
        # A crate offer quotes the bottle volume separately from bottles per crate.
        crate = re.search(r'(?:1\s*Kiste\s*=\s*|\b)(\d+)\s*(?:Flaschen|er[- ]Kiste)', size_text, re.I)
        if crate and unit == 'l':
            amount *= int(crate[1])
        return float(amount), unit, size_text.strip()
    if not amounts and re.search(r'per\s+(?:kg|Kilo)', size_text, re.I):
        return 1.0, 'kg', size_text.strip()
    if not amounts and re.search(r'100\s*g', size_text, re.I):
        return .1, 'kg', size_text.strip()
    return None, None, size_text.strip()


def calculate(price_cents, minimum=1, *, basis='discounted_each', paid=None, received=None, amount=None, unit=None):
    """A printed 'bei 6 je' price already includes the discount: never divide again."""
    if not isinstance(price_cents, int) or price_cents <= 0 or minimum < 1:
        raise ValueError('Некорректная цена или количество')
    if basis == 'single_before_free':
        if not paid or not received or received <= paid:
            raise ValueError('Неизвестны условия бесплатных товаров')
        minimum = received
        total = price_cents * paid
        effective = Decimal(total) / received
    elif basis == 'discounted_each':
        total, effective = price_cents * minimum, Decimal(price_cents)
    else:
        raise ValueError('Неизвестно, к какому количеству относится цена')
    comparable = bool(amount and amount > 0 and unit in ('l', 'kg'))
    return {'min_quantity': minimum, 'total_cents': total, 'effective_cents': float(effective),
            'unit_price': float(effective / 100 / Decimal(str(amount))) if comparable else None,
            'measure': unit if comparable else None, 'amount': amount if comparable else None}


def make_offer(*, store, flyer, page, name, price, size, promo='', minimum=1,
               member=False, start=None, end=None, evidence='', source_url='', confidence='parsed'):
    name = clean(name)
    name = re.sub(r'\b(?:div\.|versch\.|verschiedene)\s*Sorten\b', '', name, flags=re.I).strip(' ,')
    if len(name) < 3 or len(name) > 240:
        raise ValueError('Не удалось отделить название товара')
    amount, unit, _ = measure(size)
    kind = drink_kind(name) if unit == 'l' else ''
    group = 'drinks' if kind else classify({'name': name, 'category': ''})
    if group == 'alcohol':
        group = 'drinks'
    rule = re.search(r'(\d+)\s*\+\s*(\d+)', promo)
    deal = f'{rule[1]}+{rule[2]}' if rule else (f'От {minimum} шт.' if minimum > 1 else 'Цена из флюгблатта')
    if rule and minimum != int(rule[1]) + int(rule[2]):
        raise ValueError('Количество не соответствует условию акции')
    arithmetic = calculate(price, minimum, amount=amount, unit=unit)
    return {'store': store, 'flyer_id': flyer['id'], 'flyer_url': flyer['url'], 'page': page,
            'source_url': source_url or flyer['url'].rstrip('/') + '/page/' + str(page),
            'name': name, 'price_cents': price, 'size': clean(size), 'deal': deal,
            'promo_original': clean(promo), 'membership_required': member,
            'membership_label': {'lidl': 'Lidl Plus', 'spar': 'SPAR-App', 'billa': 'jö', 'penny': 'PENNY / jö', 'hofer': 'Купон'}.get(store, 'Карта / купон') if member else '',
            'valid_from': start or flyer['valid_from'], 'valid_to': end or flyer['valid_to'],
            'group_id': group, 'drink_kind': kind, 'evidence': clean(evidence)[:1800],
            'loose_weight': bool(re.search(r'per\s*(?:\d+\s*g|Kilo|kg)',re.sub(r'\([^)]*\)','',size),re.I)),
            'confidence': confidence, 'excludes_sunday': store == 'billa', **arithmetic}


ALIASES = {'кола': 'cola', 'кока': 'coca', 'пепси': 'pepsi', 'фанта': 'fanta',
           'сок': 'juice', 'соки': 'juice', 'нектар': 'juice', 'лимонад': 'soft',
           'напитки': 'drinks', 'напиток': 'drinks', 'молоко': 'milch', 'яйца': 'eier',
           'сыр': 'käse', 'шоколад': 'schokolade', 'вода': 'water', 'пиво': 'bier'}


def search_tokens(query):
    query = clean(query).casefold().replace('сладкие напитки','soft')
    return [ALIASES.get(word, word) for word in query.split()]


def matches(row, query):
    text = clean(row['name'] + ' ' + row.get('size', '')).casefold()
    for token in search_tokens(query):
        if token in ('juice', 'soft', 'water'):
            if row.get('drink_kind') != token:
                return False
        elif token == 'drinks':
            if row.get('group_id') != 'drinks':
                return False
        elif token == 'cola':
            if row.get('drink_kind') != 'cola':
                return False
        elif token not in text:
            return False
    return True
