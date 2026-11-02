# QTS Gold read-only diagnostic collector for the LAST failed dual native run.
# No MT5 launch, no compilation, no broker account access and no orders.
[CmdletBinding()]
param([switch]$NoOpen)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$root=Join-Path $repo 'gold_robot\reports_local\dual_research'
if(-not (Test-Path -LiteralPath $root -PathType Container)){
    throw 'No saved dual research run directory found.'
}
$runs=@(Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop |
    Sort-Object Name -Descending)
$chosen=$null
$parent=$null
foreach($candidate in $runs){
    $p=Join-Path $candidate.FullName 'QTS_DUAL_RESEARCH_STATUS.json'
    if(-not (Test-Path -LiteralPath $p -PathType Leaf)){continue}
    try {
        $data=Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
        if([string]$data.status -ceq 'FAILED_NO_GO'){
            $chosen=$candidate
            $parent=$data
            break
        }
    } catch {
        # Corrupt status is not evidence; keep searching for a readable failure.
    }
}
if($null -eq $chosen){
    throw 'No readable failed dual research run was found. No old result was changed.'
}
$arm=if([string]$parent.failed_variant -in @('DUAL_BOTH','DUAL_DIRECTIONAL')){
    [string]$parent.failed_variant
}else{
    # Legacy failure reports did not carry the failed child identity.
    'DUAL_BOTH'
}
$childDir=Join-Path $chosen.FullName $arm
$childFile=Join-Path $childDir 'OPEN_RESULTS.json'
$childState='MISSING_CHILD_OUTCOME'
$childReason='The child OPEN_RESULTS.json file is missing; root cause remains unknown.'
if(Test-Path -LiteralPath $childFile -PathType Leaf){
    try {
        $child=Get-Content -LiteralPath $childFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $childState=[string]$child.state
        $childReason=[string]$child.message
        if([string]::IsNullOrWhiteSpace($childReason)){
            $childReason='Native outcome exists but message is blank.'
        }
    } catch {
        $childState='UNREADABLE_CHILD_OUTCOME'
        $childReason=$_.Exception.Message
    }
}
$stage=Join-Path $chosen.FullName 'QTS_DUAL_LAST_FAILURE'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$diagnostic=[ordered]@{
    schema='qts.dual.failure_diagnostic.v1'
    status='FAILED_NO_GO_DIAGNOSTIC_ONLY'
    live='LOCKED'
    edge_validated=$false
    broker_orders_sent_by_collector=0
    original_run_status=[string]$parent.status
    original_run_reason=[string]$parent.reason
    inspected_variant=$arm
    child_state=$childState
    child_reason=$childReason
    child_report_present=(Test-Path -LiteralPath $childFile -PathType Leaf)
    compiled_source_confirmed_by_diagnostic=$false
    warning='A missing or incomplete native child report cannot establish compile success, tester readiness or trading performance.'
}
$info=Join-Path $stage 'QTS_DUAL_FAILURE_DIAGNOSTIC.json'
$diagnostic | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath $info -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $chosen.FullName 'QTS_DUAL_RESEARCH_STATUS.json') -Destination $stage -Force
if(Test-Path -LiteralPath $childFile -PathType Leaf){
    Copy-Item -LiteralPath $childFile -Destination $stage -Force
}
# Include only explicit, known research diagnostics; no terminal configurations,
# arbitrary logs, account tokens, or user files.
$op=Join-Path $childDir 'QTS_DUAL_OPPORTUNITY_SUMMARY.json'
if(Test-Path -LiteralPath $op -PathType Leaf){
    Copy-Item -LiteralPath $op -Destination $stage -Force
}
# Read the original broken native CSV, if present, WITHOUT exposing its raw
# rows or calling MT5. The verifier reports record/line/column counts only.
$nativeLedger=Join-Path $childDir 'native\QTS_7_opportunities.csv'
$ledgerScanner=Join-Path $repo 'gold_robot\research\verify_dual_opportunity.py'
if((Test-Path -LiteralPath $nativeLedger -PathType Leaf) -and
   (Test-Path -LiteralPath $ledgerScanner -PathType Leaf)){
    $scanResult=Join-Path $stage 'QTS_DUAL_RAW_LEDGER_SCAN.json'
    $py=Get-Command py -ErrorAction SilentlyContinue
    $python=Get-Command python -ErrorAction SilentlyContinue
    $mode=if($arm -eq 'DUAL_DIRECTIONAL'){2}else{1}
    if($py){
        & $py.Source -3 $ledgerScanner --input $nativeLedger --mode $mode --output $scanResult
        Write-Host ('NATIVE RAW LEDGER SCAN EXIT: '+$LASTEXITCODE)
    }elseif($python){
        & $python.Source $ledgerScanner --input $nativeLedger --mode $mode --output $scanResult
        Write-Host ('NATIVE RAW LEDGER SCAN EXIT: '+$LASTEXITCODE)
    }else{
        Write-Warning 'Python not available for native row inspection; original summary retained.'
    }
}
$zip=Join-Path $chosen.FullName 'QTS_DUAL_FAILURE_EVIDENCE.zip'
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal -Force
Write-Host ('FAILED VARIANT: '+$arm)
Write-Host ('CHILD STATE: '+$childState)
Write-Host ('CHILD REASON: '+$childReason)
Write-Host ('SEND ZIP FOR ROOT-CAUSE REVIEW: '+$zip)
if(-not $NoOpen){
    try { explorer.exe /select,"$zip" }
    catch { Write-Warning ('Cannot open File Explorer; the ZIP is at '+$zip) }
}
