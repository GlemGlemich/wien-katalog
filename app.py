"""Vienna grocery catalogue and offers from official leaflets. Python 3.10+."""
import argparse
import concurrent.futures
import json
import math
import mimetypes
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from parsers import _vienna_date
from sources import STORES, pages, network_error_kind
from categories import CATEGORIES, CATEGORY_VERSION, classify
from selections import SELECTIONS, SELECTION_VERSION, FACETS, selection_flags, product_details
from quantities import QUANTITY_VERSION, product_quantity, size_label
from flyers import SOURCES as FLYER_SOURCES, read_flyers, current as current_flyer
import offers

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'catalog.sqlite3'
LOCK = threading.Lock()
BUSY = False
FLYERS_BUSY = False
TOKEN = secrets.token_urlsafe(32)
DISCOUNT_SQL = '''(
  json_extract(payload,'$.regular_price') > json_extract(payload,'$.price')
  OR json_extract(payload,'$.single_price') > json_extract(payload,'$.price')
  OR EXISTS (
    SELECT 1 FROM json_each(products.payload,'$.offers') AS offer
    WHERE json_extract(offer.value,'$.price') > 0
      AND json_extract(offer.value,'$.price') < json_extract(products.payload,'$.price')
  )
)'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).casefold()) if not unicodedata.combining(c))


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    DB.parent.mkdir(exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
          CREATE TABLE IF NOT EXISTS products (
            store TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
            search TEXT NOT NULL, price INTEGER NOT NULL, payload TEXT NOT NULL,
            checked_at TEXT NOT NULL, run TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            valid_from TEXT, valid_to TEXT, PRIMARY KEY(store,id)
          );
          CREATE INDEX IF NOT EXISTS product_price ON products(active,price);
          CREATE INDEX IF NOT EXISTS product_store ON products(store,active);
          CREATE TABLE IF NOT EXISTS imports (
            store TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'idle',
            started_at TEXT, finished_at TEXT, last_success TEXT,
            processed INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
            saved INTEGER DEFAULT 0, unpriced INTEGER DEFAULT 0,
            progress TEXT DEFAULT '', error TEXT DEFAULT ''
          );
          CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS flyers (
            store TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
            checked_at TEXT NOT NULL, PRIMARY KEY(store,id)
          );
          CREATE TABLE IF NOT EXISTS flyer_imports (
            store TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'idle',
            checked_at TEXT, attempted_at TEXT, error TEXT NOT NULL DEFAULT ''
          );
        ''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(products)')}
        if 'group_id' not in columns:
            db.execute("ALTER TABLE products ADD COLUMN group_id TEXT NOT NULL DEFAULT 'other'")
        if 'selection_flags' not in columns:
            db.execute('ALTER TABLE products ADD COLUMN selection_flags INTEGER NOT NULL DEFAULT 0')
        if 'details' not in columns:
            db.execute("ALTER TABLE products ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")
        if 'quantity' not in columns:
            db.execute("ALTER TABLE products ADD COLUMN quantity TEXT NOT NULL DEFAULT '{}'")
        db.execute('CREATE INDEX IF NOT EXISTS product_group ON products(active,group_id,store)')
        version = db.execute("SELECT value FROM app_meta WHERE key='category_version'").fetchone()
        if not version or version[0] != str(CATEGORY_VERSION):
            updates = [(classify(json.loads(row['payload'])), row['store'], row['id'])
                       for row in db.execute('SELECT store,id,payload FROM products')]
            db.executemany('UPDATE products SET group_id=? WHERE store=? AND id=?', updates)
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES ('category_version',?)", (str(CATEGORY_VERSION),))
        version = db.execute("SELECT value FROM app_meta WHERE key='selection_version'").fetchone()
        if not version or version[0] != str(SELECTION_VERSION):
            updates = []
            for row in db.execute('SELECT store,id,payload FROM products'):
                product = json.loads(row['payload'])
                details = product_details(product)
                updates.append((selection_flags(product,details),json.dumps(details),row['store'],row['id']))
            db.executemany('UPDATE products SET selection_flags=?,details=? WHERE store=? AND id=?', updates)
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES ('selection_version',?)", (str(SELECTION_VERSION),))
        version = db.execute("SELECT value FROM app_meta WHERE key='quantity_version'").fetchone()
        if not version or version[0] != str(QUANTITY_VERSION):
            updates = [(json.dumps(product_quantity(json.loads(row['payload']))),row['store'],row['id'])
                       for row in db.execute('SELECT store,id,payload FROM products')]
            db.executemany('UPDATE products SET quantity=? WHERE store=? AND id=?',updates)
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES ('quantity_version',?)",(str(QUANTITY_VERSION),))
        # Bit masks with a bound parameter cannot use a partial index. Match
        # these trusted, fixed predicates in products() so each query reads
        # only its selection instead of scanning every product payload.
        for entry in SELECTIONS:
            flag = int(entry['flag'])
            db.execute(f'''CREATE INDEX IF NOT EXISTS product_selection_{flag}
                ON products(active,store,valid_from,valid_to,group_id)
                WHERE (selection_flags & {flag}) != 0''')
        # Include the older indexes too: missing statistics can make SQLite
        # prefer an unselective index over the small selection indexes.
        db.execute('ANALYZE products')
        for store in STORES:
            db.execute('INSERT OR IGNORE INTO imports(store) VALUES (?)', (store,))
            db.execute('INSERT OR IGNORE INTO flyer_imports(store) VALUES (?)', (store,))
        db.execute("UPDATE imports SET status='interrupted', error='Загрузка была прервана. Сохранённые товары доступны; запустите обновление.' WHERE status='running'")
        db.execute("UPDATE flyer_imports SET status='error', error='Проверка флюгблаттов была прервана. Повторите обновление.' WHERE status='running'")
        offers.initialize(db)


def state():
    today = _vienna_date(time.time())
    with connect() as db:
        stores = []
        for key, info in STORES.items():
            row = dict(db.execute('SELECT * FROM imports WHERE store=?', (key,)).fetchone())
            row.update(info)
            row['count'] = db.execute('SELECT count(*) FROM products WHERE store=? AND active=1', (key,)).fetchone()[0]
            row['current_count'] = db.execute('SELECT count(*) FROM products WHERE store=? AND active=1 AND (valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?)', (key, today, today)).fetchone()[0]
            stores.append(row)
        return {'stores': stores, 'busy': BUSY, 'token': TOKEN, 'today': today,
                'total': sum(s['count'] for s in stores),
                'current_total': sum(s['current_count'] for s in stores)}


def save_page(store, rows, run, source_url):
    stamp = now()
    values = []
    for row in rows:
        if not row.get('id') or not row.get('name'):
            raise ValueError('В товаре отсутствует название или идентификатор')
        amount = row['price']
        if not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            raise ValueError('В источнике некорректная цена')
        row['source_url'] = source_url
        row['checked_at'] = stamp
        for field in ('valid_from', 'valid_to'):
            value = row.get(field)
            if value:
                datetime.strptime(value, '%Y-%m-%d')
            else:
                row[field] = None
        details = product_details(row)
        values.append((store, row['id'], row['name'], normalize(row['name'] + ' ' + (row.get('category') or '')),
                       round(amount * 100), json.dumps(row, ensure_ascii=False), stamp, run,
                       row['valid_from'], row['valid_to'], classify(row), selection_flags(row,details), json.dumps(details),json.dumps(product_quantity(row))))
    with connect() as db:
        db.executemany('''INSERT INTO products(store,id,name,search,price,payload,checked_at,run,valid_from,valid_to,group_id,selection_flags,details,quantity)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(store,id) DO UPDATE SET
          name=excluded.name,search=excluded.search,price=excluded.price,payload=excluded.payload,
          checked_at=excluded.checked_at,run=excluded.run,active=1,valid_from=excluded.valid_from,valid_to=excluded.valid_to,group_id=excluded.group_id,selection_flags=excluded.selection_flags,details=excluded.details,quantity=excluded.quantity''', values)


def import_store(store):
    run = now() + '-' + secrets.token_hex(4)
    seen, saved_ids = set(), set()
    total = 0
    with connect() as db:
        db.execute("UPDATE imports SET status='running',started_at=?,finished_at=NULL,processed=0,total=0,saved=0,unpriced=0,progress='Подключение к магазину',error='' WHERE store=?", (now(), store))
    try:
        for rows, ids, total, progress, source_url in pages(store):
            if not ids.difference(seen) and total:
                raise ValueError('Источник повторил товары. Полный обход не подтверждён.')
            seen.update(ids)
            saved_ids.update(r['id'] for r in rows)
            save_page(store, rows, run, source_url)
            with connect() as db:
                db.execute('UPDATE imports SET processed=?,total=?,saved=?,unpriced=?,progress=? WHERE store=?',
                           (len(seen), total, len(saved_ids), len(seen - saved_ids), progress, store))
            print(f'{STORES[store]["name"]}: {len(seen)}/{total}, с ценой {len(saved_ids)}', flush=True)
        if len(seen) < total:
            raise ValueError(f'Получено {len(seen)} из {total}. Каталог мог измениться во время загрузки; повторите обновление.')
        if not seen:
            raise ValueError('Источник не вернул товаров. Сохранённый каталог оставлен без изменений.')
        if not saved_ids:
            raise ValueError('В источнике не удалось прочитать цены. Сохранённый каталог оставлен без изменений.')
        with connect() as db:
            db.execute('UPDATE products SET active=0 WHERE store=? AND run<>?', (store, run))
            db.execute("UPDATE imports SET status='complete',finished_at=?,last_success=?,progress='Каталог сайта прочитан полностью' WHERE store=?", (now(), now(), store))
    except Exception as error:
        if isinstance(error, urllib.error.HTTPError):
            message = f'Сайт магазина ответил HTTP {error.code}. Сохранённые цены остаются доступны.'
        elif network_error_kind(error) == 'access_denied':
            message = 'Система запретила программе доступ к интернету. Разрешите сетевой доступ и перезапустите каталог. Сохранённые цены доступны.'
        elif network_error_kind(error) == 'unreachable':
            message = 'Сеть недоступна для программы. Проверьте подключение и повторите обновление. Сохранённые цены доступны.'
        elif isinstance(error, (urllib.error.URLError, TimeoutError, OSError)):
            message = 'Не удалось соединиться с магазином. Проверьте интернет и повторите обновление.'
        elif isinstance(error, ValueError):
            message = str(error)[:350]
        else:
            message = 'Формат ответа магазина не удалось прочитать. Полученные ранее товары сохранены.'
        with connect() as db:
            db.execute("UPDATE imports SET status='error',finished_at=?,error=?,progress='Загрузка не завершена' WHERE store=?", (now(), message, store))
        print(f'{store}: {type(error).__name__}: {error}', flush=True)


def refresh(selected):
    global BUSY
    with LOCK:
        if BUSY:
            return False
        BUSY = True
    def work():
        global BUSY
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                list(executor.map(import_store, selected))
            with connect() as db:
                db.execute('ANALYZE products')
        finally:
            with LOCK:
                BUSY = False
    threading.Thread(target=work, daemon=True).start()
    return True


def products(params, comparison=False):
    get = lambda key, default='': params.get(key, [default])[0]
    page = max(1, min(10000, int(get('page', '1'))))
    size = 50
    terms, args = ['active=1'], []
    store = get('store')
    if store in STORES and not comparison:
        terms.append('store=?')
        args.append(store)
    for word in normalize(get('q')[:200]).split():
        terms.append("search LIKE ? ESCAPE '\\'")
        args.append('%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    today = _vienna_date(time.time())
    selection = next((s for s in SELECTIONS if s['id'] == get('selection')), None)
    if get('selection') and selection is None:
        raise ValueError('Неизвестная подборка')
    period = 'current' if selection or comparison else get('period', 'current')
    if period == 'current':
        terms.extend(['(valid_from IS NULL OR valid_from<=?)', '(valid_to IS NULL OR valid_to>=?)'])
        args.extend([today, today])
    elif period == 'future':
        terms.append('valid_from>?')
        args.append(today)
    elif period == 'expired':
        terms.append('valid_to<?')
        args.append(today)
    selection_terms, selection_args = list(terms), list(args)
    if selection:
        terms.append(f"(selection_flags & {int(selection['flag'])}) != 0")
    if get('discount') == '1':
        # Only a lower published price counts; dates, Pfand and other notes do not.
        terms.append(DISCOUNT_SQL)
    basis = get('price_basis','pack')
    if basis not in ('pack','kg','l'):
        raise ValueError('Неизвестная единица сравнения')
    if comparison and basis=='pack':
        raise ValueError('Для сравнения магазинов выберите цену за кг или литр')
    if basis != 'pack':
        terms.extend(["json_extract(quantity,'$.measure')=?", "json_extract(quantity,'$.unit_price')>0"])
        args.append(basis)
    price_order = 'price' if basis=='pack' else "json_extract(quantity,'$.unit_price')"
    order = {'price_asc': price_order+' ASC,name', 'price_desc': price_order+' DESC,name', 'name': 'name COLLATE NOCASE', 'updated': 'checked_at DESC,name'}.get(get('sort'), 'name COLLATE NOCASE')
    with connect() as db:
        selections = []
        if selection and not comparison:
            for entry in SELECTIONS:
                stats = db.execute('SELECT count(*),coalesce(sum(CASE WHEN '+DISCOUNT_SQL+' THEN 1 ELSE 0 END),0) FROM products WHERE '+
                                   ' AND '.join(selection_terms)+f" AND (selection_flags & {int(entry['flag'])}) != 0", selection_args).fetchone()
                selections.append({**entry, 'count': stats[0], 'discount_count': stats[1]})
        counts = {} if comparison else dict(db.execute('SELECT group_id,count(*) FROM products WHERE ' + ' AND '.join(terms) + ' GROUP BY group_id', args).fetchall())
        category = 'all' if selection else get('category', 'all')
        if category != 'all':
            if category not in dict(CATEGORIES):
                raise ValueError('Неизвестная категория')
            terms.append('group_id=?')
            args.append(category)
        scope = selection['id'] if selection else {'dairy':'milk','meat':'meat','alcohol':'alcohol'}.get(category,'')
        definitions = FACETS.get(scope,[])
        requested_size = get('package_size','all')
        size_terms,size_args = list(terms),list(args)
        # Size choices respect category, price basis, search and other details,
        # while retaining other sizes when one exact size has been selected.
        for key,label,options in definitions:
            value = get(key,'all')
            if value != 'all':
                if value not in dict(options):
                    raise ValueError('Неизвестный подвид товара')
                size_terms.append('json_extract(details,?)=?')
                size_args.extend(['$.'+key,value])
        size_counts = {} if comparison else dict(db.execute("SELECT json_extract(quantity,'$.size_key'),count(*) FROM products WHERE "+
                                      ' AND '.join(size_terms)+" GROUP BY json_extract(quantity,'$.size_key')",size_args).fetchall())
        if requested_size != 'all':
            if requested_size not in ('variable','unknown') and not re.fullmatch(r'(?:kg|l):[0-9]{1,8}(?:\.[0-9]{1,3})?',requested_size):
                raise ValueError('Неизвестный вес упаковки')
            terms.append("json_extract(quantity,'$.size_key')=?")
            args.append(requested_size)
            size_counts.setdefault(requested_size,0)
        def size_order(key):
            return (0 if key.startswith('kg:') else 1,float(key.split(':')[1])) if ':' in key else (2 if key=='variable' else 3,0)
        sizes = [{'id':'all','label':'Любой вес / объём','count':sum(size_counts.values())}]+[
            {'id':key,'label':size_label(key),'count':size_counts[key]} for key in sorted((k for k in size_counts if k),key=size_order)]
        chosen = {}
        for key,label,options in definitions:
            value = get(key,'all')
            if value != 'all':
                if value not in dict(options):
                    raise ValueError('Неизвестный подвид товара')
                chosen[key] = value
        # Each selector counts choices with the other selectors applied.
        facets = []
        for key,label,options in ([] if comparison else definitions):
            facet_terms,facet_args = list(terms),list(args)
            for other,value in chosen.items():
                if other != key:
                    facet_terms.append('json_extract(details,?)=?')
                    facet_args.extend(['$.'+other,value])
            values = dict(db.execute('SELECT json_extract(details,?),count(*) FROM products WHERE '+
                                    ' AND '.join(facet_terms)+' GROUP BY json_extract(details,?)',
                                    ['$.'+key]+facet_args+['$.'+key]).fetchall())
            facets.append({'id':key,'label':label,'selected':chosen.get(key,'all'),
                           'options':[{'id':'all','label':'Все','count':sum(values.values())}]+
                                     [{'id':value,'label':name,'count':values.get(value,0)} for value,name in options]})
        for key,value in chosen.items():
            terms.append('json_extract(details,?)=?')
            args.extend(['$.'+key,value])
        where = ' AND '.join(terms)
        if comparison:
            rows = db.execute('''WITH ranked AS (
                SELECT store,payload,details,quantity,
                row_number() OVER (PARTITION BY store ORDER BY json_extract(quantity,'$.unit_price'),price,name,id) AS position,
                count(*) OVER (PARTITION BY store) AS matched
                FROM products WHERE '''+where+''')
                SELECT store,payload,details,quantity,matched FROM ranked WHERE position=1''',args).fetchall()
            matches = {row['store']:row for row in rows}
            entries = []
            for key,info in STORES.items():
                row = matches.get(key)
                product = {**json.loads(row['payload']),'details':json.loads(row['details']),'quantity':json.loads(row['quantity'])} if row else None
                entries.append({'store':key,'name':info['name'],'product':product,'count':row['matched'] if row else 0})
            lowest = min((entry['product']['quantity']['unit_price'] for entry in entries if entry['product']),default=None)
            for entry in entries:
                value = entry['product']['quantity']['unit_price'] if entry['product'] else None
                entry['best'] = value is not None and value==lowest
                entry['difference'] = round(value-lowest,6) if value is not None else None
            entries.sort(key=lambda entry:(entry['product'] is None,entry['product']['quantity']['unit_price'] if entry['product'] else 0,entry['name']))
            return {'stores':entries,'price_basis':basis,'lowest':lowest,'today':today,'total':sum(entry['count'] for entry in entries)}
        total = db.execute('SELECT count(*) FROM products WHERE ' + where, args).fetchone()[0]
        page = min(page, max(1, math.ceil(total / size)))
        rows = db.execute('SELECT payload,details,quantity FROM products WHERE ' + where + ' ORDER BY ' + order + ',store,id LIMIT ? OFFSET ?', args + [size, (page - 1) * size]).fetchall()
    categories = [{'id': 'all', 'label': 'Все товары', 'count': sum(counts.values())}]
    categories.extend({'id': key, 'label': label, 'count': counts.get(key, 0)} for key, label in CATEGORIES)
    return {'items': [{**json.loads(r[0]),'details':json.loads(r[1]),'quantity':json.loads(r[2])} for r in rows], 'total': total, 'page': page, 'pages': max(1, math.ceil(total / size)), 'size': size, 'categories': categories,
            'selections': selections, 'selection': selection['id'] if selection else None, 'facets':facets,'sizes':sizes,'price_basis':basis}


def flyer_state():
    today = _vienna_date(time.time())
    with connect() as db:
        rows = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM flyers')]
        items = [row for row in rows if current_flyer(row, today)]
        items.sort(key=lambda r: (list(STORES).index(r['store']), r['valid_from'], r['id']))
        stores = []
        for key, info in STORES.items():
            row = dict(db.execute('SELECT * FROM flyer_imports WHERE store=?', (key,)).fetchone())
            row.update(name=info['name'], url=FLYER_SOURCES[key], count=sum(r['store'] == key for r in items))
            stores.append(row)
    return {'items': items, 'stores': stores, 'total': len(items), 'today': today, 'busy': FLYERS_BUSY}


def import_flyers(store):
    with connect() as db:
        known = [json.loads(row['payload'])['url'] for row in db.execute('SELECT payload FROM flyers WHERE store=?', (store,))]
        db.execute("UPDATE flyer_imports SET status='running',attempted_at=?,error='' WHERE store=?", (now(), store))
    try:
        rows, warning = read_flyers(store, _vienna_date(time.time()), known)
        if not rows:
            raise ValueError('Выпуски не получены. Сохранённые флюгблатты оставлены без изменений.')
        stamp = now()
        values = []
        for row in rows:
            start, end = (datetime.strptime(row[field], '%Y-%m-%d') for field in ('valid_from', 'valid_to'))
            if start > end or row['store'] != store:
                raise ValueError('Некорректный срок или магазин флюгблатта.')
            row['checked_at'] = stamp
            values.append((store, row['id'], json.dumps(row, ensure_ascii=False), stamp))
        # Replace only after the whole source has been read and validated.
        with connect() as db:
            db.execute('DELETE FROM flyers WHERE store=?', (store,))
            db.executemany('INSERT INTO flyers(store,id,payload,checked_at) VALUES (?,?,?,?)', values)
            db.execute('UPDATE flyer_imports SET status=?,checked_at=?,error=? WHERE store=?',
                       ('partial' if warning else 'complete', stamp, warning, store))
        print(f'{store}: прочитано флюгблаттов {len(rows)}', flush=True)
    except Exception as error:
        if isinstance(error, urllib.error.HTTPError):
            message = f'Сайт магазина недоступен для чтения (HTTP {error.code}). Попробуйте позже или откройте его напрямую.'
        elif isinstance(error, ValueError):
            message = str(error)[:350]
        else:
            message = 'Не удалось проверить флюгблатты. Сохранённые выпуски доступны до окончания их срока.'
        with connect() as db:
            db.execute("UPDATE flyer_imports SET status='error',error=? WHERE store=?", (message, store))
        print(f'{store} flyers: {type(error).__name__}: {error}', flush=True)


def refresh_flyers(selected):
    global FLYERS_BUSY
    with LOCK:
        if FLYERS_BUSY:
            return False
        FLYERS_BUSY = True
    def work():
        global FLYERS_BUSY
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                list(executor.map(import_flyers, selected))
            # PDF text extraction is memory intensive; read editions one at a time.
            for store in selected:
                offers.import_store(store,connect,now(),_vienna_date(time.time()))
        finally:
            with LOCK:
                FLYERS_BUSY = False
    threading.Thread(target=work, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, body, status=200, kind='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        host = self.headers.get('Host', '').split(':')[0]
        return host in ('127.0.0.1', 'localhost')

    def do_GET(self):
        if not self.local_request():
            return self.respond({'error': 'Недопустимый адрес'}, 403)
        target = urlparse(self.path)
        try:
            if target.path == '/api/state':
                return self.respond(state())
            if target.path == '/api/products':
                return self.respond(products(parse_qs(target.query)))
            if target.path == '/api/comparison':
                return self.respond(products(parse_qs(target.query),comparison=True))
            if target.path == '/api/flyers':
                return self.respond(flyer_state())
            if target.path == '/api/offers':
                with connect() as db:
                    result = offers.query(db,parse_qs(target.query),_vienna_date(time.time()),FLYERS_BUSY)
                return self.respond(result)
            files = {'/': 'index.html', '/app.js': 'app.js', '/offers.js': 'offers.js', '/style.css': 'style.css', '/favicon.svg': 'favicon.svg'}
            if target.path not in files:
                return self.respond({'error': 'Не найдено'}, 404)
            path = ROOT / 'static' / files[target.path]
            return self.respond(path.read_bytes(), kind=(mimetypes.guess_type(path)[0] or 'text/plain') + '; charset=utf-8')
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Switching selections may cancel an in-flight browser request.
            return
        except (ValueError, KeyError):
            return self.respond({'error': 'Некорректный запрос'}, 400)
        except Exception as error:
            print('Request error:', repr(error), flush=True)
            return self.respond({'error': 'Не удалось прочитать каталог'}, 500)

    def do_POST(self):
        if not self.local_request() or not secrets.compare_digest(self.headers.get('X-Local-Token', ''), TOKEN):
            return self.respond({'error': 'Обновите страницу и повторите действие'}, 403)
        if self.path not in ('/api/refresh', '/api/flyers/refresh'):
            return self.respond({'error': 'Не найдено'}, 404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length > 1024:
                return self.respond({'error': 'Слишком большой запрос'}, 413)
            data = json.loads(self.rfile.read(length))
            store = data.get('store', 'all')
            if store != 'all' and store not in STORES:
                raise ValueError('Магазин не найден')
            action = refresh_flyers if self.path == '/api/flyers/refresh' else refresh
            if not action(list(STORES) if store == 'all' else [store]):
                return self.respond({'error': 'Обновление уже выполняется'}, 409)
            return self.respond({'ok': True}, 202)
        except (ValueError, TypeError):
            return self.respond({'error': 'Некорректный запрос'}, 400)


def main():
    parser = argparse.ArgumentParser(description='Каталог цен магазинов Австрии')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--refresh', action='store_true', help='Считать все каталоги при запуске')
    parser.add_argument('--open', action='store_true', help='Открыть каталог в браузере')
    options = parser.parse_args()
    try:
        server = ThreadingHTTPServer(('127.0.0.1', options.port), Handler)
    except OSError:
        if options.open:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{options.port}/api/state', timeout=2) as response:
                    existing = json.load(response)
                if {s['store'] for s in existing['stores']} == set(STORES):
                    webbrowser.open(f'http://127.0.0.1:{options.port}')
                    print('Каталог уже работает. Открываю его в браузере.', flush=True)
                    return
            except Exception:
                pass
        raise SystemExit(f'Порт {options.port} занят. Закройте другой экземпляр или укажите другой --port.')
    initialize()
    print(f'Каталог: http://127.0.0.1:{server.server_port}', flush=True)
    if options.refresh:
        refresh(list(STORES))
    if options.open:
        webbrowser.open(f'http://127.0.0.1:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nКаталог остановлен. Товары сохранены.', flush=True)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
