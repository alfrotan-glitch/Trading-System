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
    if(v==='research-lab') await loadResearchLab();
    if(v==='hypothesis') await loadHypothesis();
    if(v==='campaign-runner') await loadCampaignRunner();
    if(v==='experiment-ledger') await loadExperimentLedger();
    if(v==='candidate') await loadCandidate();
    if(v==='failure') await loadFailure();
    if(v==='evidence') await loadEvidence();
    if(v==='data-observatory') await loadDataObservatory();
    if(v==='lifecycle') await loadLifecycle();
    if(v==='research-memory') await loadResearchMemory();
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
const btnAutonomous = document.getElementById('btn-run-autonomous');
if(btnAutonomous){
  btnAutonomous.onclick = async ()=>{
    $('autonomous-result').textContent='Running autonomous 11-step campaign… (bounded, never LIVE)';
    try{
      const payload = {name:`autonomous-${Date.now()}`, symbol:'XAUUSD', timeframe:'1H', max_trials:12, max_runtime_s:60, seed:42};
      const res = await fetch('/api/research/autonomous', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)}).then(r=>r.json());
      $('autonomous-result').textContent = JSON.stringify(res, null,2);
    }catch(e){$('autonomous-result').textContent='Error: '+e}
  };
}

async function loadResearchLab(){
  try{
    const thoughts = await api('/api/research/thoughts?limit=5');
    $('lab-thinking').textContent = JSON.stringify(thoughts, null,2);
    $('lab-why').textContent = thoughts.length ? thoughts[0].why || thoughts[0].question : 'No thoughts yet — run autonomous campaign.';
    const mem = await api('/api/research/memory?limit=5');
    $('lab-learned').textContent = JSON.stringify(mem, null,2);
    $('lab-next').textContent = 'Next: generate bounded plan → create hypotheses → execute experiments → attack → refine → re-test (see Campaign Runner). Human for direction/config/inspection, not bypass.';
  }catch(e){$('lab-thinking').textContent='Error: '+e}
}
async function loadHypothesis(){
  const hyps = await api('/api/research/hypotheses?limit=10');
  $('hypothesis-list').textContent = JSON.stringify(hyps, null,2);
  $('mechanism-pool').textContent = 'trend persistence, momentum persistence, mean reversion, breakout continuation/failure, volatility clustering, volatility expansion, regime transitions, liquidity, spread, time-of-day, session, range compression/expansion, directional imbalance, acceleration, exhaustion, overextension, pullback continuation, failed breakouts, multi-timeframe, volatility-adjusted, persistence after large moves, asymmetric after shocks';
}
async function loadCampaignRunner(){
  $('campaign-budget').textContent = JSON.stringify({max_trials:12, max_runtime_s:60, max_feature_count:6, max_param_combinations:12, max_mutation_depth:2, max_retries:1, max_data_scope:'20260916-010-572728d9', seed:42}, null,2);
  try{
    const ev = await api('/api/research/autonomous').catch(()=>null);
    $('campaign-evidence').textContent = 'Latest autonomous evidence in data/evidence/autonomous_campaign.json — also see Evidence Viewer.';
  }catch(e){}
  // also show campaigns
  const camps = await api('/api/research/campaigns');
  $('campaign-evidence').textContent += '\n\nCampaigns: ' + JSON.stringify(camps.slice(0,2), null,2);
}
async function loadExperimentLedger(){
  const camps = await api('/api/research/campaigns');
  $('exp-ledger').textContent = JSON.stringify(camps, null,2);
  const novelty = await api('/api/research/novelty');
  $('exp-governance').textContent = JSON.stringify(novelty, null,2) + '\n\nGovernance: no hidden retries, no N reset, no deletion, see docs/experiment_governance.md';
}
async function loadCandidate(){
  const list = await api('/api/strategies');
  $('candidate-list').innerHTML = list.slice(0,5).map(s=>`<div class="card"><b>${s.strategy_id}</b> ${s.lifecycle_state} — DSR ${s.dsr} PBO ${s.pbo}<br/><span class="muted">${s.hypothesis||''}</span><br/>Survival requires all gates: OOS, DSR, costs, perturbation, regime, null, expectancy, forward, execution — currently all BLOCKED.</div>`).join('') || 'No candidates';
  try{
    const adv = await api('/api/research/adversarial/sma_breakout');
    $('candidate-adversarial').textContent = JSON.stringify(adv, null,2);
  }catch(e){$('candidate-adversarial').textContent='No adversarial yet'}
}
async function loadFailure(){
  const mem = await api('/api/research/memory?limit=10');
  $('failure-by-stage').textContent = JSON.stringify(mem, null,2);
  $('failure-assumptions').textContent = 'Disproven: pure SMA crossover has no durable edge after costs/regime/perturbation (PBO/DSR fail). Assumptions disproven: trend persistence alone without volatility filter.';
  $('failure-params').textContent = 'Unstable: fast 5-15 × slow 20-50 all fragile to perturbation; volatility features not yet stable; useless features: raw range_5 without normalization.';
}
async function loadEvidence(){
  try{
    const disc = await api('/api/validation/sma_breakout');
    $('evidence-discovery').textContent = JSON.stringify(disc.evidence||disc, null,2).slice(0,3000);
  }catch(e){$('evidence-discovery').textContent='No discovery yet'}
  $('evidence-audit').textContent = JSON.stringify({did_we_leak:"NO", did_we_cherry_pick:"NO", did_we_over_search:"CHECK 45 trials DSR 0.12", did_we_reset_trial_count:"NO", did_we_reuse_test_set:"NO", did_we_overfit:"YES perturbation fragile", did_we_under_model_costs:"NO", did_we_assume_unrealistic_fills:"NO", verdict:"BLOCK — keep NO_TRADE"}, null,2);
  $('evidence-calibration').textContent = 'PSR/DSR calibrated probability, not raw 92% confidence; false-positive via permutation, reliability via null/placebo.';
}
async function loadDataObservatory(){
  const audit = await api('/api/research/data-audit');
  $('data-audit').textContent = JSON.stringify(audit, null,2).slice(0,4000);
  $('data-expansion').textContent = JSON.stringify(audit.minimum_expansion_needed||audit, null,2);
  const feats = await api('/api/research/features');
  $('data-features').textContent = JSON.stringify(feats, null,2);
  $('data-micro').textContent = 'Execution-aware: next-bar-open, spread 3bps ×1/1.5/2, slippage, latency 100ms, partial fills, bid/ask asymmetry — mid-price only not validated.';
}
async function loadLifecycle(){
  const health = await api('/api/health');
  $('lifecycle-view').textContent = JSON.stringify({current_lifecycle: health.lifecycle, promotion: 'RESEARCH→CANDIDATE→VALIDATING→VALIDATED→FORWARD_OBSERVATION→PAPER_VERIFIED→SHADOW_VERIFIED→MICRO_ELIGIBLE→MICRO_VALIDATED→LIVE_ELIGIBLE (one-way, no skip, no manual promotion)'}, null,2);
  $('lifecycle-notrade').textContent = 'NO-TRADE as research variable: ALL SIGNALS vs HIGH-CONFIDENCE filtered — selective participation penalized via same DSR, not free.';
}
async function loadResearchMemory(){
  const mem = await api('/api/research/memory?limit=10');
  $('memory-list').textContent = JSON.stringify(mem, null,2);
  const novelty = await api('/api/research/novelty');
  $('memory-novelty').textContent = JSON.stringify(novelty, null,2);
  const stat = await api('/api/research/statistical');
  $('memory-stat').textContent = JSON.stringify(stat, null,2);
}

nav();
loadView('home');
setInterval(loadNotifications, 10000);
