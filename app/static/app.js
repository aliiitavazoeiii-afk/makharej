const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const state = {categories: [], dashboard: null, period: null};
const nf = new Intl.NumberFormat('fa-IR');
const money = n => nf.format(Math.round(Number(n||0)));
const faDigits = s => String(s).replace(/\d/g,d=>'۰۱۲۳۴۵۶۷۸۹'[d]);
const esc = s => String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

function toast(msg, error=false){const t=$('#toast');t.textContent=msg;t.className='toast show'+(error?' error':'');clearTimeout(t._timer);t._timer=setTimeout(()=>t.className='toast',2600)}
async function api(url, opts={}){
  const options={...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}};
  const r=await fetch(url,options);
  if(r.status===401 && !url.includes('/api/login')){showLogin();throw new Error('unauthorized')}
  if(!r.ok){let e={};try{e=await r.json()}catch{};throw new Error(e.detail||'خطا در ارتباط با سرور')}
  const ct=r.headers.get('content-type')||'';return ct.includes('json')?r.json():r.text();
}
function showLogin(){ $('#appShell').classList.add('hidden');$('#loginScreen').classList.remove('hidden') }
function showApp(){ $('#loginScreen').classList.add('hidden');$('#appShell').classList.remove('hidden') }
function openModal(id){$(id).classList.remove('hidden');setTimeout(()=>$(id+' input:not([type=color]), '+id+' select')?.focus(),50)}
function closeModal(el){el.closest('.modal')?.classList.add('hidden')}

async function bootstrap(){
  try{const me=await api('/api/me');if(!me.authenticated){showLogin();return}showApp();await loadCategories();await loadDashboard();}
  catch(e){if(e.message!=='unauthorized')toast(e.message,true)}
}

$('#loginForm').addEventListener('submit',async e=>{e.preventDefault();$('#loginError').textContent='';try{await api('/api/login',{method:'POST',body:JSON.stringify({username:$('#loginUsername').value,password:$('#loginPassword').value})});showApp();await loadCategories();await loadDashboard()}catch(err){$('#loginError').textContent=err.message}});
$('#logoutBtn').addEventListener('click',async()=>{await api('/api/logout',{method:'POST'});showLogin()});
$('#mobileMenu').addEventListener('click',()=>$('.sidebar').classList.toggle('open'));

$$('.nav-item[data-page]').forEach(b=>b.addEventListener('click',()=>gotoPage(b.dataset.page)));
$$('[data-goto]').forEach(b=>b.addEventListener('click',()=>gotoPage(b.dataset.goto)));
function gotoPage(page){
  $$('.page').forEach(p=>p.classList.toggle('active',p.id===`page-${page}`));
  $$('.nav-item[data-page]').forEach(n=>n.classList.toggle('active',n.dataset.page===page));
  $('.sidebar').classList.remove('open');
  if(page==='expenses')loadExpenses(); if(page==='categories')renderCategories(); if(page==='reports')loadReports(); if(page==='budgets')loadBudgets(); if(page==='bills')loadBills(); if(page==='settings')loadSettings();
}

$$('[data-open-expense]').forEach(b=>b.addEventListener('click',()=>{if(state.dashboard)$('#expenseDate').value=state.dashboard.today_jalali||'';openModal('#expenseModal')}));
$$('[data-open-category]').forEach(b=>b.addEventListener('click',()=>openModal('#categoryModal')));
$$('[data-open-budget]').forEach(b=>b.addEventListener('click',()=>openModal('#budgetModal')));
$$('[data-open-bill]').forEach(b=>b.addEventListener('click',()=>openModal('#billModal')));
$$('.modal-close').forEach(b=>b.addEventListener('click',()=>closeModal(b)));
$$('.modal').forEach(m=>m.addEventListener('click',e=>{if(e.target===m)m.classList.add('hidden')}));

async function loadCategories(){
  state.categories=await api('/api/categories');
  const options=state.categories.map(c=>`<option value="${c.id}">${esc(c.icon)} ${esc(c.name)}</option>`).join('');
  $('#expenseCategory').innerHTML=options;$('#budgetCategory').innerHTML=options;$('#billCategory').innerHTML='<option value="">بدون دسته‌بندی</option>'+options;
  $('#expenseCategoryFilter').innerHTML='<option value="">همه دسته‌بندی‌ها</option>'+options;
}

function shiftJMonth(jy,jm,delta){let y=jy,m=jm+delta;while(m<1){m+=12;y--}while(m>12){m-=12;y++}return[y,m]}
$('#monthPicker').addEventListener('click',async()=>{if(!state.period)return;const [y,m]=shiftJMonth(state.period.jyear,state.period.jmonth,-1);await loadDashboard(y,m)});

async function loadDashboard(jy=null,jm=null){
  let url='/api/dashboard';if(jy&&jm)url+=`?jyear=${jy}&jmonth=${jm}`;
  const d=await api(url);state.dashboard=d;state.period=d.period;
  $('#periodTitle').textContent=d.period.title;$('#greetingText').textContent=`سلام ${d.display_name} جان 👋`;
  $('#kpiToday').textContent=money(d.summary.today);$('#kpiTodayCount').textContent=`${nf.format(d.summary.today_count)} مورد`;
  $('#kpiMonth').textContent=money(d.summary.month);
  $('#kpiMonthChange').textContent=d.summary.change_pct===null?'ماه قبل داده‌ای ندارد':`${d.summary.change_pct>=0?'↑':'↓'} ${nf.format(Math.abs(d.summary.change_pct))}٪ نسبت به ماه قبل`;
  $('#kpiMonthChange').style.color=d.summary.change_pct>0?'#ff7b82':'#5dd6bc';
  $('#kpiRemaining').textContent=money(d.summary.remaining);$('#kpiAverage').textContent=money(d.summary.average_daily);
  $('#kpiBudget').textContent=d.summary.budget?`از ${money(d.summary.budget)} تومان`:'بودجه تعیین نشده';
  const pct=d.summary.budget?Math.min(100,(d.summary.month/d.summary.budget)*100):0;$('#budgetProgress').style.width=pct+'%';
  renderWeeklyChart(d.daily);renderDonut(d.categories,d.summary.month);renderRecent(d.recent);renderUpcoming(d.bills);renderBudgetOverview(d.budgets);renderInsight(d.insight);
  try{const s=await api('/api/settings');d.today_jalali=s.today_jalali;if(!$('#expenseDate').value)$('#expenseDate').value=s.today_jalali;if(!$('#billDate').value)$('#billDate').value=s.today_jalali}catch{}
}

function renderWeeklyChart(data){
  const c=$('#weeklyChart'),ctx=c.getContext('2d');const rect=c.getBoundingClientRect(),dpr=window.devicePixelRatio||1;c.width=rect.width*dpr;c.height=rect.height*dpr;ctx.scale(dpr,dpr);
  const W=rect.width,H=rect.height,p={l:18,r:14,t:22,b:38};ctx.clearRect(0,0,W,H);
  const vals=data.map(x=>Number(x.amount));const max=Math.max(...vals,1);const nice=Math.ceil(max/500000)*500000||500000;
  ctx.strokeStyle='#23334d';ctx.lineWidth=1;ctx.setLineDash([4,5]);ctx.fillStyle='#77869f';ctx.font='10px Tahoma';ctx.textAlign='right';
  for(let i=0;i<=4;i++){const y=p.t+(H-p.t-p.b)*i/4;ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(W-p.r,y);ctx.stroke();ctx.fillText(money(nice*(4-i)/4),W-p.r,y-5)}ctx.setLineDash([]);
  const pts=vals.map((v,i)=>({x:p.l+(W-p.l-p.r)*(i/(vals.length-1||1)),y:H-p.b-(H-p.t-p.b)*(v/nice)}));
  const grad=ctx.createLinearGradient(0,p.t,0,H-p.b);grad.addColorStop(0,'rgba(91,140,255,.30)');grad.addColorStop(1,'rgba(91,140,255,0)');
  ctx.beginPath();pts.forEach((pt,i)=>i?ctx.lineTo(pt.x,pt.y):ctx.moveTo(pt.x,pt.y));ctx.lineTo(pts[pts.length-1].x,H-p.b);ctx.lineTo(pts[0].x,H-p.b);ctx.closePath();ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();pts.forEach((pt,i)=>i?ctx.lineTo(pt.x,pt.y):ctx.moveTo(pt.x,pt.y));ctx.strokeStyle='#6e9cff';ctx.lineWidth=3;ctx.shadowBlur=12;ctx.shadowColor='rgba(91,140,255,.45)';ctx.stroke();ctx.shadowBlur=0;
  pts.forEach(pt=>{ctx.beginPath();ctx.arc(pt.x,pt.y,4,0,Math.PI*2);ctx.fillStyle='#eef4ff';ctx.fill();ctx.beginPath();ctx.arc(pt.x,pt.y,2,0,Math.PI*2);ctx.fillStyle='#5b8cff';ctx.fill()});
  ctx.textAlign='center';ctx.fillStyle='#8291a8';ctx.font='10px Tahoma';data.forEach((x,i)=>ctx.fillText(x.label,pts[i].x,H-13));
}
window.addEventListener('resize',()=>state.dashboard&&renderWeeklyChart(state.dashboard.daily));

function renderDonut(cats,total){
  const shown=cats.filter(c=>c.amount>0).slice(0,6);let cursor=0,parts=[];shown.forEach(c=>{const p=total?c.amount*100/total:0;parts.push(`${c.color} ${cursor}% ${cursor+p}%`);cursor+=p});if(cursor<100)parts.push(`#20314a ${cursor}% 100%`);$('#donutChart').style.background=`conic-gradient(${parts.join(',')})`;$('#donutTotal').textContent=money(total);
  $('#categoryLegend').innerHTML=shown.length?shown.map(c=>`<div class="legend-row"><i style="background:${esc(c.color)}"></i><span>${esc(c.name)}</span><b>${money(c.amount)}</b><em>${nf.format(c.percentage)}٪</em></div>`).join(''):'<div class="empty">هنوز خرجی ثبت نشده</div>';
}
function renderRecent(items){$('#recentTransactions').innerHTML=items.length?items.slice(0,4).map(x=>`<div class="compact-item"><div class="compact-icon" style="color:${esc(x.color)}">${esc(x.icon)}</div><div class="compact-text"><strong>${esc(x.note||x.category)}</strong><span>${esc(x.date_label)} · ${esc(x.category)}</span></div><div class="compact-amount">${money(x.amount)}<br><span>تومان</span></div></div>`).join(''):'<div class="empty">اولین خرجت را ثبت کن</div>'}
function renderUpcoming(items){$('#upcomingBills').innerHTML=items.length?items.slice(0,3).map(x=>`<div class="compact-item"><div class="compact-icon">${esc(x.icon||'◷')}</div><div class="compact-text"><strong>${esc(x.title)}</strong><span class="${x.overdue?'overdue':''}">${esc(x.date_label)}</span></div><div class="compact-amount">${money(x.amount)}<br><span>تومان</span></div></div>`).join(''):'<div class="empty">پرداخت آینده‌ای ثبت نشده</div>'}
function renderBudgetOverview(items){$('#budgetOverview').innerHTML=items.length?items.slice(0,4).map(x=>`<div class="budget-row"><div class="budget-row-head"><span>${esc(x.name)}</span><span>${money(x.spent)} / ${money(x.amount)}</span></div><div class="progress"><i style="width:${x.percentage}%;background:${esc(x.color)}"></i></div></div>`).join(''):'<div class="empty">برای دسته‌ها بودجه تعریف کن</div>'}
function renderInsight(i){if(!i){$('#insightText').textContent='بعد از ثبت چند خرج، اینجا الگوی هزینه‌هایت را می‌بینی.';return}let text=`بیشترین خرج این ماه مربوط به «${i.category}» با ${money(i.amount)} تومان است.`;if(i.change_pct!==null)text+=` نسبت به ماه قبل ${nf.format(Math.abs(i.change_pct))}٪ ${i.change_pct>=0?'بیشتر':'کمتر'} شده.`;$('#insightText').textContent=text}

$('#expenseForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/expenses',{method:'POST',body:JSON.stringify({amount:$('#expenseAmount').value,category_id:Number($('#expenseCategory').value),note:$('#expenseNote').value,expense_date:$('#expenseDate').value})});$('#expenseModal').classList.add('hidden');e.target.reset();await loadDashboard(state.period?.jyear,state.period?.jmonth);toast('خرج ثبت شد');if($('#page-expenses').classList.contains('active'))loadExpenses()}catch(err){toast(err.message,true)}});

let searchTimer;$('#expenseSearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadExpenses,250)});$('#expenseCategoryFilter').addEventListener('change',loadExpenses);
async function loadExpenses(){const q=encodeURIComponent($('#expenseSearch').value||'');const cat=$('#expenseCategoryFilter').value;const items=await api(`/api/expenses?q=${q}${cat?`&category_id=${cat}`:''}`);$('#expensesTable').innerHTML=items.length?items.map(x=>`<tr><td><strong>${esc(x.note||'بدون شرح')}</strong></td><td><span class="cat-chip"><i class="cat-dot" style="background:${esc(x.color)}"></i>${esc(x.icon)} ${esc(x.category)}</span></td><td>${esc(x.date_label)}</td><td class="money">${money(x.amount)} تومان</td><td><button class="delete-btn" onclick="deleteExpense(${x.id})">حذف</button></td></tr>`).join(''):'<tr><td colspan="5"><div class="empty">مخارجی پیدا نشد</div></td></tr>'}
window.deleteExpense=async id=>{if(!confirm('این خرج حذف شود؟'))return;try{await api(`/api/expenses/${id}`,{method:'DELETE'});toast('حذف شد');await loadExpenses();await loadDashboard(state.period?.jyear,state.period?.jmonth)}catch(e){toast(e.message,true)}};

function renderCategories(){$('#categoriesGrid').innerHTML=state.categories.map(c=>`<article class="category-card"><div class="category-top"><div class="category-icon" style="background:${esc(c.color)}22;color:${esc(c.color)}">${esc(c.icon)}</div><span class="pill">${nf.format(c.expense_count)} تراکنش</span></div><h3>${esc(c.name)}</h3><p>${money(c.total_spent)} تومان خرج ثبت‌شده</p>${c.expense_count?``:`<button class="delete-btn" onclick="deleteCategory(${c.id})">حذف</button>`}</article>`).join('')}
$('#categoryForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/categories',{method:'POST',body:JSON.stringify({name:$('#categoryName').value,icon:$('#categoryIcon').value,color:$('#categoryColor').value})});$('#categoryModal').classList.add('hidden');e.target.reset();$('#categoryIcon').value='◌';$('#categoryColor').value='#5b8cff';await loadCategories();renderCategories();toast('دسته‌بندی ساخته شد')}catch(err){toast(err.message,true)}});
window.deleteCategory=async id=>{if(!confirm('دسته‌بندی حذف شود؟'))return;try{await api(`/api/categories/${id}`,{method:'DELETE'});await loadCategories();renderCategories();toast('حذف شد')}catch(e){toast(e.message,true)}};

async function loadReports(){const r=await api('/api/report?months=6');$('#reportTotal').textContent=money(r.total);$('#reportCount').textContent=nf.format(r.count);$('#reportAverage').textContent=money(r.average);const max=Math.max(...r.monthly.map(x=>x.amount),1);$('#monthlyBars').innerHTML=r.monthly.map(x=>`<div class="bar-col"><div class="bar-value">${money(x.amount)}</div><i style="height:${Math.max(2,x.amount/max*190)}px"></i><span>${esc(x.label)}</span></div>`).join('');const total=r.categories.reduce((s,x)=>s+x.amount,0);$('#reportCategories').innerHTML=r.categories.filter(x=>x.amount).map((x,i)=>`<div class="rank-row"><div class="rank-icon" style="background:${esc(x.color)}22;color:${esc(x.color)}">${esc(x.icon)}</div><div><p>${i+1}. ${esc(x.name)}</p><small>${total?nf.format(Math.round(x.amount*100/total)):0}٪ از کل</small></div><strong>${money(x.amount)} تومان</strong></div>`).join('')||'<div class="empty">هنوز گزارشی وجود ندارد</div>'}

async function loadBudgets(){const r=await api(`/api/budgets${state.period?`?jyear=${state.period.jyear}&jmonth=${state.period.jmonth}`:''}`);$('#budgetsGrid').innerHTML=r.items.map(x=>`<article class="budget-card"><div class="budget-card-head"><div class="category-icon" style="background:${esc(x.color)}22;color:${esc(x.color)}">${esc(x.icon)}</div><h3>${esc(x.name)}</h3></div><div class="budget-numbers"><span>خرج: <strong>${money(x.spent)}</strong></span><span>بودجه: <strong>${money(x.amount)}</strong></span></div><div class="progress"><i style="width:${Math.min(100,x.percentage)}%;background:${esc(x.color)}"></i></div><div class="budget-pct">${x.amount?`${nf.format(Math.round(x.percentage))}٪ مصرف شده`:'بودجه‌ای تعیین نشده'}</div></article>`).join('')}
$('#budgetForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/budgets',{method:'POST',body:JSON.stringify({category_id:Number($('#budgetCategory').value),amount:$('#budgetAmount').value,jyear:state.period?.jyear,jmonth:state.period?.jmonth})});$('#budgetModal').classList.add('hidden');e.target.reset();await loadBudgets();await loadDashboard(state.period?.jyear,state.period?.jmonth);toast('بودجه ذخیره شد')}catch(err){toast(err.message,true)}});

async function loadBills(){const items=await api('/api/bills');$('#billsList').innerHTML=items.length?items.map(x=>`<article class="bill-card ${x.paid?'paid':''}"><div class="category-icon" style="background:${esc(x.color||'#5b8cff')}22;color:${esc(x.color||'#5b8cff')}">${esc(x.icon||'◷')}</div><div><strong>${esc(x.title)}</strong><p>${esc(x.date_label)} · ${money(x.amount)} تومان${x.recurring_monthly?' · ماهانه':''}</p></div><div class="bill-actions">${x.paid?'<span class="pill">پرداخت شده</span>':`<button class="small-btn pay" onclick="payBill(${x.id})">پرداخت شد</button>`}<button class="small-btn" onclick="deleteBill(${x.id})">حذف</button></div></article>`).join(''):'<div class="panel empty">قبض یا پرداخت آینده‌ای ثبت نشده</div>'}
$('#billForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/bills',{method:'POST',body:JSON.stringify({title:$('#billTitle').value,amount:$('#billAmount').value,due_date:$('#billDate').value,category_id:$('#billCategory').value?Number($('#billCategory').value):null,recurring_monthly:$('#billRecurring').checked})});$('#billModal').classList.add('hidden');e.target.reset();await loadBills();await loadDashboard(state.period?.jyear,state.period?.jmonth);toast('پرداخت آینده ثبت شد')}catch(err){toast(err.message,true)}});
window.payBill=async id=>{if(!confirm('این مبلغ به عنوان خرج امروز هم ثبت شود؟'))return;try{await api(`/api/bills/${id}/pay`,{method:'POST'});toast('پرداخت ثبت شد');await loadBills();await loadDashboard(state.period?.jyear,state.period?.jmonth)}catch(e){toast(e.message,true)}};
window.deleteBill=async id=>{if(!confirm('این مورد حذف شود؟'))return;try{await api(`/api/bills/${id}`,{method:'DELETE'});await loadBills();toast('حذف شد')}catch(e){toast(e.message,true)}};

async function loadSettings(){const s=await api('/api/settings');$('#displayName').value=s.display_name;$('#monthlyBudget').value=s.monthly_budget||'';$('#todayJalali').textContent=faDigits(s.today_jalali)}
$('#settingsForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/settings',{method:'POST',body:JSON.stringify({display_name:$('#displayName').value,monthly_budget:$('#monthlyBudget').value||0})});toast('تنظیمات ذخیره شد');await loadDashboard(state.period?.jyear,state.period?.jmonth)}catch(err){toast(err.message,true)}});

bootstrap();
