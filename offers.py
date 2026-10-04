"""Offers come exclusively from official leaflet PDFs, independently of the catalogue."""
import hashlib
import json
import math
import re
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from categories import CATEGORIES as CATALOG_CATEGORIES
# Leaflets already have an Alcohol filter within Drinks. Keep saved and newly
# read leaflet rows in that existing navigation while the catalogue separates it.
CATEGORIES = [(key,label) for key,label in CATALOG_CATEGORIES if key!='alcohol']
from flyers import current, script_json, https
from sources import fetch, STORES
from offer_model import DRINKS, matches
from offer_pdf import read_pdf, parse_pages

PARSER_VERSION = 3
CACHE = Path(__file__).parent / 'data' / 'leaflet-cache'


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS flyer_offers (store TEXT NOT NULL, id TEXT NOT NULL,
        payload TEXT NOT NULL, PRIMARY KEY(store,id));
      CREATE TABLE IF NOT EXISTS offer_imports (store TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'idle', checked_at TEXT, attempted_at TEXT,
        count INTEGER NOT NULL DEFAULT 0, omitted INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '');
    ''')
    for store in STORES:
        db.execute('INSERT OR IGNORE INTO offer_imports(store) VALUES (?)',(store,))
    db.execute("UPDATE offer_imports SET status='error',error='Чтение товаров было прервано. Повторите обновление.' WHERE status='running'")


def cache_path(flyer):
    return CACHE / (hashlib.sha256(flyer['id'].encode()).hexdigest()[:24]+'.pdf')


def pdf_url(flyer):
    store = flyer['store']
    if store in ('billa','hofer'):
        data = script_json(fetch(flyer['url']), 'var data =')
        url = data.get('config',{}).get('downloadPdfUrl','')
    elif store == 'spar':
        url = flyer['url'].rstrip('/')+'/ViewPdf.ashx'
    else:
        url = flyer.get('pdf_url','')
    if not https(url):
        raise ValueError('Ссылка на PDF этого выпуска недоступна. Откройте оригинал флюгблатта.')
    return url


def download(flyer):
    path = cache_path(flyer)
    if path.exists() and time.time()-path.stat().st_mtime < 6*3600:
        return path
    url = pdf_url(flyer)
    CACHE.mkdir(parents=True,exist_ok=True)
    tmp = path.with_suffix('.part')
    try:
        request = urllib.request.Request(url, headers={'User-Agent':'ViennaCatalogue/1.0'})
        with urllib.request.urlopen(request,timeout=60) as response, tmp.open('wb') as output:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > 220*1024*1024:
                    raise ValueError('PDF превышает допустимый размер 220 МБ.')
                output.write(chunk)
        with tmp.open('rb') as file:
            if file.read(5) != b'%PDF-':
                raise ValueError('Магазин не вернул PDF. Прежние товары сохранены.')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def read_offers(flyers):
    rows, omitted = [], 0
    for flyer in flyers:
        path = download(flyer)
        # Cache geometry by PDF contents, so a revised edition is parsed again.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        cache = path.with_suffix('.json')
        cached = json.loads(cache.read_text('utf-8')) if cache.exists() else {}
        if cached.get('sha') != digest:
            cached = {'sha':digest,'pages':read_pdf(path)}
            cache.write_text(json.dumps(cached,ensure_ascii=False),encoding='utf-8')
        found, skipped = parse_pages(cached['pages'],flyer['store'],flyer)
        rows.extend(found); omitted += skipped
    return rows, omitted


def save(db, store, rows, omitted, stamp):
    if not rows:
        raise ValueError('Не удалось уверенно прочитать товары и условия. Оригинал флюгблатта доступен во вкладке «Буклеты».')
    for row in rows:
        if row['store'] != store or row['price_cents'] <= 0 or not row['flyer_id'] or row['valid_from'] > row['valid_to']:
            raise ValueError('Некорректные данные предложения')
        row['checked_at'] = stamp
    db.execute('DELETE FROM flyer_offers WHERE store=?',(store,))
    db.executemany('INSERT INTO flyer_offers VALUES (?,?,?)',[(store,r['id'],json.dumps(r,ensure_ascii=False)) for r in rows])
    db.execute("UPDATE offer_imports SET status='partial',checked_at=?,count=?,omitted=?,error='' WHERE store=?",
               (stamp,len(rows),omitted,store))


def import_store(store, connect, stamp, today):
    with connect() as db:
        db.execute("UPDATE offer_imports SET status='running',attempted_at=?,error='' WHERE store=?",(stamp,store))
        flyers = [json.loads(r[0]) for r in db.execute('SELECT payload FROM flyers WHERE store=?',(store,))]
    try:
        if store == 'penny':
            raise ValueError('PENNY: просмотрщик не предоставляет доступный PDF для чтения товаров. Буклет можно открыть на сайте; цены каталога сюда не подставляются.')
        flyers = [f for f in flyers if current(f,today)]
        if not flyers:
            raise ValueError('Нет доступного флюгблатта на сегодня.')
        rows, omitted = read_offers(flyers)
        with connect() as db:
            save(db,store,rows,omitted,stamp)
    except Exception as error:
        message = str(error)[:350] if isinstance(error,ValueError) else 'Не удалось прочитать PDF магазина. Прежние предложения сохранены до окончания их срока.'
        with connect() as db:
            db.execute("UPDATE offer_imports SET status='error',error=? WHERE store=?",(message,store))
        print(f'{store} leaflet products: {type(error).__name__}: {error}',flush=True)


def billa_closed(day):
    """The leaflet excludes Sundays and Austrian public holidays."""
    if day.weekday() == 6 or (day.month,day.day) in {(1,1),(1,6),(5,1),(8,15),(10,26),(11,1),(12,8),(12,25),(12,26)}:
        return True
    y = day.year
    a,b,c = y%19,y//100,y%100
    d,e = b//4,b%4
    f = (b+8)//25
    g = (b-f+1)//3
    h = (19*a+b-d-g+15)%30
    i,k = c//4,c%4
    l = (32+2*e+2*i-h-k)%7
    m = (a+11*h+22*l)//451
    n = h+l-7*m+114
    easter = date(y,n//31,n%31+1)
    return any(day == easter+timedelta(days=offset) for offset in (1,39,50,60))


def valid(row,today):
    return current(row,today) and not (row.get('excludes_sunday') and billa_closed(date.fromisoformat(today)))


def query(db,params,today,busy=False):
    get = lambda key,default='':params.get(key,[default])[0]
    rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM flyer_offers')]
    rows = [r for r in rows if valid(r,today)]
    stores = [dict(r) for r in db.execute('SELECT * FROM offer_imports')]
    for s in stores:
        s.update(name=STORES[s['store']]['name'],count=sum(r['store']==s['store'] for r in rows))
    all_total = len(rows)
    if get('store') in STORES:
        rows = [r for r in rows if r['store']==get('store')]
    if get('membership') == 'no':
        rows = [r for r in rows if not r['membership_required']]
    limit = max(0,min(100,int(get('quantity','0'))))
    if limit:
        rows = [r for r in rows if r['min_quantity'] <= limit]
    rows = [r for r in rows if matches(r,get('q')[:200])]
    categories = [{'id':'all','label':'Все товары','count':len(rows)}]+[
        {'id':key,'label':label,'count':sum(r['group_id']==key for r in rows)} for key,label in CATEGORIES]
    if get('category','all') != 'all':
        rows = [r for r in rows if r['group_id']==get('category')]
    drinks = [{'id':key,'label':label,'count':sum((key=='all' and r['group_id']=='drinks') or r['drink_kind']==key for r in rows)} for key,label in DRINKS]
    if get('drink','all') != 'all':
        rows = [r for r in rows if r['drink_kind']==get('drink')]
    order = get('sort','unit')
    rows.sort(key=lambda r: ((r['price_cents'] if order=='price' else r['name'].casefold() if order=='name' else
                            (r['measure'] or 'z',r['unit_price'] if r['unit_price'] is not None else math.inf)),r['store'],r['id']))
    # Only a selected beverage family can be ranked by litre; all food types are never mixed.
    kinds = {r['drink_kind'] for r in rows}
    comparable = [r for r in rows if r['measure']=='l' and r['unit_price'] is not None]
    best = min(comparable,key=lambda r:r['unit_price']) if len(kinds)==1 and '' not in kinds and len({r['store'] for r in comparable})>1 else None
    page = max(1,min(int(get('page','1')),max(1,math.ceil(len(rows)/40))))
    return {'items':rows[(page-1)*40:page*40],'total':len(rows),'page':page,'pages':max(1,math.ceil(len(rows)/40)),
            'categories':categories,'drinks':drinks,'stores':stores,'all_total':all_total,'today':today,'best':best,'busy':busy}
