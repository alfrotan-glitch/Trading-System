# Read-only comparison of four user-exported native MT5 Strategy Tester reports.
[CmdletBinding()]
param([string]$ReportDirectory="",[string]$OutputDirectory="",[switch]$NoOpen)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(-not $ReportDirectory){$ReportDirectory=Join-Path $root 'reports_local\native'}
if(-not $OutputDirectory){$OutputDirectory=Join-Path $root 'reports_local'}
New-Item -ItemType Directory -Path $OutputDirectory -Force|Out-Null
function HtmlEscape([object]$v){return [System.Net.WebUtility]::HtmlEncode([string]$v)}
function AsNumber([string]$raw){
  $part=($raw -split '\(')[0].Trim()
  $part=($part -replace '[\s,\u00a0\u202f]','')
  $num=0.0
  if(-not [double]::TryParse($part,[Globalization.NumberStyles]::Float,
                            [Globalization.CultureInfo]::InvariantCulture,[ref]$num) -or
     [double]::IsNaN($num) -or [double]::IsInfinity($num)){throw 'Invalid MT5 numeric field'}
  return $num
}
function ParseNative([string]$filepath){
  $item=Get-Item -LiteralPath $filepath
  if($item.Length -lt 100 -or $item.Length -gt 10000000){throw 'Unexpected report size'}
  $html=[IO.File]::ReadAllText($filepath)
  if($html -notmatch '(?is)<!doctype\s+html\b|<html\b'){
    if($html -match '(?m)^\uFEFF?CS\t\d+\t' -or $html.Contains('MetaTester 5 build')){
      throw 'MetaTester agent log, not an HTML backtest report. Use Strategy Tester > Backtest > Save as Report.'
    }
    throw 'Not a native MT5 HTML backtest report.'
  }
  $found=@{}
  $keys=@('Total Net Profit','Profit Factor','Total Trades','Equity Drawdown Maximal')
  foreach($row in [regex]::Matches($html,'(?is)<tr\b[^>]*>(.*?)</tr>')){
    $cells=@()
    foreach($cell in [regex]::Matches($row.Groups[1].Value,'(?is)<td\b[^>]*>(.*?)</td>')){
      $str=[regex]::Replace($cell.Groups[1].Value,'(?is)<[^>]*>','')
      $cells+=([System.Net.WebUtility]::HtmlDecode($str).Trim())
    }
    for($i=0;$i -lt ($cells.Count-1);$i++){
      $key=$cells[$i].TrimEnd(':').Trim()
      if($key -in $keys -and -not $found.ContainsKey($key)){$found[$key]=$cells[$i+1]}
    }
  }
  foreach($key in $keys){if(-not $found.ContainsKey($key)){throw "Missing MT5 field: $key"}}
  $net=AsNumber $found['Total Net Profit']
  $pf=AsNumber $found['Profit Factor']
  $trades=AsNumber $found['Total Trades']
  $dd=AsNumber $found['Equity Drawdown Maximal']
  if($pf -lt 0 -or $trades -lt 0 -or $trades -ne [math]::Floor($trades) -or $dd -lt 0){
    throw 'Invalid MT5 profit factor, trades or drawdown'
  }
  return [ordered]@{
    state='PARSED';net_usd=$net;profit_factor=$pf;trades=[int]$trades
    maximal_equity_drawdown=$dd;sha256=(Get-FileHash -LiteralPath $filepath -Algorithm SHA256).Hash
  }
}
$labels=@('FORMER_STOP','RETEST','BREAK_ACCEPT_RETEST','SWEEP_RECLAIM')
$results=@()
for($style=0;$style -lt 4;$style++){
  $filename='QTS_{0}.htm' -f $style
  $path=Join-Path $ReportDirectory $filename
  $entry=[ordered]@{style=$style;label=$labels[$style];file=$filename;state='MISSING'
                   message='Save the matching native MT5 HTML report with this filename'}
  if(Test-Path -LiteralPath $path -PathType Leaf){
    try{
      $details=ParseNative $path
      foreach($k in $details.Keys){$entry[$k]=$details[$k]}
      $entry.message='Native tester values; actual broker costs/edge not validated'
    }catch{
      $entry.message=[string]$_.Exception.Message
      $entry.state=if($entry.message -like 'MetaTester agent log*'){'LOG_ONLY'}else{'INVALID'}
    }
  }else{
    $logPath=Join-Path $ReportDirectory ($filename+'.log')
    if(Test-Path -LiteralPath $logPath -PathType Leaf){
      $entry.state='LOG_ONLY'
      $entry.message='MetaTester agent log found, but no HTML report. Save from Strategy Tester Backtest tab.'
    }
  }
  $results+=,[pscustomobject]$entry
}
$rows=@()
foreach($item in $results){
  $trades='—';$net='—';$pf='—';$dd='—'
  if($item.state -eq 'PARSED'){
    $trades=[string]$item.trades
    $net=$item.net_usd.ToString('0.00',[Globalization.CultureInfo]::InvariantCulture)
    $pf=$item.profit_factor.ToString('0.00',[Globalization.CultureInfo]::InvariantCulture)
    $dd=$item.maximal_equity_drawdown.ToString('0.00',[Globalization.CultureInfo]::InvariantCulture)
  }
  $rows+=('<tr><th>{0}: {1}</th><td>{2}</td><td>{3}</td><td>{4}</td><td>{5}</td><td>{6}</td></tr>' -f
         $item.style,(HtmlEscape $item.label),(HtmlEscape $item.state),
         (HtmlEscape $trades),(HtmlEscape $net),(HtmlEscape $pf),(HtmlEscape $dd))
}
$parsed=@($results|Where-Object{$_.state -eq 'PARSED'}).Count
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$stampHtml=Get-Date -Format 'yyyy-MM-dd HH:mm'
$htmlFile=Join-Path $OutputDirectory ("QTS_Gold_Comparison_"+$stamp+".html")
$jsonFile=Join-Path $OutputDirectory ("QTS_Gold_Comparison_"+$stamp+".json")
$tableRows=$rows -join [Environment]::NewLine
$html=@"
<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QTS Gold - Native MT5 Strategy Comparison</title><style>
*{box-sizing:border-box}body{font-family:"Segoe UI",Tahoma,sans-serif;background:#f4f6f9;color:#182536;margin:0}
main{max-width:1000px;margin:30px auto;padding:0 20px 50px}
header{background:#163450;color:white;border-radius:16px;padding:28px}
header h1{font-size:24px;margin:0 0 12px}header p{line-height:1.9;margin:0;color:#cddbea}
section{background:white;border-radius:13px;padding:22px;margin:18px 0;border:1px solid #e0e7f0}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:13px 9px;text-align:left;border-bottom:1px solid #eef1f5}
thead{background:#edf2f8}.note{border-left:4px solid #2563eb;background:#eef5fc;padding:13px;line-height:1.9}
p{line-height:1.8}footer{font-size:12px;color:#6c798b;text-align:center}
@media(max-width:700px){section{overflow-x:auto}table{min-width:700px}}
</style></head><body><main>
<header><h1>QTS Gold | Four-Strategy MT5 Comparison</h1>
<p>Comparison of native Strategy Tester reports. Read-only; no broker orders are sent.</p>
<small>$(HtmlEscape $stampHtml) | XAUUSD@ | Native reports: $parsed / 4 | LIVE LOCKED</small></header>
<section><h2>Available results</h2><table>
<thead><tr><th>Entry style</th><th>Status</th><th>Trades</th><th>Net profit/loss</th><th>Profit Factor</th><th>Maximum equity drawdown</th></tr></thead>
<tbody>$tableRows</tbody></table>
<p class="note">For a valid comparison, all four tests must use the same dates, symbol, real-tick model, USD 3,000 tester deposit and execution costs. Missing data is not a zero result. Future returns and independent edge remain unvalidated.</p></section>
<section><h2>Operator instructions</h2>
<p>Save the four native MT5 reports as QTS_0.htm, QTS_1.htm, QTS_2.htm and QTS_3.htm under gold_robot/reports_local/native, then regenerate the comparison. Preserve each run's Report, Deals, Orders and Journal independently.</p></section>
<footer>Read-only native report comparison | No credentials | No broker orders</footer>
</main></body></html>
"@
[IO.File]::WriteAllText($htmlFile,$html,([Text.UTF8Encoding]::new($false)))
@{mode='READ_ONLY';live='LOCKED';validated_edge=$false;reports_parsed=$parsed;results=$results} |
  ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $jsonFile -Encoding UTF8
Write-Host ('Comparison HTML: '+$htmlFile)
Write-Host ('Comparison JSON: '+$jsonFile)
Write-Host ('Reports parsed: '+$parsed+'/4. No validated trading edge.')
if(-not $NoOpen){Invoke-Item -LiteralPath $htmlFile}
