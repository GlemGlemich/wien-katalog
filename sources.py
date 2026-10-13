"""Read only the public, paginated catalogues of the five Austrian retailers."""
import json
import errno
import gzip
import http.client
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from parsers import parse_rewe, parse_spar, parse_hofer, parse_lidl, decode_nuxt

STORES = {
    'spar': {'name': 'SPAR', 'url': 'https://www.spar.at/produktwelt', 'scope': 'Открытый каталог SPAR. Цены отдельных филиалов могут отличаться.'},
    'billa': {'name': 'BILLA', 'url': 'https://shop.billa.at', 'scope': 'Каталог BILLA Online Shop без выбора адреса доставки.'},
    'hofer': {'name': 'HOFER', 'url': 'https://www.hofer.at/produkte', 'scope': 'Опубликованный каталог HOFER. Сайт содержит часть ассортимента филиалов.'},
    'penny': {'name': 'PENNY', 'url': 'https://www.penny.at', 'scope': 'Опубликованные товары PENNY; большинство цен ограничены сроками предложений.'},
    'lidl': {'name': 'Lidl', 'url': 'https://www.lidl.at/q/search', 'scope': 'Опубликованный каталог Lidl Österreich без выбора филиала; преимущественно предложения недели.'},
}


def network_error_kind(error):
    """Keep TLS/OpenSSL error codes separate from operating-system errno codes."""
    while isinstance(error, urllib.error.URLError) and isinstance(error.reason, BaseException):
        error = error.reason
    # SSL_ERROR_SSL is 1, just like POSIX EPERM. It does not mean that Windows
    # blocked the network. Certificate failures may also come from a local
    # antivirus HTTPS scanner, so do not attribute them to the retailer alone.
    if isinstance(error, ssl.SSLCertVerificationError):
        if getattr(error, 'verify_code', None) == 10:
            return 'certificate_expired'
        if getattr(error, 'verify_code', None) == 9:
            return 'certificate_not_yet_valid'
        return 'certificate_invalid'
    if isinstance(error, ssl.SSLError):
        return 'tls_error'
    codes = {getattr(error,'winerror',None),getattr(error,'errno',None)}
    if codes.intersection({10013,errno.EACCES,errno.EPERM}):
        return 'access_denied'
    if codes.intersection({10050,10051,10065,errno.ENETDOWN,errno.ENETUNREACH,errno.EHOSTUNREACH}):
        return 'unreachable'
    return None


NETWORK_MESSAGES = {
    'access_denied': 'Система запретила программе доступ к интернету. Разрешите сетевой доступ и перезапустите каталог. Сохранённые цены доступны.',
    'unreachable': 'Сеть недоступна для программы. Проверьте подключение и повторите обновление. Сохранённые цены доступны.',
    'certificate_expired': 'Истёк срок сертификата HTTPS. Проверьте дату и время компьютера. Если они верны, проверьте обновления антивируса и повторите позже. Сохранённые данные доступны.',
    'certificate_not_yet_valid': 'Сертификат HTTPS ещё не вступил в силу. Проверьте дату и время компьютера. Сохранённые данные доступны.',
    'certificate_invalid': 'Не удалось проверить сертификат HTTPS. Проверьте обновления Windows и антивируса. Если ошибка остаётся, повторите позже. Сохранённые данные доступны.',
    'tls_error': 'Не удалось установить защищённое HTTPS-соединение. Повторите позже; если ошибка остаётся, проверьте антивирус. Сохранённые данные доступны.',
}


def network_error_message(error):
    """Use the same actionable explanation for catalogues, leaflets and PDFs."""
    return NETWORK_MESSAGES.get(network_error_kind(error), '')


def fetch(url):
    for attempt in range(3):
        try:
            # Use standard TLS verification and do not bypass retailer access controls.
            started = time.monotonic()
            request = urllib.request.Request(url, headers={'Accept-Encoding': 'gzip'})
            with urllib.request.urlopen(request, timeout=30) as response:
                chunks = []
                length = 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    length += len(chunk)
                    if length > 25_000_000 or time.monotonic() - started > 90:
                        raise TimeoutError('Ответ магазина не завершился вовремя')
                    chunks.append(chunk)
                body = b''.join(chunks)
                if response.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
                if len(body) > 25_000_000:
                    raise ValueError('Ответ магазина превышает допустимый размер')
                return body.decode('utf-8')
        except urllib.error.HTTPError as error:
            if error.code not in (429, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(min(10, 2 ** (attempt + 1)))
        except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as error:
            if network_error_kind(error) or attempt == 2:
                raise
            time.sleep(2 ** attempt)


def pages(store):
    """Yield (parsed rows, raw identities, total, human progress, source URL)."""
    if store in ('billa', 'penny'):
        base = 'https://shop.billa.at' if store == 'billa' else 'https://www.penny.at'
        page = 0
        seen = set()
        while True:
            url = base + '/api/product-discovery/products?' + urlencode({'pageSize': 500, 'page': page})
            data = json.loads(fetch(url))
            if data.get('isTotalTruncated'):
                raise ValueError('Магазин ограничил размер каталога; полный обход не подтверждён')
            raw = data['results']
            total = data['total']
            ids = {str(p['sku']) for p in raw}
            if raw and not ids.difference(seen):
                raise ValueError('Магазин повторил страницу; полный обход не подтверждён')
            seen.update(ids)
            yield parse_rewe(data, store), ids, total, f'Страница {page + 1}', url
            if data['offset'] + data['count'] >= total:
                break
            if not raw:
                raise ValueError('Каталог закончился раньше заявленного количества товаров')
            page += 1
            time.sleep(0.35)
    elif store == 'spar':
        page = 1
        while True:
            url = 'https://search-spar.spar-ics.com/fact-finder/rest/v4/search/products_lmos_at?' + urlencode({'query': '*', 'page': page, 'hitsPerPage': 500, 'useAsn': 'false', 'useCampaigns': 'false'})
            data = json.loads(fetch(url))
            if data.get('timedOut'):
                raise ValueError('SPAR вернул неполный результат по тайм-ауту')
            hits = data['hits'] if isinstance(data['hits'], list) else data['hits']['hits']
            ids = {str(p['masterValues']['product-number']) for p in hits}
            yield parse_spar(data), ids, data['totalHits'], f"Страница {page} из {data['paging']['pageCount']}", url
            if page >= data['paging']['pageCount']:
                break
            if not hits:
                raise ValueError('Пустая страница внутри каталога SPAR')
            page += 1
            time.sleep(0.35)
    elif store == 'hofer':
        page = 1
        while True:
            url = 'https://www.hofer.at/produkte' + (f'?page={page}' if page > 1 else '')
            html = fetch(url)
            data = decode_nuxt(html)['pinia']['search']['searchResult']
            meta = data['meta']['pagination']
            from parsers import _objects
            ids = {str(p['sku']) for p in _objects(data['data']) if p.get('sku') and 'name' in p}
            yield parse_hofer(html), ids, meta['totalCount'], f'Страница {page}', url
            if meta['offset'] + meta['limit'] >= meta['totalCount']:
                break
            if not ids or meta['offset'] != (page - 1) * meta['limit']:
                raise ValueError('HOFER не подтвердил переход к следующей странице')
            page += 1
            time.sleep(0.35)
    elif store == 'lidl':
        offset = 0
        while True:
            url = 'https://www.lidl.at/q/search?' + urlencode({'fetchSize': 60, 'offset': offset})
            html = fetch(url)
            data = decode_nuxt(html)['pinia']['useProductStore']
            # Earlier chunks are skeletons when offset > 0; they must not advance pagination.
            raw = [p for group in data['products'].values() for p in group
                   if p and (p.get('gridBox') or {}).get('gridBoxData')]
            ids = {str(p['gridBox']['gridBoxData']['productId']) for p in raw}
            yield parse_lidl(html), ids, data['numFound'], f'Товары {offset + 1}–{offset + len(raw)}', url
            offset += len(raw)
            if offset >= data['numFound']:
                break
            if not raw:
                raise ValueError('Lidl вернул пустую страницу до конца каталога')
            time.sleep(0.35)
    else:
        raise ValueError('Неизвестный магазин')
