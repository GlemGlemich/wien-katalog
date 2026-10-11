"""Dependency-free research parsers for public HOFER/Lidl Nuxt catalogue HTML.

Both sites serialize server-rendered product data using Nuxt/devalue references.
Prices are taken from structured data, never guessed from text surrounding images.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin
from matching import retailer_identity


class _NuxtScript(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == '__NUXT_DATA__':
            self.capture = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.fragments.append(data)


def decode_nuxt(html):
    parser = _NuxtScript()
    parser.feed(html)
    if not parser.fragments:
        raise ValueError('No server-rendered Nuxt data found')
    flat = json.loads(''.join(parser.fragments))
    cache = {}

    def resolve(index):
        if index < 0:
            return None
        if index in cache:
            return cache[index]
        node = flat[index]
        if isinstance(node, dict):
            result = {}
            cache[index] = result
            result.update((key, resolve(value)) for key, value in node.items())
        elif isinstance(node, list):
            if node and isinstance(node[0], str):
                if node[0] in ('Reactive', 'ShallowReactive', 'Ref', 'ShallowRef', 'Date'):
                    result = resolve(node[1])
                elif node[0] == 'EmptyRef':
                    result = None
                elif node[0] in ('Set', 'Map'):
                    result = [resolve(value) for value in node[1:]]
                else:
                    result = node
                cache[index] = result
            else:
                result = []
                cache[index] = result
                result.extend(resolve(value) for value in node)
        else:
            result = node
            cache[index] = result
        return result

    return resolve(0)


def _objects(value):
    seen = set()
    def visit(node):
        if not isinstance(node, (dict, list)) or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, dict):
            yield node
            for child in node.values():
                yield from visit(child)
        else:
            for child in node:
                yield from visit(child)
    yield from visit(value)


def _money(text):
    if not text:
        return None
    match = re.search(r'([0-9]+(?:[. ][0-9]{3})*,[0-9]{2})', str(text))
    return float(match[1].replace('.', '').replace(' ', '').replace(',', '.')) if match else None


def _text(value):
    return unescape(re.sub(r'<[^>]+>', '', str(value or ''))).strip()


def _vienna_date(timestamp):
    if not isinstance(timestamp, (int, float)) or not timestamp:
        return None
    moment = datetime.fromtimestamp(timestamp, timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return moment.astimezone(ZoneInfo('Europe/Vienna')).date().isoformat()
    except (ImportError, KeyError):
        # Windows runtimes may lack the IANA database; Vienna uses EU DST.
        def last_sunday(month):
            day = datetime(moment.year, month, 31, 1, tzinfo=timezone.utc)
            return day - timedelta(days=(day.weekday() + 1) % 7)
        hours = 2 if last_sunday(3) <= moment < last_sunday(10) else 1
        return (moment + timedelta(hours=hours)).date().isoformat()


def parse_hofer(html):
    result = {}
    decoded = decode_nuxt(html)
    catalogue = decoded.get('pinia', {}).get('search', {}).get('searchResult', {}).get('data', decoded)
    for product in _objects(catalogue):
        if not ('sku' in product and 'name' in product and isinstance(product.get('price'), dict)):
            continue
        price = product['price']
        amount = price.get('amountRelevant')
        if not isinstance(amount, (int, float)):
            amount = price.get('amount')
        if not isinstance(amount, (int, float)) or amount <= 0:
            continue
        sku = str(product['sku'])
        slug = product.get('urlSlugText') or sku
        assets = product.get('assets') or []
        image = assets[0].get('url') if assets else None
        if image:
            image = image.replace('{width}', '480').replace('{slug}', slug)
        conditions = []
        if product.get('isRandomWeight'):
            conditions.append('Весовой товар; итоговая стоимость зависит от веса')
        if price.get('bottleDeposit'):
            conditions.append('Pfand: ' + str(price.get('bottleDepositDisplay') or price['bottleDeposit'] / 100))
        if price.get('additionalInfo'):
            conditions.append(_text(price['additionalInfo']))
        if product.get('onSaleDate'):
            conditions.append('Пока товар есть в наличии')
        result[sku] = {
            **retailer_identity(product, product.get('brandName')),
            'store': 'hofer', 'id': sku,
            'name': ' '.join(filter(None, [product.get('brandName'), product['name']])),
            'price': round(amount / 100, 2),
            'regular_price': _money(price.get('wasPriceDisplay')),
            'unit': product.get('sellingSize') or price.get('perUnitDisplay') or product.get('sellingUnitDisplay'),
            'unit_price_text': price.get('comparisonDisplay'),
            'image': image,
            'url': 'https://www.hofer.at/produkt/' + slug + '-' + sku,
            'valid_from': str(product['onSaleDate'])[:10] if product.get('onSaleDate') else None, 'valid_to': None,
            'conditions': conditions,
            'category': ', '.join(c.get('name', '') for c in product.get('categories') or []),
            'membership_required': False,
            'is_variable_weight': bool(product.get('isRandomWeight')),
        }
    return list(result.values())


def parse_lidl(html):
    result = {}
    decoded = decode_nuxt(html)
    for product in _objects(decoded.get('pinia', {}).get('useProductStore', {}).get('products', {})):
        if not ('productId' in product and 'fullTitle' in product and isinstance(product.get('price'), dict)):
            continue
        alternatives = []
        if isinstance(product['price'].get('price'), (int, float)):
            alternatives.append((product['price'], False, ''))
        for index, offer in enumerate(product.get('lidlPlus') or []):
            if isinstance(offer.get('price', {}).get('price'), (int, float)):
                alternatives.append((offer['price'], True, f'-plus-{index + 1}'))
        for price, loyalty, suffix in alternatives:
            amount = price['price']
            if amount <= 0:
                continue
            package = _text((price.get('basePrice') or {}).get('text'))
            discount = price.get('discount') or {}
            conditions = ['Lidl Plus'] if loyalty else []
            if re.search(r'\b(?:Ab|Bei)\s+\d', package, re.I):
                conditions.append(package.split('(')[0].strip())
            if 'gratis' in str(discount.get('discountText', '')).lower():
                conditions.append(_text(discount['discountText']))
            regular = price.get('oldPrice') or discount.get('deletedPrice')
            if discount.get('fromRecommendedPrice') or not isinstance(regular, (int, float)):
                regular = None
            identity = str(product['productId']) + suffix
            result[identity] = {
                **retailer_identity(product),
                'store': 'lidl', 'id': identity, 'name': product['fullTitle'],
                'price': round(amount, 2), 'regular_price': regular,
                'unit': package.split('(')[0].strip() or None,
                'unit_price_text': package or None,
                'image': product.get('image'),
                'url': urljoin('https://www.lidl.at', product.get('canonicalUrl') or product.get('canonicalPath') or ''),
                'valid_from': _vienna_date(product.get('storeStartDate')),
                'valid_to': _vienna_date(product.get('storeEndDate')),
                'conditions': conditions,
                'category': (product.get('keyfacts') or {}).get('wonCategoryPrimary'),
                'membership_required': loyalty,
            }
    merged = {}
    for row in result.values():
        key = row['id'].split('-plus-')[0]
        if not row['membership_required']:
            merged[key] = row
    for row in result.values():
        key = row['id'].split('-plus-')[0]
        if row['membership_required']:
            if key in merged:
                merged[key].setdefault('offers', []).append({'price': row['price'], 'conditions': row['conditions']})
            else:
                row['id'] = key
                merged[key] = row
    return list(merged.values())


def catalogue_info(html, store):
    data = decode_nuxt(html)
    if store == 'hofer':
        return data['pinia']['search']['searchResult']['meta']['pagination']
    if store == 'lidl':
        return {
            'totalCount': data['pinia']['useProductStore']['numFound'],
            **data['pinia']['useStorefrontConfigurationStore']['config'],
            'route': data['pinia']['useRouteStore'],
        }
    raise ValueError('Unknown store')


def parse_rewe(data, store):
    result = []
    base = 'https://shop.billa.at' if store == 'billa' else 'https://www.penny.at'
    for product in data['results']:
        prices = product.get('price') or {}
        current = prices.get('regular') or {}
        value = current.get('value')
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        conditions = []
        quantity = current.get('promotionQuantity') or 1
        if quantity > 1:
            conditions.append(current.get('promotionText') or f'От {quantity:g} шт., цена за одну')
        elif current.get('promotionText'):
            conditions.append(current['promotionText'])
        if product.get('bundleInfo'):
            conditions.append(_text(product['bundleInfo']))
        if product.get('weightArticle') or product.get('weightPieceArticle'):
            conditions.append('Весовой товар; итог зависит от веса')
        if prices.get('depositPrice'):
            conditions.append(f"+ Pfand {prices['depositPrice'] / 100:.2f} €")
        standard = (prices.get('standard') or {}).get('value')
        prior = standard or prices.get('crossed')
        unit_price = current.get('perStandardizedQuantity')
        base_unit = ' '.join(str(v) for v in [prices.get('basePriceFactor'), prices.get('baseUnitShort')] if v)
        row = {
            **retailer_identity(product),
            'store': store, 'id': product['sku'], 'name': product['name'],
            'price': value / 100, 'regular_price': prior / 100 if prior and prior != value else None,
            'single_price': standard / 100 if quantity > 1 and standard else None,
            'unit': ' '.join(str(v) for v in [product.get('amount'), product.get('volumeLabelShort')] if v),
            'unit_price_text': f'{unit_price / 100:.2f} € / {base_unit}' if unit_price else None,
            'category': product.get('category') or '',
            'category_path': ' · '.join(dict.fromkeys(category.get('name', '')
                              for branch in product.get('parentCategories') or [] for category in branch)),
            'image': (product.get('images') or [None])[0],
            'url': base + '/produkte/' + product['slug'],
            'valid_from': prices.get('validityStart'), 'valid_to': prices.get('validityEnd'),
            'conditions': conditions, 'membership_required': False, 'offers': [],
        }
        loyalty = prices.get('loyalty') or {}
        if loyalty.get('value'):
            terms = ['С картой jö']
            if loyalty.get('promotionText'):
                terms.append(loyalty['promotionText'])
            elif (loyalty.get('promotionQuantity') or 1) > 1:
                terms.append(f"От {loyalty['promotionQuantity']:g} шт.")
            row['offers'].append({'price': loyalty['value'] / 100, 'conditions': terms})
        result.append(row)
    return result


def parse_spar(data):
    result = []
    hits = data.get('hits', [])
    if isinstance(hits, dict):
        hits = hits.get('hits', [])
    for hit in hits:
        p = hit['masterValues']
        # `best-price` can be the kilogram price even when `price` is per 100 g.
        value = p.get('price')
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        ident = str(p['product-number'])
        slug = (p.get('url') or '').split('/p/')[0].strip('/')
        regular = p.get('regular-price')
        conditions = []
        if p.get('item-type') == 'WeightProduct':
            conditions.append('Весовой товар; цена за указанное количество')
        result.append({
            **retailer_identity(p, p.get('ecr-brand') or p.get('brand')),
            'store': 'spar', 'id': ident,
            'name': ' '.join(v for v in [p.get('title'), p.get('short-description-2') or p.get('short-description')] if v),
            'price': value, 'regular_price': regular if regular and regular != value else None,
            'unit': p.get('short-description-3') or p.get('additional-quantity') or '',
            'unit_price_text': p.get('price-per-unit'), 'image': p.get('image-url'),
            'url': 'https://www.spar.at/produktwelt/' + slug + '-p' + ident,
            'category': p.get('category-names', '').replace('|', ' · '),
            'valid_from': None, 'valid_to': None, 'conditions': conditions,
            'membership_required': False,
        })
    return result
