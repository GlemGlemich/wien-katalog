'use strict';
(() => {
  let group='all', drink='all', offerSelection='', offerPage=1, version=0, timer, signature='', data=null;
  window.offerMode='offers';
  const sizeLabel=r=>{
    const units={ml:t("мл"),cl:t("сл"),l:t("л"),liter:t("л"),g:t("г"),kg:t("кг")};
    const pack=r.size.match(/(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(ml|cl|liter|l|kg|g)\b/i);
    if(pack)return pack[1]+' × '+pack[2].replace('.',',')+' '+units[pack[3].toLowerCase()];
    const num=n=>new Intl.NumberFormat(locale(),{maximumFractionDigits:3}).format(n);
    return r.amount?(r.measure==='kg'&&r.amount<1?num(r.amount*1000)+t(" г"):num(r.amount)+' '+(r.measure==='l'?t("л"):t("кг"))):r.size;
  };
  const unitLabel=r=>r.unit_price!==null?euros(r.unit_price)+' / '+(r.measure==='l'?t("л"):t("кг")):'';
  function row(r) {
    const el=node('article','offer-row');
    const info=node('div','offer-info');
    const preview=externalLink('',''+r.source_url,'offer-preview');
    preview.title=t("Открыть страницу ")+r.page+t(" оригинального флюгблатта");
    const image=node('img');image.loading='lazy';image.alt=t("Страница ")+r.page+t(" буклета ")+names[r.store];image.width=110;image.height=145;
    image.src='/api/offer-preview?'+new URLSearchParams({store:r.store,id:r.id});
    image.onerror=()=>{image.remove();preview.classList.add('preview-unavailable');};
    preview.append(image,node('span','',t("Стр. ")+r.page+' ↗'));info.append(preview);
    const top=node('div','offer-row-top');top.append(node('span','store-badge symbol-'+r.store,names[r.store]),node('span','offer-period',shortDate(r.valid_from)+' — '+shortDate(r.valid_to)));
    info.append(top,node('h2','offer-name',r.name),node('div','offer-size',sizeLabel(r)+' · '+(r.loose_weight?t("весовой товар"):r.min_quantity>1?t("нужно ")+r.min_quantity+t(" уп."):t("можно купить 1 уп."))));
    const source=externalLink(t("Флюгблатт · стр. ")+r.page+' ↗',r.source_url,'offer-source');
    source.title=t("Страница ")+r.page+t(" в PDF; нумерация печатного буклета может отличаться");
    const detail=node('details','offer-details');detail.append(node('summary','',t("Условия и источник")));
    detail.append(node('p','',r.size));
    if(r.promo_original)detail.append(node('p','',r.promo_original));
    if(r.store==='billa')detail.append(node('p','',t("Акции BILLA не действуют по воскресеньям и в праздничные дни.")));
    if(r.deposit_note)detail.append(node('p','',t("Залог за тару: ")+r.deposit_note));
    detail.append(node('p','',t("Проверено ")+timeLabel(r.checked_at)),source);info.append(detail);
    const terms=node('div','offer-terms');terms.append(node('span','offer-deal'+(r.min_quantity>1?' bulk':''),t(r.deal)));
    if(r.membership_required)terms.append(node('span','offer-card-required',t("Нужна ")+t(r.membership_label)));
    else terms.append(node('span','offer-no-card',t("Без карты магазина")));
    if(r.min_quantity>1)terms.append(node('span','offer-total','≈ '+euros(r.total_cents/100)+t(" за ")+r.min_quantity+t(" уп.")));
    const price=node('div','offer-price');price.append(node('strong','',euros(r.price_cents/100)),node('span','',t("за ")+sizeLabel(r)),node('b','offer-unit',unitLabel(r)));
    el.append(info,terms,price);return el;
  }
  function chips(container, groups, selectedId, action) {
    const list=$(container);
    for(const g of groups) {
      let b=list.querySelector('[data-value="'+g.id+'"]');
      if(!b){b=node('button','category-tab');b.dataset.value=g.id;list.append(b);}
      b.classList.toggle('selected',g.id===selectedId);b.setAttribute('aria-pressed',String(g.id===selectedId));
      b.replaceChildren(node('span','',t(g.label)),node('span','category-count',count(g.count)));b.onclick=()=>action(g.id);
    }
  }
  function render(d) {
    data=d;offerPage=d.page;
    window.offerSummary={total:d.all_total,stores:d.stores};
    $('flyers-tab-count').textContent=count(d.all_total);
    chips('offer-categories',d.categories,group,id=>{group=id;drink='all';offerSelection='';offerPage=1;load();});
    chips('offer-drinks',d.drinks,drink,id=>{drink=id;offerPage=1;load();});
    $('offer-drinks').classList.toggle('hidden',group!=='drinks');
    const successful=d.stores.filter(s=>s.checked_at&&s.count);
    const scope=d.stores.filter(s=>selected==='all'||s.store===selected);
    const available=successful.map(s=>s.name).join(', ');
    const omitted=scope.reduce((sum,s)=>sum+(s.omitted||0),0);
    $('offer-coverage').textContent=d.busy?t("Обновляем буклеты и читаем товары. Это может занять несколько минут."):
      t("Часть предложений из буклетов: ")+(available||t("пока нет прочитанных товаров"))+t(". Полный охват всех пяти магазинов пока недоступен.");
    if(omitted)$('offer-coverage').append(node('span','',t(" Пропущено сложных блоков с ценами: ")+count(omitted)+t(". Они доступны в оригиналах буклетов.")));
    $('offer-selection-label').classList.toggle('hidden',!offerSelection);
    $('offer-selection-label').textContent=offerSelection?t("Показаны акции выбранной подборки. «Сбросить» — все предложения."):'';
    const stale=scope.some(s=>s.checked_at&&Date.now()-new Date(s.checked_at).getTime()>86400000);
    if(stale)$('offer-coverage').append(node('span','stale',t(" Цены проверялись больше суток назад — обновите акции.")));
    const best=$('offer-best');best.replaceChildren();best.classList.toggle('hidden',!d.best);
    if(d.best){const r=d.best;const text=node('div');text.append(node('span','best-kicker',t("НИЖЕ ЦЕНА ЗА ЛИТР СРЕДИ НАЙДЕННЫХ")),node('strong','',names[r.store]+' · '+r.name),node('span','',
      euros(r.price_cents/100)+t(" за ")+sizeLabel(r)+(r.min_quantity>1?t(" при покупке ")+r.min_quantity+t(" уп."):'')+(r.membership_required?t(" · нужна ")+t(r.membership_label):t(" · без карты"))));
      best.append(text,node('strong','best-price',unitLabel(r)));
    }
    $('offer-list').replaceChildren(...d.items.map(row));$('offer-empty').classList.toggle('hidden',d.total>0);
    $('offer-count').textContent=t("Найдено предложений: ")+count(d.total);
    $('offer-page-info').textContent=d.total?t("Страница ")+d.page+t(" из ")+d.pages:t("Нет результатов");
    $('offer-prev').disabled=d.page<=1;$('offer-next').disabled=d.page>=d.pages;
    $('offer-sources').replaceChildren(...d.stores.map(s=>{
      const el=node('div','flyer-source-row');const info=node('div');
      info.append(node('div','',s.status==='running'?t("Читаем PDF…"):s.count?t("Доступно сегодня: ")+s.count+t(" · прочитана часть буклета"):t("Товары пока недоступны")));
      if(s.checked_at)info.append(node('p','source-desc',t("Последнее чтение ")+timeLabel(s.checked_at)));
      if(t(s.error))info.append(node('p','source-desc',t(s.error)));
      if(s.omitted)info.append(node('p','source-desc',t("Сложные блоки с ценами пропущены: ")+s.omitted+t(". Их можно посмотреть в оригинале.")));
      el.append(node('strong','',s.name),info);return el;
    }));
    if(lastState)renderStores(lastState);
  }
  async function load(reset=false) {
    if(reset)offerPage=1;
    const current=++version;
    const params=new URLSearchParams({store:selected,category:group,drink,selection:offerSelection,q:$('offer-search').value,membership:$('offer-member').value,quantity:$('offer-quantity').value,sort:$('offer-sort').value,page:String(offerPage)});
    try {const result=await json('/api/offers?'+params);if(current!==version)return;const next=language+JSON.stringify(result)+params;
      if(next!==signature){signature=next;render(result);}
    } catch(e){$('offer-coverage').textContent=e.message;}
  }
  window.loadOffers=load;
  window.showSelectionOffers=(id,q)=>{offerSelection=id;group='all';drink='all';offerPage=1;$('offer-search').value=q;$('offer-member').value='all';$('offer-quantity').value='0';$('offers-mode').click();load(true);};
  for(const mode of ['offers','books'])$(mode+'-mode').onclick=()=>{
    window.offerMode=mode;for(const id of ['offers','books']){$(id+'-view').classList.toggle('hidden',id!==mode);$(id+'-mode').classList.toggle('selected',id===mode);$(id+'-mode').setAttribute('aria-pressed',String(id===mode));}
    if(lastState)renderStores(lastState);
  };
  $('offer-search').oninput=()=>{clearTimeout(timer);group='all';drink='all';offerSelection='';timer=setTimeout(()=>load(true),250);};
  for(const id of ['offer-member','offer-quantity','offer-sort'])$(id).onchange=()=>load(true);
  $('offer-reset').onclick=()=>{group='all';drink='all';offerSelection='';$('offer-search').value='';$('offer-member').value='all';$('offer-quantity').value='0';load(true);};
  $('offer-prev').onclick=()=>{offerPage--;load();};$('offer-next').onclick=()=>{offerPage++;load();};
  load();
})();
