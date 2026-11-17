'use strict';
/* TOURIST Mini App: browser and Telegram use the same API. */
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const $ = selector => document.querySelector(selector);
const $$ = selector => Array.from(document.querySelectorAll(selector));
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const demoBrowser = !tg?.initData;
const statusRU = {open:'Запись открыта',closed:'Запись закрыта',cancelled:'Отменено',pending:'На рассмотрении',confirmed:'Подтверждено',rejected:'Отклонено',cancel_requested:'Отмена на рассмотрении'};
const roleRU = {owner:'Владелец',senior:'Старший',admin:'Администратор',guest:'Гость'};
const state = {screen:'home',kind:'all',adminTab:'overview',events:[],adminEvents:[],me:null,locked:false,clubTimezone:'Europe/Moscow',pendingKeys:{},profileEditSerial:0};
const fullDate = iso => {try{return new Intl.DateTimeFormat('ru-RU',{timeZone:state.clubTimezone,day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(iso));}catch{return iso;}};
const localTime = iso => {try{return new Intl.DateTimeFormat('ru-RU',{timeZone:state.clubTimezone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(iso));}catch{return iso;}};
function clubInput(date) {
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:state.clubTimezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date).map(x=>[x.type,x.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}
async function api(path,options={}) {
  const headers={...(options.headers||{})};
  if (options.body!==undefined) headers['Content-Type']='application/json';
  if (tg?.initData) headers['X-Telegram-Init-Data']=tg.initData;
  if (demoBrowser) headers['X-Demo-User-ID']='900001'; // honored ONLY by localhost demo server
  let response;
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),15000);
  try { response=await fetch(path,{...options,headers,signal:controller.signal,cache:'no-store'}); }
  catch(error) {
    if(error?.name==='AbortError') throw Error('Сервер не ответил за 15 секунд. Повторите действие.');
    throw Error('Не удаётся связаться с сервером. Проверьте подключение.');
  } finally {clearTimeout(timer);} 
  let body;
  try { body=await response.json(); }
  catch { throw Error('Не удалось прочитать ответ сервера.'); }
  if(!response.ok) throw Error(typeof body.detail==='string'?body.detail:'Не удалось выполнить действие. Проверьте введённые данные.');
  return body;
}
function requestKey(operation,payload) {
  const identity=operation+':'+JSON.stringify(payload);
  const cached=state.pendingKeys[operation];
  if(cached?.identity===identity) return cached.key;
  const key=globalThis.crypto?.randomUUID?.() || `try_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  state.pendingKeys[operation]={identity,key};
  return key;
}
function requestDone(operation){delete state.pendingKeys[operation];}
function notice(message,error=false) {
  const el=$('#notice'); el.textContent=message; el.className='notice'+(error?' error':'');
  el.scrollIntoView({behavior:'smooth',block:'nearest'});
}
function clearNotice(){ $('#notice').classList.add('hidden'); }
const V17='/assets/visual/v017/';
const assetUrl = path => window.__v17QAAssets?.[path] || V17+path;
let popupPreviousFocus=null;
function showResultPopup(title,message,illustration='02_confirm_action.png'){
  const dlg=$('#result-popup');
  popupPreviousFocus=document.activeElement instanceof HTMLElement?document.activeElement:null;
  $('#result-popup-title').textContent=title;
  $('#result-popup-text').textContent=message;
  $('#result-popup-image').src=V17+'illustrations/'+illustration;
  dlg.classList.remove('hidden');
  document.body.classList.add('popup-open');
  dlg.querySelector('.popup-close').focus({preventScroll:true});
}
function hideResultPopup(){
  const dlg=$('#result-popup');
  if(dlg.classList.contains('hidden'))return;
  dlg.classList.add('hidden');
  document.body.classList.remove('popup-open');
  popupPreviousFocus?.focus?.({preventScroll:true});
  popupPreviousFocus=null;
}
document.addEventListener('click', event=>{
  if(event.target.closest('[data-popup-close]'))hideResultPopup();
  if(event.target.closest('[data-show-booking-info]'))showResultPopup('Всё для игры','Кии и шары предоставляются вместе со столом. Выберите время, а администратор подтвердит бронирование.','02_confirm_action.png');
});
document.addEventListener('keydown',event=>{
  const dialog=$('#result-popup');
  if(dialog.classList.contains('hidden'))return;
  if(event.key==='Escape'){event.preventDefault();hideResultPopup();return;}
  if(event.key!=='Tab')return;
  const items=Array.from(dialog.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),[tabindex]:not([tabindex="-1"])'));
  if(!items.length)return;
  const first=items[0],last=items[items.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
});

function haptic(success){tg?.HapticFeedback?.notificationOccurred(success?'success':'error');}
async function action(callback){
  if(state.locked) return;
  state.locked=true;
  document.body.classList.add('is-busy');
  document.body.setAttribute('aria-busy','true');
  try {await callback();haptic(true);}
  catch(error){haptic(false);notice(error.message,true);}
  finally {state.locked=false;document.body.classList.remove('is-busy');document.body.removeAttribute('aria-busy');}
}
function go(screen,kind) {
  if(kind) state.kind=kind;
  if(screen==='admin' && !['owner','senior','admin'].includes(state.me?.user?.role)) return go('profile');
  const previousScreen=state.screen;
  state.screen=screen;
  $$('.screen').forEach(el=>el.classList.toggle('active',el.id==='screen-'+screen));
  $$('.nav-btn').forEach(el=>{const active=el.dataset.screen===screen;el.classList.toggle('active',active);if(active)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  $$('.chip').forEach(el=>el.classList.toggle('selected',el.dataset.kind===state.kind));
  $('#home-hero').classList.toggle('hidden',screen!=='home');
  clearNotice();
  if(previousScreen===screen){
    window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  }
  if(previousScreen!==screen){
    // Native page transition: no external Vue runtime / no extra HTTP dependency.
    const next=$('#screen-'+screen);
    next?.classList.remove('entering');
    if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
      void next?.offsetWidth; // restart CSS keyframes on a repeated visit
      next?.classList.add('entering');
    }
    window.scrollTo({top:0,behavior:'instant'});
  }
  if(screen==='schedule') renderEvents();
  if(screen==='profile') loadMe();
  if(screen==='admin') loadAdminTab();
  if(screen==='billiard') loadBusy();
  if(screen==='support') loadSupportMine();
}
function emptyView(image,message){return `<div class="empty art-empty"><img loading="lazy" src="${assetUrl("illustrations/"+image)}" alt="" aria-hidden="true"><span>${escapeHtml(message)}</span></div>`;}
function eventCard(e,compact=false) {
  const image=e.kind==='poker'?'objects/poker.png':'events/mafia.png';
  const typeIcon=e.kind==='poker'?'03_poker.png':'02_mafia.png';
  const free=Math.max(0,e.capacity-Number(e.occupied||0));
  const blocked=free===0||e.status!=='open';
  return `<article class="item event-item"><div class="event-visual" aria-hidden="true"><img src="${assetUrl(image)}" alt="" loading="lazy"></div><div class="event-date"><span>${escapeHtml(new Intl.DateTimeFormat('ru-RU',{timeZone:state.clubTimezone,day:'2-digit'}).format(new Date(e.starts_at)))}</span><small>${escapeHtml(new Intl.DateTimeFormat('ru-RU',{timeZone:state.clubTimezone,month:'short'}).format(new Date(e.starts_at)))}</small></div><div class="event-detail"><div class="item-top"><span class="tag"><img class="tag-icon" src="${assetUrl("icons/topics/"+typeIcon)}" alt="">${e.kind==='mafia'?'МАФИЯ':'ПОКЕР'}</span><span class="tag status">${blocked?'ЗАПИСЬ ЗАКРЫТА':`МЕСТ: ${free}`}</span></div>
    <h3>${escapeHtml(e.title)}</h3><p>${escapeHtml(fullDate(e.starts_at))}</p>
    ${e.kind==='poker'?`<p>Стек ${escapeHtml(e.stack)}, блайнды ${escapeHtml(e.blinds)}</p>`:''}
    <div class="bar"><span style="width:${Math.min(100,100*Number(e.occupied||0)/e.capacity)}%"></span></div>
    <div class="item-actions"><button class="affirm" data-join="${e.id}" ${blocked?'disabled':''}>${blocked?'Нет записи':'Записаться'}</button>
    ${!compact?`<button data-members="${e.id}">Кто играет?</button>`:''}</div></div></article>`;
}
function renderEvents(){
  const chosen=state.events.filter(x=>state.kind==='all'||x.kind===state.kind);
  $('#event-list').innerHTML=chosen.length?chosen.map(x=>eventCard(x)).join(''):emptyView('07_no_events.png','Мероприятия пока не опубликованы.');
  $('#home-events').innerHTML=state.events.length?state.events.slice(0,2).map(x=>eventCard(x,true)).join(''):emptyView('07_no_events.png','Ближайших встреч пока нет. Следите за расписанием.');
}
async function refreshEvents(){ try {state.events=await api('/api/schedule');renderEvents();} catch(error){notice(error.message,true);} }
function cancelButton(category,x){
  return ['pending','confirmed'].includes(x.status)?`<div class="item-actions"><button data-cancel="${category}:${x.id}">Запросить отмену</button></div>`:'';
}
async function loadMe(){
  // Don't overwrite a guest's typing when a slow /api/me reply arrives.
  const editAtRequest=state.profileEditSerial;
  try {
    state.me=await api('/api/me');const u=state.me.user;
    if(editAtRequest===state.profileEditSerial){
      $('#full-name').value=u.full_name||'';$('#phone').value=u.phone||'';$('#nickname').value=u.nickname||'';
    }
    const admin=['owner','senior','admin'].includes(u.role);
    $('#admin-nav').classList.toggle('hidden',!admin);
    $('#admin-create').classList.toggle('hidden',!['owner','senior'].includes(u.role));
    $('#audit-tab').classList.toggle('hidden',!['owner','senior'].includes(u.role));
    const cards=[];
    for(const x of state.me.requests.events) cards.push(`<article class="item"><div class="item-top"><span class="tag">ИГРА</span><span class="tag">${statusRU[x.status]||escapeHtml(x.status)}</span></div><h3>${escapeHtml(x.title)}</h3><p>${escapeHtml(fullDate(x.starts_at))}</p>${cancelButton('event',x)}</article>`);
    for(const x of state.me.requests.billiard) cards.push(`<article class="item"><div class="item-top"><span class="tag">БИЛЬЯРД</span><span class="tag">${statusRU[x.status]||escapeHtml(x.status)}</span></div><h3>${escapeHtml(fullDate(x.starts_at))}</h3><p>Гостей: ${Number(x.guest_count)}</p>${cancelButton('billiard',x)}</article>`);
    $('#my-requests').innerHTML=cards.length?cards.join(''):emptyView('06_no_bookings.png','Пока нет заявок. Выберите игру и запишитесь.');
    return state.me;
  } catch(error) {
    notice((demoBrowser?'Для записи и личного кабинета откройте приложение через Telegram. ':'')+error.message,true);
    return null;
  }
}
async function needProfile(){
  const me=await loadMe();
  if(!me) return false;
  if(!me.profile_ready){go('profile');notice('Для записи сначала укажите имя, телефон и уникальный игровой ник.');return false;}
  return true;
}
function bookingDay(date) { return clubInput(date).slice(0,10); }
function renderBookingDays(){
  const current=$('#bill-start').value.slice(0,10);
  const today=Date.now();
  $('#booking-days').innerHTML=Array.from({length:7},(_,i)=>{
    const d=new Date(today+i*86400000);
    const iso=bookingDay(d);
    const label=new Intl.DateTimeFormat('ru-RU',{timeZone:state.clubTimezone,day:'2-digit',month:'short'}).format(d);
    const dow=new Intl.DateTimeFormat('ru-RU',{timeZone:state.clubTimezone,weekday:'short'}).format(d);
    return `<button type="button" class="day-chip ${iso===current?'selected':''}" data-bill-day="${iso}" aria-pressed="${iso===current}"><span>${escapeHtml(dow)}</span><strong>${escapeHtml(label)}</strong></button>`;
  }).join('');
}
function renderBookingTimes(){
  const current=$('#bill-start').value;
  const day=current.slice(0,10);
  const selected=current.slice(11,16);
  const duration=Number($('#bill-hours').value)||1;
  const busy=state.busyIntervals||[];
  const times=['16:00','17:00','18:00','19:00','20:00','21:00','22:00','23:00'];
  $('#booking-times').innerHTML=times.map(hour=>{
    const start=Number(hour.slice(0,2))*60;const end=start+duration*60;
    const occupied=busy.some(b=>{
      const bd=bookingDay(new Date(b.starts_at)),ed=bookingDay(new Date(b.ends_at));
      if(bd>day||ed<day)return false;
      const bs=bd===day?Number(localTime(b.starts_at).slice(0,2))*60+Number(localTime(b.starts_at).slice(3,5)):0;
      const be=ed===day?Number(localTime(b.ends_at).slice(0,2))*60+Number(localTime(b.ends_at).slice(3,5)):1440;
      return start<be&&end>bs;
    });
    return `<button type="button" data-bill-time="${hour}" class="time-chip ${hour===selected?'selected':''}" aria-pressed="${hour===selected}" ${occupied?'disabled':''}>${hour}${occupied?' — занято':''}</button>`;
  }).join('');
  refreshBookingSummary();
}
function refreshBookingSummary(){
  const value=$('#bill-start')?.value||'';
  const hours=Number($('#bill-hours')?.value)||1;
  const d=value?new Date(value+':00'):null;
  $('#booking-summary-date').textContent=value?value.slice(8,10)+'.'+value.slice(5,7)+'.'+value.slice(0,4):'Выберите дату';
  $('#booking-summary-time').textContent=(value.slice(11,16)||'Время не выбрано')+' — '+hours+' '+(hours===1?'час':'часа');
  $('#booking-summary-total').textContent=new Intl.NumberFormat('ru-RU').format(hours*900)+' ₽';
  document.querySelectorAll('[data-duration]').forEach(el=>{const selected=Number(el.dataset.duration)===hours;el.classList.toggle('selected',selected);el.setAttribute('aria-pressed',String(selected));});
}
async function loadBusy(){
  const serial=(state.busySerial||0)+1; state.busySerial=serial;
  const value=$('#bill-start').value;
  if(!value){$('#busy-list').textContent='Выберите дату и время.';state.busyIntervals=[];renderBookingDays();renderBookingTimes();return;}
  $('#busy-list').innerHTML='<img class="inline-loading" src="/assets/visual/v017/illustrations/10_loading.png" alt="" aria-hidden="true"> Проверяем занятость…';
  try{
    const result=await api(`/api/billiard/busy?date=${encodeURIComponent(value.slice(0,10))}`);
    if(serial!==state.busySerial)return;
    state.busyIntervals=result.busy;renderBookingDays();renderBookingTimes();
    $('#busy-list').textContent=result.busy.length
      ? result.busy.map(x=>`${localTime(x.starts_at)}–${localTime(x.ends_at)} (занято или ожидает подтверждения)`).join(', ')
      : 'Пока нет других броней на эту дату. Окончательная проверка происходит при отправке заявки.';
  }catch(error){if(serial===state.busySerial){state.busyIntervals=[];renderBookingDays();renderBookingTimes();}if(serial===state.busySerial)$('#busy-list').textContent=error.message;}
}
function pendingCard(x,category,title){
  const isCancel=x.status==='cancel_requested';
  const yes=isCancel?'Подтвердить отмену':'Подтвердить';
  const no=isCancel?'Оставить заявку':'Отклонить';
  return `<article class="item"><div class="item-top"><span class="tag">${category==='event'?'ИГРА':'БИЛЬЯРД'}</span><span class="tag">${statusRU[x.status]}</span></div>
    <h3>${escapeHtml(title)} №${x.id}</h3><p>${escapeHtml(x.full_name||'Без имени')}, ${escapeHtml(x.phone||'Без телефона')}</p>
    <div class="item-actions"><button class="affirm" data-decide="${category}:${x.id}:1">${yes}</button><button class="reject" data-decide="${category}:${x.id}:0">${no}</button></div></article>`;
}
async function loadDashboard(){
  const x=await api('/api/admin/dashboard');
  const metrics=[
    ['Новые заявки',x.pending_total,'Нужны решения'],
    ['Ближайшие игры',x.upcoming_events,'В расписании'],
    ['Игроки',x.confirmed_events,'Подтверждённые заявки'],
    ['Бильярд',x.confirmed_billiard,'Предстоящие брони'],
    ['Гости',x.guests,'Зарегистрированы'],
    ['Открыта запись',x.open_events,'Доступные события'],
  ];
  $('#pending-counter').textContent=x.pending_total;
  $('#admin-metrics').innerHTML=metrics.map(([title,value,description])=>
    `<div class="metric"><div class="metric-label">${escapeHtml(title)}</div><div class="metric-value">${Number(value)||0}</div><div class="metric-caption">${escapeHtml(description)}</div></div>`).join('');
}
async function loadPending(){
  const p=await api('/api/admin/pending');const cards=[];
  p.events.forEach(x=>cards.push(pendingCard(x,'event',x.title)));
  p.billiard.forEach(x=>cards.push(pendingCard(x,'billiard',fullDate(x.starts_at))));
  $('#pending-counter').textContent=cards.length;
  $('#admin-pending').innerHTML=cards.length?cards.join(''):emptyView('06_no_bookings.png','Все заявки обработаны.');
}
async function loadAdminEvents(){
  state.adminEvents=await api('/api/admin/events');
  const canEdit=['owner','senior'].includes(state.me?.user?.role);
  $('#admin-events').innerHTML=state.adminEvents.length?state.adminEvents.map(e=>`<article class="item"><div class="item-top"><span class="tag">${e.kind==='mafia'?'МАФИЯ':'ПОКЕР'}</span><span class="tag">${statusRU[e.status]||e.status}</span></div>
    <h3>${escapeHtml(e.title)}</h3><p>${escapeHtml(fullDate(e.starts_at))}, ${e.occupied}/${e.capacity} мест</p>
    ${canEdit?`<div class="item-actions"><button data-edit="${e.id}" ${e.status==='cancelled'?'disabled':''}>Изменить</button></div>`:''}</article>`).join(''):emptyView('07_no_events.png','Мероприятий ещё нет.');
}
function showEdit(id){
  if(!['owner','senior'].includes(state.me?.user?.role)){notice('Редактирование доступно старшему администратору и владельцу.',true);return;}
  const e=state.adminEvents.find(x=>x.id===id);if(!e)return;
  const fields={id:e.id,kind:e.kind,title:e.title,start:clubInput(new Date(e.starts_at)),cap:e.capacity,min:e.min_players,format:e.format||'classic',stack:e.stack||'',blinds:e.blinds||'',status:e.status};
  Object.entries(fields).forEach(([name,value])=>{$(`#edit-${name}`).value=value;});
  setFormKind('edit');$('#admin-edit').classList.remove('hidden');$('#admin-edit').scrollIntoView({behavior:'smooth',block:'start'});
}
function eventPayload(prefix){
  const v=name=>$(`#${prefix}-${name}`).value;
  const kind=v('kind');
  return {kind,title:v('title').trim(),starts_at:v('start'),capacity:Number(v('cap')),min_players:Number(v('min')),format:kind==='mafia'?v('format'):'',stack:kind==='poker'?v('stack'):'',blinds:kind==='poker'?v('blinds'):''};
}
function setFormKind(prefix){
  const isPoker=$(`#${prefix}-kind`).value==='poker';
  for(const id of ['format','stack','blinds']){
    const element=$(`#${prefix}-${id}`);
    element.closest('label').classList.toggle('hidden',isPoker?id==='format':id!=='format');
    element.disabled=isPoker?id==='format':id!=='format';
  }
}
function userCard(u){
  const owner=state.me?.user?.role==='owner';
  const manager=owner||state.me?.user?.role==='senior';
  const canChange=manager && u.role!=='owner' && (owner||u.role!=='senior');
  const options=['guest','admin',...(owner?['senior']:[])].map(role=>`<option value="${role}" ${u.role===role?'selected':''}>${roleRU[role]}</option>`).join('');
  return `<article class="item"><div class="item-top"><span class="tag">${escapeHtml(roleRU[u.role]||u.role)}</span><span class="tag">ID ${u.telegram_id}</span></div>
     <h3>${escapeHtml(u.nickname||u.full_name||u.first_name||'Гость')}</h3><p>${escapeHtml(u.full_name||'')}, ${escapeHtml(u.phone||'Телефон не указан')}</p>
     ${canChange?`<div class="role-actions"><select aria-label="Роль гостя" data-role-for="${u.telegram_id}">${options}</select><button data-role-save="${u.telegram_id}">Сохранить роль</button></div>`:''}
   </article>`;
}
async function loadUsers(){
  const serial=(state.userSearchSerial||0)+1; state.userSearchSerial=serial;
  const q=$('#user-query').value;
  const users=await api('/api/admin/users?q='+encodeURIComponent(q));
  if(serial!==state.userSearchSerial)return;
  $('#admin-users').innerHTML=users.length?users.map(userCard).join(''):emptyView('09_no_messages.png','Не нашли гостей по Вашему запросу.');
}
async function loadAudit(){
  const items=await api('/api/admin/audit');
  $('#admin-audit').innerHTML=items.length?items.map(x=>`<article class="audit-row"><div><strong>${escapeHtml(x.action)}</strong><span class="meta">${escapeHtml(x.entity_type)} #${x.entity_id??'—'}, автор ${x.actor_id??'система'}</span></div><span class="meta">${escapeHtml(fullDate(x.created_at))}</span></article>`).join(''):'<div class="empty">История пуста.</div>';
}
async function loadOperationsStatus(){
  const box=$('#operations-box');
  if(state.me?.user?.role!=='owner'){box.classList.add('hidden');return;}
  box.classList.remove('hidden');
  const el=$('#operations-info');
  try {
    const data=await api('/api/admin/operations');
    const rows=[
      `База: ${data.database.quick_check_ok?'целостность подтверждена':'НУЖНА ПРОВЕРКА'}, гостей ${data.database.users??'—'}`,
      `Диск: свободно ${data.disk.free_mb??'—'} МБ${data.disk.low_space?', МАЛО МЕСТА':''}`,
      `Уведомления: ожидают ${data.notifications.pending}, ошибок ${data.notifications.failed}`,
      `Google: ${!data.google.configured?'не подключён':data.google.has_error?'ошибка синхронизации':data.google.behind?'есть невыгруженные изменения':'без ошибок'}`,
      `Mini App HTTPS: ${data.telegram.miniapp_https_configured?'адрес настроен':'ожидает подключения'}`,
      `Внешняя шифрованная копия: ${data.offsite?.present ? `последняя проверенная выгрузка ${fullDate(data.offsite.last_verified_upload_at)}` : 'не подтверждена (может быть не настроена)'}`
    ];
    el.textContent=rows.join(', ');
  } catch(error) {el.textContent='Не удалось получить диагностику: '+error.message;}
}
async function loadBackupStatus(){
  const data=await api('/api/admin/backups');
  let message;
  if(!data.enabled) message='Автоматические копии отключены. Включите их в .env перед запуском клуба.';
  else if(!data.active) message='Автоматические резервные копии пока не включены.';
  else if(!data.last_created_at) message='Автоматическая копия ещё не создана. Проверьте состояние после первого запуска.';
  else {
    const date=fullDate(data.last_created_at);
    message=`Последняя копия: ${date}. Всего автоматических копий: ${data.copies}.`;
    if(data.overdue) message+=' Внимание: по расписанию уже пора создать следующую копию.';
  }
  if(data.last_error) message+=` Ошибка последней попытки: ${data.last_error}.`;
  $('#backup-info').textContent=message;
}

async function loadAdminStatus(){
  const [sync,queue]=await Promise.all([api('/api/admin/sync'),api('/api/admin/notifications')]);
  $('#sync-info').textContent=sync.configured?`Google Sheets: синхронизировано ${sync.synced_revision} из ${sync.revision}${sync.last_error?', Ошибка синхронизации':''}`:'Google Sheets: подключение ещё не настроено.';
  $('#notify-info').textContent=demoBrowser?'Telegram-уведомления сейчас недоступны.':`Очередь Telegram: ожидают ${queue.pending}, отправлены ${queue.sent}, ошибка ${queue.failed}.`;
}
async function loadAdminTab(){
  if(state.screen!=='admin')return;
  try{
    const tab=state.adminTab;
    if(tab==='overview')await Promise.all([loadDashboard(),loadBackupStatus(),loadOperationsStatus()]);
    if(tab==='pending')await loadPending();
    if(tab==='support')await loadAdminSupport();
    if(tab==='events')await loadAdminEvents();
    if(tab==='users')await loadUsers();
    if(tab==='audit')await loadAudit();
    await loadAdminStatus();
  }catch(error){notice(error.message,true);}
}
function adminTab(tab){
  if(tab==='audit'&&!['owner','senior'].includes(state.me?.user?.role))return;
  state.adminTab=tab;
  $$('.admin-tab').forEach(el=>{const selected=el.dataset.adminTab===tab;el.classList.toggle('selected',selected);el.setAttribute('aria-selected',String(selected));});
  $$('.admin-panel').forEach(el=>el.classList.toggle('hidden',el.dataset.adminPanel!==tab));
  loadAdminTab();
}
async function loadSupportMine(){
  try {
    const mine=await api('/api/support/mine');
    $('#support-mine').innerHTML=mine.length?mine.map(t=>`<article class="item support-item"><div class="item-top"><span class="tag">ВОПРОС №${t.id}</span><span class="tag status">${t.status==='answered'?'ЕСТЬ ОТВЕТ':'НА РАССМОТРЕНИИ'}</span></div><p>${escapeHtml(t.question)}</p>${t.answer?`<div class="answer"><strong>Администратор</strong><p>${escapeHtml(t.answer)}</p></div>`:''}</article>`).join(''):'<div class="empty">Пока нет обращений. Напишите вопрос выше — он попадёт сотруднику клуба.</div>';
  }catch(error){$('#support-mine').innerHTML=`<div class="empty">${escapeHtml(error.message)}</div>`;}
}
async function loadAdminSupport(){
  const tickets=await api('/api/admin/support');
  $('#admin-support').innerHTML=tickets.length?tickets.map(t=>`<article class="item support-item"><div class="item-top"><span class="tag">№${t.id} ГОСТЬ ${t.telegram_id}</span><span class="tag status">${t.status==='answered'?'ОТВЕЧЕНО':'ЖДЁТ ОТВЕТА'}</span></div><p>${escapeHtml(t.question)}</p><form data-support-reply="${t.id}" class="support-reply"><label>Ответ сотрудника<textarea name="answer" rows="3" maxlength="2000" minlength="2" placeholder="Напишите ответ…" required></textarea></label><button type="submit" class="primary">Отправить ответ</button></form></article>`).join(''):emptyView('09_no_messages.png','Обращений пока нет.');
}
$$('[data-screen]').forEach(button=>button.addEventListener('click',()=>{go(button.dataset.screen,button.dataset.filter||null);if(button.dataset.prefill&&button.dataset.screen==='support'&&!$('#support-message').value.trim())$('#support-message').value=button.dataset.prefill;}));
$$('.chip').forEach(button=>button.addEventListener('click',()=>{state.kind=button.dataset.kind;$$('.chip').forEach(el=>el.classList.toggle('selected',el===button));renderEvents();}));
$$('[data-admin-tab]').forEach(button=>button.addEventListener('click',()=>adminTab(button.dataset.adminTab)));

$('#refresh-admin').addEventListener('click',()=>action(loadPending));
$('#refresh-overview').addEventListener('click',()=>action(loadAdminTab));
$$('[data-admin-jump]').forEach(button=>button.addEventListener('click',()=>adminTab(button.dataset.adminJump)));
$('#refresh-events').addEventListener('click',()=>action(loadAdminEvents));
$('#refresh-support').addEventListener('click',()=>action(loadSupportMine));
$('#refresh-support-admin').addEventListener('click',()=>action(loadAdminSupport));
$('#edit-close').addEventListener('click',()=>$('#admin-edit').classList.add('hidden'));
$('#bill-start').addEventListener('change',loadBusy);
$('#bill-hours').addEventListener('change',renderBookingTimes);
document.addEventListener('click',event=>{
  const duration=event.target.closest('[data-duration]');
  if(!duration)return;
  $('#bill-hours').value=duration.dataset.duration;
  $('#bill-hours').dispatchEvent(new Event('change',{bubbles:true}));
});

document.addEventListener('click',event=>{
  const day=event.target.closest('[data-bill-day]');
  if(day){$('#bill-start').value=day.dataset.billDay+'T'+($('#bill-start').value.slice(11,16)||'18:00');loadBusy();return;}
  const time=event.target.closest('[data-bill-time]');
  if(time&&!time.disabled){$('#bill-start').value=$('#bill-start').value.slice(0,10)+'T'+time.dataset.billTime;renderBookingTimes();loadBusy();}
});
$('#bill-start').addEventListener('input',()=>{if($('#bill-start').value.length>=10)loadBusy();});
$('#user-query').addEventListener('input',()=>{clearTimeout(window._userSearchTimer);window._userSearchTimer=setTimeout(()=>{if(state.screen==='admin'&&state.adminTab==='users')loadUsers().catch(error=>notice(error.message,true));},250);});
for(const prefix of ['create','edit']) $(`#${prefix}-kind`).addEventListener('change',()=>{
  setFormKind(prefix);
  if(prefix==='create'){$('#create-cap').value='10';$('#create-min').value='1';}
});
$('#create-format').addEventListener('change',()=>{$('#create-cap').value=$('#create-format').value==='city'?'15':'10';$('#create-min').value=$('#create-format').value==='city'?'10':'1';});
document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.join)action(async()=>{
    if(!await needProfile())return;
    const key=requestKey('event:'+button.dataset.join,{event_id:Number(button.dataset.join)});
    await api(`/api/events/${button.dataset.join}/join`,{method:'POST',headers:{'X-Idempotency-Key':key}});
    requestDone('event:'+button.dataset.join);
    await refreshEvents();notice('Заявка отправлена. Администратор проверит её.');
  });
  if(button.dataset.members)action(async()=>{
    const members=await api(`/api/events/${button.dataset.members}/confirmed`);
    notice(members.length?'Участники: '+members.map(x=>x.nickname_snapshot).join(', '):'Подтверждённых участников пока нет.');
  });
  if(button.dataset.cancel)action(async()=>{
    const [cat,id]=button.dataset.cancel.split(':');
    await api(`/api/${cat}/${id}/cancel`,{method:'POST'});
    await loadMe();notice('Запрос отмены отправлен администратору.');
  });
  if(button.dataset.decide)action(async()=>{
    const [category,id,approve]=button.dataset.decide.split(':');
    await api('/api/admin/decide',{method:'POST',body:JSON.stringify({category,request_id:Number(id),approve:approve==='1'})});
    await loadPending();await loadDashboard();await loadAdminStatus();await refreshEvents();notice('Решение сохранено.');
  });
  if(button.dataset.retryNotifications)action(async()=>{
    if(state.me?.user?.role!=='owner')throw Error('Доступно только владельцу.');
    if(!window.confirm('Повторить отправку временно не доставленных уведомлений? Иногда адресат может получить сообщение повторно.'))return;
    const result=await api('/api/admin/notifications/retry',{method:'POST'});
    await Promise.all([loadAdminStatus(),loadOperationsStatus()]);
    notice(result.requeued?`Поставлено в очередь повторно: ${result.requeued}.`:'Нет временных ошибок, подходящих для повтора.');
  });
  if(button.dataset.edit)showEdit(Number(button.dataset.edit));
  if(button.dataset.roleSave)action(async()=>{
    const id=button.dataset.roleSave;const select=document.querySelector(`[data-role-for="${id}"]`);
    await api('/api/admin/roles',{method:'POST',body:JSON.stringify({telegram_id:Number(id),role:select.value})});
    await loadUsers();notice('Роль изменена.');
  });
});
document.addEventListener('submit',event=>{
  const form=event.target.closest('[data-support-reply]');if(!form)return;
  event.preventDefault();
  action(async()=>{
    const id=Number(form.dataset.supportReply);
    await api(`/api/admin/support/${id}/reply`,{method:'POST',body:JSON.stringify({text:form.elements.answer.value})});
    await loadAdminSupport();notice('Ответ отправлен в очередь Telegram и сохранён для гостя.');
  });
});
$('#support-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  const text=$('#support-message').value.trim();
  const key=requestKey('support',{text});
  const t=await api('/api/support/tickets',{method:'POST',headers:{'X-Idempotency-Key':key},body:JSON.stringify({text})});
  requestDone('support');
  $('#support-message').value='';
  await loadSupportMine();notice(`Вопрос №${t.id} передан администратору. Ответ придёт в Telegram.`);
});});
$('#profile-form').addEventListener('input',()=>{state.profileEditSerial+=1;});
$('#profile-form').addEventListener('change',()=>{state.profileEditSerial+=1;});
$('#profile-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  await api('/api/profile',{method:'PUT',body:JSON.stringify({full_name:$('#full-name').value,phone:$('#phone').value,nickname:$('#nickname').value})});
  await loadMe();notice('Профиль сохранён. Можно записываться.');
});});
$('#billiard-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  if(!await needProfile())return;
  const payload={starts_at:$('#bill-start').value,hours:Number($('#bill-hours').value),guest_count:Number($('#bill-guests').value)};
  const key=requestKey('billiard',payload);
  await api('/api/billiard',{method:'POST',headers:{'X-Idempotency-Key':key},body:JSON.stringify(payload)});
  requestDone('billiard');
  await loadBusy();go('profile');notice('Заявка на бильярд отправлена и ждёт подтверждения.');
});});
$('#create-event-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  await api('/api/admin/events',{method:'POST',body:JSON.stringify(eventPayload('create'))});
  await Promise.all([loadAdminEvents(),refreshEvents(),loadDashboard()]);notice('Мероприятие добавлено в расписание.');
});});
$('#edit-event-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  const payload={...eventPayload('edit'),status:$('#edit-status').value};
  if(payload.status==='cancelled'&&!window.confirm('Отменить мероприятие и все активные заявки? Это действие нельзя отменить.'))return;
  await api(`/api/admin/events/${$('#edit-id').value}`,{method:'PUT',body:JSON.stringify(payload)});
  $('#admin-edit').classList.add('hidden');
  await Promise.all([loadAdminEvents(),refreshEvents(),loadDashboard()]);notice('Изменения мероприятия сохранены.');
});});

function addChatMessage(text,who='bot') {
  const el=document.createElement('div');el.className='chat-msg '+who;
  el.textContent=text;
  const log=$('#chat-messages');log.appendChild(el);log.scrollTop=log.scrollHeight;
}
async function submitChatQuestion(question) {
  const value=String(question||'').trim();if(!value)return;
  addChatMessage(value,'guest');$('#chat-question').value='';
  try {
    const result=await api('/api/assistant/reply',{method:'POST',body:JSON.stringify({text:value})});
    addChatMessage(result.answer,'bot');
    if(!result.matched){addChatMessage('Если нужно, откройте раздел «Связь» и передайте этот вопрос администратору.','bot');}
  }catch(error){addChatMessage(error.message,'bot');}
}
$('#chat-form').addEventListener('submit',event=>{
  event.preventDefault();
  const input=$('#chat-question');const value=input.value;
  action(async()=>submitChatQuestion(value));
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-ask-example]');
  if(button)action(async()=>submitChatQuestion(button.dataset.askExample));
});

window.addEventListener('offline',()=>notice('Нет подключения к интернету. Изменения не отправятся до восстановления связи.',true));
window.addEventListener('online',()=>notice('Подключение восстановлено. Можно продолжать работу.'));
(async()=>{
  setFormKind('create');setFormKind('edit');
  try {
    const config=await api('/api/config');
    state.clubTimezone=config.club_timezone;
    $$('.club-timezone').forEach(el=>el.textContent=state.clubTimezone);
  } catch(error) { notice('Настройки времени пока недоступны: '+error.message,true); }
  $('#bill-start').value=clubInput(new Date(Date.now()+60*60*1000));
  renderBookingDays();renderBookingTimes();
  await refreshEvents();
  const me=await loadMe();
  if(!me && demoBrowser)notice('Откройте приложение через Telegram, чтобы войти в личный кабинет.',true);
})();
