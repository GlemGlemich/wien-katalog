'use strict';
const $ = id => document.getElementById(id);
const count = n => new Intl.NumberFormat(locale()).format(n);
const euros = n => new Intl.NumberFormat(locale(), {style:'currency', currency:'EUR'}).format(n);
const names = {spar:'SPAR', billa:'BILLA', hofer:'HOFER', penny:'PENNY', lidl:'Lidl'};
let selected = 'all', category = 'all', page = 1, lastState = null, request = 0, searchTimer, lastSignature = '';
let view = location.hash === '#shopping' ? 'shopping' : location.hash === '#flugblatt' ? 'flyers' : location.hash === '#selected' ? 'selections' : 'catalog', flyersState = null, flyersLoading = false;
let selection='sweet_drinks', detailFilters={};
let comparisonOpen=false, comparisonRequest=0;
let productController=null, comparisonController=null;
const productFilters={catalog:{category:'all',q:'',period:'current',sort:'name',discount:false},selections:{category:'all',q:'',period:'current',sort:'updated',discount:false}};
function node(tag, className, text) { const el = document.createElement(tag); if(className) el.className = className; if(text !== undefined) el.textContent = text; return el; }
function safeUrl(value) { try { const u = new URL(value); return u.protocol === 'https:' ? u.href : ''; } catch { return ''; } }
function shortDate(value) { if(!value) return ''; return new Date(value.length === 10 ? value + 'T12:00:00Z' : value).toLocaleDateString(locale(),{day:'2-digit', month:'2-digit', timeZone:'Europe/Vienna'}); }
function timeLabel(value) { if(!value) return ''; return new Date(value).toLocaleString(locale(),{day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', timeZone:'Europe/Vienna'}); }
function notice(text, progress=false) { $('message').textContent = t(text); $('message').className = text ? 'message' + (progress ? ' progress' : '') : 'message hidden'; }
async function json(url, options) { const response=await fetch(url,options); const data=await response.json(); if(!response.ok) throw new Error(t(data.error) || t("Не удалось загрузить данные")); return data; }
function renderStores(state) {
  const nav=$('stores'); nav.replaceChildren();
  const scope = view === 'flyers' ? (window.offerMode==='books'?flyersState:window.offerSummary||flyersState) : state;
  for(const [id,name,amount] of [['all',t("Все магазины"),scope?.total ?? 0],...state.stores.map(s=>[s.store,s.name,scope?.stores.find(row=>row.store===s.store)?.count ?? 0])]) {
    const b=node('button','store'+(id===selected?' selected':'')); b.dataset.store=id; b.setAttribute('aria-pressed',String(id===selected));
    b.append(node('span','store-symbol '+(id==='all'?'all-symbol':'symbol-'+id),id==='all'?'▦':name.slice(0,2).toUpperCase()),node('span','',name),node('span','count',count(amount)));
    b.onclick=()=>{selected=id;page=1;productHeading();renderStores(lastState);renderSummary(lastState);if(view==='flyers'){renderFlyers();window.loadOffers?.(true);}else loadProducts();};nav.append(b);
  }
}
function renderSummary(state) {
  const scope=selected==='all'?state.stores:state.stores.filter(s=>s.store===selected);
  $('total').textContent=count(scope.reduce((n,s)=>n+s.count,0));$('today-total').textContent=count(scope.reduce((n,s)=>n+s.current_count,0));
  const running=state.stores.filter(s=>s.status==='running'); const errors=state.stores.filter(s=>['error','interrupted'].includes(s.status));
  $('refresh').disabled=state.busy;$('refresh').classList.toggle('spinning',state.busy);$('refresh').querySelector('span').textContent=state.busy?t("Считываем…"):view==='selections'?t("Обновить цены"):selected==='all'?t("Считать цены"):t("Обновить ")+names[selected];
  if(state.busy) {
    $('sync-label').textContent=t("Каталоги загружаются");
    notice(running.length?running.map(s=>`${s.name}: ${count(s.processed)}${s.total?' / '+count(s.total):''}`).join(' · '):t("Подключаемся к магазинам…"),true);
  } else if(errors.length) {
    $('sync-label').textContent=t("Не все источники обновлены");
    const reasons=[...new Set(errors.map(s=>t(s.error)).filter(Boolean))];
    notice(reasons.length===1?t("Не удалось обновить ")+errors.map(s=>s.name).join(', ')+'. '+reasons[0]:t("Не завершено: ")+errors.map(s=>s.name).join(', ')+t(". Подробности — в состоянии источников. Полученные товары доступны."));
  } else {
    const dates=state.stores.map(s=>s.last_success).filter(Boolean).sort();
    $('sync-label').textContent=dates.length?t("Последняя загрузка ")+timeLabel(dates.at(-1)):t("Готов к первой загрузке");
    if(dates.length && Date.now()-new Date(dates[0]).getTime()>86400000)notice(t("Часть цен проверялась больше суток назад. Нажмите «Считать цены», чтобы обновить каталог."));else notice('');
  }
  const panel=$('sources-panel');panel.replaceChildren();
  for(const s of state.stores) {
    const row=node('div','source-row'), link=node('a','source-name',s.name);link.href=s.url;link.target='_blank';link.rel='noopener noreferrer';
    const desc=node('div','');desc.append(node('div','',s.total?t("{0} из {1} позиций сайта · с ценой {2}", count(s.processed), count(s.total), count(s.saved)):s.count?t("В этой попытке товары не получены · сохранено {0}", count(s.count)):t("Источник ещё не прочитан")),node('p','source-desc',t(s.scope)));
    if(s.unpriced)desc.append(node('p','source-desc',t("{0} позиций без опубликованной цены не включены.", count(s.unpriced))));
    if(t(s.error))desc.append(node('p','source-error',t(s.error)));
    const status=node('div','source-status');status.append(node('div',s.status==='complete'?'source-ok':'',t(s.progress)||t("Ожидает загрузки")));
    if(s.last_success)status.append(node('div','source-desc',t("Полностью: ")+timeLabel(s.last_success)));
    row.append(link,desc,status);panel.append(row);
  }
}
async function loadState() {
  try { const data=await json('/api/state');lastState=data;renderStores(data);renderSummary(data);
    const signature=data.stores.map(s=>[s.status,s.saved,s.count,s.finished_at].join(':')).join('|');
    if(signature!==lastSignature){lastSignature=signature;if(view==='shopping')window.loadShopping?.();else loadProducts();}
  } catch(e) {notice(t("Программа недоступна. Откройте «Запустить каталог.cmd», затем обновите страницу."));$('sync-label').textContent=t("Нет соединения");}
}
function renderProduct(p) {
  const tr=node('tr');const first=node('td');const product=node('div','product');
  const imageUrl=safeUrl(p.image);if(imageUrl) { const img=node('img','product-image');img.src=imageUrl;img.alt='';img.loading='lazy';img.width=65;img.height=68;img.referrerPolicy='no-referrer';img.onerror=()=>img.replaceWith(node('span','image-placeholder',names[p.store].slice(0,1)));product.append(img); } else product.append(node('span','image-placeholder',names[p.store].slice(0,1)));
  const info=node('div');info.append(node('div','product-name',p.name));if(p.category){const cat=p.category.split(' · ').filter(c=>c!=='Produkte').slice(0,2).join(' · ');info.append(node('div','category',cat));}
  const tags=productTags(p.details||{});if(tags.length){const list=node('div','product-tags');for(const tag of tags)list.append(node('span','',tag));info.append(list);}
  const actions=node('div','product-actions'),add=node('button','text-button shopping-add',t('В список'));
  add.onclick=()=>{if(window.addShoppingProduct?.(p)){add.textContent=t('Добавлено');setTimeout(()=>{add.textContent=t('В список');},1500);}};
  const compare=node('button','text-button product-match',t('В других магазинах'));compare.setAttribute('aria-haspopup','dialog');compare.onclick=()=>window.openProductMatches?.(p);
  const history=node('button','text-button product-history',t('История цен'));history.setAttribute('aria-haspopup','dialog');history.onclick=()=>window.openPriceHistory?.(p);
  actions.append(add,compare,history);info.append(actions);product.append(info);first.append(product);
  const store=node('td');store.append(node('span','store-badge symbol-'+p.store,names[p.store]));
  const unit=node('td','unit',p.unit||t("Не указано"));
  const quantity=p.quantity||{},basis=$('price-basis').value,comparing=basis!=='pack'&&quantity.measure===basis&&quantity.unit_price;
  const measureLabel=quantity.measure==='kg'?t("кг"):t("л"),normalPrice=quantity.unit_price?euros(quantity.unit_price)+' / '+measureLabel:'';
  if(quantity.variable_weight)unit.append(node('div','quantity-note',t("Весовой товар")));
  else if(quantity.size_key&&quantity.size_key!=='unknown'&&/[x×]/i.test(p.unit||''))unit.append(node('div','quantity-note',t("Всего: ")+t(quantity.size_label)));
  const price=node('td','price-cell');
  if(comparing)price.append(node('div','price'+(p.regular_price>p.price?' deal':''),normalPrice),node('div','price-note',t("Цена на сайте: ")+euros(p.price)));
  else price.append(node('div','price'+(p.regular_price>p.price?' deal':''),euros(p.price)));
  if(p.regular_price && p.regular_price>p.price && !p.single_price){const old=node('div','old-price',(comparing?t("Ранее на сайте: "):'')+euros(p.regular_price));if(comparing)price.append(old);else price.prepend(old);}
  if(p.single_price)price.append(node('div','price-note',t("За 1: ")+euros(p.single_price)));
  if(normalPrice&&!comparing){const normalized=node('div','normalized-price',normalPrice);normalized.title=quantity.source==='retailer'?t("Цена магазина: ")+p.unit_price_text:t("Рассчитано по указанному весу или объёму");price.append(normalized);}
  else if(!normalPrice&&p.unit_price_text)price.append(node('div','price-note',p.unit_price_text));
  if(comparing&&quantity.source==='retailer'){const original=node('div','price-note',p.unit_price_text);price.append(original);}
  if(p.conditions?.length)price.append(node('div','conditions',p.conditions.map(value=>t(value)).join(' · ')));
  for(const offer of p.offers||[]){const amount=comparing?t("≈ {0} / {1} ({2} на сайте)", euros(quantity.unit_price*offer.price/p.price), measureLabel, euros(offer.price)):euros(offer.price);price.append(node('div','member',`${amount} · ${(offer.conditions||[]).map(value=>t(value)).join(' · ')}`));}
  const dates=node('td');const today=lastState?.today||new Date().toISOString().slice(0,10);let range=t("Срок не указан"),cls='validity';
  if(p.valid_from&&p.valid_to)range=shortDate(p.valid_from)+'–'+shortDate(p.valid_to);else if(p.valid_from)range=t("С ")+shortDate(p.valid_from);else if(p.valid_to)range=t("До ")+shortDate(p.valid_to);
  if(p.valid_to&&p.valid_to<today){range+=t(" · истёк");cls+=' expired';}else if(p.valid_from&&p.valid_from>today){cls+=' future';range+=t(" · скоро");}
  dates.append(node('div',cls,range));const stale=Date.now()-new Date(p.checked_at).getTime()>86400000;const checked=node('div','check-time'+(stale?' stale':''),t("Проверено\n")+timeLabel(p.checked_at));checked.title=t("Дата получения цены с сайта, время Вены");dates.append(checked);
  const source=node('td');const link=node('a','source-link');link.href=safeUrl(p.url)||'#';link.target='_blank';link.rel='noopener noreferrer';link.title=t("Открыть товар на сайте ")+names[p.store];link.setAttribute('aria-label',link.title);
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M14 3h7v7M21 3 11 13M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5');svg.append(path);link.append(svg);source.append(link);
  tr.append(first,store,unit,price,dates,source);return tr;
}
function renderCategories(categories) {
  const nav=$('categories');
  for(const group of categories) {
    let button=nav.querySelector(`[data-category="${group.id}"]`);
    if(!button) {button=node('button','category-tab');button.dataset.category=group.id;nav.append(button);}
    button.classList.toggle('selected',group.id===category);button.setAttribute('aria-pressed',String(group.id===category));
    button.replaceChildren(node('span','',t(group.label)),node('span','category-count',count(group.count)));
    button.onclick=()=>{if(category!==group.id){detailFilters={};resetQuantityFilters();}category=group.id;$('comparison-basis').value=defaultComparisonBasis();page=1;for(const tab of nav.children){tab.classList.toggle('selected',tab.dataset.category===category);tab.setAttribute('aria-pressed',String(tab.dataset.category===category));}loadProducts();};
  }
}
function productTags(d) {
  const labels={milk_kind:{plant:t("Растительное"),flavoured:t("Со вкусом")},milk_lactose:{free:'Laktosefrei'},milk_fat:{whole:'Vollmilch',light:t("Нежирное"),skim:t("Обезжиренное")},milk_storage:{fresh:'Frisch',esl:'Länger frisch',uht:'H-Milch'},meat_kind:{chicken:t("Курица"),pork:t("Свинина"),beef:t("Говядина"),turkey:t("Индейка"),veal:t("Телятина"),lamb:t("Баранина"),duck_goose:t("Утка / гусь / другая птица"),game:t("Дичь"),mixed:t("Смешанное мясо"),fish:t("Рыба и морепродукты")},meat_form:{cuts:t("Куски / филе"),minced:t("Фарш"),processed:t("Колбасы / копчёности"),prepared:t("Подготовленные блюда")}};
  labels.alcohol_kind={beer:t("Пиво / сидр"),wine:t("Вино"),sparkling:t("Игристое"),spirits:t("Крепкие / ликёры"),mixed:t("Коктейль / микс")};
  return Object.entries(labels).map(([key,values])=>values[d[key]]).filter(Boolean);
}
function renderFacets(facets) {
  const panel=$('product-facets'),fields=$('facet-fields'),active=document.activeElement?.id;
  panel.classList.toggle('hidden',!facets.length);fields.replaceChildren();
  const milk=facets.some(f=>f.id==='milk_kind'),alcohol=facets.some(f=>f.id==='alcohol_kind');
  $('facet-title').textContent=alcohol?t("Какой напиток ищем?"):milk?t("Какое молоко ищем?"):t("Какое мясо или рыбу ищем?");
  panel.querySelector('.facet-note').textContent=alcohol?t("Выберите вид напитка, объём бутылки и цену за литр. Безалкогольные версии остаются в разделе «Напитки»."):milk?t("Признаки взяты из названий и разделов магазина. «Без отметки Laktosefrei» означает, что безлактозность не указана."):t("Вид мяса и форма продукта указаны по названиям и разделам магазина. Если данных нет, товар остаётся в группе «Вид не указан».");
  for(const facet of facets){
    const label=node('label','facet-field'),select=node('select');select.id='facet-'+facet.id;
    label.append(node('span','',t(facet.label)));
    for(const item of facet.options){const option=node('option','',t(item.label)+' · '+count(item.count));option.value=item.id;option.disabled=item.count===0&&item.id!=='all'&&item.id!==facet.selected;select.append(option);}
    select.value=facet.selected;select.onchange=()=>{if(select.value==='all')delete detailFilters[facet.id];else detailFilters[facet.id]=select.value;page=1;loadProducts();};
    label.append(select);fields.append(label);
  }
  if(active?.startsWith('facet-'))$(active)?.focus({preventScroll:true});
}
function resetQuantityFilters(){ $('price-basis').value='pack';$('package-size').value='all'; }
function defaultComparisonBasis(){return $('price-basis').value!=='pack'?$('price-basis').value:((view==='selections'&&['milk','sweet_drinks','alcohol'].includes(selection))||['drinks','alcohol'].includes(category)?'l':'kg');}
function productParams(){return new URLSearchParams({store:selected,category,selection:view==='selections'?selection:'',q:$('search').value,period:$('period').value,discount:$('discount-only').checked?'1':'0',sort:$('sort').value,price_basis:$('price-basis').value,package_size:$('package-size').value||'all',page:String(page),...detailFilters});}
async function loadComparison(){
  if(!comparisonOpen||!['catalog','selections'].includes(view))return;
  comparisonController?.abort();
  comparisonController=new AbortController();
  const id=++comparisonRequest,params=productParams();params.set('price_basis',$('comparison-basis').value);
  $('store-comparison').setAttribute('aria-busy','true');$('comparison-status').textContent=t("Сравниваем предложения…");$('comparison-list').replaceChildren();
  try{
    const data=await json('/api/comparison?'+params,{signal:comparisonController.signal});if(id!==comparisonRequest)return;
    const measure=data.price_basis==='kg'?t("кг"):t("л"),available=data.stores.filter(s=>s.product).length;
    $('comparison-status').textContent=available?t("На сегодня · найдено в ")+available+t(" из 5 магазинов · ")+count(data.total)+t(" подходящих товаров"):t("На сегодня нет подходящих товаров с известной ценой за ")+measure+t(". Измените фильтры или единицу сравнения.");
    for(const entry of data.stores){
      const row=node('article','comparison-row'+(entry.best?' comparison-best':''));
      const shop=node('div','comparison-shop');shop.append(node('span','store-badge symbol-'+entry.store,entry.name));
      if(entry.best)shop.append(node('span','best-label',t("Самая низкая цена")));
      row.append(shop);
      if(!entry.product){row.append(node('p','comparison-missing',t("В загруженном каталоге нет подходящих товаров с известной ценой за ")+measure));$('comparison-list').append(row);continue;}
      const p=entry.product,info=node('div','comparison-info'),link=node('a','comparison-product',p.name);link.href=safeUrl(p.url)||'#';link.target='_blank';link.rel='noopener noreferrer';
      info.append(link,node('div','comparison-size',(p.quantity.variable_weight?t("Весовой товар · "):'')+(p.unit||t("Количество не указано"))),node('div','check-time',t("Проверено ")+timeLabel(p.checked_at)));
      const pricing=node('div','comparison-pricing');pricing.append(node('strong','',euros(p.quantity.unit_price)+' / '+measure));
      if(entry.difference>0)pricing.append(node('span','comparison-difference',t("На {0} / {1} дороже", euros(entry.difference), measure)));
      pricing.append(node('span','price-note',t("Цена на сайте: ")+euros(p.price)));
      if(p.conditions?.length)pricing.append(node('div','conditions',p.conditions.map(value=>t(value)).join(' · ')));
      for(const offer of p.offers||[])pricing.append(node('div','member',t("≈ {0} / {1} ({2} на сайте) · {3}", euros(p.quantity.unit_price*offer.price/p.price), measure, euros(offer.price), (offer.conditions||[]).map(value=>t(value)).join(' · '))));
      row.append(info,pricing);$('comparison-list').append(row);
    }
  }catch(e){if(id===comparisonRequest&&e.name!=='AbortError')$('comparison-status').textContent=e.message;}
  finally{if(id===comparisonRequest)$('store-comparison').setAttribute('aria-busy','false');}
}
$('compare-stores').onclick=()=>{comparisonOpen=!comparisonOpen;comparisonRequest++;comparisonController?.abort();$('store-comparison').classList.toggle('hidden',!comparisonOpen);$('compare-stores').setAttribute('aria-expanded',String(comparisonOpen));$('compare-stores').textContent=comparisonOpen?t("Скрыть сравнение"):t("Сравнить магазины");if(comparisonOpen){$('comparison-basis').value=defaultComparisonBasis();loadComparison();$('store-comparison').scrollIntoView({block:'start'});}};
$('comparison-basis').onchange=loadComparison;
function renderQuantityFilters(data){
  const select=$('package-size'),selectedSize=select.value||'all';select.replaceChildren();
  const groups={kg:node('optgroup'),l:node('optgroup'),other:node('optgroup')};groups.kg.label=t("Вес упаковки");groups.l.label=t("Объём упаковки");groups.other.label=t("Другие варианты");
  for(const item of data.sizes||[]){const option=node('option','',t(item.label)+' · '+count(item.count));option.value=item.id;option.disabled=item.count===0&&item.id!==selectedSize&&item.id!=='all';if(item.id==='all')select.append(option);else (groups[item.id.split(':')[0]]||groups.other).append(option);}
  for(const group of Object.values(groups))if(group.children.length)select.append(group);
  select.value=selectedSize;
  const basis=$('price-basis').value,label=basis==='kg'?t("кг"):t("л");
  $('sort').querySelector('[value="price_asc"]').textContent=basis==='pack'?t("Сначала дешевле"):t("Дешевле за ")+label;
  $('sort').querySelector('[value="price_desc"]').textContent=basis==='pack'?t("Сначала дороже"):t("Дороже за ")+label;
  $('quantity-hint').textContent=basis==='pack'?t("Вес относится ко всей упаковке, включая наборы. Весовые товары — отдельный вариант."):t("Показаны товары с известной ценой за ")+label+t(". Сортировка — по основной цене с указанными условиями покупки; цены по карте показаны отдельно.");
  $('reset-filters').classList.toggle('hidden',!$('search').value&&!$('discount-only').checked&&!Object.keys(detailFilters).length&&$('period').value==='current'&&basis==='pack'&&selectedSize==='all');
}
async function loadProducts() {
  if(!['catalog','selections'].includes(view))return;
  clearTimeout(searchTimer);
  productController?.abort();comparisonController?.abort();
  productController=new AbortController();
  const id=++request;const params=productParams();comparisonRequest++;
  document.querySelector('.table-wrap').setAttribute('aria-busy','true');
  $('result-count').textContent=t("Загружаем товары…");$('prev').disabled=true;$('next').disabled=true;
  if(view==='selections')highlightSelection();
  if(comparisonOpen){$('comparison-status').textContent=t("Обновляем сравнение…");$('comparison-list').replaceChildren();}
  try{const data=await json('/api/products?'+params,{signal:productController.signal});if(id!==request)return;page=data.page;
    renderCategories(data.categories);
    if(view==='selections'){renderSelections(data.selections);renderSelectionLeaflets(data.leaflet_offers);}
    renderFacets(data.facets||[]);
    renderQuantityFilters(data);
    loadComparison();
    $('products').replaceChildren(...data.items.map(renderProduct));$('empty').classList.toggle('hidden',data.total>0);document.querySelector('.table-wrap').classList.toggle('hidden',!data.total);
    const hasCatalogue=(lastState?.total||0)>0;
    $('empty-title').textContent=hasCatalogue?t("Товары не найдены"):t("Товаров пока нет");
    $('empty-text').textContent=hasCatalogue?t("Снимите часть фильтров, измените название или выберите другой магазин."):lastState?.busy?t("Каталог появится по мере загрузки."):t("Нажмите «Считать цены», чтобы загрузить каталоги магазинов.");
    $('reset-search').classList.toggle('hidden',!hasCatalogue);
    $('result-count').textContent=t("Найдено ")+count(data.total)+(view==='selections'?t(" · на сегодня"):'');$('page-info').textContent=data.total?t("{0}–{1} из {2}", count((page-1)*data.size+1), count(Math.min(page*data.size,data.total)), count(data.total)):t("Нет результатов");
    $('prev').disabled=page<=1;$('next').disabled=page>=data.pages;
  }catch(e){if(id===request&&e.name!=='AbortError'){$('result-count').textContent=t("Не удалось загрузить товары");notice(e.message);}}
  finally{if(id===request){document.querySelector('.table-wrap').setAttribute('aria-busy','false');productController=null;}}
}
$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;loadProducts();},250);});
for(const id of ['period','sort','discount-only','package-size'])$(id).onchange=()=>{page=1;loadProducts();};
$('price-basis').onchange=()=>{$('package-size').value='all';$('sort').value='price_asc';$('comparison-basis').value=defaultComparisonBasis();page=1;loadProducts();};
$('prev').onclick=()=>{page--;loadProducts();};$('next').onclick=()=>{page++;loadProducts();document.querySelector('.catalog').scrollIntoView({block:'start'});};
$('sources-toggle').onclick=()=>{const open=$('sources-panel').classList.toggle('hidden');$('sources-toggle').setAttribute('aria-expanded',String(!open));};
function resetProductFilters(){clearTimeout(searchTimer);$('search').value='';$('period').value='current';$('discount-only').checked=false;detailFilters={};resetQuantityFilters();page=1;loadProducts();}
$('reset-search').onclick=resetProductFilters;$('reset-filters').onclick=resetProductFilters;
$('refresh').onclick=async()=>{if(!lastState)return;$('refresh').disabled=true;try{await json('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':lastState.token},body:JSON.stringify({store:selected})});await loadState();}catch(e){notice(e.message);$('refresh').disabled=false;}};
function productHeading() {
  $('title').textContent=view==='selections'?t("Выбранные продукты"):selected==='all'?t("Каталог товаров"):t("Каталог ")+names[selected];
  $('subtitle').textContent=view==='selections'?t("Готовые подборки · обычные цены и доступные скидки"):selected==='all'?t("Цены с официальных сайтов магазинов"):t(lastState?.stores.find(s=>s.store===selected)?.scope)||'';
}
function renderSelections(items) {
  const nav=$('selections-list');
  for(const item of items) {
    let b=nav.querySelector('[data-selection="'+item.id+'"]');
    if(!b){b=node('button','selection-card');b.dataset.selection=item.id;nav.append(b);}
    b.classList.toggle('selected',item.id===selection);b.setAttribute('aria-pressed',String(item.id===selection));
    const title=node('span','selection-title',t(item.label)),desc=node('span','selection-desc',t(item.description)),stats=node('span','selection-stats');
    stats.append(node('span','',count(item.count)+t(" товаров")),node('span','selection-discounts',count(item.discount_count)+t(" со скидкой")));
    b.replaceChildren(title,desc,stats);
    b.onclick=()=>{if(selection===item.id)return;detailFilters={};resetQuantityFilters();selection=item.id;$('comparison-basis').value=defaultComparisonBasis();page=1;loadProducts();};
  }
}
function highlightSelection(){
  for(const button of $('selections-list').children){
    const active=button.dataset.selection===selection;
    button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));
  }
}
function renderSelectionLeaflets(data){
  const panel=$('selection-leaflets'),list=$('selection-leaflet-list');
  panel.classList.toggle('hidden',!data?.total);list.replaceChildren();
  for(const offer of data?.items||[]){
    const line=node('div','selection-leaflet-row');
    line.append(node('span','',names[offer.store]+' · '+offer.name+' · '+offer.size),node('strong','',euros(offer.price_cents/100)+' · '+t(offer.deal)),
      node('span','',(offer.min_quantity>1?t("При покупке ")+offer.min_quantity+t(" уп."):t("За 1 уп."))+(offer.membership_required?t(" · нужна ")+t(offer.membership_label):'')),
      node('span','',shortDate(offer.valid_from)+' — '+shortDate(offer.valid_to)));
    list.append(line);
  }
  $('selection-leaflet-open').textContent=t("Все акции подборки (")+count(data?.total||0)+') →';
}
$('selection-leaflet-open').onclick=()=>{window.showSelectionOffers?.(selection,$('search').value);switchView('flyers');};
function switchView(next, updateAddress=true) {
  clearTimeout(searchTimer);
  if(next!==view&&productFilters[view])productFilters[view]={category,q:$('search').value,period:$('period').value,sort:$('sort').value,discount:$('discount-only').checked,details:{...detailFilters},priceBasis:$('price-basis').value,packageSize:$('package-size').value||'all'};
  if(productFilters[next]&&(next!==view||!lastState)){
    const f=productFilters[next];category=f.category;detailFilters={...f.details};$('search').value=f.q;$('period').value=f.period;$('sort').value=f.sort;$('discount-only').checked=f.discount;page=1;
    $('price-basis').value=f.priceBasis||'pack';const option=node('option','',f.packageSize||'all');option.value=f.packageSize||'all';$('package-size').replaceChildren(option);$('package-size').value=option.value;
  }
  productController?.abort();comparisonController?.abort();
  view=next;request++;comparisonRequest++;$('comparison-basis').value=defaultComparisonBasis();
  for(const id of ['catalog','selections','flyers','shopping']) {
    const active=id===view;
    $(id+'-tab').classList.toggle('selected',active);
    $(id+'-tab').setAttribute('aria-selected',String(active));
    $(id+'-tab').tabIndex=active?0:-1;
  }
  $('shopping-view').classList.toggle('hidden',view!=='shopping');$('catalog-view').classList.toggle('hidden',!['catalog','selections'].includes(view));$('flyers-view').classList.toggle('hidden',view!=='flyers');
  $('catalog-view').setAttribute('aria-labelledby',view==='selections'?'selections-tab':'catalog-tab');
  $('selections-panel').classList.toggle('hidden',view!=='selections');$('categories').classList.toggle('hidden',view==='selections');
  $('period').closest('label').classList.toggle('hidden',view==='selections');$('period').disabled=view==='selections';
  productHeading();
  if(updateAddress)history.replaceState(null,'',view==='shopping'?'#shopping':view==='flyers'?'#flugblatt':view==='selections'?'#selected':location.pathname);
  if(lastState){renderStores(lastState);renderSummary(lastState);}
  if(view==='shopping')window.loadShopping?.();else if(view==='flyers')loadFlyers(true);else if(lastState)loadProducts();
}
for(const id of ['catalog','selections','flyers','shopping']) {
  $(id+'-tab').onclick=()=>switchView(id);
  $(id+'-tab').onkeydown=e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    e.preventDefault();const tabs=['catalog','selections','flyers','shopping'];const next=e.key==='Home'?tabs[0]:e.key==='End'?tabs.at(-1):tabs[(tabs.indexOf(view)+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];
    switchView(next);$(next+'-tab').focus();
  };
}
function externalLink(label, url, cls='') {
  const a=node('a',cls,label);a.href=safeUrl(url);a.target='_blank';a.rel='noopener noreferrer';return a;
}
function renderFlyer(f) {
  const card=node('article','flyer-card');
  const cover=externalLink('',f.url,'flyer-cover');cover.setAttribute('aria-label',t("Открыть флюгблатт ")+names[f.store]);
  const fallback=node('div','flyer-cover-fallback');fallback.append(node('strong','',names[f.store]),node('span','','Flugblatt'),node('small','',t("Посмотреть на сайте магазина")));
  if(safeUrl(f.image)) {
    const img=node('img');img.src=f.image;img.alt=t("Обложка флюгблатта ")+names[f.store];img.loading='lazy';img.referrerPolicy='no-referrer';
    img.onerror=()=>img.replaceWith(fallback);cover.append(img);
  } else cover.append(fallback);
  const body=node('div','flyer-body');
  const heading=node('div','flyer-card-heading');heading.append(node('span','store-badge symbol-'+f.store,names[f.store]),node('span','flyer-region',t(f.region)));
  const stale=Date.now()-new Date(f.checked_at).getTime()>86400000;
  const crossYear=f.valid_from.slice(0,4)!==f.valid_to.slice(0,4);
  const dateText=value=>shortDate(value)+(crossYear?'.'+value.slice(0,4):'');
  const dates=node('h2','flyer-dates',dateText(f.valid_from)+' — '+dateText(f.valid_to));
  const detail=[String(new Date(f.valid_to+'T12:00:00Z').getUTCFullYear()),f.pages?f.pages+t(" стр."):'Flugblatt'].join(' · ');
  body.append(heading,dates,node('div','flyer-edition',detail),node('span','flyer-valid'+(stale?' stale':''),stale?t("Нужна повторная проверка"):t("Действует сегодня")));
  if(t(f.note))body.append(node('p','flyer-note',t(f.note)));
  const actions=node('div','flyer-actions');actions.append(externalLink(t("Открыть флюгблатт ↗"),f.url,'secondary'));
  if(safeUrl(f.pdf_url))actions.append(externalLink('PDF ↗',f.pdf_url,'flyer-pdf'));
  body.append(actions,node('div','flyer-checked',t("Проверено ")+timeLabel(f.checked_at)));
  card.append(cover,body);return card;
}
function renderFlyers() {
  if(!flyersState)return;
  const data=flyersState,items=data.items.filter(f=>selected==='all'||f.store===selected),scope=data.stores.filter(s=>selected==='all'||s.store===selected);
  $('flyers-tab-count').textContent=count(window.offerSummary?.total??data.total);
  $('flyer-date').textContent=t("Сегодня, ")+shortDate(data.today);
  $('flyer-count').textContent=(selected==='all'?t("Все магазины"):names[selected])+t(" · выпусков: ")+count(items.length);
  // Keep covers loaded while polling unchanged state.
  const signature=language+JSON.stringify(items)+items.map(f=>Date.now()-new Date(f.checked_at).getTime()>86400000).join();
  if($('flyer-grid').dataset.signature!==signature){$('flyer-grid').replaceChildren(...items.map(renderFlyer));$('flyer-grid').dataset.signature=signature;}
  $('flyer-empty').classList.toggle('hidden',items.length>0||data.busy);
  const button=$('refresh-flyers');button.disabled=data.busy;button.classList.toggle('spinning',data.busy);
  button.querySelector('span').textContent=data.busy?t("Читаем акции…"):selected==='all'?t("Обновить акции"):t("Обновить ")+names[selected];
  const problems=scope.filter(s=>['error','partial'].includes(s.status));
  let message=data.busy?t("Проверяем флюгблатты на официальных сайтах…"):problems.map(s=>s.name+': '+t(s.error)).join(' ');
  if(!message&&scope.some(s=>s.checked_at&&Date.now()-new Date(s.checked_at).getTime()>86400000))message=t("Список проверялся больше суток назад. Обновите акции перед покупкой.");
  $('flyer-message').textContent=message;$('flyer-message').className=message?'message'+(data.busy?' progress':''):'message hidden';
  $('flyer-source-status').textContent=data.busy?t("Идёт обновление"):problems.length?t("Есть замечания"):t("5 магазинов");
  const list=$('flyer-sources-list');list.replaceChildren();
  for(const s of data.stores) {
    const row=node('div','flyer-source-row');const text=node('div');
    const status={idle:t("Ещё не проверено"),running:t("Проверяем…"),complete:t("Список проверен"),partial:t("Список новых выпусков недоступен"),error:t("Не удалось обновить")}[s.status];
    text.append(node('div',s.status==='complete'?'source-ok':'',status+(s.checked_at?' · '+timeLabel(s.checked_at):'')));
    if(t(s.error))text.append(node('p','source-desc',t(s.error)));
    row.append(externalLink(s.name,s.url,'source-name'),text,externalLink(t("На сайт ↗"),s.url,'flyer-pdf'));list.append(row);
  }
  if(lastState)renderStores(lastState);
}
async function loadFlyers(auto=false) {
  if(flyersLoading)return;
  flyersLoading=true;
  try {
    flyersState=await json('/api/flyers');renderFlyers();await window.loadOffers?.();
    const due=flyersState.stores.some(s=>!s.attempted_at||Date.now()-new Date(s.attempted_at).getTime()>6*3600000);
    if(auto&&lastState&&!flyersState.busy&&due)await startFlyerRefresh('all');
  } catch(e) {$('flyer-message').textContent=e.message;$('flyer-message').className='message';}
  finally {flyersLoading=false;}
}
async function startFlyerRefresh(store) {
  if(!lastState)return;
  $('refresh-flyers').disabled=true;
  try {
    await json('/api/flyers/refresh',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':lastState.token},body:JSON.stringify({store})});
    flyersState=await json('/api/flyers');renderFlyers();await window.loadOffers?.();
  } catch(e) {$('flyer-message').textContent=e.message;$('flyer-message').className='message';$('refresh-flyers').disabled=false;}
}
$('refresh-flyers').onclick=()=>startFlyerRefresh(selected);
window.addEventListener('hashchange',()=>switchView(location.hash==='#shopping'?'shopping':location.hash==='#flugblatt'?'flyers':location.hash==='#selected'?'selections':'catalog',false));
switchView(view,false);
(async()=>{await loadState();await loadFlyers(view==='flyers');})();
setInterval(()=>{loadState();if(view==='flyers'||flyersState?.busy)loadFlyers(view==='flyers');},4000);

window.addEventListener('languagechange', () => {
  productHeading();
  if (lastState) { renderStores(lastState); renderSummary(lastState); }
  $('compare-stores').textContent = comparisonOpen ? t('Скрыть сравнение') : t('Сравнить магазины');
  renderFlyers();
  // Read the local catalogue without triggering a download from the stores.
  if (['catalog','selections'].includes(view)) loadProducts();
  window.loadOffers?.();
});
