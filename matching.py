"""Local product matching. Store SKUs and similar names never prove identity."""
import json
import re
import unicodedata

VERSION = '1'
GTIN_FIELDS = ('gtin', 'gtin8', 'gtin12', 'gtin13', 'gtin14', 'ean', 'ean13', 'barcode', 'gtins')
STOP_WORDS = set('und mit ohne der die das fur von im in je ab bei pack packung flasche dose stk stuck liter bio'.split())


def gtin(value):
    # Reject numeric values: a source converting codes to numbers may lose zeros.
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not re.fullmatch(r'(?:[0-9]{8}|[0-9]{12,14})', value) or len(set(value)) == 1:
        return None
    if (sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(value[-2::-1])) + int(value[-1])) % 10:
        return None
    canonical = value.zfill(14)
    short = canonical.lstrip('0')
    if len(short) <= 8:
        if len(short) != 8 or short[0] == '2':
            return None
    else:
        # GS1 restricted-circulation prefixes are not cross-retailer identifiers.
        prefix = int(canonical[1:4])
        if 20 <= prefix <= 29 or 40 <= prefix <= 49 or 200 <= prefix <= 299 or canonical[1:8] == '0000000':
            return None
    return canonical


def codes(product):
    found = set()
    for key in GTIN_FIELDS:
        raw = product.get(key)
        for value in raw if isinstance(raw, list) else [raw]:
            code = gtin(value)
            if code:
                found.add(code)
    return sorted(found)


def retailer_identity(product, brand=None):
    """Copy only explicit identifiers of this item, never nested recommendations."""
    brand = brand if brand is not None else product.get('brand')
    if isinstance(brand, dict):
        brand = brand.get('name')
    if isinstance(brand, list):
        brand = brand[0] if len(brand) == 1 else None
    return {'brand': brand.strip() if isinstance(brand, str) else None, 'gtins': codes(product)}


def terms(product):
    text = unicodedata.normalize('NFKD', (str(product.get('brand') or '') + ' ' + str(product.get('name', ''))).casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c)).replace('ß', 'ss')
    # Remove pack sizes but retain distinguishing numbers such as fat percentage.
    text = re.sub(r'\b\d+(?:[.,]\d+)?\s*(?:kg|mg|g|ml|cl|dl|l|liter|stk|stuck)\b', ' ', text)
    return set(re.findall(r'[a-z0-9а-я]{2,}', text)) - STOP_WORDS


def index_products(db, products):
    for product in products:
        key = (product['store'], str(product['id']))
        db.execute('DELETE FROM product_match_terms WHERE store=? AND id=?', key)
        db.execute('DELETE FROM product_match_codes WHERE store=? AND id=?', key)
        db.executemany('INSERT INTO product_match_terms VALUES (?,?,?)',
                       [(*key, token) for token in sorted(terms(product))[:40]])
        # Multiple codes can refer to assorted variants: don't confirm any one.
        identifiers = codes(product)
        if len(identifiers) == 1:
            db.execute('INSERT INTO product_match_codes VALUES (?,?,?)', (*key, identifiers[0]))


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS product_match_terms (
        store TEXT NOT NULL, id TEXT NOT NULL, term TEXT NOT NULL, PRIMARY KEY(store,id,term));
      CREATE INDEX IF NOT EXISTS match_term ON product_match_terms(term,store,id);
      CREATE TABLE IF NOT EXISTS product_match_codes (
        store TEXT NOT NULL, id TEXT NOT NULL, gtin TEXT NOT NULL, PRIMARY KEY(store,id));
      CREATE INDEX IF NOT EXISTS match_code ON product_match_codes(gtin,store,id);
    ''')
    version = db.execute("SELECT value FROM app_meta WHERE key='matching_version'").fetchone()
    if not version or version[0] != VERSION:
        index_products(db, (json.loads(row['payload']) for row in db.execute('SELECT payload FROM products')))
        db.execute("INSERT OR REPLACE INTO app_meta VALUES ('matching_version',?)", (VERSION,))


def unpack(row):
    return {**json.loads(row['payload']), 'quantity': json.loads(row['quantity'])}


def size_relation(left, right):
    a, b = left['quantity'], right['quantity']
    if a.get('variable_weight') or b.get('variable_weight'):
        return 'unknown'
    keys = [a.get('size_key'), b.get('size_key')]
    if any(key in (None, '', 'unknown') for key in keys):
        return 'unknown'
    return 'same' if keys[0] == keys[1] else 'different'


def compare(db, store, ident, today, stores):
    if store not in stores or not ident or len(ident) > 200:
        raise ValueError('Invalid product reference')
    row = db.execute('SELECT * FROM products WHERE store=? AND id=?', (store, ident)).fetchone()
    if row is None:
        return None
    reference = unpack(row)
    reference_current = bool(row['active'] and (not row['valid_from'] or row['valid_from'] <= today)
                             and (not row['valid_to'] or row['valid_to'] >= today))
    current_sql = '''p.active=1 AND p.store<>? AND (p.valid_from IS NULL OR p.valid_from<=?)
                     AND (p.valid_to IS NULL OR p.valid_to>=?)'''
    identifiers = codes(reference)
    exact_candidates = []
    if len(identifiers) == 1:
        exact_candidates = db.execute(f'''SELECT p.* FROM product_match_codes c
            JOIN products p ON p.store=c.store AND p.id=c.id
            WHERE c.gtin=? AND {current_sql}''', (identifiers[0], store, today, today)).fetchall()
    tokens = sorted(terms(reference))[:40]
    similar_candidates = []
    if tokens:
        marks = ','.join('?' for _ in tokens)
        # The inverted index keeps this independent of catalogue page size.
        similar_candidates = db.execute(f'''WITH candidates AS (
            SELECT p.store,p.id,COUNT(*) AS shared FROM product_match_terms m
            JOIN products p ON p.store=m.store AND p.id=m.id
            WHERE m.term IN ({marks}) AND {current_sql} AND p.group_id=?
            GROUP BY p.store,p.id), ranked AS (
            SELECT *,ROW_NUMBER() OVER (PARTITION BY store ORDER BY shared DESC,id) AS position FROM candidates)
            SELECT p.* FROM ranked r JOIN products p ON p.store=r.store AND p.id=r.id WHERE r.position<=75''',
            (*tokens, store, today, today, row['group_id'])).fetchall()
    exact, similar, seen = [], [], set()
    for candidate in [*exact_candidates, *similar_candidates]:
        key = (candidate['store'], candidate['id'])
        if key in seen:
            continue
        seen.add(key)
        product = unpack(candidate)
        other_codes = codes(product)
        same_code = len(identifiers) == len(other_codes) == 1 and identifiers == other_codes
        size = size_relation(reference, product)
        entry = {'product': product, 'size': size}
        if same_code and size != 'different':
            exact.append(entry)
            continue
        other = terms(product)
        overlap = len(set(tokens) & other)
        score = 2 * overlap / max(1, len(tokens) + len(other))
        if not same_code and (score < .5 or (overlap < 2 and set(tokens) != other)):
            continue
        entry['reason'] = 'size_conflict' if same_code else 'different_code' if identifiers and other_codes and not set(identifiers) & set(other_codes) else 'name'
        entry['score'] = score + (0.15 if size == 'same' else 0)
        similar.append(entry)
    similar.sort(key=lambda e: (-e['score'], e['product']['price'], e['product']['store'], str(e['product']['id'])))
    selected = [{key: value for key, value in entry.items() if key != 'score'} for entry in similar]
    return {'reference': reference, 'reference_current': reference_current, 'today': today,
            'barcode': identifiers[0] if len(identifiers) == 1 else None,
            'exact': exact, 'similar': selected,
            'stores': [{'store': key, 'exact': sum(e['product']['store'] == key for e in exact),
                        'similar': sum(e['product']['store'] == key for e in selected)}
                       for key in stores if key != store]}
