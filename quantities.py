"""Comparable catalogue prices and exact package sizes from retailer fields."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

QUANTITY_VERSION = 1
NUMBER = r'\d+(?:[.,]\d+)?'
MONEY = r'\d+(?:[.,]\d+)*'
UNIT = r'(?:kilogramm|kilogram|kilo|kg|gramm|gram|g|milliliter|ml|cl|liter|litre|l)\b'
FACTORS = {'kg':1,'kilo':1,'kilogramm':1,'kilogram':1,'g':.001,'gramm':.001,'gram':.001,
           'l':1,'liter':1,'litre':1,'ml':.001,'milliliter':.001,'cl':.01}


def clean(value):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(value or '')).casefold()).strip()


def number(value):
    if ',' in value and '.' in value:
        value=value.replace('.','')
    return Decimal(value.replace(',','.'))


def measure(amount, unit):
    # German catalogue labels use 3.000 ML for a 3-litre multipack;
    # decimals such as 0.275 liter and 0,036 g must remain fractional.
    if unit in ('g','gram','gramm','ml','milliliter') and re.fullmatch(r'[1-9]\d{0,2}(?:\.\d{3})+',amount):
        amount=amount.replace('.','')
    return number(amount)*Decimal(str(FACTORS[unit])), 'kg' if unit in ('kg','kilo','kilogram','kilogramm','g','gram','gramm') else 'l'


def package_size(text):
    text=re.sub(r'\([^)]*\)','',clean(text))
    # Ranges, alternate variants, approximate and combined sizes stay unknown.
    if re.search(r'\bca\.?\s|circa|ungefahr|ungefähr|approx|~|≈|\+|\d\s*(?:'+UNIT+r')?\s*(?:[/–—-]|bis|oder|und)\s*\d',text):
        return None
    matches=list(re.finditer(r'(?<![\w.,])((?:\d+\s*[x×]\s*)*)('+NUMBER+r')\s*('+UNIT+r')',text))
    if len(matches)!=1:
        return None
    match=matches[0]
    amount,unit=measure(match[2],match[3])
    for factor in re.findall(r'\d+',match[1]):
        amount*=int(factor)
    return (amount,unit) if amount>0 else None


def reference_price(text):
    """Retailer reference prices take priority, including drained-weight prices."""
    text=clean(text)
    patterns=[
        r'(?<![\d.,])(?P<price>'+MONEY+r')\s*€\s*/\s*(?P<amount>'+NUMBER+r')?\s*(?P<unit>'+UNIT+r')',
        r'€\s*(?P<price>'+MONEY+r')\s*/\s*(?P<amount>'+NUMBER+r')?\s*(?P<unit>'+UNIT+r')',
        r'(?<![\w.,])(?P<amount>'+NUMBER+r')\s*(?P<unit>'+UNIT+r')(?:\s+abtr\.?\s*g\.?)?\s*=\s*€?\s*(?P<price>'+MONEY+r')',
    ]
    values=set()
    for pattern in patterns:
        for match in re.finditer(pattern,text):
            if re.match(r'\s*[/–—-]\s*\d',text[match.end():]):
                return None
            try:
                amount,unit=measure(match['amount'] or '1',match['unit'])
                price=number(match['price'])
                if amount>0 and price>0:
                    values.add((price/amount,unit))
            except (InvalidOperation,ZeroDivisionError):
                continue
    return next(iter(values)) if len(values)==1 else None


def size_label(key):
    if key=='variable': return 'Весовые товары'
    if key=='unknown': return 'Вес / объём не указан'
    unit,raw=key.split(':')
    amount=Decimal(raw)
    suffix='г' if unit=='kg' else 'мл'
    if amount>=1000:
        amount/=1000
        suffix='кг' if unit=='kg' else 'л'
    return format(amount.normalize(),'f').replace('.',',')+' '+suffix


def product_quantity(product):
    unit_text=clean(product.get('unit'))
    conditions=clean(' '.join(product.get('conditions') or []))
    variable=bool(product.get('is_variable_weight') or 'весовой' in conditions or
                  re.search(r'\bca\.?\s|circa|ungefahr|ungefähr|\blose\b|\b(?:per|pro|je)\s*(?:kg|kilo)\b|^kg$',unit_text))
    size=package_size(unit_text)
    key='variable' if variable else 'unknown'
    if size and not variable:
        amount,unit=size
        key=unit+':'+format((amount*1000).normalize(),'f')
    reference=reference_price(product.get('unit_price_text'))
    # An unparsed mass/volume reference may contain alternative prices. Do not
    # silently replace it with a different weight basis or an invented average.
    ambiguous_reference=bool(re.search(r'[/=]\s*\d*\s*(?:'+UNIT+r')|'+UNIT+r'\s*=',clean(product.get('unit_price_text'))))
    source='retailer' if reference else None
    if not reference and size and not variable and not ambiguous_reference:
        amount,unit=size
        price=number(str(product['price']))
        reference=(price/amount,unit)
        source='calculated'
    # A bare "per kg" is explicitly a price basis, not a fixed 1 kg pack.
    if not reference and re.fullmatch(r'(?:je|per|pro)\s*(?:kg|kilo)',unit_text):
        reference=(number(str(product['price'])),'kg')
        source='calculated'
    return {'unit_price':round(float(reference[0]),6) if reference else None,
            'measure':reference[1] if reference else None,'source':source,
            'size_key':key,'size_label':size_label(key),'variable_weight':variable}
