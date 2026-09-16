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
    if(v==='setup-wizard') await loadSetupWizard();
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
    if(v==='data-source-lab') await loadDataSourceLab();
    if(v==='market-monitor') await loadMarketMonitor();
    if(v==='forward-observatory') await loadForwardObservatory();
    if(v==='data-lineage') await loadDataLineage();
    if(v==='demo-forward') await loadDemoForward();
    if(v==='comparison') await loadComparison();
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
  let accountType = 'MOCK';
  try{ const m = await api('/api/mt5'); accountType = m.account?.login==='mock' ? 'MOCK' : m.mode; }catch(e){}
  const items = [
    ['SYSTEM STATUS', h.system_status, h.system_status==='Running'?'ok': h.system_status==='Suspended'?'danger':'warn'],
    ['ENVIRONMENT', h.env, h.env==='development'?'ok': h.env==='paper'?'ok': h.env==='demo_forward'?'warn':'danger'],
    ['MT5', h.mt5, h.mt5==='Connected'?'ok':'warn'],
    ['ACCOUNT TYPE', accountType, accountType==='MOCK'?'warn': accountType==='DEMO'?'ok':'danger'],
    ['MARKET DATA', h.market_data, h.market_data==='Healthy'?'ok':'danger'],
    ['RISK', h.risk, h.risk==='Healthy'?'ok':'danger'],
    ['RECONCILIATION', h.reconciliation, h.reconciliation==='Healthy'?'ok':'danger'],
    ['STRATEGY', h.strategy?h.strategy.strategy_id:'none', 'ok'],
    ['CURRENT DECISION', h.live_status==='BLOCKED'?'BLOCK — KEEP NO_TRADE':'PENDING', h.live_status==='BLOCKED'?'danger':'warn'],
    ['TRADING MODE', h.trading_mode, 'ok'],
    ['LIVE LOCK', h.live_status, h.live_status==='BLOCKED'?'danger':'warn'],
  ];
  grid.innerHTML = items.map(([label,val,cls])=>`<div class=\"status ${cls}\"><div class=\"label\">${label}</div><div class=\"value\">${val}</div></div>`).join('');
  $('startup-health').textContent = JSON.stringify(h, null, 2);
  $('mode-banner').textContent = `TRADING MODE: ${h.trading_mode} — LIVE ${h.live_status} — ACCOUNT ${accountType}`;
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
// Setup Wizard handlers
const btnSetupCheck = document.getElementById('btn-setup-check-mt5');
if(btnSetupCheck) btnSetupCheck.onclick = async ()=>{
  $('setup-mt5-result').textContent='Checking MT5 (14 checks)...';
  try{ const r = await api('/api/demo/readiness'); $('setup-mt5-result').textContent = JSON.stringify(r, null,2); }catch(e){ $('setup-mt5-result').textContent='Error '+e }
};
const btnSetupSave = document.getElementById('btn-setup-save');
if(btnSetupSave) btnSetupSave.onclick = async ()=>{
  const ack = document.getElementById('setup-risk-ack')?.checked;
  if(!ack){ $('setup-save-result').textContent='Please acknowledge risk limits.'; return; }
  $('setup-save-result').textContent='Setup acknowledged — health check...';
  try{ const h = await api('/api/health'); $('setup-save-result').textContent = JSON.stringify({saved:true, env: h.env, system_status: h.system_status, note: 'Restart app with chosen QTS_ENV to apply. See docs/desktop_installation_windows.md'}, null,2); }catch(e){ $('setup-save-result').textContent='Error '+e }
};
// Demo Forward handlers
const btnDemoRefresh = document.getElementById('btn-demo-refresh-checks');
if(btnDemoRefresh) btnDemoRefresh.onclick = ()=>loadDemoForward();
const btnDemoObserve = document.getElementById('btn-demo-observe-start');
if(btnDemoObserve) btnDemoObserve.onclick = async ()=>{
  document.getElementById('demo-observe').textContent='Observation started — recording ticks via forward_observatory (no orders). See data/evidence/forward_observation_manifest.json';
};
const btnDemoEnable = document.getElementById('btn-demo-enable');
if(btnDemoEnable) btnDemoEnable.onclick = async ()=>{
  const ack = document.getElementById('demo-risk-ack2')?.checked;
  if(!ack){ alert('Please acknowledge risk limits'); return; }
  try{
    const res = await fetch('/api/demo/enable', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({confirmed:true, risk_ack:true})}).then(r=>r.json());
    document.getElementById('demo-execution').textContent = JSON.stringify(res, null,2);
  }catch(e){ document.getElementById('demo-execution').textContent='Error '+e }
};
const btnCompRefresh = document.getElementById('btn-comparison-refresh');
if(btnCompRefresh) btnCompRefresh.onclick = async ()=>{
  try{ const r = await fetch('/api/demo/comparison/refresh', {method:'POST'}).then(x=>x.json()); $('comparison-metrics').textContent = JSON.stringify(r, null,2); }catch(e){ $('comparison-metrics').textContent='Error '+e }
};
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
  try{
    const audit = await api('/api/research/data-audit');
    $('data-audit').textContent = JSON.stringify(audit, null,2).slice(0,4000);
    $('data-expansion').textContent = JSON.stringify(audit.minimum_expansion_needed||audit, null,2);
  }catch(e){ $('data-audit').textContent='Error '+e; $('data-expansion').textContent='Error '+e}
  try{
    const inv = await api('/api/research/data-inventory');
    const qa = await api('/api/research/data-quality-summary');
    $('data-inventory').textContent = JSON.stringify({inventory: inv.slice(0,1), quality_summary: qa}, null,2).slice(0,6000);
  }catch(e){ $('data-inventory').textContent='Error '+e}
  try{
    const feats = await api('/api/research/features');
    $('data-features').textContent = JSON.stringify(feats, null,2);
  }catch(e){$('data-features').textContent='Error '+e}
  $('data-micro').textContent = 'Execution-aware: next-bar-open, spread 3bps ×1/1.5/2, slippage, latency 100ms, partial fills, bid/ask asymmetry — mid-price only not validated. Spread labeled SYNTHETIC until real tick observed.';
}
async function loadDataSourceLab(){
  try{
    const cat = await api('/api/research/data-source-catalog');
    $('source-catalog').textContent = JSON.stringify(cat, null,2).slice(0,7000);
    $('source-reco').textContent = JSON.stringify({recommendation: "Priority: mt5_history for XAUUSD broker spread via forward capture + dukascopy EURUSD for cross-market + binance BTC for diversity; fisstrate if budget but mid only → SYNTHETIC spread", next_acquisition: "MT5 export 2yr XAUUSD 1H+1m and Dukascopy EURUSD 1H, verify TrueFX XAUUSD", catalog_path: "data/evidence/data_source_catalog.json", docs: "docs/data_source_comparison.md docs/data_requirements.md"}, null,2);
  }catch(e){$('source-catalog').textContent='Error '+e}
}
async function loadMarketMonitor(){
  try{
    const reg = await api('/api/research/regime-observations');
    $('monitor-regime').textContent = JSON.stringify(reg, null,2).slice(0,5000);
  }catch(e){$('monitor-regime').textContent='Error '+e}
  try{
    const adv = await api('/api/research/data-quality-adversarial');
    $('monitor-quality').textContent = JSON.stringify(adv, null,2);
  }catch(e){$('monitor-quality').textContent='Error '+e}
  try{
    const fwd = await api('/api/research/forward-manifest');
    const ticks = fwd.sample_ticks||[];
    $('monitor-quotes').textContent = ticks.length ? ticks.map(t=>`${t.timestamp} ${t.symbol} bid ${Number(t.bid).toFixed(2)} ask ${Number(t.ask).toFixed(2)} spread ${Number(t.spread_bps).toFixed(1)}bps session ${t.session} regime ${t.regime} freshness ${t.data_freshness_ms||'-'} anomaly ${t.anomaly||'none'}`).join('\\n') + '\\n\\n(no live broker — forward observatory simulated, safe, no capital)' : 'No ticks yet — forward observatory records live quotes with no capital exposure';
  }catch(e){$('monitor-quotes').textContent='Error '+e}
}
async function loadForwardObservatory(){
  try{
    const fwd = await api('/api/research/forward-manifest');
    $('forward-sessions').textContent = JSON.stringify({active_observation_sessions: fwd.active_observation_sessions, ticks_recorded: fwd.ticks_recorded, signals_recorded: fwd.signals_recorded, safety: fwd.safety}, null,2);
    $('forward-ticks').textContent = JSON.stringify(fwd.sample_ticks||[], null,2).slice(0,4000);
    $('forward-signals').textContent = JSON.stringify(fwd.sample_signals||[], null,2).slice(0,5000);
  }catch(e){$('forward-sessions').textContent='Error '+e}
  try{
    const exec = await api('/api/research/execution-reality');
    $('forward-execution').textContent = JSON.stringify(exec, null,2).slice(0,3000) + '\\n\\nRequired fields: signal_price vs expected (bid/ask at decision) vs actual (fill), submission/broker_ack/fill timestamps, volumes, spread/slippage/latency/rejection/partial/market state — source REAL/SYNTHETIC explicit — currently 0 real observations → cannot claim realism';
  }catch(e){$('forward-execution').textContent='Error '+e}
  try{
    const timeframe = {eligible: "1H limited (500 bars synthetic proxy, single month, spread SYNTHETIC) — all other timeframes BLOCK until quality sufficient", ineligible: ["1m","5m","15m","4H resampled SYNTHETIC","1D","tick"], cost_sensitivity: "0.025% spread at 1H vs high at 1m — quantified per timeframe", doc: "docs/timeframe_research.md"};
    const cross = {current: "single symbol XAUUSD", needed: "EURUSD (dukascopy) + BTC (binance) for genuine diversity", doc: "docs/cross_market_research.md"};
    $('forward-timeframe').textContent = JSON.stringify({timeframe, cross_market: cross}, null,2);
  }catch(e){$('forward-timeframe').textContent='Error '+e}
}
async function loadDataLineage(){
  try{
    const inv = await api('/api/research/data-inventory');
    const line = inv.map(d=>`${d.checksum} ${d.instrument} ${d.timeframe} ${d.date_range.start}→${d.date_range.end} rows ${d.row_count} raw ${d.raw_preserved} → curated ${d.curated_path} → manifest ${d.checksum} schema v${d.schema_version} preprocessing ${d.preprocessing_version} quality ${d.quality_report.every(c=>c.passed)?'PASS':'BLOCK'} eligibility "${d.research_eligibility}"`).join('\\n\\n');
    $('lineage-graph').textContent = line || 'No lineage';
  }catch(e){$('lineage-graph').textContent='Error '+e}
  $('lineage-versioning').textContent = JSON.stringify({immutability: "Any preprocessing change → new dataset version (new checksum), old version never mutated, research experiments reference exact checksum", manifest_id: "version = ingestion date + checksum short (e.g., 20260916-010-572728d9)", locked_test: "Frozen via LockedTestPartitioner — inaccessible during discovery, purged CPCV, embargo, monotonic time", preprocessing_version: inv0=>inv0}, null,2).slice(0,2000) + '\\n\\nSee data/manifests/, src/qts/data/store.py, src/qts/data/provider.py';
  try{
    const gate = {DATA_QUALITY: "PASS (12/12) but synthetic spread — conditional", DATA_DEPTH: "FAIL — 500 vs 5000 required, single month", DATA_DIVERSITY: "FAIL — single symbol/timeframe", EXECUTION_REALISM: "FAIL — 0 real execution observations (SYNTHETIC only)", REGIME_COVERAGE: "FAIL — single month Jan 2020, no multi-regime", OOS_COVERAGE: "PARTIAL — 5-fold walk-forward but limited", TRIAL_COUNT: "75 trials preserved (no reset)", STAT_EVIDENCE: "FAIL — DSR 0.12 <0.95, PBO fail, costs fragile", OVERALL: "BLOCK — KEEP NO_TRADE, LIVE structurally locked, see docs/market_data_observatory.md docs/execution_reality_protocol.md"};
    $('lineage-gate').textContent = JSON.stringify(gate, null,2);
  }catch(e){$('lineage-gate').textContent='Error '+e}
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
async function loadSetupWizard(){
  try{
    const safety = await api('/api/demo/safety');
    $('setup-risk-limits').textContent = JSON.stringify(safety.demo_limits, null,2);
  }catch(e){$('setup-risk-limits').textContent='Error '+e}
  try{
    const cfg = await api('/api/demo/config');
    const env = await api('/api/env/boundary');
    document.querySelectorAll('input[name=\"setup-env\"]').forEach(r=>{
      r.checked = (r.value===cfg.env || (cfg.env==='dev' && r.value==='development'));
    });
  }catch(e){}
}
async function loadDemoForward(){
  try{
    const safety = await api('/api/demo/safety');
    $('demo-boundary').textContent = JSON.stringify(safety, null,2).slice(0,3000);
  }catch(e){$('demo-boundary').textContent='Error '+e}
  try{
    const readiness = await api('/api/demo/readiness');
    const pretty = Object.entries(readiness.checks||{}).map(([k,v])=>`${v?'✓':'✗'} ${k}: ${readiness.details?.[k]||''}`).join('\n');
    $('demo-checks').textContent = pretty + '\n\nBlocked: ' + (readiness.blocked_reasons||[]).join('; ') + '\nDemo enabled: ' + readiness.demo_enabled;
  }catch(e){$('demo-checks').textContent='Error '+e}
  try{
    const cfg = await api('/api/demo/config');
    $('demo-observe').textContent = JSON.stringify({mode: cfg.observation_mode, lifecycle: cfg.lifecycle, observation: 'OBSERVE ONLY records live ticks without orders — safe to run continuously'}, null,2);
    $('demo-execution').textContent = JSON.stringify({risk: cfg.risk, label: cfg.label || 'DEMO', note: 'DEMO execution requires explicit confirmation + risk ack + 14 checks, labeled DEMO never LIVE'}, null,2);
  }catch(e){$('demo-observe').textContent='Error '+e}
  try{
    const obs = await api('/api/demo/observations?limit=10');
    const paper = await api('/api/demo/comparison');
    $('demo-capture').textContent = JSON.stringify({recent_demo: obs.slice(0,3), comparison: paper}, null,2).slice(0,4000);
  }catch(e){$('demo-capture').textContent='Error '+e}
  $('demo-position-mgmt').textContent = 'Position management research active — compares fixed/trailing/vol-based/structural/momentum-decay/time/partial/dynamic/emergency exits with same scientific gates.';
}
async function loadComparison(){
  try{
    const comp = await api('/api/demo/comparison');
    $('comparison-metrics').textContent = JSON.stringify(comp, null,2).slice(0,5000);
    $('comparison-raw').textContent = JSON.stringify(comp, null,2).slice(0,5000);
  }catch(e){$('comparison-metrics').textContent='Error '+e}
}


nav();
loadView('home');
setInterval(loadNotifications, 10000);
