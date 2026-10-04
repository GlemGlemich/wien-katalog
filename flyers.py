"""Public weekly leaflets; dates come from the retailer, never from a guessed week."""
import json
import re
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from parsers import decode_nuxt, _objects
from sources import fetch

SOURCES = {
    'spar': 'https://www.spar.at/aktionen',
    'billa': 'https://www.billa.at/unsere-aktionen/flugblatt',
    'hofer': 'https://www.hofer.at/flugblatt',
    'penny': 'https://www.penny.at/angebote/flugblaetter',
    'lidl': 'https://www.lidl.at/c/flugblatt/s10012330',
}


class Element:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def walk(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, Element):
                if (not tag or child.tag == tag) and (not cls or cls in child.attrs.get('class', '').split()):
                    yield child
                yield from child.walk(tag, cls)

    def text(self):
        return ' '.join(c.text() if isinstance(c, Element) else c for c in self.children)


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Element()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        child = Element(tag, attrs, self.current)
        self.current.children.append(child)
        if tag not in self.VOID:
            self.current = child

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        current = self.current
        while current.parent:
            if current.tag == tag:
                self.current = current.parent
                return
            current = current.parent

    def handle_data(self, text):
        self.current.children.append(text)

    def meta(self, name):
        return next((el.attrs.get('content', '') for el in self.root.walk('meta')
                     if el.attrs.get('property', el.attrs.get('name')) == name), '')


def https(value, hosts=None):
    if not isinstance(value, str):
        return ''
    parsed = urlparse(value)
    return value if parsed.scheme == 'https' and parsed.hostname and (not hosts or parsed.hostname in hosts) else ''


def date_range(text, today):
    """Parse the two printed dates; infer an omitted year near today's Vienna date."""
    matches = list(re.finditer(r'(?<!\d)(\d{1,2})\.\s*(\d{1,2})(?:\.\s*(20\d{2}|\d{2}(?!\d)))?', text))
    if len(matches) < 2:
        raise ValueError('В источнике не удалось прочитать срок действия флюгблатта.')
    d1, m1, y1 = matches[0].groups()
    d2, m2, y2 = matches[1].groups()
    d1, m1, d2, m2 = map(int, (d1, m1, d2, m2))
    year = lambda value: int(value) + (2000 if len(value) == 2 else 0)
    crosses_year = (m2, d2) < (m1, d1)
    if y1:
        first_year = year(y1)
    elif y2:
        first_year = year(y2) - int(crosses_year)
    else:
        current = date.fromisoformat(today)
        candidates = []
        for y in range(current.year - 1, current.year + 2):
            try:
                candidates.append(date(y, m1, d1))
            except ValueError:
                pass
        if not candidates:
            raise ValueError('Некорректная дата флюгблатта.')
        first_year = min(candidates, key=lambda d: abs((d - current).days)).year
    start = date(first_year, m1, d1)
    end = date(year(y2) if y2 else first_year + int(crosses_year), m2, d2)
    if end < start or (end - start).days > 370:
        raise ValueError('Некорректный срок флюгблатта.')
    return start.isoformat(), end.isoformat()


def current(row, today):
    return bool(row.get('valid_from') and row.get('valid_to') and row['valid_from'] <= today <= row['valid_to'])


def item(store, url, dates, **extra):
    if not https(url):
        raise ValueError('Некорректная ссылка на флюгблатт.')
    return {'id': url, 'store': store, 'title': 'Еженедельные акции', 'url': url,
            'source_url': SOURCES[store], 'valid_from': dates[0], 'valid_to': dates[1],
            'region': 'Вена' if store in ('spar', 'billa') else 'Австрия',
            'image': '', 'pdf_url': '', 'pages': None, **extra}


def script_json(html, marker):
    start = html.find(marker)
    if start < 0:
        return {}
    return json.JSONDecoder().raw_decode(html[start + len(marker):].lstrip())[0]


def publitas(url):
    html = fetch(url)
    doc = Document(html)
    data = script_json(html, 'var data =')
    return doc, {'image': https(doc.meta('og:image')), 'pages': data.get('numPages')}


def read_billa(today):
    html = fetch(SOURCES['billa'])
    urls = []
    for obj in _objects(decode_nuxt(html)):
        value = obj.get('url', '')
        if isinstance(value, str) and https(value, {'view.publitas.com'}) and '/billa-at/' in value and 'wien' in value.lower():
            urls.append(value.split('?')[0].rstrip('/'))
    urls = list(dict.fromkeys(urls))
    if not urls:
        raise ValueError('На странице BILLA не найден флюгблатт для Вены.')
    pdfs = [el.attrs.get('href', '') for el in Document(html).root.walk('a')
            if 'BILLA Flugblatt als PDF' in el.text()]
    result = []
    for url in urls[:8]:
        doc, meta = publitas(url)
        dates = date_range(doc.meta('og:description'), today)
        # Attach only the matching edition; a link for BILLA PLUS is a different flyer.
        pdf = next((p for p in pdfs if urlparse(url).path.split('/')[-1].lower() in p.lower()), '')
        result.append(item('billa', url, dates, pdf_url=https(pdf), **meta))
    return result


def read_hofer(today):
    doc = Document(fetch(SOURCES['hofer']))
    result = []
    for block in doc.root.walk(cls='cms-multilayout-teaser'):
        links = [a.attrs.get('href', '').split('?')[0].rstrip('/') for a in block.walk('a')
                 if https(a.attrs.get('href', ''), {'katalog.hofer.at'}) and 'flipbook_kw' in a.attrs['href']]
        if not links:
            continue
        dates = date_range(block.text(), today)
        url = links[0]
        if any(r['id'] == url for r in result):
            continue
        # The index prints the range; the cover lists several individual starting days.
        meta = {}
        if dates[1] >= today:
            _, meta = publitas(url)
        result.append(item('hofer', url, dates, **meta))
    return result


def read_penny(today):
    doc = Document(fetch(SOURCES['penny']))
    result = []
    for el in doc.root.walk():
        if el.tag not in ('iframe', 'a'):
            continue
        url = https(el.attrs.get('src' if el.tag == 'iframe' else 'href', ''), {'e.issuu.com'})
        params = parse_qs(urlparse(url).query)
        slug = params.get('d', [''])[0]
        if params.get('u') != ['pennyat'] or not slug.startswith('penny_flugblatt_'):
            continue
        dates = date_range(slug.replace('_', ' '), today)
        cover = next((https(image.attrs.get('src', '')) for image in el.walk('img')), '')
        # Issuu can refuse automated access; the official PENNY page remains the reader.
        result.append(item('penny', SOURCES['penny'], dates, id=slug, image=cover,
                           note='Выпуск открывается на сайте PENNY.'))
    return result


def parse_lidl(data):
    flyer = data['flyer']
    if not data.get('success') or flyer.get('countryCode') != 'AT':
        raise ValueError('Не получен австрийский флюгблатт Lidl.')
    # Publication dates differ from offer dates: only offer dates describe promotions.
    start = date.fromisoformat(flyer['offerStartDate']).isoformat()
    end = date.fromisoformat(flyer['offerEndDate']).isoformat()
    if end < start:
        raise ValueError('Некорректный срок акций Lidl.')
    return item('lidl', flyer['flyerUrlAbsolute'], (start, end),
                image=https(flyer.get('thumbnailUrl')), pdf_url=https(flyer.get('pdfUrl')),
                pages=len(flyer.get('pages', [])) or None,
                note='Общий выпуск. Региональные предложения уточняйте при выборе филиала на сайте Lidl.')


def read_lidl(today):
    doc = Document(fetch(SOURCES['lidl']))
    result, seen = [], set()
    for el in doc.root.walk('a', 'flyer'):
        title = next((e.text().strip() for e in el.walk(cls='flyer__title')), '')
        url = https(urljoin(SOURCES['lidl'], el.attrs.get('href', '')), {'www.lidl.at'})
        match = re.search(r'/l/de/flugblatt/([^/]+)/ar/(\d+)', url)
        if title != 'Flugblatt' or not match or url in seen:
            continue
        seen.add(url)
        params = urlencode({'flyer_identifier': match[1], 'region_id': match[2], 'region_code': match[2]})
        result.append(parse_lidl(json.loads(fetch('https://endpoints.leaflets.schwarz/v4/flyer?' + params))))
    return result


def read_spar(today, known):
    warning = ''
    try:
        html = fetch(SOURCES['spar'])
        # Only SPAR Wien, excluding EUROSPAR, INTERSPAR and other Bundeslaender.
        urls = re.findall(r'https://flugblatt\.spar\.at/wien/spar/[^\s"<>]+', unescape(html))
        urls = list(dict.fromkeys(u.split('?')[0].replace('\\/', '/').rstrip('/') + '/' for u in urls))
        if not urls:
            raise ValueError('Список венских выпусков не найден')
    except Exception:
        warning = 'Список новых выпусков недоступен. Показаны только ранее найденные флюгблатты; полный список смотрите на сайте магазина.'
        seed = Path(__file__).parent / 'data' / 'flyer-sources.json'
        urls = known or (json.loads(seed.read_text('utf-8')).get('spar', []) if seed.exists() else [])
    result = []
    for url in urls[:20]:
        if not https(url, {'flugblatt.spar.at'}) or not urlparse(url).path.startswith('/wien/spar/'):
            continue
        html = fetch(url)
        doc = Document(html)
        data = script_json(html, 'window.staticSettings =')
        dates = date_range(data.get('pageTitleUndecorated') or doc.meta('og:title'), today)
        result.append(item('spar', url, dates, image=https(doc.meta('og:image')),
                           pages=len(data.get('pages', [])) or None))
    return result, warning


def read_flyers(store, today, known=()):
    if store == 'spar':
        result, warning = read_spar(today, known)
    else:
        result, warning = {'billa': read_billa, 'hofer': read_hofer, 'penny': read_penny, 'lidl': read_lidl}[store](today), ''
    if not result:
        raise ValueError('На странице магазина не удалось найти флюгблатты со сроком действия. Откройте официальный сайт.')
    return list({row['id']: row for row in result}.values()), warning
