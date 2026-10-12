"""Observed website prices; crossed-out prices never become past observations."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def cents(value):
    if value is None:
        return None
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def snapshot(product):
    return {
        'name': product['name'], 'unit': product.get('unit') or '',
        'variable_weight': bool(product.get('is_variable_weight')),
        'price_cents': cents(product['price']),
        'regular_cents': cents(product.get('regular_price')),
        'single_cents': cents(product.get('single_price')),
        'conditions': product.get('conditions') or [],
        'membership_required': bool(product.get('membership_required')),
        'offers': [{'price_cents': cents(p['price']), 'conditions': p.get('conditions') or []}
                   for p in product.get('offers') or []],
        'valid_from': product.get('valid_from'), 'valid_to': product.get('valid_to'),
        'url': product.get('url'),
    }


def record(db, store, ident, product, checked_at):
    value = json.dumps(snapshot(product), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    last = db.execute('''SELECT entry_id,last_seen,snapshot FROM price_history
                         WHERE store=? AND product_id=? ORDER BY entry_id DESC LIMIT 1''',
                      (store, str(ident))).fetchone()
    # A delayed/older import cannot rewrite the newer observation timeline.
    if last and checked_at < last['last_seen']:
        return
    if last and last['snapshot'] == value:
        if checked_at > last['last_seen']:
            db.execute('UPDATE price_history SET last_seen=? WHERE entry_id=?', (checked_at, last['entry_id']))
        return
    db.execute('''INSERT INTO price_history(store,product_id,first_seen,last_seen,snapshot)
                  VALUES (?,?,?,?,?)''', (store, str(ident), checked_at, checked_at, value))


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS price_history (
        entry_id INTEGER PRIMARY KEY, store TEXT NOT NULL, product_id TEXT NOT NULL,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, snapshot TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS history_product ON price_history(store,product_id,entry_id DESC);
    ''')
    # Seed only missing histories with their actual saved check time. Repeated
    # startup, classification migrations and failed downloads add no observations.
    rows = db.execute('''SELECT p.store,p.id,p.checked_at,p.payload FROM products p
        WHERE NOT EXISTS (SELECT 1 FROM price_history h WHERE h.store=p.store AND h.product_id=p.id)''')
    for row in rows:
        record(db, row['store'], row['id'], json.loads(row['payload']), row['checked_at'])


def context(entry):
    """Conservative comparison: pack and purchase terms must still match."""
    if not entry['unit']:
        return None
    return (entry['name'], entry['unit'], entry['variable_weight'], tuple(entry['conditions']), entry['membership_required'])


def query(db, store, ident, days, now, stores):
    if store not in stores or not ident or len(ident) > 200 or days not in (0, 30, 90):
        raise ValueError('Invalid history request')
    product = db.execute('SELECT payload,active FROM products WHERE store=? AND id=?', (store, ident)).fetchone()
    if product is None:
        return None
    moment = datetime.fromisoformat(now).astimezone(timezone.utc)
    cutoff = (moment - timedelta(days=days)).isoformat(timespec='seconds') if days else ''
    rows = db.execute('''SELECT * FROM price_history WHERE store=? AND product_id=?
        AND last_seen>=? AND first_seen<=? ORDER BY entry_id DESC LIMIT 501''', (store, ident, cutoff, now)).fetchall()
    truncated = len(rows) > 500
    entries = []
    for row in reversed(rows[:500]):
        entry = {**json.loads(row['snapshot']), 'first_seen': row['first_seen'], 'last_seen': row['last_seen']}
        # Only plot actual check timestamps; never manufacture a point at the
        # window boundary or at the crossed-out price. Equal checks are compacted.
        entry['observed_at'] = [row['first_seen']] if row['first_seen'] >= cutoff else []
        if row['last_seen'] != row['first_seen'] and row['last_seen'] <= now:
            entry['observed_at'].append(row['last_seen'])
        if entry['observed_at']:
            entries.append(entry)
    minimum = delta = None
    if entries:
        latest = entries[-1]
        if context(latest) is not None:
            comparable = [e for e in entries if context(e) == context(latest)]
            minimum = min(e['price_cents'] for e in comparable)
            if len(entries) > 1 and context(entries[-2]) == context(latest):
                delta = latest['price_cents'] - entries[-2]['price_cents']
    return {'product': json.loads(product['payload']), 'active': bool(product['active']),
            'days': days, 'entries': entries, 'truncated': truncated,
            'minimum_cents': minimum, 'change_cents': delta}
