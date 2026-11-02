# QTS Gold three isolated real-tick MT5 research arms. No live orders.
# Same fresh EX5/source/time window for an evidence-based exploratory ranking.
[CmdletBinding()]
param(
    [string]$FromDate='2026.10.01',
    [string]$ToDate='2026.11.01'
)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$runner=Join-Path $repo 'gold_robot\research\RunAutomaticTester.ps1'
$comparison=Join-Path $repo 'gold_robot\research\compare_dual_modes.py'
if(-not (Test-Path -LiteralPath $runner -PathType Leaf) -or
   -not (Test-Path -LiteralPath $comparison -PathType Leaf)){
    throw 'Missing canonical QTS research runner or independent three-arm verifier.'
}
$folder=Join-Path $repo ('gold_robot\reports_local\dual_threeway\'+(Get-Date -Format 'yyyyMMdd_HHmmss_ffff'))
New-Item -ItemType Directory -Force -Path $folder | Out-Null
Write-Host 'RESEARCH ONLY. LIVE LOCKED. No demonstrated profitable edge.'
if($FromDate -eq '2026.10.01' -and $ToDate -eq '2026.11.01'){
    Write-Host 'October 2026 is a discovery/engineering sample, NOT unseen holdout.' -ForegroundColor Yellow
}
$variants=@('DUAL_BOTH','DUAL_DIRECTIONAL','DUAL_QUALITY')
foreach($variant in $variants){
    $out=Join-Path $folder $variant
    Write-Host ('Native MT5 quality comparison: '+$variant)
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass',
                 '-File',$runner,'-OnlyStyles','7',
                 '-ResearchVariant',$variant,'-FromDate',$FromDate,
                 '-ToDate',$ToDate,'-OutputDirectory',$out,'-NoOpen')
    & (Join-Path $PSHOME 'powershell.exe') @arguments
    $exitCode=[int]$LASTEXITCODE
    if($exitCode -ne 0){
        throw ($variant+' native tester failed exit='+$exitCode+
               '; inspect '+(Join-Path $out 'OPEN_RESULTS.json'))
    }
}
$review=Join-Path $folder 'QTS_DUAL_THREEWAY_REVIEW.json'
$pythonArgs=@('-3',$comparison,
              '--both',(Join-Path $folder 'DUAL_BOTH'),
              '--directional',(Join-Path $folder 'DUAL_DIRECTIONAL'),
              '--quality',(Join-Path $folder 'DUAL_QUALITY'),
              '--output',$review)
& py @pythonArgs
if($LASTEXITCODE -ne 0){
    throw ('Three-way market/source/provenance comparison FAILED: '+$review)
}
$report=Get-Content -LiteralPath $review -Raw -Encoding UTF8 | ConvertFrom-Json
if([string]$report.status -cne 'THREE_MODE_RESEARCH_REVIEW_ONLY' -or
   [string]$report.live -cne 'LOCKED' -or
   $report.edge_validated -ne $false -or
   $report.trade_permission -ne $false -or
   $report.same_native_source_and_signals_verified -ne $true){
    throw 'Three-way research result missing mandatory NO-GO and provenance controls.'
}
$stage=Join-Path $folder 'QTS_DUAL_THREEWAY_EVIDENCE'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item -LiteralPath $review -Destination $stage -Force
foreach($variant in $variants){
    $target=Join-Path $stage $variant
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    foreach($relative in @('OPEN_RESULTS.json','QTS_TRADE_BY_TRADE.json',
                           'QTS_DUAL_OPPORTUNITY_SUMMARY.json',
                           'native\QTS_7_opportunities.csv',
                           'native\QTS_7_trades.csv','native\QTS_7.htm')){
        $source=Join-Path (Join-Path $folder $variant) $relative
        if(-not (Test-Path -LiteralPath $source -PathType Leaf)){
            throw ('Missing verified native research evidence: '+$source)
        }
        $destination=Join-Path $target $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}
$zip=Join-Path $folder 'QTS_DUAL_THREEWAY_EVIDENCE.zip'
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal -Force
if(-not (Test-Path -LiteralPath $zip -PathType Leaf)){
    throw 'Three-arm native evidence ZIP missing.'
}
Write-Host ('SEND NATIVE THREE-WAY EVIDENCE: '+$zip) -ForegroundColor Green
Write-Host 'No live orders, no profitable edge approval. LIVE LOCKED.'
try{explorer.exe /select,"$zip"}
catch{Write-Warning ('Open ZIP manually: '+$zip)}
