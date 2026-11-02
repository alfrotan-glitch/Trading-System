# QTS Gold two STRATEGY TESTER-ONLY hypotheses. No broker login/order API.
# Running these is not a current profitable-edge certificate. One click;
# two separate fresh native M15 runs, no arithmetic summing of their PnL.
[CmdletBinding()]
param([switch]$PrepareOnly)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$runner=Join-Path $repo 'gold_robot\research\RunAutomaticTester.ps1'
$folder=Join-Path $repo ('gold_robot\reports_local\dual_research\'+(Get-Date -Format 'yyyyMMdd_HHmmss_ffff'))
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$summary=Join-Path $folder 'QTS_DUAL_RESEARCH_STATUS.json'
$results=@()
$state='FAILED_NO_GO'
$reason=''
try {
    if(-not (Test-Path -LiteralPath $runner -PathType Leaf)){
        throw 'Native tester not present. Obtain the full canonical QTS kit.'
    }
    foreach($name in @('DUAL_BOTH','DUAL_DIRECTIONAL')){
        $target=Join-Path $folder $name
        $args=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$runner,
                '-OnlyStyles','7','-ResearchVariant',$name,
                '-OutputDirectory',$target,'-NoOpen')
        if($PrepareOnly){$args+=,'-PrepareOnly'}
        Write-Host ('QTS research-only: '+$name)
        & (Join-Path $PSHOME 'powershell.exe') @args
        if($LASTEXITCODE -ne 0){throw ('Native tester refused '+$name)}
        $report=Join-Path $target 'OPEN_RESULTS.json'
        if(-not (Test-Path -LiteralPath $report -PathType Leaf)){
            throw ('Missing native outcome for '+$name)
        }
        $data=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
        # Check the child's result independently of its process exit code.
        # A present JSON file is not evidence that the native test passed.
        $expectedState=if($PrepareOnly){'PREPARED_ONLY'}else{'SELECTED_TESTS_FINISHED_REVIEW_REQUIRED'}
        if([string]$data.state -cne $expectedState){
            throw ('Native outcome not accepted for '+$name+': expected '+$expectedState+', got '+[string]$data.state)
        }
        if($data.edge_validated -eq $true){
            throw ('Report unexpectedly claims validated profitable edge: '+$name)
        }
        if($data.live -ne 'LOCKED'){
            # Current native outcome schema does not necessarily include a
            # live field; enforce no unsupported positive authorization instead.
            if($data.live -and $data.live -ne 'LOCKED'){
                throw ('Report unexpectedly claims trade authority: '+$name)
            }
        }
        $results+=@{variant=$name;run_directory=$target;state=[string]$data.state}
    }
    $state=if($PrepareOnly){'PREPARED_ONLY_NO_TRADES'}else{'TWO_NATIVE_RUNS_FINISHED_REVIEW_REQUIRED'}
    $reason='Each tested separately; no combined portfolio PnL, no profit approval.'
}catch {
    $reason=[string]$_.Exception.Message
    Write-Host ('QTS DUAL NO_GO: '+$reason)
}
finally {
    [ordered]@{
        schema='qts.gold.dual_native_review.v1'
        status=$state
        reason=$reason
        variants=@($results)
        live='LOCKED'
        edge_validated=$false
        broker_orders_sent_by_launcher=0
        current_source_native_compile_verified_here=$false
        no_portfolio_pnl_inference=$true
        generated_utc=[DateTimeOffset]::UtcNow.ToString('o')
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary -Encoding UTF8
    Write-Host ('QTS DUAL STATUS: '+$summary)
}
if($state -eq 'FAILED_NO_GO'){exit 2}
exit 0
