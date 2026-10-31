# QTS Gold: one-click research acceptance of V2 vs baseline.
# Four strategies INDEPENDENTLY; native WMMarkets MT5 real ticks.
# No connected orders, historical source overwrites, or live authorization.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$gold=Join-Path $repo 'gold_robot'
$runner=Join-Path $gold 'research\RunAutomaticTester.ps1'
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$root=Join-Path $gold ('reports_local\revised_comparison\'+$stamp)
New-Item -ItemType Directory -Path $root -Force | Out-Null
$from='2026.10.01'
$to='2026.10.30'
$styles='1,3,7,8'
Write-Host '=============================================================='
Write-Host 'QTS GOLD V2 - BASELINE vs REVISED - REAL TICK TESTER'
Write-Host 'Exploratory 2026-10-01 to 2026-10-30 (previously inspected; NOT holdout).'
Write-Host 'Four styles separately. CONNECTED LIVE/DEMO ORDERS LOCKED.'
Write-Host '=============================================================='
$runLog=Join-Path $root 'RUN_STATUS.txt'
$outline=@('QTS Gold V2 A/B study - four independent strategies',
           'Baseline flags OFF versus revised combined flags ON',
           'Exploratory: October 2026 already inspected, real-tick tester, 3000 USD simulated',
           'No portfolio summation, no live account permission',
           ('Study root: '+$root))
[IO.File]::WriteAllLines($runLog,$outline,[Text.Encoding]::UTF8)
foreach($arm in @('BASELINE','COMBINED')){
    $out=Join-Path $root ($arm.ToLowerInvariant())
    Write-Host ('Starting native MT5 arm '+$arm+' (4 styles).')
    $args=@('-NoProfile','-ExecutionPolicy','Bypass',
        '-File',('"'+$runner+'"'),
        '-ResearchVariant',$arm,'-OnlyStyles',$styles,
        '-FromDate',$from,'-ToDate',$to,
        '-OutputDirectory',('"'+$out+'"'),'-NoOpen')
    $job=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $args -PassThru -Wait
    if($job.ExitCode -ne 0){
        throw ('Native '+$arm+' tester failed. Inspect '+$out+'\OPEN_RESULTS.html')
    }
    Add-Content -LiteralPath $runLog -Value ($arm+' native reports passed structural checks.')
}
$py=Join-Path $gold 'reports_local\mt5_quote_bridge_env\Scripts\python.exe'
$boot=@()
if(-not (Test-Path -LiteralPath $py)){
    if(Get-Command py.exe -ErrorAction SilentlyContinue){
        $py='py.exe'; $boot=@('-3')
    }elseif(Get-Command python.exe -ErrorAction SilentlyContinue){
        $py='python.exe'
    }else{ throw 'Python 3 is required to compare native evidence.' }
}
$report=Join-Path $root 'QTS_V2_HOLDOUT_COMPARISON.json'
$cmd=@((Join-Path $gold 'research\compare_revised_variants.py'),
       '--baseline',(Join-Path $root 'baseline'),
       '--combined',(Join-Path $root 'combined'),
       '--output',$report)
& $py @boot @cmd
if($LASTEXITCODE -ne 0){throw 'Independent baseline/V2 exploratory comparison failed.'}
$bundle=Join-Path $root 'QTS_V2_HOLDOUT_EVIDENCE.zip'
$stage=Join-Path $root 'evidence'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item -LiteralPath @($report,$runLog) -Destination $stage
foreach($arm in @('baseline','combined')){
    $source=Join-Path $root $arm
    $dst=Join-Path $stage $arm
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    $files=@((Join-Path $source 'OPEN_RESULTS.json'),
             (Join-Path $source 'QTS_TRADE_BY_TRADE.json'))
    $files+=@(Get-ChildItem -LiteralPath $source -Filter 'QTS_Gold_Comparison_*.json' -File |
              Select-Object -ExpandProperty FullName)
    foreach($style in @(1,3,7,8)){
        $files+=,(Join-Path $source ('native\QTS_'+$style+'_trades.csv'))
    }
    foreach($file in $files){
        if(-not (Test-Path -LiteralPath $file -PathType Leaf)){
            throw ('Missing canonical native A/B proof: '+$file)
        }
        Copy-Item -LiteralPath $file -Destination $dst -Force
    }
}
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $bundle -Force
Write-Host ('DONE: '+$report)
Write-Host ('SEND THE ZIP FOR REVIEW: '+$bundle)
Write-Host 'V2 NOT APPROVED FOR LIVE. October holdout may be too small.'
Start-Process -FilePath explorer.exe -ArgumentList ('/select,"'+$bundle+'"') | Out-Null
