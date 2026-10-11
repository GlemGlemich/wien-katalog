'use strict';
(() => {
  const dialog=$('product-matches');
  let data=null, product=null, controller=null, generation=0;

  function productCard(entry, reference=false) {
    const p=entry.product,q=p.quantity||{},card=node('article','match-card'+(reference?' match-selected':''));
    const shop=node('div','match-shop');shop.append(node('span','store-badge symbol-'+p.store,names[p.store]));
    if(reference)shop.append(node('span','match-label',t('Выбранный товар')));
    const imageUrl=safeUrl(p.image);
    if(imageUrl){const img=node('img','match-image');img.src=imageUrl;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';img.onerror=()=>img.remove();shop.append(img);}
    const info=node('div','match-info'),link=node('a','comparison-product',p.name);const url=safeUrl(p.url);
    if(url){link.href=url;link.target='_blank';link.rel='noopener noreferrer';}
    info.append(link,node('div','comparison-size',(q.variable_weight?t('Весовой товар · '):'')+(p.unit||t('Количество не указано'))));
    if(!reference){
      info.append(node('div','match-label',entry.size==='same'?t('Тот же вес / объём'):entry.size==='different'?t('Другой вес / объём'):t('Размер упаковки не подтверждён')));
      if(entry.reason==='different_code')info.append(node('div','match-warning',t('Другой штрихкод')));
      if(entry.reason==='size_conflict')info.append(node('div','match-warning',t('Штрихкод совпал, но размер отличается — проверьте источник')));
    }
    if(p.valid_from||p.valid_to)info.append(node('div','validity',(p.valid_from?t('С ')+shortDate(p.valid_from):'')+(p.valid_from&&p.valid_to?' · ':'')+(p.valid_to?t('До ')+shortDate(p.valid_to):'')));
    const stale=!p.checked_at||Date.now()-new Date(p.checked_at).getTime()>86400000;
    info.append(node('div','check-time'+(stale?' stale':''),t('Проверено ')+timeLabel(p.checked_at)));
    if(stale)info.append(node('div','match-warning',t('Цена проверялась больше суток назад')));
    const add=node('button','text-button shopping-add',t('В список'));
    add.onclick=()=>{if(window.addShoppingProduct?.(p)){add.textContent=t('Добавлено');setTimeout(()=>{add.textContent=t('В список');},1500);}};info.append(add);
    const pricing=node('div','comparison-pricing'),unitPrice=q.unit_price&&q.measure?euros(q.unit_price)+' / '+(q.measure==='kg'?t('кг'):t('л')):null;
    const useUnit=$('match-sort').value!=='pack'&&q.measure===$('match-sort').value;
    pricing.append(node('strong','',useUnit&&unitPrice?unitPrice:euros(p.price)));
    if(useUnit&&unitPrice)pricing.append(node('span','price-note',t('Цена на сайте: ')+euros(p.price)));
    else if(unitPrice)pricing.append(node('span','normalized-price',unitPrice));
    if(p.regular_price>p.price&&!p.single_price)pricing.append(node('span','old-price',t('Ранее на сайте: ')+euros(p.regular_price)));
    if(p.single_price)pricing.append(node('span','price-note',t('За 1: ')+euros(p.single_price)));
    if(p.membership_required)pricing.append(node('div','member',t('Нужна карта магазина')));
    if(p.conditions?.length)pricing.append(node('div','conditions',p.conditions.map(value=>t(value)).join(' · ')));
    for(const offer of p.offers||[])pricing.append(node('div','member',euros(offer.price)+' · '+(offer.conditions||[]).map(value=>t(value)).join(' · ')));
    card.append(shop,info,pricing);return card;
  }

  function entries(items, limit=false) {
    const basis=$('match-sort').value;
    const seen={};
    // Keep the most relevant names per store, then order those offers by price.
    return items.filter(e=>(!$('match-size').checked||e.size==='same')&&(basis==='pack'||(e.product.quantity?.measure===basis&&e.product.quantity.unit_price>0)))
      .filter(e=>!limit||(seen[e.product.store]=(seen[e.product.store]||0)+1)<=3)
      .sort((a,b)=>(basis==='pack'?a.product.price-b.product.price:a.product.quantity.unit_price-b.product.quantity.unit_price)||a.product.name.localeCompare(b.product.name,locale()));
  }

  function render() {
    if(!data)return;
    const previous=$('match-sort').value;
    $('match-sort').replaceChildren();
    const pack=node('option','',t('Цена на сайте'));pack.value='pack';$('match-sort').append(pack);
    const measure=data.reference.quantity?.measure;
    if(measure){const option=node('option','',measure==='kg'?t('Цена за 1 кг'):t('Цена за 1 л'));option.value=measure;$('match-sort').append(option);}
    $('match-sort').value=previous&&[measure,'pack'].includes(previous)?previous:(measure||'pack');
    $('match-size').disabled=!data.reference.quantity?.size_key||data.reference.quantity.size_key==='unknown'||data.reference.quantity.variable_weight;
    if($('match-size').disabled)$('match-size').checked=false;
    $('match-reference').replaceChildren(productCard({product:data.reference},true));
    $('match-status').textContent=data.reference_current?'':t('Выбранный товар сейчас не активен. Его цена показана для справки.');
    $('match-identity').textContent=data.barcode?t('Штрихкод источника: {0}',data.barcode):t('В источнике нет однозначного штрихкода. Подтвердить одинаковый товар пока нельзя.');
    const exact=entries(data.exact),similar=entries(data.similar,true);
    $('match-exact').replaceChildren(...exact.map(e=>productCard(e)));
    if(!exact.length)$('match-exact').append(node('p','match-note',t('Подтверждённых совпадений по этим фильтрам нет.')));
    $('match-alternatives').classList.toggle('hidden',!$('match-similar').checked);
    $('match-list').replaceChildren(...similar.map(e=>productCard(e)));
    if(!similar.length)$('match-list').append(node('p','match-note',t('Похожих товаров по этим фильтрам не найдено.')));
    const shown=[...exact,...($('match-similar').checked?similar:[])];
    const missing=data.stores.filter(s=>!shown.some(e=>e.product.store===s.store)).map(s=>names[s.store]);
    $('match-missing').textContent=missing.length?t('Нет результатов: {0}. Это не означает, что товара нет в магазине.',missing.join(', ')):'';
  }

  async function load() {
    controller?.abort();controller=new AbortController();const id=++generation;
    data=null;$('match-content').classList.add('hidden');$('match-status').textContent=t('Ищем этот товар в других магазинах…');dialog.setAttribute('aria-busy','true');
    try{
      const result=await json('/api/product-matches?'+new URLSearchParams({store:product.store,id:product.id}),{signal:controller.signal});
      if(id!==generation)return;
      data=result;$('match-sort').replaceChildren();render();$('match-content').classList.remove('hidden');
    }catch(e){if(id===generation&&e.name!=='AbortError')$('match-status').textContent=t('Не удалось сравнить товар. Закройте окно и попробуйте ещё раз.');}
    finally{if(id===generation)dialog.setAttribute('aria-busy','false');}
  }
  window.openProductMatches=p=>{product=p;$('match-size').checked=false;$('match-similar').checked=true;if(!dialog.open)dialog.showModal();load();};
  $('match-close').onclick=()=>dialog.close();
  dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();}});
  dialog.addEventListener('close',()=>{generation++;controller?.abort();dialog.setAttribute('aria-busy','false');});
  for(const id of ['match-size','match-sort','match-similar'])$(id).addEventListener('change',render);
  window.addEventListener('languagechange',()=>{if(dialog.open){if(data)render();else $('match-status').textContent=t('Ищем этот товар в других магазинах…');}});
})();
