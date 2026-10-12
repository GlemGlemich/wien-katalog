'use strict';
(() => {
  const dialog=$('price-history');
  let product=null,data=null,days=90,controller=null,revision=0,loading=false;
  const stamp=value=>new Date(value).toLocaleString(locale(),{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Vienna'});
  const date=value=>new Date(value).toLocaleDateString(locale(),{day:'2-digit',month:'2-digit',year:'numeric',timeZone:'Europe/Vienna'});
  function comparable(a,b){return Boolean(a.unit)&&a.name===b.name&&a.unit===b.unit&&a.variable_weight===b.variable_weight&&a.membership_required===b.membership_required&&JSON.stringify(a.conditions)===JSON.stringify(b.conditions);}
  function svgNode(tag,attrs={},text){const element=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))element.setAttribute(key,String(value));if(text!==undefined)element.textContent=text;return element;}

  function chart(entries){
    const points=entries.flatMap(e=>e.observed_at.map(at=>({at,entry:e,value:e.price_cents/100}))),host=$('history-chart');host.replaceChildren();
    if(!points.length)return;
    const width=Math.max(280,Math.min(780,host.clientWidth||780)),height=245,left=72,right=20,top=22,bottom=42;
    const times=points.map(p=>Date.parse(p.at)),values=points.map(p=>p.value),first=Math.min(...times),last=Math.max(...times);
    let low=Math.min(...values),high=Math.max(...values);const pad=Math.max(.1,(high-low)*.18);low=Math.max(0,low-pad);high+=pad;
    const x=time=>first===last?(width+left-right)/2:left+(time-first)/(last-first)*(width-left-right);
    const y=value=>top+(high-value)/(high-low)*(height-top-bottom);
    const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':t('График сохранённых цен; точные значения указаны ниже')});
    svg.append(svgNode('title',{},t('История цен')));
    for(let i=0;i<4;i++){const value=low+(high-low)*i/3,position=y(value);svg.append(svgNode('line',{x1:left,x2:width-right,y1:position,y2:position,class:'history-grid'}),svgNode('text',{x:left-10,y:position+4,'text-anchor':'end',class:'history-axis'},euros(value)));}
    svg.append(svgNode('text',{x:left,y:height-12,class:'history-axis'},date(points[0].at)));
    if(first!==last)svg.append(svgNode('text',{x:width-right,y:height-12,'text-anchor':'end',class:'history-axis'},date(points.at(-1).at)));
    points.forEach((point,index)=>{
      const px=x(Date.parse(point.at)),py=y(point.value),previous=points[index-1];
      if(previous&&comparable(previous.entry,point.entry))svg.append(svgNode('line',{x1:x(Date.parse(previous.at)),y1:y(previous.value),x2:px,y2:py,class:'history-line'}));
      const dot=svgNode('circle',{cx:px,cy:py,r:4,class:'history-dot'});dot.append(svgNode('title',{},`${stamp(point.at)} · ${euros(point.value)} · ${point.entry.unit}`));svg.append(dot);
    });
    host.append(svg);
  }

  function entryRow(entry,previous){
    const row=node('article','history-entry'),when=node('div','history-when');when.append(node('strong','',stamp(entry.last_seen)));
    if(entry.first_seen!==entry.last_seen)when.append(node('span','',t('Первая проверка: {0}',stamp(entry.first_seen))));
    const info=node('div','history-info');info.append(node('div','comparison-product',entry.name),node('div','comparison-size',entry.unit||t('Количество не указано')));
    if(entry.valid_from||entry.valid_to)info.append(node('div','validity',(entry.valid_from?t('С ')+date(entry.valid_from+'T12:00:00Z'):'')+(entry.valid_from&&entry.valid_to?' · ':'')+(entry.valid_to?t('До ')+date(entry.valid_to+'T12:00:00Z'):'')));
    if(previous&&!comparable(previous,entry))info.append(node('div','match-warning',t('Название, упаковка или условия изменились')));
    if(entry.conditions.length)info.append(node('div','conditions',entry.conditions.map(s=>t(s)).join(' · ')));
    if(entry.membership_required)info.append(node('div','member',t('Нужна карта магазина')));
    const price=node('div','comparison-pricing');price.append(node('strong','',euros(entry.price_cents/100)));
    if(entry.regular_cents>entry.price_cents)price.append(node('span','price-note',t('Перечёркнутая на сайте: {0}',euros(entry.regular_cents/100))));
    if(entry.single_cents)price.append(node('span','price-note',t('За 1: ')+euros(entry.single_cents/100)));
    for(const offer of entry.offers)price.append(node('div','member',euros(offer.price_cents/100)+' · '+offer.conditions.map(s=>t(s)).join(' · ')));
    row.append(when,info,price);return row;
  }

  function render(){
    $('history-product').textContent=product?names[product.store]+' · '+product.name:'';
    for(const button of $('history-period').children)button.setAttribute('aria-pressed',String(Number(button.dataset.days)===days));
    if(!data)return;
    const entries=data.entries;$('history-content').classList.toggle('hidden',!entries.length);
    if(!entries.length){$('history-status').textContent=t('За этот период проверок нет. Выберите всю историю или обновите цены в каталоге.');return;}
    const latest=entries.at(-1),summary=$('history-summary');summary.replaceChildren();
    const cards=[{label:t('Последняя запись'),value:euros(latest.price_cents/100),note:stamp(latest.last_seen)},
      {label:t('Минимум при тех же условиях'),value:data.minimum_cents===null?'—':euros(data.minimum_cents/100),note:data.minimum_cents===null?t('Недостаточно сопоставимых данных'):t('Среди показанных записей с той же упаковкой и условиями')},
      {label:t('К предыдущей записи'),value:data.change_cents===null?'—':data.change_cents===0?t('Без изменения'):(data.change_cents>0?'+':'−')+euros(Math.abs(data.change_cents)/100),note:data.change_cents===null?t('Недостаточно сопоставимых данных'):t('Сравниваем цену с сайта при тех же условиях')}];
    for(const card of cards){const block=node('div','history-stat');block.append(node('span','',card.label),node('strong','',card.value),node('small','',card.note));summary.append(block);}
    chart(entries);
    const points=entries.reduce((n,e)=>n+e.observed_at.length,0);
    $('history-explanation').textContent=points===1?t('Пока есть одна проверка. После следующих обновлений здесь появятся новые точки.'):t('Линии соединяют проверки с одинаковой упаковкой и условиями. Точная дата изменения цены неизвестна.');
    $('history-entries').replaceChildren(...entries.map((e,i)=>entryRow(e,entries[i-1])).reverse());
    const messages=[];
    if(!data.active)messages.push(t('Товар больше не активен в сохранённом каталоге. История остаётся доступна.'));
    if(Date.now()-Date.parse(latest.last_seen)>86400000)messages.push(t('Цена проверялась больше суток назад'));
    if(data.truncated)messages.push(t('Показаны последние 500 записей за выбранный период.'));
    $('history-status').textContent=messages.join(' ');
  }

  async function load(){
    controller?.abort();controller=new AbortController();const id=++revision;loading=true;data=null;render();
    $('history-content').classList.add('hidden');$('history-status').textContent=t('Читаем историю цен…');dialog.setAttribute('aria-busy','true');
    try{const response=await json('/api/price-history?'+new URLSearchParams({store:product.store,id:product.id,days:String(days)}),{signal:controller.signal});if(id!==revision)return;data=response;product=response.product;render();}
    catch(e){if(id===revision&&e.name!=='AbortError')$('history-status').textContent=t('Не удалось прочитать историю. Закройте окно и попробуйте ещё раз.');}
    finally{if(id===revision){loading=false;dialog.setAttribute('aria-busy','false');}}
  }
  window.openPriceHistory=p=>{product=p;days=90;if(!dialog.open)dialog.showModal();load();};
  $('history-close').onclick=()=>dialog.close();
  $('history-period').onclick=event=>{const button=event.target.closest('button[data-days]');if(button&&Number(button.dataset.days)!==days){days=Number(button.dataset.days);load();}};
  dialog.addEventListener('close',()=>{revision++;controller?.abort();loading=false;dialog.setAttribute('aria-busy','false');});
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  window.addEventListener('languagechange',()=>{if(dialog.open){render();if(loading)$('history-status').textContent=t('Читаем историю цен…');}});
  window.addEventListener('resize',()=>{if(dialog.open&&data?.entries.length)chart(data.entries);});
})();
