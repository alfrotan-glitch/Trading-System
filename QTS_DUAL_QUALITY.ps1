# QTS GOLD research-only quality challenger, ONE native MT5 Style-7 test.
# Historical October is a technical replay, NOT an independent holdout.
[CmdletBinding()]
param(
    [string]$FromDate='2026.10.01',
    [string]$ToDate='2026.11.01'
)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$runner=Join-Path $repo 'gold_robot\research\RunAutomaticTester.ps1'
if(-not (Test-Path -LiteralPath $runner -PathType Leaf)){
    throw 'QTS native MT5 tester is missing. Update the full repository.'
}
$folder=Join-Path $repo ('gold_robot\reports_local\dual_quality\'+(Get-Date -Format 'yyyyMMdd_HHmmss_ffff'))
New-Item -ItemType Directory -Path $folder -Force | Out-Null
Write-Host 'QTS DUAL QUALITY: TESTER ONLY, NO LIVE AUTHORIZATION.'
Write-Host ('Period '+$FromDate+' to '+$ToDate+'; one Style-7 native research test.')
if($FromDate -eq '2026.10.01' -and $ToDate -eq '2026.11.01'){
    Write-Host 'OCTOBER IS DISCOVERY/ENGINEERING DATA, NOT AN INDEPENDENT HOLDOUT.' -ForegroundColor Yellow
}
$args=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$runner,
        '-OnlyStyles','7','-ResearchVariant','DUAL_QUALITY',
        '-FromDate',$FromDate,'-ToDate',$ToDate,
        '-OutputDirectory',$folder,'-NoOpen')
& (Join-Path $PSHOME 'powershell.exe') @args
$childExitCode=[int]$LASTEXITCODE
$outcome=Join-Path $folder 'OPEN_RESULTS.json'
if(-not (Test-Path -LiteralPath $outcome -PathType Leaf)){
    throw ('No native outcome after MT5 tester exit '+$childExitCode)
}
$report=Get-Content -LiteralPath $outcome -Raw -Encoding UTF8 | ConvertFrom-Json
$incident=($childExitCode -eq 2 -and
           [string]$report.state -ceq 'SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO')
if($childExitCode -ne 0 -and -not $incident){
    throw ('Native mode-3 test failed (exit '+$childExitCode+'). Inspect '+$outcome)
}
if([string]$report.research_variant -cne 'DUAL_QUALITY' -or
   [string]$report.state -cnotin @('SELECTED_TESTS_FINISHED_REVIEW_REQUIRED',
                                   'SELECTED_TESTS_WITH_SAFETY_INCIDENT_NO_GO') -or
   [string]$report.live -cne 'LOCKED' -or
   $report.validated_edge -ne $false -or
   $report.real_money_orders -ne $false){
    throw 'Native quality research identity, safety or completion evidence is invalid.'
}
if(@($report.selected_styles).Count -ne 1 -or
   [int]$report.selected_styles[0] -ne 7 -or
   [string]$report.timeframe -cne 'M15' -or
   [int]$report.model -ne 4 -or
   [string]$report.from_date -cne $FromDate -or
   [string]$report.to_date -cne $ToDate -or
   [string]::IsNullOrWhiteSpace([string]$report.compiled_ex5_sha256)){
    throw 'Quality run native style/timeframe/model/dates/compiled EA identity mismatch.'
}
$nativeSummary=Join-Path $folder 'QTS_DUAL_OPPORTUNITY_SUMMARY.json'
if(-not (Test-Path -LiteralPath $nativeSummary -PathType Leaf)){
    throw 'Native quality opportunity summary missing: no research acceptance.'
}
$nativeResult=Get-Content -LiteralPath $nativeSummary -Raw -Encoding UTF8 | ConvertFrom-Json
if([string]$nativeResult.status -cne 'NATIVE_OPPORTUNITIES_VERIFIED_RESEARCH_ONLY' -or
   [int]$nativeResult.mode -ne 3 -or
   [int]$nativeResult.bars -le 0 -or
   [int]$nativeResult.rows -ne 2*[int]$nativeResult.bars -or
   $nativeResult.edge_validated -ne $false -or
   [string]$nativeResult.live -cne 'LOCKED'){
    throw 'Native mode-3 paired opportunity validation failed or evidence was incomplete.'
}
if($incident){
    $safetyFile=Join-Path $folder 'QTS_POST_FILL_SAFETY_AUDIT.json'
    if(-not (Test-Path -LiteralPath $safetyFile -PathType Leaf)){
        throw 'Safety incident was reported but native incident audit JSON is missing.'
    }
    $safety=Get-Content -LiteralPath $safetyFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if([string]$safety.status -cne 'POST_FILL_SAFETY_INCIDENT_NO_GO' -or
       [string]$safety.live -cne 'LOCKED' -or
       $safety.edge_validated -ne $false -or
       $safety.trade_permission -ne $false){
        throw 'Unsafe-fill incident audit state is invalid. Fail closed.'
    }
}
$stage=Join-Path $folder 'QTS_DUAL_QUALITY_EVIDENCE'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
foreach($relative in @('OPEN_RESULTS.json','QTS_TRADE_BY_TRADE.json',
                       'QTS_DUAL_OPPORTUNITY_SUMMARY.json',
                       'native\QTS_7_opportunities.csv',
                       'native\QTS_7_trades.csv',
                       'native\QTS_7.htm',
                       'QTS_POST_FILL_SAFETY_AUDIT.json')){
    if($relative -eq 'QTS_POST_FILL_SAFETY_AUDIT.json' -and -not $incident){
        continue
    }
    $source=Join-Path $folder $relative
    if(-not (Test-Path -LiteralPath $source -PathType Leaf)){
        throw ('Missing native mode-3 evidence: '+$source)
    }
    $dest=Join-Path $stage $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $dest -Force
}
$zip=Join-Path $folder 'QTS_DUAL_QUALITY_EVIDENCE.zip'
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal -Force
if(-not (Test-Path -LiteralPath $zip -PathType Leaf)){
    throw 'Native mode-3 evidence ZIP missing; no approval.'
}
if($incident){
    Write-Host ('MT5 SAFETY INCIDENT NO-GO. Send ZIP for review: '+$zip) -ForegroundColor Red
}else{
    Write-Host ('MODE 3 RESEARCH EVIDENCE ONLY: '+$zip) -ForegroundColor Green
}
Write-Host 'No profitability validation. LIVE LOCKED.'
try {explorer.exe /select,"$zip"}catch {Write-Warning ('Open file manually: '+$zip)}
if($incident){exit 2}
