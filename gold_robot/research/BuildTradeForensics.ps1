# QTS MT5 position-by-position forensic audit from broker-authored Tester deals.
# Read-only, offline; no prediction of hidden causes or trading permissions.
[CmdletBinding()]
param([string]$InputDirectory="",[string]$OutputDirectory="",[switch]$NoOpen,
      [int[]]$SelectedStyles=@())
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
if(-not $InputDirectory){$InputDirectory=Join-Path $gold 'reports_local\native'}
if(-not $OutputDirectory){$OutputDirectory=Join-Path $gold 'reports_local'}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
function E([object]$value){return [System.Net.WebUtility]::HtmlEncode([string]$value)}
function N([object]$raw){
    $value=0.0
    if(-not [double]::TryParse([string]$raw,[Globalization.NumberStyles]::Float,
                [Globalization.CultureInfo]::InvariantCulture,[ref]$value) -or
       [double]::IsNaN($value) -or [double]::IsInfinity($value)){
        throw ('Invalid numeric deal field: '+$raw)
    }
    return $value
}
function F([double]$value){return $value.ToString('0.0000',[Globalization.CultureInfo]::InvariantCulture)}
$names=@('Former stop','Retest','Break and retest','Sweep and reclaim',
         'Trend impulse','Range rejection','Inside-bar breakout','Adaptive router','SMC FVG OB','M1 scalp')
# Selective forensic review has explicitly scoped evidence. Unselected
# strategies must not be misrepresented as missing broker trade exports.
$targeted=$PSBoundParameters.ContainsKey('SelectedStyles')
$requiredStyles=@(0..9)
if($targeted){
    $requiredStyles=@($SelectedStyles)
    if($requiredStyles.Count -lt 1 -or
       @($requiredStyles | Sort-Object -Unique).Count -ne $requiredStyles.Count -or
       @($requiredStyles | Where-Object {$_ -lt 0 -or $_ -gt 9}).Count -gt 0){
        throw 'Invalid selected forensic strategy IDs.'
    }
}
$positions=New-Object System.Collections.ArrayList
$evidence=New-Object System.Collections.ArrayList
$allComplete=$true
for($style=0;$style -lt $names.Count;$style++){
    if($style -notin $requiredStyles){
        [void]$evidence.Add([ordered]@{style=$style;status='NOT_SELECTED';deals=0})
        continue
    }
    $path=Join-Path $InputDirectory ('QTS_'+$style+'_trades.csv')
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){
        $allComplete=$false
        [void]$evidence.Add([ordered]@{style=$style;status='MISSING';deals=0})
        continue
    }
    $deals=@(Import-Csv -LiteralPath $path -Delimiter ';')
    if($deals.Count -eq 0){
        $allComplete=$false
        [void]$evidence.Add([ordered]@{style=$style;status='EMPTY_NO_TRADES';deals=0})
        continue
    }
    $required=@('position_id','deal_id','order_id','entry','reason','type',
                'time_msc','volume','price','sl','tp','gross','commission','swap','fee')
    foreach($col in $required){
        if($null -eq $deals[0].PSObject.Properties[$col]){
            throw ('Invalid forensic CSV; missing '+$col+': '+$path)
        }
    }
    [void]$evidence.Add([ordered]@{style=$style;status='IMPORTED';deals=$deals.Count})
    foreach($group in ($deals | Group-Object position_id)){
        $items=@($group.Group|Sort-Object {[long]$_.time_msc})
        $entries=@($items|Where-Object{$_.entry -in @('DEAL_ENTRY_IN','DEAL_ENTRY_INOUT')})
        $exits=@($items|Where-Object{$_.entry -in @('DEAL_ENTRY_OUT','DEAL_ENTRY_OUT_BY','DEAL_ENTRY_INOUT')})
        $quality='COMPLETE'
        if($entries.Count -eq 0 -or $exits.Count -eq 0){$quality='INCOMPLETE_POSITION'}
        # DEAL_ENTRY_INOUT represents a netting reversal, not a standalone
        # completed trade. A naive IN/OUT grouping would double-count risk.
        if(@($items|Where-Object{$_.entry -eq 'DEAL_ENTRY_INOUT'}).Count -gt 0){
            $quality='REVERSAL_UNSUPPORTED'
        }
        $inVolume=0.0;$inValue=0.0;$outVolume=0.0;$outValue=0.0
        foreach($d in $entries){$v=N $d.volume;$inVolume+=$v;$inValue+=(N $d.price)*$v}
        foreach($d in $exits){$v=N $d.volume;$outVolume+=$v;$outValue+=(N $d.price)*$v}
        if($inVolume -le 0.0 -or $outVolume -le 0.0){$quality='INCOMPLETE_POSITION'}
        if($inVolume -gt 0.0 -and $outVolume -gt 0.0 -and
           [Math]::Abs($inVolume-$outVolume)>0.0000001){$quality='PARTIAL_OR_OPEN'}
        $distinctExitReasons=@($exits | Select-Object -ExpandProperty reason -Unique)
        if($quality -eq 'COMPLETE' -and $exits.Count -gt 1){
            $quality='COMPLETE_MULTI_EXIT'
        }
        $entryPrice=if($inVolume -gt 0.0){$inValue/$inVolume}else{0.0}
        $exitPrice=if($outVolume -gt 0.0){$outValue/$outVolume}else{0.0}
        $first=if($entries.Count){$entries[0]}else{$null}
        $last=if($exits.Count){$exits[-1]}else{$null}
        $initialSL=if($first){N $first.sl}else{0.0}
        $initialTP=if($first){N $first.tp}else{0.0}
        $exitSL=if($last){N $last.sl}else{0.0}
        $exitTP=if($last){N $last.tp}else{0.0}
        $gross=0.0;$charges=0.0
        foreach($d in $items){$gross+=(N $d.gross);$charges+=(N $d.commission)+(N $d.swap)+(N $d.fee)}
        $net=$gross+$charges
        $reason=if($last){[string]$last.reason}else{'NO_EXIT'}
        if($distinctExitReasons.Count -gt 1){$reason='MIXED_EXIT_REASONS'}
        $entrySetup='NOT_RECORDED'
        if($first -and $null -ne $first.PSObject.Properties['setup_reason']){
            $candidate=[string]$first.setup_reason
            if(-not [string]::IsNullOrWhiteSpace($candidate)){$entrySetup=$candidate}
        }
        $exitLegs=@()
        foreach($leg in $exits){
            $exitLegs+=,[ordered]@{
                deal_id=[string]$leg.deal_id
                reason=[string]$leg.reason
                time_msc=[string]$leg.time_msc
                lots=N $leg.volume
                price=N $leg.price
                sl=N $leg.sl
                tp=N $leg.tp
                gross=N $leg.gross
                charges=(N $leg.commission)+(N $leg.swap)+(N $leg.fee)
            }
        }
        $side=if($first -and $first.type -eq 'DEAL_TYPE_BUY'){'BUY'}elseif($first -and $first.type -eq 'DEAL_TYPE_SELL'){'SELL'}else{'UNKNOWN'}
        $riskGap=if($initialSL -gt 0 -and $entryPrice -gt 0){[Math]::Abs($entryPrice-$initialSL)}else{0.0}
        $rewardGap=if($initialTP -gt 0 -and $entryPrice -gt 0){[Math]::Abs($initialTP-$entryPrice)}else{0.0}
        $minutes=if($first -and $last){[Math]::Round(((N $last.time_msc)-(N $first.time_msc))/60000.0,2)}else{$null}
        $slip=0.0
        # Multiple exit legs can have different fill prices and stop levels.
        # A single last-exit slippage value is NOT representative in that case.
        if($reason -eq 'DEAL_REASON_SL' -and $exits.Count -eq 1 -and $exitSL -gt 0){
            $slip=if($side -eq 'BUY'){$exitSL-$exitPrice}else{$exitPrice-$exitSL}
        }
        $why=switch($reason){
           'MIXED_EXIT_REASONS' {'More than one broker exit cause: inspect every exit leg separately. The last deal must NOT override earlier outcomes.'}
           'DEAL_REASON_SL' {'Broker stop-loss execution. Verify entry setup, initial stop room, later stop modifications, adverse price movement and exit slippage.'}
           'DEAL_REASON_TP' {'Broker take-profit execution. Verify gross reward, cost drag, target distance and whether the position was stopped earlier in other partial fills.'}
           'DEAL_REASON_SO' {'Broker stop-out: inspect margin, liquidation and broker contract; not a planned protective exit.'}
           'DEAL_REASON_EXPERT' {'Expert-driven exit. Inspect max-position-time, protective halts or manual changes; broker reason alone is insufficient.'}
           'DEAL_REASON_CLIENT' {'Terminal/client-origin exit; inspect operator actions and the MT5 journal.'}
           'NO_EXIT' {'No exit deal available. This is NOT a completed trade.'}
           default {'Other broker-recorded exit reason. Inspect journal and all associated deals.'}
        }
        if($quality -notin @('COMPLETE','COMPLETE_MULTI_EXIT')){
            $why='INCOMPLETE POSITION EVIDENCE. '+$why
            $allComplete=$false
        }
        [void]$positions.Add([ordered]@{
            style=$style;strategy=$names[$style];position_id=[string]$group.Name;
            setup_reason=$entrySetup;exit_legs=$exitLegs;
            status=$quality;side=$side;entry_price=[Math]::Round($entryPrice,5);
            exit_price=[Math]::Round($exitPrice,5);initial_sl=$initialSL;
            initial_tp=$initialTP;exit_sl=$exitSL;exit_tp=$exitTP;
            risk_price_distance=[Math]::Round($riskGap,5);
            target_price_distance=[Math]::Round($rewardGap,5);
            exit_reason=$reason;exit_adverse_slippage_price=[Math]::Round($slip,5);
            initial_rr_price=if($riskGap -gt 0){[Math]::Round($rewardGap/$riskGap,3)}else{$null};
            minutes_held=$minutes;entry_lots=$inVolume;exit_lots=$outVolume;
            gross_usd=[Math]::Round($gross,2);charges_usd=[Math]::Round($charges,2);
            net_usd=[Math]::Round($net,2);deal_count=$items.Count;
            interpretation=$why
        })
    }
}
$rows=@()
foreach($p in $positions){
    $legsText=($p.exit_legs | ForEach-Object {
        $_.deal_id+':'+$_.reason+' @'+(F $_.price)+' ('+(F $_.lots)+' lots)'
    }) -join '; '
    $columns=@($p.strategy,$p.position_id,$p.setup_reason,$p.side,$p.status,
       $p.exit_reason,$legsText,
       (F $p.entry_price),(F $p.initial_sl),(F $p.initial_tp),
       (F $p.exit_price),$p.minutes_held,(F $p.exit_adverse_slippage_price),
       (F $p.net_usd),$p.interpretation)
    $cells=($columns|ForEach-Object{'<td>'+(E $_)+'</td>'}) -join ''
    $rows+='<tr>'+$cells+'</tr>'
}
if(-not $rows){$rows=@('<tr><td colspan="15">No per-position broker evidence was exported.</td></tr>')}
$state=if($allComplete){
    if($targeted){'SELECTED_IMPORTED_FOR_REVIEW'}else{'IMPORTED_FOR_REVIEW'}
}else{'EVIDENCE_GAPS_NO_GO'}
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$report=Join-Path $OutputDirectory 'QTS_TRADE_BY_TRADE.html'
$reportJson=Join-Path $OutputDirectory 'QTS_TRADE_BY_TRADE.json'
[ordered]@{schema='qts.mt5.trade_forensics.v1';status=$state;
          broker_fact_not_causal_proof=$true;live='LOCKED';edge_validated=$false;
          targeted=$targeted;selected_styles=@($requiredStyles);
          evidence=@($evidence.ToArray());trades=@($positions.ToArray())} |
    ConvertTo-Json -Depth 9 | Set-Content -LiteralPath $reportJson -Encoding UTF8
$safeRows=$rows -join [Environment]::NewLine
$html=@"
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QTS Gold | Individual Trade Forensics</title>
<style>body{background:#f4f6f9;font:14px/1.65 'Segoe UI',Arial,sans-serif;color:#17304c}
main{max-width:1500px;margin:auto;padding:20px}header{padding:25px;background:#18334b;color:white;border-radius:12px}
section{background:white;border:1px solid #dfe7ef;padding:20px;border-radius:12px;margin-top:16px;overflow-x:auto}
table{border-collapse:collapse;min-width:1500px;width:100%;font-size:12px}
td,th{padding:9px;border-bottom:1px solid #e7eef4;text-align:left;vertical-align:top}
th{background:#edf2f9}.warning{border-left:4px solid #b4801f;padding:8px 12px}</style></head>
<body><main><header><h1>QTS Gold | Individual Trade Forensics</h1>
<p>Status: $(E $state) | LIVE LOCKED | PROFITABLE EDGE NOT VALIDATED</p></header>
<section><h2>Every position, separately</h2><table><thead><tr>
<th>Strategy</th><th>Position</th><th>Entry setup (order comment)</th><th>Side</th><th>Evidence</th>
<th>Broker exit</th><th>Every exit leg</th>
<th>Entry</th><th>Initial SL</th><th>Initial TP</th><th>Exit</th><th>Minutes</th>
<th>Adverse SL slip (price)</th><th>Net USD</th><th>What the evidence can explain</th>
</tr></thead><tbody>$safeRows</tbody></table></section>
<section class="warning"><h2>What this does NOT prove</h2>
<p>SL and TP reasons come from MT5 broker deal history, not from a guessed win/loss sign.
Initial/exit stop values can differ if the stop moved. Gaps, spreads, slippage,
market context, unobserved highs/lows and signals rejected before entry require
more data than the broker deal history alone.</p>
<p>Zero commission in a tester report is not verified WMMarkets pricing.
No single trade, hit rate, or group of profitable trades certifies an edge.
Partially closed positions are explicitly marked incomplete.</p></section></main></body></html>
"@
[IO.File]::WriteAllText($report,$html,([Text.UTF8Encoding]::new($false)))
Write-Host ('TRADE_BY_TRADE_STATUS='+$state+' POSITIONS='+$positions.Count)
Write-Host ('TRADE_BY_TRADE_HTML='+$report)
if(-not $NoOpen){Invoke-Item -LiteralPath $report}
