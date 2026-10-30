# QTS Gold: interpret *actual* Style-7 position evidence.
# READ ONLY. No strategy tuning, network, terminal interaction or broker orders.
[CmdletBinding()]
param([string]$RunDirectory="",[switch]$NoOpen)
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$root=Join-Path $gold 'reports_local\auto_runs'
if(-not $RunDirectory){
    $runs=@(Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop |
        Where-Object {Test-Path -LiteralPath (Join-Path $_.FullName 'QTS_TRADE_BY_TRADE.json') -PathType Leaf} |
        Sort-Object Name -Descending)
    if($runs.Count -eq 0){throw 'No completed local trade-by-trade report was found.'}
    $RunDirectory=$runs[0].FullName
}
$RunDirectory=(Resolve-Path -LiteralPath $RunDirectory -ErrorAction Stop).Path
$forensicPath=Join-Path $RunDirectory 'QTS_TRADE_BY_TRADE.json'
if(-not (Test-Path -LiteralPath $forensicPath -PathType Leaf)){
    throw 'Missing QTS_TRADE_BY_TRADE.json: no individual positions to audit.'
}
$forensics=Get-Content -LiteralPath $forensicPath -Raw -Encoding UTF8|ConvertFrom-Json
$comparison=@(Get-ChildItem -LiteralPath $RunDirectory -Filter 'QTS_Gold_Comparison_*.json' -File |
    Sort-Object LastWriteTimeUtc -Descending|Select-Object -First 1)
if($comparison.Count -ne 1){throw 'Missing native MT5 comparison JSON: cannot reconcile Adaptive.'}
$cmp=Get-Content -LiteralPath $comparison[0].FullName -Raw -Encoding UTF8|ConvertFrom-Json
$mt=@($cmp.results|Where-Object {[int]$_.style -eq 7})
if($mt.Count -ne 1 -or [string]$mt[0].state -ne 'PARSED'){
    throw 'Adaptive native report is not style-verified and parsed.'
}
$names=@{
 'QTS OLD-SL LIMIT DEMO'='Former stop'
 'QTS RETEST LIMIT DEMO'='Retest'
 'QTS BREAK HOLD LIMIT'='Break and retest'
 'QTS SWEEP RECLAIM'='Sweep and reclaim'
 'QTS TREND IMPULSE'='Trend impulse'
 'QTS RANGE REJECT'='Range rejection'
 'QTS INSIDE BREAK'='Inside-bar breakout'
}
$groups=[ordered]@{}
foreach($n in @('Former stop','Retest','Break and retest','Sweep and reclaim',
                 'Trend impulse','Range rejection','Inside-bar breakout','UNKNOWN')){
    $groups[$n]=New-Object System.Collections.ArrayList
}
$trades=@($forensics.trades|Where-Object {[int]$_.style -eq 7})
$errors=New-Object System.Collections.ArrayList
if([string]$forensics.status -ne 'IMPORTED_FOR_REVIEW'){
    [void]$errors.Add('Trade ledger contains incomplete/missing position evidence.')
}
foreach($t in $trades){
    $label='UNKNOWN'
    $comment=([string]$t.setup_reason).Trim().ToUpperInvariant()
    if($names.ContainsKey($comment)){$label=$names[$comment]}
    if([string]$t.status -notin @('COMPLETE','COMPLETE_MULTI_EXIT')){
        [void]$errors.Add(('Position '+[string]$t.position_id+' incomplete: '+[string]$t.status))
    }
    $pnl=[double]$t.net_usd
    if([double]::IsNaN($pnl) -or [double]::IsInfinity($pnl)){
        throw ('Invalid broker PnL in position '+[string]$t.position_id)
    }
    [void]$groups[$label].Add($t)
}
function Summary([object[]]$rows){
    $gain=0.0;$loss=0.0;$net=0.0;$sl=0;$tp=0;$other=0;$fees=0.0
    foreach($r in $rows){
        $value=[double]$r.net_usd
        $net+=$value
        if($value -gt 0.0){$gain+=$value}
        elseif($value -lt 0.0){$loss+=-$value}
        $fees+=[double]$r.charges_usd
        if($r.exit_reason -eq 'DEAL_REASON_SL'){$sl++}
        elseif($r.exit_reason -eq 'DEAL_REASON_TP'){$tp++}
        else{$other++}
    }
    $pf=$null
    if($loss -gt 0.000001){$pf=[math]::Round($gain/$loss,4)}
    return [ordered]@{
        positions=$rows.Count; net_usd=[math]::Round($net,2)
        profit_factor_after_recorded_costs=$pf
        stop_loss_exits=$sl; take_profit_exits=$tp; other_exits=$other
        recorded_charges_usd=[math]::Round($fees,2)
    }
}
$total=Summary $trades
$expectedTrades=[int]$mt[0].trades
$expectedNet=[double]$mt[0].net_usd
if($total.positions -ne $expectedTrades){
    [void]$errors.Add(('Count mismatch: broker position rows='+$total.positions+' native report='+$expectedTrades))
}
if([math]::Abs($total.net_usd-$expectedNet) -gt 0.05){
    [void]$errors.Add(('Net mismatch: broker position sum='+$total.net_usd+' native report='+$expectedNet))
}
if(@($groups['UNKNOWN']).Count -gt 0){
    [void]$errors.Add(('Missing or unrecognized broker entry comment on '+@($groups['UNKNOWN']).Count+' positions; cannot attribute those strategies.'))
}
$breakdown=@()
foreach($k in $groups.Keys){
    $rows=@($groups[$k].ToArray())
    if($rows.Count -eq 0){continue}
    $summary=Summary $rows
    $breakdown+=,[ordered]@{
        family=$k;positions=$summary.positions;net_usd=$summary.net_usd
        profit_factor=$summary.profit_factor_after_recorded_costs
        sl_exits=$summary.stop_loss_exits;tp_exits=$summary.take_profit_exits
        other_exits=$summary.other_exits;recorded_charges_usd=$summary.recorded_charges_usd
    }
}
$perMonth=@{}
$unplaced=0
foreach($t in $trades){
    $legs=@($t.exit_legs)
    if($legs.Count -eq 0){$unplaced++;continue}
    $last=$legs|Sort-Object { [long]$_.time_msc }|Select-Object -Last 1
    try{$key=[DateTimeOffset]::FromUnixTimeMilliseconds([long]$last.time_msc).UtcDateTime.ToString('yyyy-MM')}
    catch{$unplaced++;continue}
    if(-not $perMonth.ContainsKey($key)){$perMonth[$key]=New-Object System.Collections.ArrayList}
    [void]$perMonth[$key].Add($t)
}
$monthly=@()
foreach($key in @($perMonth.Keys|Sort-Object)){
    $r=Summary @($perMonth[$key].ToArray())
    $monthly+=,[ordered]@{exit_month_utc=$key;positions=$r.positions;net_usd=$r.net_usd;sl=$r.stop_loss_exits;tp=$r.take_profit_exits}
}
if($unplaced -gt 0){[void]$errors.Add(("$unplaced positions lack a usable final broker exit timestamp"))}
$costCases=@()
foreach($extra in @(0.25,0.50,1.00,2.00)){
    $costCases+=,[ordered]@{
        extra_usd_per_position=$extra
        adjusted_net_usd=[math]::Round($total.net_usd-$extra*$total.positions,2)
    }
}
$worst=@($trades|Sort-Object {[double]$_.net_usd}|Select-Object -First 12|ForEach-Object {
    [ordered]@{
        position_id=[string]$_.position_id
        setup_reason=[string]$_.setup_reason
        exit_reason=[string]$_.exit_reason
        net_usd=[double]$_.net_usd
        exit_adverse_slippage_price=[double]$_.exit_adverse_slippage_price
        minutes_held=[double]$_.minutes_held
    }
})
$state=if($errors.Count -eq 0){'RECONCILED_REVIEW_REQUIRED'}else{'EVIDENCE_CONFLICT_NO_GO'}
$out=[ordered]@{
    schema='qts.adaptive_attribution.v1'
    status=$state;live='LOCKED';edge_validated=$false
    source='QTS_TRADE_BY_TRADE.json and style-7 native comparison'
    does_not_establish='The market regime at order time, the counterfactual winner, future profitability, MFE/MAE or actual unreported broker fees.'
    native_report=[ordered]@{
        style=7;trades=$expectedTrades;net_usd=$expectedNet
        profit_factor=$mt[0].profit_factor
        maximal_equity_drawdown=$mt[0].maximal_equity_drawdown
    }
    broker_positions=$total
    selected_family=$breakdown
    by_exit_month_utc=$monthly
    incremental_cost_scenarios=$costCases
    worst_positions=$worst
    evidence_gaps=@($errors.ToArray())
}
$jsonPath=Join-Path $RunDirectory 'QTS_ADAPTIVE_REVIEW.json'
$out|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $jsonPath -Encoding UTF8
function H([object]$v){return [System.Net.WebUtility]::HtmlEncode([string]$v)}
$rows=@()
foreach($b in $breakdown){
    $rows+=('<tr><td>'+(H $b.family)+'</td><td>'+$b.positions+'</td><td>'+
          $b.net_usd+'</td><td>'+(H $b.profit_factor)+'</td><td>'+
          $b.sl_exits+'</td><td>'+$b.tp_exits+'</td><td>'+$b.other_exits+'</td></tr>')
}
$monthRows=@()
foreach($m in $monthly){
    $monthRows+=('<tr><td>'+$m.exit_month_utc+'</td><td>'+$m.positions+'</td><td>'+
                 $m.net_usd+'</td><td>'+$m.sl+'</td><td>'+$m.tp+'</td></tr>')
}
$gapText=if($errors.Count){(H ($errors.ToArray() -join '; '))}else{'Broker ledger counts match MT5 style-7 report.'}
$html=@"
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>QTS Adaptive Router | Actual Position Attribution</title>
<style>body{font:15px/1.7 'Segoe UI',Arial,sans-serif;background:#f4f7fb;color:#17273b}
main{max-width:1100px;margin:32px auto;padding:16px}section,header{background:white;border:1px solid #ddd;border-radius:12px;margin-bottom:18px;padding:22px}
header{background:#142e48;color:white}table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:10px;border-bottom:1px solid #e1e5eb}th{background:#edf2f8}</style></head>
<body><main><header><h1>Adaptive Router — Which strategy was actually chosen?</h1>
<p>$(H $state) | LIVE LOCKED | NOT A PROFITABLE EDGE APPROVAL</p></header>
<section><p>Broker positions: $($total.positions); Native MT5 positions: $expectedTrades.
Position net: $($total.net_usd) USD; MT5 net: $expectedNet USD.
Profit Factor (MT5): $($mt[0].profit_factor).
Maximum equity drawdown (MT5): $($mt[0].maximal_equity_drawdown).</p>
<p>$(H $gapText)</p></section>
<section><h2>Selected strategy attribution</h2>
<p>Family comes ONLY from the original broker order comment, not a guessed market regime.</p>
<table><tr><th>Family</th><th>Positions</th><th>Net USD</th><th>PF</th><th>SL</th><th>TP</th><th>Other</th></tr>
$($rows -join [Environment]::NewLine)</table></section>
<section><h2>Exit month in UTC</h2><table>
<tr><th>Month</th><th>Positions</th><th>Net USD</th><th>SL</th><th>TP</th></tr>
$($monthRows -join [Environment]::NewLine)</table></section>
<section><h2>Limits</h2><p>This report cannot tell whether a different strategy would have won the SAME trade.
Cost scenarios in accompanying JSON only ADD potential unrecorded costs; do not subtract recorded spreads again.
A positive result on the same period used to design the router is NOT independent validation.
No real-money trading is authorized.</p></section></main></body></html>
"@
$htmlPath=Join-Path $RunDirectory 'QTS_ADAPTIVE_REVIEW.html'
[IO.File]::WriteAllText($htmlPath,$html,([Text.UTF8Encoding]::new($false)))
Write-Host ('ADAPTIVE ATTRIBUTION: '+$state+'; positions='+$total.positions+'; net='+$total.net_usd)
Write-Host ('Adaptive review HTML: '+$htmlPath)
Write-Host ('Adaptive review JSON: '+$jsonPath)
if(-not $NoOpen){Invoke-Item -LiteralPath $htmlPath}
if($errors.Count -gt 0){exit 2}
