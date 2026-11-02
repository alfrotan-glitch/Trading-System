# QTS Gold | 2025-to-last-completed-day native WMMarkets MT5 historical REPLAY.
# By default test the provisional DUAL_DIRECTIONAL research candidate, NOT
# real orders. Never auto-reset safety halts or re-enable broker trading.
[CmdletBinding()]
param(
    [ValidateSet('DUAL_BOTH','DUAL_DIRECTIONAL','DUAL_QUALITY')]
    [string]$Variant='DUAL_DIRECTIONAL',
    [string]$ToDate='',
    [ValidateRange(1,480)]
    [int]$TimeoutMinutesPerRun=480
)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$runner=Join-Path $repo 'gold_robot\research\RunAutomaticTester.ps1'
$summaryTool=Join-Path $repo 'gold_robot\research\summarize_2025_history.py'
$start='2025.01.01'
# The MT5 tester uses an EXCLUSIVE ToDate. End at the beginning of the
# current local day: only completed past trading days are examined.
if([string]::IsNullOrWhiteSpace($ToDate)){
    $ToDate=(Get-Date).ToString('yyyy.MM.dd')
}
if(-not (Test-Path -LiteralPath $runner -PathType Leaf) -or
   -not (Test-Path -LiteralPath $summaryTool -PathType Leaf)){
    throw 'Missing QTS 2025 history tools. Update git main before running.'
}
$folder=Join-Path $repo ('gold_robot\reports_local\history_2025_to_date\'+
                         (Get-Date -Format 'yyyyMMdd_HHmmss_ffff')+'_'+$Variant)
New-Item -ItemType Directory -Path $folder -Force|Out-Null
function ExportHistoricalDiagnostic([string]$reason){
    $diag=Join-Path $folder 'QTS_2025_DIAGNOSTIC_NO_GO'
    New-Item -ItemType Directory -Path $diag -Force|Out-Null
    Set-Content -LiteralPath (Join-Path $diag 'WHY_NO_GO.txt') -Value $reason -Encoding UTF8
    foreach($rel in @('OPEN_RESULTS.json','OPEN_RESULTS.html',
                      'QTS_2025_TO_DATE_SUMMARY.json',
                      'QTS_POST_FILL_SAFETY_AUDIT.json',
                      'QTS_TRADE_BY_TRADE.json',
                      'QTS_DUAL_OPPORTUNITY_SUMMARY.json')){
        $source=Join-Path $folder $rel
        if(Test-Path -LiteralPath $source -PathType Leaf){
            Copy-Item -LiteralPath $source -Destination $diag -Force
        }
    }
    $diagnosticZip=Join-Path $folder 'QTS_2025_DIAGNOSTIC_NO_GO.zip'
    Compress-Archive -LiteralPath $diag -DestinationPath $diagnosticZip -Force -CompressionLevel Optimal
    Write-Host ('NO-GO DIAGNOSTIC ZIP: '+$diagnosticZip) -ForegroundColor Yellow
    try{explorer.exe /select,"$diagnosticZip"}catch{Write-Warning ('Open ZIP manually: '+$diagnosticZip)}
}
Write-Host ('QTS GOLD MT5: '+$Variant+' | '+$start+' -> '+$ToDate)
Write-Host 'The end date is EXCLUSIVE: current partial trading day is not tested.'
Write-Host 'RESEARCH ONLY. LIVE LOCKED. NO REAL MONEY ORDERS.' -ForegroundColor Yellow
Write-Host 'Missing 2025 broker real ticks or execution incidents are NO-GO, not zero profit.'
$params=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$runner,
          '-OnlyStyles','7','-ResearchVariant',$Variant,
          '-FromDate',$start,'-ToDate',$ToDate,
          '-TimeoutMinutesPerRun',[string]$TimeoutMinutesPerRun,
          '-OutputDirectory',$folder,'-NoOpen')
& (Join-Path $PSHOME 'powershell.exe') @params
$nativeExit=[int]$LASTEXITCODE
$metaPath=Join-Path $folder 'OPEN_RESULTS.json'
if(-not (Test-Path -LiteralPath $metaPath -PathType Leaf)){
    ExportHistoricalDiagnostic ('MT5 did not produce a native completion report. Exit='+$nativeExit)
    exit 2
}
$meta=Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8|ConvertFrom-Json
$validState=([string]$meta.state -cin @('SELECTED_TESTS_FINISHED_REVIEW_REQUIRED',
                                      'SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO'))
$incident=([string]$meta.state -ceq 'SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO')
if($nativeExit -notin @(0,2) -or
   ($nativeExit -eq 0 -and $incident) -or
   ($nativeExit -eq 2 -and -not $incident) -or
   -not $validState -or
   [string]$meta.research_variant -cne $Variant -or
   [string]$meta.live -cne 'LOCKED' -or
   $meta.validated_edge -ne $false -or
   $meta.real_money_orders -ne $false -or
   [string]$meta.from_date -cne $start -or
   [string]$meta.to_date -cne $ToDate -or
   [string]$meta.symbol -cne 'XAUUSD@' -or
   [string]$meta.timeframe -cne 'M15' -or
   [int]$meta.model -ne 4 -or
   [int]$meta.deposit_usd -ne 3000 -or
   @($meta.selected_styles).Count -ne 1 -or
   [int]$meta.selected_styles[0] -ne 7 -or
   [string]::IsNullOrWhiteSpace([string]$meta.compiled_ex5_sha256)){
    ExportHistoricalDiagnostic ('Native tester returned invalid/incomplete identity: exit='+
       $nativeExit+' state='+[string]$meta.state)
    exit 2
}
$python=Get-Command py -ErrorAction SilentlyContinue
if($python){
    $bin=$python.Source
    $prefix=@('-3')
}else{
    $python=Get-Command python -ErrorAction SilentlyContinue
    if(-not $python){throw 'Python 3 required for native 2025-history analysis.'}
    $bin=$python.Source
    $prefix=@()
}
$summary=Join-Path $folder 'QTS_2025_TO_DATE_SUMMARY.json'
$summaryArgs=@($prefix)+@($summaryTool,'--folder',$folder,'--variant',$Variant,
                  '--from-date',$start,'--to-date',$ToDate,'--output',$summary)
& $bin @summaryArgs
$summaryExit=[int]$LASTEXITCODE
if(-not (Test-Path -LiteralPath $summary -PathType Leaf)){
    throw 'Independent historical summary missing; result not reportable.'
}
$review=Get-Content -LiteralPath $summary -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$review.live -cne 'LOCKED' -or
   $review.edge_validated -ne $false -or
   $review.trade_permission -ne $false){
    throw 'Unsafe historical summary. No output can be promoted.'
}
$stage=Join-Path $folder 'QTS_2025_TO_DATE_EVIDENCE'
New-Item -ItemType Directory -Path $stage -Force|Out-Null
foreach($rel in @('OPEN_RESULTS.json','OPEN_RESULTS.html',
                  'QTS_2025_TO_DATE_SUMMARY.json',
                  'QTS_POST_FILL_SAFETY_AUDIT.json',
                  'QTS_TRADE_BY_TRADE.json',
                  'QTS_DUAL_OPPORTUNITY_SUMMARY.json',
                  'native\QTS_7_trades.csv',
                  'native\QTS_7_opportunities.csv',
                  'native\QTS_7.htm')){
    $source=Join-Path $folder $rel
    if(-not (Test-Path -LiteralPath $source -PathType Leaf)){
        throw ('Incomplete broker-native history package, missing '+$source)
    }
    $dest=Join-Path $stage $rel
    New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force|Out-Null
    Copy-Item -LiteralPath $source -Destination $dest -Force
}
$zip=Join-Path $folder 'QTS_2025_TO_DATE_EVIDENCE.zip'
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal -Force
if(-not (Test-Path -LiteralPath $zip -PathType Leaf)){throw 'ZIP generation failed.'}
Write-Host ('Historical result: '+[string]$review.status)
Write-Host ('Native closed bars: '+[string]$review.native_m15_closed_bars)
Write-Host ('Completed broker positions: '+[string]$review.native_completed_positions)
Write-Host ('Broker-recorded net USD (NOT approved PnL): '+[string]$review.native_positions_net_usd)
Write-Host ('Native safety incident: '+[string]$review.native_safety_audit_status)
Write-Host ('SEND THIS ZIP FOR REVIEW: '+$zip) -ForegroundColor Green
Write-Host 'LIVE LOCKED. Do not reset safety incident or enable demo/live orders.'
try {explorer.exe /select,"$zip"}catch {Write-Warning ('Open ZIP manually: '+$zip)}
if($nativeExit -ne 0 -or $summaryExit -ne 0 -or
   [string]$review.status -cne 'HISTORICAL_RESEARCH_COMPLETE_NOT_LIVE_APPROVED'){
    # NO-GO is intentionally a nonzero exit, even when ZIP was saved.
    exit 2
}
exit 0
