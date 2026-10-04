"""Small, shared taxonomy for the different German retailer catalogues."""
import re
import unicodedata

CATEGORY_VERSION = 3
CATEGORIES = [
    ('drinks', 'Напитки'),
    ('alcohol', 'Алкоголь'),
    ('sweets', 'Сладкое и снеки'),
    ('produce', 'Овощи и фрукты'),
    ('dairy', 'Молочное и яйца'),
    ('meat', 'Мясо и рыба'),
    ('pantry', 'Хлеб и бакалея'),
    ('prepared', 'Готовая еда'),
    ('other', 'Другое'),
]


def clean(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text).casefold()) if not unicodedata.combining(c))


def pattern(words):
    return re.compile(words)


# Prefer retailer departments over product-name ingredients: chocolate milk is
# dairy; cat food and coconut shampoo must not become food categories.
HOME = pattern(r'haustier|tiernahrung|tierbedarf|\btiere\b|katze|\bhunde?\b|hundefutter|katzenfutter|nassfutter|trockenfutter|menuschalen|haushalt|kuche & tisch|kuche & haushalt|\bkuche\b|beauty|drogerie|pflege|hygiene|reinig|waschmittel|weichspul|shampoo|dusch|deodor|zahn|mund &|haut|kosmetik|rasur|gesicht|haare|haarfarb|windel|feuchttuch|damenschutz|slipeinlag|tampon|binde\b|putz|bekleidung|textilien|mode &|schuhe|socken|strumpf|baumarkt|werkzeug|wohnen|einrichtung|gartengerat|gartenwerkzeug|pflanzen|blumen|spielware|spielzeug|spiel(e|en)|\bbucher\b|papier, schule|buro|kochen & backen|kochgeschirr|geschirr|kuhlschrank|elektro|batterie|kerze|grablicht|vorratsdose|glasdose|backform|kaffeemaschine|kaffeevollautomat|kaffeefilter|kaffeemuhle|teefilter|\bteelicht|\btasse\b|kuchenrolle|toilettenpapier|kuchengerat|insekten|fussel|entkalk|mullsack|simpex|workzone|scheppach|komposter|pantoffel|bettwasche')
DAIRY = pattern(r'molkerei|milchprodukte|milch(?!schokol)|joghurt|jogurt|topfen|schlagobers|\bobers\b|\brahm\b|\bsahne\b|frischkase|huttenkase|weichkase|hartkase|schnittkase|schmelzkase|\bkase\b|\beier\b|eier aus|eierhaltung|\bbutter\b|margarine|butterschmalz|kasealternative')
MEAT = pattern(r'fleisch|fisch|meeresfrucht|\bwurst|wurstwaren|schinken|speck|geflugel|\bschwein|\brind|\bkalb|lamm|wildfleisch|aufschnitt|wurstel|wurste|wurstchen|surimi|lachs|garnelen|thunfisch|scholle|kabeljau|hering|sardinen|sardellen|forelle|pangasius|leberkase|extrawurst|salami|bratwurst|krainer|landjager|leberwurst')
DRINKS = pattern(r'getrank|softdrink|limonade|\bcola\b|\bsafte\b|saft|smoothie|nektar|mineralwasser|tafelwasser|\bwasser\b|energydrink|eistee|\btee\b|krautertee|fruchtetee|schwarztee|gruntee|kaffee|cappuccino|espresso|ganze bohne|kapseln & pads|\bbier\b|flaschenbier|dosenbier|radler|cider|\bwein\b|rotwein|weisswein|rosewein|sekt|schaumwein|champagner|spirituosen|whisk|cognac|aperitif|digestif|\brum\b|\bgin\b|vodka|wodka|likor|schnaps|edelbrand|sirupe|sirup|\bkakao\b|malzgetrank')
SWEETS = pattern(r'susswaren|sussigkeiten|susses|susse|schokol|schokowaren|kekse|biskott|pralinen|dragee|bonbon|pastillen|fruchtgummi|zuckerl|knabber|\bchips\b|\bsnips\b|nusse|kerne|trockenfrucht|trockenobst|riegel|kuchen|muffin|konditorei|torte|brioche|plunder|striezel|\beis\b|eiscreme|eisbecher|mehlspeisen|snacks|popcorn|waffel|wafers|gummib|toffifee|nutella')
PREPARED = pattern(r'fertiggericht|schnelle kuche|pizza|sandwich|antipasti|to go|pommes|kroketten|nuggets|kartoffelprodukte|gefullte teigwaren|tortellini|ravioli|lasagne|gnocchi|knodel|spatzle|fertigsalat|frische pasta|quiche|sushi')
PANTRY = pattern(r'vorrat|lebensmittelvorrat|grundnahrungsmittel|beilagen|basisprodukt|backzutaten|backen|mehl|getreide|reis|pasta|nudel|teigwaren|brot|backwaren|backerei|bakerei|backbox|geback|semmel|toast|baguette|wrap|muesli|musli|cerealien|fruhstuck|konserve|eingeleg|sauerwaren|essig|\bole\b|\bol\b|fette|gewurz|sauce|sossen|sosse|dressing|sugo|ketchup|mayonnaise|senf|salz|zucker|honig|marmelade|konfiture|aufstrich|pastete|hulsenfrucht|kochzutaten|\basien\b|asia|orient|mexik|\bteig\b|blatterteig|strudelteig|semmelwurfel|nahrungserganz|reform|ernahrung|babynahrung|babybrei')
PRODUCE = pattern(r'obst|gemuse|frischobst|frischgemuse|gartengemuse|wurzelgemuse|kartoffel|salate|\bsalat\b|\bpilze\b|krauter|apfel|birne|banane|zitrus|beeren|trauben')


ALCOHOL_KINDS = [
    ('mixed', r'\bcocktails?\b|\blongdrinks?\b|\bspritz(?:er)?\b|sangria|hard.?seltzer|\bpre.?mixe?s?\b|\bgin[ &-]*(?:tonic|lemon)\b|\brum[ &-]*cola\b'),
    ('sparkling', r'\bsekt\b|prosecco|schaumwein|champagn|\bcava\b|spumante|frizzante|perlwein|sparkling'),
    ('beer', r'\bbier\b|flaschenbier|dosenbier|weizenbier|\bradler\b|\bmarzen\b|\bhelles\b|\bpils(?:ner)?\b|\blager\b|\bipa\b|\bcider\b|apfelwein|\bgosser\b|\bstiegl\b|ottakringer|heineken|wieselburger|zwettler|eggenberg|\bzipfer\b|schwechater|murauer|budweiser'),
    ('spirits', r'spirituos|likor|vodka|wodka|whisk(?:y|ey)|cognac|\bbrandy\b|branntwein|schnaps|schnapse|edelbrand|tequila|\bgin\b|\brum\b|inlanderrum|amaretto|grappa|\bouzo\b|\braki\b|aquavit|sambuca|limoncello|jagermeister|aperol|campari|baileys|fernet|bacardi|havana club|malibu|bombay'),
    ('wine', r'\bwein\b|rotwein|weisswein|rosewein|dessertwein|portwein|gluhwein|veltliner|zweigelt|chardonnay|riesling|cabernet|merlot|blaufrankisch|sauvignon|rioja|chianti|muskateller|grauburgunder|weissburgunder|blauburgunder|\bpinot\b'),
]
ALCOHOL_FREE = pattern(r'alkoholfrei|alkohol.?free|ohne alkohol|entalkoholis|non.?alcohol|\b0[.,]0\b')
ALCOHOL_FOOD = pattern(r'essig|essenz|aroma|schoko|pralin|bonbon|fruchtgummi|riegel|marzipan|\bgerm\b|marinade|sauce|sosse|gewurz|\bkase\b|fleisch|wurst|salami|nassfutter|trockenfutter|katzen|hundefutter|reiniger|shampoo|dusch|pflege|kosmetik|glaser|weinglas|bierglas|nahrungserganz')


def alcohol_kind(product):
    name = clean(product.get('name') or '')
    category = clean(product.get('category_path') or product.get('category') or '')
    # This section contains drinks; gram-based products include sweets, tea
    # mixes and canned fruit even when retailer categories mention alcohol.
    if re.search(r'\b(?:kg|gramm|g)\b',clean(product.get('unit') or '')):
        return None
    if ALCOHOL_FREE.search(name+' '+category) or HOME.search(category) or ALCOHOL_FOOD.search(category):
        return None
    if re.search(r'zooroyal|purina|whiskas|pedigree|sheba|vitakraft',name):
        return None
    # Remove broad parent sections before deciding a subtype; Lidl's parent
    # mentions wine, beer and spirits together, SPAR's includes sparkling wine.
    specific = re.sub(r'wein,? bier und spirituosen|wein & schaumwein','',category)
    known_category = any(re.search(regex,category) for _,regex in ALCOHOL_KINDS)
    if not known_category:
        if ALCOHOL_FOOD.search(name) or HOME.search(name) or any(p.search(category) for p in (DAIRY,MEAT,PANTRY,PRODUCE,SWEETS)):
            return None
        if re.search(r'softdrink|limonad|tonic & bitter|\bsafte\b|saftgetrank|mineralwasser',category):
            return None
    # A specific sparkling-wine or premix department is more informative than
    # a grape variety or spirit mentioned in the product name.
    for kind,regex in ALCOHOL_KINDS[:2]:
        if re.search(regex,specific):
            return kind
    for text in (name,specific):
        for kind,regex in ALCOHOL_KINDS:
            if re.search(regex,text):
                return kind
    return 'other' if known_category else None


def classify(product):
    name = clean(product.get('name') or '')
    category = clean(product.get('category_path') or product.get('category') or '')
    # The generic PENNY "Schnelle Küche" and food-side dressing categories
    # contain the same words as household departments, so check exact phrases.
    household_category = category.replace('schnelle kuche', '').replace('internationale kuche', '').replace('kuchenkrauter', '').replace('pflanzenbasis', '')
    if re.search(r'zooroyal|purina|whiskas|pedigree|sheba|dreamies|vitakraft|katzenfutter|hundefutter', name):
        return 'other'
    if HOME.search(household_category):
        return 'other'
    if alcohol_kind(product):
        return 'alcohol'
    if category.strip() in ('still', 'prickelnd', 'mild', 'naturlicher fruchtsaft'):
        return 'drinks'
    if re.search(r'backpulver|backhilfen|puddingpulver|geliermittel|hefe|natron|basis.? & fix|fixprodukt', category):
        return 'pantry'
    if re.search(r'fertiggericht|schnelle kuche|pizza|pommes|kroketten|sandwich|antipasti|to go|knodel|nockerl', category):
        return 'prepared'
    if DAIRY.search(category):
        return 'dairy'
    if DRINKS.search(category):
        return 'drinks'
    if SWEETS.search(category):
        return 'sweets'
    if MEAT.search(category):
        return 'meat'
    if PANTRY.search(category):
        return 'pantry'
    if PRODUCE.search(category):
        return 'produce'
    if PREPARED.search(category):
        return 'prepared'
    # Names are a fallback for missing or promotional categories like Weihnachten.
    household_name = name.replace('sonnenblumenol', '').replace('sonnenblumenkerne', '').replace('pflanzenbasis', '')
    if HOME.search(household_name):
        return 'other'
    if re.search(r'suppe|eintopf|nockerl', name):
        return 'prepared'
    if re.search(r'sodawasser|\bsoda[ -]|kefir', name):
        return 'dairy' if 'kefir' in name else 'drinks'
    if PREPARED.search(name):
        return 'prepared'
    if re.search(r'kasekrainer|kasewurst|leberkase|kaseleberkase', name):
        return 'meat'
    if re.search(r'schokolade|schokoriegel|milka|toffifee|pocket coffee|pain au chocolat|butterkeks|buttercroissant|waffel|knabber|popcorn|snack fun|pufuleti', name):
        return 'sweets'
    if re.search(r'brot|geback|semmel|toast(?!schinken)|baguette|wrap|spaghetti|penne|fusilli|farfalle|tagliatelle|haferflocken|mehl|maisstarke|sonnenblumenol|olivenol|rapsol', name):
        return 'pantry'
    if MEAT.search(name) or re.search(r'hendl|chicken|puten|knacker|\btann\b', name):
        return 'meat'
    if DAIRY.search(name) or re.search(r'gouda|emmentaler|mozzarella|parmesan|feta|brie|camembert|philadelphia|cheddar|skyr|haferdrink|sojadrink|mandeldrink', name):
        return 'dairy'
    if DRINKS.search(name) or re.search(r'coca.cola|pepsi|fanta|sprite|red bull|cappy|rauch happy day|almdudler|vöslauer', name):
        return 'drinks'
    if SWEETS.search(name) or re.search(r'mandel|cashew|pistazie|erdnuss|haselnuss|walnuss|cranberr|dattel|rosinen', name):
        return 'sweets'
    if PANTRY.search(name):
        return 'pantry'
    if PRODUCE.search(name) or re.search(r'fenchel|gurke|tomate|paprika|avocado|zucchini|melanzani|brokkoli|karotte|blumenkohl|zwiebel|knoblauch|champignon|kurbi|orange|zitrone|mandarine|mango|ananas|kiwi|pfirsich|nektarine|marille|zwetsch|pflaume|melone|ingwer|spinat|fisolen|erbsen|porree|lauch', name):
        return 'produce'
    return 'other'
