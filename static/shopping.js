'use strict';
(() => {
  const storageKey='wien-katalog.shopping.v1';
  const units={pack:'упаковки',pcs:'шт.',kg:'кг',l:'л'};
  let items=[], result=null, timer, controller, revision=0, storageFailed=false;
  let limit='1';
  function valid(item) {
    return item && typeof item.id==='string' && typeof item.query==='string' && item.query.trim().length>=2 && item.query.length<=160 &&
      Object.hasOwn(units,item.unit) && Number.isFinite(item.amount) && item.amount>0 && item.amount<=10000 &&
      (!['pack','pcs'].includes(item.unit)||Number.isInteger(item.amount)) &&
      (!item.product||(Object.hasOwn(names,item.product.store)&&typeof item.product.id==='string'));
  }
  try {
    const saved=JSON.parse(localStorage.getItem(storageKey)||'null');
    if(saved?.version===1 && Array.isArray(saved.items)) {
      const ids=new Set();
      items=saved.items.filter(item=>{if(!valid(item)||ids.has(item.id))return false;ids.add(item.id);return true;}).slice(0,30);
      if(['1','2'].includes(saved.limit))limit=saved.limit;
    }
  } catch {storageFailed=true;}
  $('basket-limit').value=limit;
  function save() {
    try {localStorage.setItem(storageKey,JSON.stringify({version:1,items,limit}));}
    catch {storageFailed=true;}
    storageMessage();
    $('shopping-tab-count').textContent=count(items.length);
  }
  function storageMessage() {
    $('basket-storage').textContent=storageFailed?t('Браузер не сохранил список. Он доступен до закрытия страницы.'):t('Список сохраняется в этом браузере.');
  }
  const amountText=(amount,unit)=>count(amount)+' '+t(units[unit]);
  function invalidate() {
    clearTimeout(timer);controller?.abort();revision++;result=null;
    $('basket-results').classList.add('hidden');
    $('basket-status').textContent='';
  }
  function schedule() {invalidate();timer=setTimeout(load,300);}
  function renderItems() {
    const list=$('basket-items');list.replaceChildren();
    for(const item of items) {
      const row=node('div','basket-item');row.dataset.item=item.id;
      const field=node('label','facet-field basket-query');field.append(node('span','',t('Продукт')));
      const query=node('input');query.value=item.query;query.minLength=2;query.maxLength=160;query.required=true;query.readOnly=!!item.product;
      query.setAttribute('aria-label',t('Продукт'));
      field.append(query);
      if(item.product)field.append(node('small','',t('Конкретный товар · {0}',names[item.product.store])));
      const amountField=node('label','facet-field basket-amount');amountField.append(node('span','',t('Количество')));
      const amount=node('input');amount.type='number';amount.min=['pack','pcs'].includes(item.unit)?'1':'0.001';amount.max='10000';amount.step=['pack','pcs'].includes(item.unit)?'1':'any';amount.value=item.amount;amount.required=true;
      amountField.append(amount);
      const unitField=node('label','facet-field');unitField.append(node('span','',t('Единица')));
      const unit=node('select');
      for(const [key,label] of Object.entries(units)){const option=node('option','',t(label));option.value=key;unit.append(option);}
      unit.value=item.unit;unitField.append(unit);
      const remove=node('button','text-button basket-remove',t('Удалить'));remove.setAttribute('aria-label',t('Удалить {0}',item.query));
      remove.onclick=()=>{items=items.filter(entry=>entry.id!==item.id);save();renderItems();schedule();};
      const update=()=>{
        if(!query.checkValidity()||!amount.checkValidity()){invalidate();$('basket-status').textContent=t('Проверьте название и количество. Упаковки и штуки должны быть целыми.');return;}
        item.query=query.value.trim();item.amount=Number(amount.value);item.unit=unit.value;save();schedule();
      };
      query.oninput=()=>{invalidate();};amount.oninput=()=>{invalidate();};
      query.onchange=update;amount.onchange=update;
      unit.onchange=()=>{amount.min=['pack','pcs'].includes(unit.value)?'1':'0.001';amount.step=['pack','pcs'].includes(unit.value)?'1':'any';update();};
      row.append(field,amountField,unitField,remove);list.append(row);
    }
    $('basket-empty').classList.toggle('hidden',items.length>0);
    $('basket-calculate').disabled=!items.length;
    $('shopping-tab-count').textContent=count(items.length);
    storageMessage();
  }
  function add(query,amount,unit,product=null) {
    query=query.trim();
    const existing=items.find(item=>item.query.toLocaleLowerCase()===query.toLocaleLowerCase()&&item.unit===unit&&JSON.stringify(item.product||null)===JSON.stringify(product));
    if((existing&&existing.amount+amount>10000)||(!existing&&items.length>=30)){
      $('basket-status').textContent=t('Можно добавить до 30 строк и до 10000 единиц в строке.');
      switchView('shopping');return false;
    }
    if(existing)existing.amount+=amount;
    else items.push({id:crypto.randomUUID(),query,amount,unit,product});
    save();renderItems();schedule();return true;
  }
  window.addShoppingProduct=product=>add(product.name.slice(0,160),1,product.quantity?.variable_weight?'kg':'pack',{store:product.store,id:String(product.id)});
  $('basket-form').onsubmit=event=>{
    event.preventDefault();
    const amount=Number($('basket-amount').value),unit=$('basket-unit').value;
    if(['pcs','pack'].includes(unit)&&!Number.isInteger(amount)){
      $('basket-status').textContent=t('Проверьте название и количество. Упаковки и штуки должны быть целыми.');return;
    }
    if(add($('basket-query').value,amount,unit))$('basket-query').value='';
  };
  const presets={milk:['Молоко',1,'l'],eggs:['Яйца',10,'pcs'],cola:['Кола',2,'l']};
  for(const button of document.querySelectorAll('[data-preset]'))button.onclick=()=>{
    const [query,amount,unit]=presets[button.dataset.preset];add(t(query),amount,unit);
  };
  function planLine(line,lookup) {
    const item=lookup.get(line.item_id),row=node('div','basket-plan-row');
    const heading=node('div','basket-line-heading');heading.append(node('strong','',item.query),node('span','',t('Нужно: {0}',amountText(item.amount,item.unit))));row.append(heading);
    const choice=line.choice;
    if(!choice){row.append(node('p','basket-missing',t('Не найдена подходящая цена.')));return row;}
    const info=node('div','basket-choice');info.append(node('span','store-badge symbol-'+choice.store,names[choice.store]));
    info.append(externalLink(choice.name,choice.url,'comparison-product'));
    info.append(node('div','',t('Купить: {0}',amountText(choice.bought,item.unit))+(choice.packs!==null?t(' · {0} уп. по {1}',count(choice.packs),choice.unit||t('Количество не указано')):t(' · весовой товар'))));
    if(choice.bought>item.amount)info.append(node('div','basket-extra',t('Сверх списка: {0}',amountText(Number((choice.bought-item.amount).toFixed(6)),item.unit))));
    if(choice.single_price)info.append(node('div','price-note',t('Расчёт по одиночной цене без условия покупки нескольких упаковок.')));
    else if(choice.conditions.length)info.append(node('div','conditions',choice.conditions.map(value=>t(value)).join(' · ')));
    const stale=Date.now()-new Date(choice.checked_at).getTime()>86400000;
    info.append(node('div','check-time'+(stale?' stale':''),t('Проверено ')+timeLabel(choice.checked_at)));
    if(choice.valid_from||choice.valid_to)info.append(node('div','check-time',[shortDate(choice.valid_from),shortDate(choice.valid_to)].filter(Boolean).join(' — ')));
    const price=node('strong','basket-line-price',(choice.variable?'≈ ':'')+euros(choice.cost_cents/100));row.append(info,price);return row;
  }
  function render() {
    if(!result)return;
    const lookup=new Map(result.items.map(item=>[item.id,item]));
    $('basket-results').classList.remove('hidden');$('basket-summary').replaceChildren();
    for(const [key,label] of [['best_single','Один магазин'],['best_two','До двух магазинов']]) {
      const plan=result[key],card=node('div','basket-total'+((limit==='1')===(key==='best_single')?' active':''));
      card.append(node('span','',t(label)),node('strong','',plan?euros(plan.total_cents/100):t('Нет полного расчёта')));
      card.append(node('span','',plan?plan.used_stores.map(store=>names[store]).join(' + '):t('Для части списка нет подходящих цен.')));$('basket-summary').append(card);
    }
    $('basket-saving').textContent=result.saving_cents>0?t('Экономия при посещении двух магазинов: {0}. Стоимость дороги не учтена.',euros(result.saving_cents/100)):
      result.best_single?t('По найденным ценам второй магазин не снижает сумму.'):'';
    const best=limit==='1'?result.best_single:result.best_two;
    $('basket-plan').replaceChildren();
    if(best)$('basket-plan').append(...best.lines.map(line=>planLine(line,lookup)));
    else $('basket-plan').append(node('p','basket-note',t('В выбранном числе магазинов полный список не рассчитан. Ниже видно, какие позиции найдены в каждом магазине.')));
    const stores=$('basket-stores');stores.replaceChildren();
    for(const plan of result.stores) {
      const details=node('details','basket-store'),summary=node('summary');
      summary.append(node('span','store-badge symbol-'+plan.stores[0],names[plan.stores[0]]),
        node('span','',t('Найдено {0} из {1}',plan.covered,result.items.length)),
        node('strong','',plan.complete?euros(plan.total_cents/100):t('Часть списка: {0}',euros(plan.subtotal_cents/100))));
      details.append(summary,...plan.lines.map(line=>planLine(line,lookup)));stores.append(details);
    }
    const skipped=result.items.filter(item=>item.excluded);
    $('basket-status').textContent=skipped.length?t('Часть совпадений исключена: неясный размер или условия цены. Проверьте выбранные товары ниже.'):t('Расчёт готов. Проверьте выбранные товары и даты цен.');
  }
  async function load() {
    clearTimeout(timer);
    if(view!=='shopping')return;
    if(!items.length){invalidate();return;}
    if([...$('basket-items').querySelectorAll('input')].some(input=>!input.checkValidity())){
      invalidate();$('basket-status').textContent=t('Проверьте название и количество. Упаковки и штуки должны быть целыми.');return;
    }
    if(!lastState){$('basket-status').textContent=t('Ожидаем соединения с каталогом…');return;}
    controller?.abort();controller=new AbortController();const current=++revision;
    $('basket-results').classList.add('hidden');$('basket-status').textContent=t('Считаем стоимость списка…');
    try {
      const data=await json('/api/shopping/quote',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':lastState.token},body:JSON.stringify({items}),signal:controller.signal});
      if(current!==revision)return;
      result=data;render();
    } catch(error) {
      if(current===revision&&error.name!=='AbortError')$('basket-status').textContent=t('Не удалось рассчитать список. Проверьте соединение и попробуйте ещё раз.');
    }
  }
  window.loadShopping=load;
  $('basket-calculate').onclick=load;
  $('basket-limit').onchange=()=>{limit=$('basket-limit').value;save();render();};
  window.addEventListener('languagechange',()=>{renderItems();render();});
  renderItems();if(view==='shopping')load();
})();
