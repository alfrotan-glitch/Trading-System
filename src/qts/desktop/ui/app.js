const $ = id => document.getElementById(id);
const api = p => fetch(p).then(r=>r.json());

function nav(){
  document.querySelectorAll('.nav button').forEach(b=>{
    b.onclick = ()=>{
      document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));
      b.classList.add('active');
      const v=b.dataset.view;
      document.querySelectorAll('.view').forEach(s=>s.classList.remove('active'));
      document.getElementById('view-'+v).classList.add('active');
      loadView(v);
    };
  });
}
async function loadView(v){
  try{
    if(v==='home') await loadHome();
    if(v==='dashboard') await loadDashboard();
    if(v==='research') await loadResearch();
    if(v==='strategies') await loadStrategies();
    if(v==='validation') {} // manual
    if(v==='paper') await loadPaperShadow();
    if(v==='execution') await loadExecution();
    if(v==='risk') await loadRisk();
    if(v==='mt5') await loadMT5();
    if(v==='audit') await loadAudit();
    if(v==='live') await loadLive();
    await loadNotifications();
  }catch(e){console.error(e)}
}

async function loadHome(){
  const h = await api('/api/health');
  $('env-badge').textContent = h.env;
  $('env-badge').className = 'badge ' + (h.env==='live'?'live':'');
  $('health-mini').textContent = `${h.system_status} • ${h.mt5} • ${h.market_data}`;
  $('health-mini').style.background = h.system_status==='Running'?'#022c22': h.system_status==='Suspended'?'#450a0a':'#451a03';
  const grid = $('home-grid');
  const items = [
    ['SYSTEM STATUS', h.system_status, h.system_status==='Running'?'ok': h.system_status==='Suspended'?'danger':'warn'],
    ['MT5', h.mt5, h.mt5==='Connected'?'ok':'warn'],
    ['MARKET DATA', h.market_data, h.market_data==='Healthy'?'ok':'danger'],
    ['RISK', h.risk, h.risk==='Healthy'?'ok':'danger'],
    ['RECONCILIATION', h.reconciliation, h.reconciliation==='Healthy'?'ok':'danger'],
    ['STRATEGY', h.strategy?h.strategy.strategy_id:'none', 'ok'],
    ['TRADING MODE', h.trading_mode, 'ok'],
    ['LIVE STATUS', h.live_status, h.live_status==='BLOCKED'?'danger':'warn'],
  ];
  grid.innerHTML = items.map(([label,val,cls])=>`<div class="status ${cls}"><div class="label">${label}</div><div class="value">${val}</div></div>`).join('');
  $('startup-health').textContent = JSON.stringify(h, null, 2);
  $('mode-banner').textContent = `TRADING MODE: ${h.trading_mode} — LIVE ${h.live_status}`;
}
async function loadDashboard(){
  const d = await api('/api/dashboard');
  const h = d.health || {};
  const safety = $('safety-banner');
  if(h.system_status!=='Running' || d.reconciliation_status!=='Healthy'){
    safety.className='banner danger';
    safety.textContent = `SAFETY: ${h.system_status} — ${h.risk} — ${h.reconciliation} — trading blocked until healthy`;
  } else {
    safety.className='banner ok';
    safety.textContent = `SAFETY: Running — risk healthy — reconciliation healthy`;
  }
  $('kpi-grid').innerHTML = [
    ['Equity', d.equity?.toFixed?.(2)??d.equity],
    ['Balance', d.balance?.toFixed?.(2)??d.balance],
    ['Unrealized PnL', d.unrealized_pnl],
    ['Realized PnL', d.realized_pnl],
    ['Drawdown', d.drawdown],
    ['Exposure', d.exposure],
    ['Market', d.market_status],
    ['Spread', d.spread],
  ].map(([k,v])=>`<div class="kpi"><div class="label">${k}</div><div class="value">${v}</div></div>`).join('');
  $('positions').textContent = (d.open_positions && d.open_positions.length) ? JSON.stringify(d.open_positions, null,2) : 'No open positions (paper/mock)';
  $('decisions').textContent = d.latest_decision? JSON.stringify(d.latest_decision,null,2) : 'No recent decisions';
  $('recon').textContent = d.reconciliation_status;
}
async function loadResearch(){
  const campaigns = await api('/api/research/campaigns');
  $('campaigns-list').innerHTML = campaigns.length ? campaigns.map(c=>`<div class="card"><b>${c.id}</b> ${c.config.family} ${c.config.symbol} ${c.config.timeframe} — ${c.status} — trials ${c.config.max_trials}<br/><span class="muted">${JSON.stringify(c.config.param_space)}</span></div>`).join('') : '<span class="muted">No campaigns yet — create one above.</span>';
  // trial ledger via audit? We'll show recent experiments count
  try{
    const audit = await api('/api/audit?limit=3');
    $('trial-ledger').textContent = JSON.stringify(audit.slice(0,5), null,2);
  }catch(e){$('trial-ledger').textContent='No ledger yet'}
}
async function loadStrategies(){
  const list = await api('/api/strategies');
  $('strategy-cards').innerHTML = list.map(s=>`<div class="card-strategy">
    <h4>${s.strategy_id} <span class="badge-state">${s.lifecycle_state||s.decision||'RESEARCH'}</span></h4>
    <div class="meta">${s.name||''} • ${s.symbol||''} ${s.timeframe||''} • family ${s.family||''} • v${s.version||''}</div>
    <div class="meta">OOS Sharpe ${s.oos_sharpe??'—'} • DSR ${s.dsr??'—'} • PBO ${s.pbo??'—'}</div>
    <div class="meta">Expectancy ${s.expectancy??'—'} • Drawdown ${s.max_drawdown??'—'} • Cost tol ${s.cost_tolerance??'—'}</div>
    <div class="meta">Last validation ${s.last_validation||'—'} • Decision ${s.decision||s.lifecycle_state}</div>
  </div>`).join('') || '<span class="muted">No strategies registered — run a campaign or qts research propose.</span>';
}
async function loadPaperShadow(){
  const paper = await api('/api/paper');
  const shadow = await api('/api/shadow');
  $('paper-view').textContent = JSON.stringify(paper, null,2);
  $('shadow-view').textContent = JSON.stringify(shadow, null,2);
  $('shadow-paper-diff').textContent = JSON.stringify(shadow.shadow_vs_paper_discrepancy, null,2);
}
async function loadExecution(){
  const orders = await api('/api/execution/orders?limit=20');
  $('orders').innerHTML = orders.map(o=>`<div class="card"><div class="meta">${o.time||''} ${o.type||''}</div><pre class="pre">${JSON.stringify(o.payload||o,null,2)}</pre></div>`).join('') || 'No orders';
}
async function loadRisk(){
  const r = await api('/api/risk');
  $('risk-limits').innerHTML = Object.entries(r.limits).map(([k,v])=>`<div class="kpi"><div class="label">${k}</div><div class="value">${v}</div></div>`).join('');
  // wrap in grid
  $('risk-limits').className='kpi-grid';
  $('risk-block').className = r.blocked ? 'banner danger' : 'banner ok';
  $('risk-block').textContent = r.blocked ? `TRADING BLOCKED — Reasons: ${r.blocked_reasons.join('; ')}` : 'TRADING ALLOWED (mock/demo)';
}
async function loadMT5(){
  const m = await api('/api/mt5');
  $('mt5-view').innerHTML = `<div class="card"><b>Mode ${m.mode}</b> — ${m.connected?'Connected':'Disconnected'}<br/>${m.terminal_status}<br/><pre class="pre">${JSON.stringify(m.spec||m,null,2)}</pre><div class="banner warn">${m.warning||''}</div><div class="meta">Mock vs Real clearly distinguished — never imply mock is real.</div></div>`;
}
async function loadAudit(){
  const q = $('audit-q').value || '';
  const url = q ? `/api/audit?limit=50&q=${encodeURIComponent(q)}` : '/api/audit?limit=50';
  const list = await api(url);
  $('audit-list').textContent = JSON.stringify(list, null,2);
}
async function loadLive(){
  const l = await api('/api/live/status');
  $('live-badge').className = l.eligible ? 'banner warn' : 'banner danger';
  $('live-badge').textContent = l.live_trading;
  const checklist = l.checklist || {};
  $('live-checklist').innerHTML = Object.entries(checklist).map(([k,v])=>`<div class="status ${v?'ok':'warn'}"><div class="label">${k}</div><div class="value">${v?'✓':'✗'} ${k}</div></div>`).join('');
  $('live-checklist').className='status-grid';
  $('live-reasons').textContent = (l.blocked_reasons||[]).join('\n') + '\n\n' + l.message;
  $('btn-request-live').disabled = true;
}

async function loadNotifications(){
  const notes = await api('/api/notifications');
  $('notifications').innerHTML = notes.map(n=>`<div class="note ${n.level==='critical'?'critical':''}"><b>${n.title}</b><div class="meta">${n.detail}</div></div>`).join('');
}

$('btn-start-campaign').onclick = async ()=>{
  const payload = {
    name: `campaign-${Date.now()}`,
    symbol: $('campaign-symbol').value || 'XAUUSD',
    timeframe: $('campaign-timeframe').value || '1H',
    data_version: $('campaign-version').value || (await api('/api/health')).latest_version || '20260916-010-572728d9',
    family: $('campaign-family').value,
    param_space: {}, // use bounded defaults
    max_trials: parseInt($('campaign-trials').value,10)||12,
    max_runtime_s: 60,
    max_param_combinations: parseInt($('campaign-trials').value,10)||12,
    seed: 42,
  };
  $('campaign-result').textContent='Running campaign… (bounded, reproducible)';
  try{
    const res = await fetch('/api/research/campaigns', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)}).then(r=>r.json());
    $('campaign-result').textContent = JSON.stringify(res, null,2);
    loadResearch();
  }catch(e){$('campaign-result').textContent='Error: '+e}
};

$('btn-load-validation').onclick = async ()=>{
  const sid=$('val-strategy').value||'sma_breakout';
  const v = await api(`/api/validation/${encodeURIComponent(sid)}`);
  $('validation-detail').textContent = JSON.stringify(v.evidence||v, null,2);
  const sc = await api(`/api/strategies/${encodeURIComponent(sid)}/scorecard`).catch(()=>null);
  if(sc){
    $('scorecard').innerHTML = `<h3>Edge Scorecard — Each dimension independently</h3><pre class="pre">${JSON.stringify(sc,null,2)}</pre><div class="banner ${sc.overall_passed?'ok':'danger'}">${sc.overall_passed?'PASS — all mandatory gates passed':'BLOCK — keep NO_TRADE — '+ (sc.blocked_reasons||[]).join(', ')}</div>`;
  }
};
$('btn-audit-search').onclick = loadAudit;

nav();
loadView('home');
setInterval(loadNotifications, 10000);
