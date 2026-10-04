"""Conservative layout extraction from the text layer of official leaflet PDFs.

Names, price labels and their conditions must form an unambiguous local group.
Uncertain groups are omitted, not filled with catalogue prices.
"""
import hashlib
import json
import re
from datetime import date

from flyers import date_range
from offer_model import clean, cents, make_offer, measure


def box(words):
    return {'x0': min(w['x0'] for w in words), 'x1': max(w['x1'] for w in words),
            'top': min(w['top'] for w in words), 'bottom': max(w['bottom'] for w in words)}


def lines(words):
    """Rebuild nearby words without reading across unrelated columns."""
    rows = []
    for w in sorted(words, key=lambda w: (round(w['top']), w['x0'])):
        row = next((r for r in reversed(rows[-12:]) if abs(r[0]['top']-w['top']) < 2
                    and -1 <= w['x0']-r[-1]['x1'] < max(16, w['size']*2)), None)
        if row is None:
            rows.append([w])
        else:
            row.append(w)
    def text(row):
        result = row[0]['text']
        for prev,w in zip(row,row[1:]):
            result += ('' if w['x0']-prev['x1'] < .8 else ' ')+w['text']
        return clean(result)
    return [dict(box(row), words=row, text=text(row)) for row in rows]


def paragraphs(words, max_width):
    groups = []
    for line in sorted(lines(words), key=lambda l: (l['top'], l['x0'])):
        choices = []
        for g in groups:
            overlap = min(g['x1'], line['x1'])-max(g['x0'], line['x0'])
            gap = line['top']-g['bottom']
            if (-1 <= gap <= 5 and (overlap > 1 or abs(g['x0']-line['x0']) < 10 or abs(g['x1']-line['x1']) < 10)
                    and max(g['x1'], line['x1'])-min(g['x0'], line['x0']) < max_width):
                choices.append((gap, g))
        if choices:
            g = min(choices, key=lambda v: v[0])[1]
            g['words'].extend(line['words'])
            g.update(box(g['words']))
            g['text'] += ' ' + line['text']
        else:
            groups.append(line)
    return groups


def name_word(w, store):
    font, size = w['fontname'], w['size']
    if store == 'billa':
        return 'Axiforma-Black' in font and 7 <= size <= 11
    if store == 'hofer':
        return 'ALDISUEDOT-Bold' in font and 9 <= size <= 10.1
    if store == 'spar':
        return 'Gilroy-Bold' in font and 7.9 <= size <= 9.05
    return 'LidlFontCondPro-Bold' in font and 8 <= size <= 13


def body_word(w, store):
    font, size = w['fontname'], w['size']
    if store == 'billa':
        return 'Axiforma-Medium' in font and 6 <= size <= 7
    if store == 'hofer':
        return 'ALDISUEDOT-Regular' in font and 7 <= size <= 8.2
    if store == 'spar':
        return 'Gilroy-Regular' in font and 7.8 <= size <= 9.2
    return 'LidlFontCondPro-Regular' in font and 7 <= size <= 10


def price_labels(words, store):
    labels = []
    for w in words:
        text = clean(w['text'])
        if store == 'billa':
            if 'Axiforma-Black' not in w['fontname'] or w['size'] < 30 or not re.fullmatch(r'\d{1,3}', text):
                continue
            tails = [t for t in words if 'Axiforma-Black' in t['fontname']
                     and re.fullmatch(r'\d{2}', t['text']) and .4 < t['size']/w['size'] < .65
                     and -5 < t['x0']-w['x1'] < 15 and abs(t['top']-w['top']) < 8]
            if len(tails) != 1:
                continue
            t = tails[0]
            labels.append(dict(box([w, t]), price=int(text)*100+int(t['text']), words=[w, t]))
        else:
            font_ok = ('ALDISUEDOT-Black' in w['fontname'] if store == 'hofer' else
                       'Gilroy-Bold' in w['fontname'] if store == 'spar' else 'LidlFontPrice' in w['fontname'])
            if font_ok and w['size'] >= (20 if store == 'lidl' else 22) and re.fullmatch(r'\d{1,3}[.,]\d{2}', text):
                labels.append(dict(box([w]), price=cents(text), words=[w]))
    return [p for p in labels if p['price'] > 0]


def distance(a, b):
    dx = max(a['x0']-b['x1'], b['x0']-a['x1'], 0)
    dy = max(a['top']-b['bottom'], b['top']-a['bottom'], 0)
    return dx + dy*1.3


def reference_prices(body):
    result = []
    body = re.sub(r'(\d*[.,]\d{2})\s*/\s*(\d*[.,]\d{2})', r'\2', body)
    for m in re.finditer(r'(?:(1|100)\s*(kg|l|Liter|g|ml)\s*=?\s*|Mit Lidl Plus\s*)(\d*[.,]\d{2})(?!\d)', body, re.I):
        member = m[0].lower().startswith('mit')
        scale = 10 if m[1] == '100' else 1
        result.append((float(('0'+m[3]).replace(',', '.'))*scale, member))
    return result


def page_dates(page, store, flyer):
    # Header/footer dates, excluding print production timestamps and product sizes.
    words = [w for w in page['words'] if (w['top'] < page['height']*.25 or w['top'] > page['height']*.85)
             and w['size'] >= (12 if store in ('lidl', 'hofer') else 13)]
    text = ' '.join(l['text'] for l in lines(words))
    start, end = flyer['valid_from'], flyer['valid_to']
    pattern = r'(?:\d{1,2})\.\s*(?:\d{1,2})\.'
    if len(re.findall(pattern, text)) >= 2:
        try:
            a, b = date_range(text, start)
            start, end = max(start, a), min(end, b)
        except ValueError:
            pass
    elif re.search(r'\bAb\b', text, re.I) and re.search(pattern, text):
        token = re.search(pattern, text)[0]
        try:
            a, _ = date_range(token+' bis '+token, start)
            start = max(start, a)
        except ValueError:
            pass
    return start, end


def parse_page(page, store, flyer):
    width, height = page['width'], page['height']
    words = [w for w in page['words'] if 0 <= w['x0'] < width and 0 <= w['top'] < height and w['x1'] <= width+2]
    names = paragraphs([w for w in words if name_word(w, store)], width*.38)
    bodies = paragraphs([w for w in words if body_word(w, store)], width*.4)
    prices = price_labels(words, store)
    start, end = page_dates(page, store, flyer)
    if start > end:
        return [], len(prices)
    # Multiple alternate weekday prices in one tile need a richer template.
    if store == 'billa' and re.search(r'DO,?\s*MO\s*[–-]\s*MI', page['text']):
        return [], len(prices)
    if store == 'spar' and re.search(r'SPAR.?App|Joker|Gutschein', page['text'], re.I):
        return [], len(prices)
    if store == 'hofer' and 'HOFER ONLINESHOP' in page['text']:
        return [], len(prices)
    valid_names = []
    for n in names:
        if (len(n['text']) < 3 or len(n['text']) > 200 or not re.search(r'[A-Za-zÄÖÜäöüß]{3}',n['text']) or
                re.search(r'gültig|HOFER\s*\||\bAKTION|\bTIEFPREIS|\bBEI\b|\bJE\b|GÜNSTIGER|^Nur |^aus |^hergestellt|Österreich\.$', n['text'], re.I)):
            continue
        if sum(len(t) == 1 for t in n['text'].split()) > len(n['text'].split())*.6:
            continue
        if re.match(r'^(?:in Selbstbedienung|per\s|saftig\b|natur,|mit Knochen)',n['text'],re.I):
            continue
        near = [b for b in bodies if -2 <= b['top']-n['bottom'] < 13
                and (min(n['x1'], b['x1']) > max(n['x0'], b['x0']) or abs(b['x0']-n['x0']) < 12)]
        body = min(near, key=lambda b: distance(n, b)) if near else None
        n['body'] = body['text'] if body else ''
        n['fullbox'] = dict(box(n['words']+(body['words'] if body else [])))
        if store == 'hofer':
            brand = [w for w in words if 'ALDISUEDOT-Bold' in w['fontname'] and 5.5 <= w['size'] <= 6.5
                     and 0 < n['top']-w['bottom'] < 12 and n['x0']-3 <= w['x0'] <= n['x1']]
            if brand:
                n['text'] = clean(' '.join(w['text'] for w in sorted(brand,key=lambda w:w['x0']))+' '+n['text'])
        valid_names.append(n)
    # Score every plausible pair, then require a unique local assignment.
    pairs = []
    for ni, n in enumerate(valid_names):
        amount, unit, _ = measure(n['body'])
        refs = reference_prices(n['body'])
        for pi, p in enumerate(prices):
            dist = distance(n['fullbox'], p)
            if dist > width*(.72 if store == 'hofer' else .48 if store == 'lidl' else .30):
                continue
            if store == 'billa' and p['x1'] < n['x0']-3:
                continue
            if store in ('hofer','lidl'):
                if int(n['x0']/(width/2)) != int(((p['x0']+p['x1'])/2)/(width/2)):
                    continue
                if any(other['top'] > n['bottom']+10 and other['top'] < p['top']-8
                       and int(other['x0']/(width/2)) == int(n['x0']/(width/2)) for other in valid_names):
                    continue
            if store == 'billa' and n['top'] > p['bottom']+10:
                continue
            if store == 'hofer' and p['top'] < n['top']-12:
                continue
            verified_unit = False
            member_ref = False
            pair_refs = refs
            if store == 'spar':
                nearby = clean(' '.join(w['text'] for w in sorted(words,key=lambda w:(round(w['top']/3),w['x0']))
                              if p['x0']-20 <= w['x0'] <= p['x1']+20 and p['bottom']-10 <= w['top'] <= p['bottom']+35))
                pair_refs = [(float(v.replace(',','.')),False) for v in re.findall(r'per\s*(?:Liter|kg)\s*(\d+[.,]\d{2})',nearby,re.I)]
            if pair_refs and amount and unit:
                expected = p['price']/100/amount
                matched = [(ref,member) for ref,member in pair_refs if abs(expected-ref) <= max(.025, ref*.015)]
                if not matched:
                    continue
                member_ref = matched[0][1]
                verified_unit = True
            # Only publish the simpler, measurable templates. Other tiles remain in the original.
            if not amount or (unit == 'l' and amount < .02) or (store in ('lidl','spar') and not verified_unit):
                continue
            cxn=(n['x0']+n['x1'])/2
            cxp=(p['x0']+p['x1'])/2
            score=dist + abs(cxn-cxp)*.08 - (width*.03 if verified_unit else 0)
            pairs.append((score, ni, pi, verified_unit, member_ref))
    used_names, used_prices, offers = set(), set(), []
    for score, ni, pi, verified, member_ref in sorted(pairs):
        if (ni in used_names and store != 'lidl') or pi in used_prices:
            continue
        n,p=valid_names[ni],prices[pi]
        # Another nearby name with almost the same score makes the mapping uncertain.
        rivals=[s for s,nj,pj,v,m in pairs if pj==pi and nj!=ni and nj not in used_names]
        if rivals and min(rivals)-score < 3:
            continue
        if store=='billa':
            local=[w for w in words if p['x0']-24 <= w['x0'] and w['x1'] <= p['x1']+28
                   and p['top']-115 <= w['top'] <= p['bottom']+10 and not name_word(w,store) and not body_word(w,store)]
        else:
            local=[w for w in words if p['x0']-width*.045 <= w['x0'] and w['x1'] <= p['x1']+width*.08
                   and p['top']-height*.115 <= w['top'] <= p['bottom']+height*.055
                   ]
        local_lines=lines(local)
        conditions=' '.join(l['text'] for l in sorted(local_lines,key=lambda l:(l['top'],l['x0'])))
        if store == 'hofer':
            refs = re.findall(r'(\d+[.,]\d{2})\s*/\s*(Liter|kg|100\s*g|0[.,]5\s*Liter)', conditions, re.I)
            amount, unit, _ = measure(n['body'])
            if refs:
                values = [float(v.replace(',','.'))*(10 if u.lower().startswith('100') else 2 if u[0]=='0' else 1) for v,u in refs]
                expected = p['price']/100/amount
                if not any(abs(expected-v) <= max(.04,v*.02) for v in values):
                    continue
        minimum_matches=[(l['top'],m) for l in local_lines if (m:=re.search(r'\b(?:ab|bei)\s+(\d+)\s+(?!g\b|kg\b|ml\b|l\b)',l['text'],re.I))]
        minimum=int(max(minimum_matches,key=lambda x:x[0])[1][1]) if minimum_matches else 1
        rules=[dict(l,rule=m[1]+'+'+m[2]) for l in local_lines if (m:=re.search(r'(?<!\d)(\d+)\s*\+\s*(\d+)(?!\d)',l['text']))]
        # SPAR's tilted promo lettering can put each digit on a separate baseline.
        for plus in local:
            if plus['text'] != '+' or plus['size'] < 12:
                continue
            left=[w for w in local if re.fullmatch(r'\d{1,2}',w['text']) and abs(w['x1']-plus['x0'])<5 and abs(w['top']-plus['top'])<6]
            right=[w for w in local if re.fullmatch(r'\d{1,2}',w['text']) and abs(w['x0']-plus['x1'])<5 and abs(w['top']-plus['top'])<6]
            if len(left)==1 and len(right)==1:
                rules.append(dict(box([left[0],plus,right[0]]),rule=left[0]['text']+'+'+right[0]['text']))
        rule=min(rules,key=lambda w:distance(w,p))['rule'] if rules else ''
        if store == 'hofer' and not refs and not rule:
            continue
        if rule and not minimum_matches:
            minimum=sum(map(int,rule.split('+')))
        if minimum > 100:
            continue
        member=member_ref or bool(re.search(r'Lidl\s*Plus|SPAR[- ]App|Gutschein|jö\b|nur.*App',conditions,re.I))
        if store == 'lidl' and 'Mit Lidl Plus' in n['body']:
            member = member_ref
        # A reference price for both regular and member prices must not silently pick one.
        evidence=' | '.join([n['text'],n['body'],conditions])
        try:
            row=make_offer(store=store,flyer=flyer,page=page['number'],name=n['text'],price=p['price'],
                           size=n['body'],promo=rule or conditions,minimum=minimum,member=member,
                           start=start,end=end,evidence=evidence,confidence='unit_checked' if verified else 'layout')
        except ValueError:
            continue
        row['id']=hashlib.sha256((flyer['id']+str(page['number'])+n['text']+str(p['price'])+str(minimum)).encode()).hexdigest()[:24]
        row['bbox']=[round(n['fullbox']['x0']/width,4),round(n['fullbox']['top']/height,4),round(p['x1']/width,4),round(p['bottom']/height,4)]
        if store=='lidl':
            row['source_url']=flyer['url'].rstrip('/')+'?page='+str(page['number'])
        if store=='spar':
            row['source_url']=flyer['url'].rstrip('/')+'/?page='+str(page['number'])
        if 'Pfand' in n['body']:
            row['deposit_note']=n['body'][n['body'].find('zzgl.'):]
        offers.append(row)
        used_names.add(ni);used_prices.add(pi)
    return offers, max(0,len(prices)-len(used_prices))


def parse_pages(pages, store, flyer):
    rows, omitted = [], 0
    for page in pages:
        found, skipped=parse_page(page,store,flyer)
        rows.extend(found);omitted+=skipped
    # Duplicate cover/inside offers have the same conditions and date. Prefer inside page.
    dedup={}
    for row in rows:
        key=(row['name'],row['price_cents'],row['size'],row['min_quantity'],row['valid_from'],row['valid_to'],row['membership_required'])
        dedup[key]=row
    return list(dedup.values()), omitted


def read_pdf(path):
    try:
        import pdfplumber
    except ImportError as error:
        raise ValueError('Для чтения товаров из PDF установите зависимости из requirements.txt.') from error
    pages=[]
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages)>160:
            raise ValueError('Слишком большой флюгблатт для чтения.')
        for number,page in enumerate(pdf.pages,1):
            page=page.dedupe_chars()
            words=page.extract_words(x_tolerance=1.5,y_tolerance=2,extra_attrs=['fontname','size'])
            pages.append({'number':number,'width':page.width,'height':page.height,'words':words,
                          'text':page.extract_text(x_tolerance=2,y_tolerance=3) or ''})
    return pages
