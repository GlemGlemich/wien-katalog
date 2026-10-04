"""Overlapping product selections based on retailer labels, not inferred nutrition."""
import re
from categories import clean, classify, alcohol_kind

SELECTION_VERSION = 4
SELECTIONS = [
    {'id': 'sweet_drinks', 'flag': 1, 'label': 'Сладкие напитки',
     'description': 'Кола, соки, лимонады, холодный чай и энергетики. Включая Zero.'},
    {'id': 'protein', 'flag': 2, 'label': 'Продукты с протеином',
     'description': 'Батончики, десерты, напитки и другие продукты с пометками Protein или Eiweiß.'},
    {'id': 'milk', 'flag': 4, 'label': 'Молоко',
     'description': 'Обычное, Laktosefrei, Vollmilch и растительные напитки. Фильтры жирности и хранения.'},
    {'id': 'meat', 'flag': 8, 'label': 'Мясо и рыба',
     'description': 'Курица, свинина, говядина и другие виды. Куски, фарш, колбасы и готовые продукты.'},
    {'id': 'alcohol', 'flag': 16, 'label': 'Алкоголь',
     'description': 'Пиво, вино, игристое, крепкие напитки и коктейли. Сравнение цен за литр.'},
]

NONFOOD = re.compile(r'zooroyal|purina|whiskas|pedigree|sheba|vitakraft|tiernahrung|tierbedarf|nassfutter|trockenfutter|hundefutter|katzenfutter|\bkatzen?\b|\bhunde?\b|shampoo|haar|pflege|hygiene|dusch|kosmetik|reinig|waschmittel|weichspul|spulmittel|seife|beauty|bodylotion')
ALCOHOL = re.compile(r'bier|radler|\bwein\b|weisswein|rotwein|rosewein|spirituos|cocktail|likor|vodka|wodka|whisk|\bgin\b|\brum\b|sekt|prosecco|cider')
SWEET_DRINK = re.compile(r'limonad|softdrink|\bcola\b|pepsi|fanta|sprite|almdudler|schweppes|eistee|iced? tea|energy|red bull|monster|saft|safte|nektar|smoothie|happy day|cappy|fruchtgetrank|vitamingetrank|vitaminwasser|vitamin well|sportgetrank|gatorade|powerade|dreh.*trink|wasser mit geschmack|flavours|flavor|voslauer balance')
PROTEIN = re.compile(r'protein|eiwei(?:ss|ß)|\bwhey\b')


MILK_EXCLUDE = re.compile(r'joghurt|jogurt|kefir|buttermilch|sauermilch|dickmilch|milchreis|milchschnitt|milchsnack|pudding|dessert|topfen|kase|butter|obers|rahm|sahne|schokolade|schokotropf|schokorasp|schoko chips|kuverture|glasur|bake drops|keks|schnitten|pralin|konfekt|eiscreme|ice cream|\beis\b|anfangsmilch|folgemilch|kindermilch|milchpulver|babynahrung|milchfertignahrung|kaffeemilch|kondensmilch|flaschensauger')
PLANT_MILK = re.compile(r'haferdrink|sojadrink|mandeldrink|reisdrink|kokosdrink|erbsendrink|oatly|not.?milk|not.?m.?lk|hafermilch|sojamilch|mandelmilch|kartoffelmilch|milchalternative|kokos(?:nuss)?milch')
MEAT_NAMES = [
    ('game', r'\bwildschwein|\bwildfleisch|\bhirsch|\breh(?:\b|[a-z])|\bwild(?:brat|ragout|gulasch)'),
    ('chicken', r'\bhuhn|\bhuhner|\bhenne|\bhendl|\bhahnchen|\bchicken'),
    ('pork', r'\bschwein|\bpork'), ('beef', r'\brind|\bbeef'),
    ('turkey', r'\bpute|\btruthahn|\bturkey'), ('veal', r'\bkalb|\bveal'),
    ('lamb', r'\blamm|\blamb'), ('duck_goose', r'\bente|\bgans|\bganse|\bwachtel|\bperlhuhn'),
    ('fish', r'fisch|lachs|forelle|thunfisch|garnel|crevette|shrimp|hering|makrel|sardine|sardelle|kabeljau|dorsch|pangasius|zander|scholle|dorade|wolfsbarsch|heilbutt|tintenfisch|calamari|\bmuschel|miesmuschel|meeresfrucht|surimi'),
]
VEGGIE = re.compile(r'vegan|vegetar|veggie|vegavita|plant.?based|pflanzenbasis|fleischfrei|ohne fleisch|no.?chicken|beyond meat')
MEAT_EXCLUDE = re.compile(r'babynahrung|babybeikost|\bab \d+\.? monat|geschmack|\btaste\b|instant|basis.*fix|fix.*basis|bruhw[uu]rfel|bouillon|suppenpulver')
PROCESSED = re.compile(r'wurst|wurstel|wurste|schinken|speck|salami|frankfurter|knacker|krainer|landjager|leberkase|pariser|cabanossi|bacon|sulze|prosciutto|raucherlachs')


def product_details(product):
    name = clean(product.get('name') or '')
    category = clean(product.get('category_path') or product.get('category') or '')
    text = name+' '+category
    group = classify(product)
    if NONFOOD.search(text) and group != 'alcohol':
        return {}
    details = {}
    milk_category = any(c.strip() in ('milch', 'haltbar milch', 'milchalternativen') for c in re.split(r'[·/]',category))
    plant = bool(PLANT_MILK.search(name) or 'milchalternativen' in category)
    if not MILK_EXCLUDE.search(text) and (plant or milk_category or re.search(r'milch\b',name)):
        flavour = bool(re.search(r'schoko|kakao|vanille|banane|erdbeer|honigmilch|milchgetrank',name))
        details['milk_kind'] = 'plant' if plant else 'flavoured' if flavour else 'plain'
        details['milk_lactose'] = 'not_applicable' if plant else 'free' if re.search(r'lakto[sz]e.?frei|lactose.?free|minus\s*[-–]?\s*l\b|lakto.?free',text) else 'unmarked'
        fat = re.search(r'(?<!\d)(\d+(?:[.,]\d+)?)\s*%',name)
        value = float(fat[1].replace(',','.')) if fat else None
        details['milk_fat'] = ('not_applicable' if plant else
            ('whole' if value>=3.5 else 'light' if 1<=value<=2 else 'skim' if value<=.5 else 'other') if value is not None else
            'whole' if 'vollmilch' in name else 'light' if re.search(r'leicht|fettarm|teilentrahmt',name) else
            'skim' if re.search(r'magermilch|entrahmte milch',name) else 'unknown')
        details['milk_storage'] = ('uht' if re.search(r'haltbar|\bh[- ](?:voll|leicht|mager)?milch|\buht\b|ultrahocherhitzt',name+' '+('haltbar' if 'haltbar milch' in category else '')) else
            'esl' if re.search(r'langer.*frisch|\besl\b',name) else 'fresh' if re.search(r'frisch|rohmilch',name) else 'unknown')
    if group == 'alcohol':
        details['alcohol_kind'] = alcohol_kind(product)
    kinds = [key for key,pattern in MEAT_NAMES if re.search(pattern,name)]
    if not VEGGIE.search(text) and not MEAT_EXCLUDE.search(text) and (group == 'meat' or (group == 'prepared' and kinds)):
        if not kinds:
            # Remove broad departments that mention several species together.
            specific = re.sub(r'wurst,? fleisch & fisch|fleisch & fisch|fleisch & geflugel|frischfleisch & -?geflugel','',category)
            kinds = [key for key,pattern in MEAT_NAMES if re.search(pattern,specific)]
        kind = 'mixed' if len(kinds)>1 or re.search(r'faschiert.*gemischt|gemischt.*faschiert|hackfleisch.*gemischt',name) else kinds[0] if kinds else 'unknown'
        details['meat_kind'] = kind
        details['meat_form'] = ('minced' if re.search(r'faschiert|hackfleisch|burger.?patt',name) else
            'processed' if PROCESSED.search(name) else
            'prepared' if re.search(r'nugget|cordon.?bleu|pulled|sous.?vide|paniert|knodel|pizza|lasagne',name) else
            'cuts' if re.search(r'filet|brust|keule|schnitzel|steak|karree|gulasch|geschnetzel|braten|bratfertig|suppenfleisch|ripperl|kotelett',name) else 'unknown')
    return details


FACETS = {
    'alcohol': [
        ('alcohol_kind','Вид напитка',[('beer','Пиво и сидр'),('wine','Вино'),('sparkling','Игристое'),('spirits','Крепкие напитки и ликёры'),('mixed','Коктейли и миксы'),('other','Другой алкоголь')]),
    ],
    'milk': [
        ('milk_kind','Вид',[('plain','Молоко без добавок'),('flavoured','Со вкусом'),('plant','Растительные напитки')]),
        ('milk_lactose','Лактоза',[('free','Laktosefrei · без лактозы'),('unmarked','Без отметки Laktosefrei')]),
        ('milk_fat','Жирность',[('whole','Vollmilch · цельное'),('light','Нежирное · 1–2%'),('skim','Обезжиренное · до 0,5%'),('other','Другая жирность'),('unknown','Не указана')]),
        ('milk_storage','Хранение',[('fresh','Frisch · свежее'),('esl','Länger frisch · ESL'),('uht','H-Milch · длительное'),('unknown','Не указано')]),
    ],
    'meat': [
        ('meat_kind','Вид мяса',[('chicken','Курица'),('pork','Свинина'),('beef','Говядина'),('turkey','Индейка'),('veal','Телятина'),('lamb','Баранина'),('duck_goose','Утка, гусь и другая птица'),('game','Дичь'),('mixed','Смешанное мясо'),('fish','Рыба и морепродукты'),('unknown','Вид не указан')]),
        ('meat_form','Форма продукта',[('cuts','Куски, филе и тушки'),('minced','Фарш'),('processed','Колбасы и копчёности'),('prepared','Подготовленные блюда'),('unknown','Другое / не указано')]),
    ],
}


def selection_flags(product, details=None):
    name = clean(product.get('name') or '')
    category = clean(product.get('category_path') or product.get('category') or '')
    text = name + ' ' + category
    group = classify(product)
    if NONFOOD.search(text) and group != 'alcohol':
        return 0
    flags = 2 if PROTEIN.search(text) else 0
    if group == 'drinks' and not ALCOHOL.search(text) and SWEET_DRINK.search(text):
        flags |= 1
    details = product_details(product) if details is None else details
    if 'milk_kind' in details:
        flags |= 4
    if 'meat_kind' in details:
        flags |= 8
    if 'alcohol_kind' in details:
        flags |= 16
    return flags
