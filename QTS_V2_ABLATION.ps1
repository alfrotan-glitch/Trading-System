# QTS Gold: four-way ablation of V2 entry and exit mechanisms.
# Four strategies INDEPENDENTLY; native WMMarkets MT5 real ticks.
# No connected orders, historical source overwrites, or live authorization.
[CmdletBinding()]
param([string]$FromDate='2026.10.01', [string]$ToDate='2026.10.30',
      [string]$OutputDirectory='', [switch]$NoOpen)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$gold=Join-Path $repo 'gold_robot'
$runner=Join-Path $gold 'research\RunAutomaticTester.ps1'
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$root=if($OutputDirectory){$OutputDirectory}else{Join-Path $gold ('reports_local\revised_comparison\'+$stamp)}
New-Item -ItemType Directory -Path $root -Force | Out-Null
$from=$FromDate
$to=$ToDate
$ci=[Globalization.CultureInfo]::InvariantCulture
$start=[datetime]::MinValue;$end=[datetime]::MinValue
if(-not [datetime]::TryParseExact($from,'yyyy.MM.dd',$ci,0,[ref]$start) -or
   -not [datetime]::TryParseExact($to,'yyyy.MM.dd',$ci,0,[ref]$end)){
   throw 'Ablation requires yyyy.MM.dd native tester dates.'
}
$legacy=($from -eq '2026.10.01' -and $to -eq '2026.10.30')
$future=($start -ge [datetime]'2026-11-01' -and $start.Day -eq 1 -and
         $end -eq $start.AddMonths(1))
if(-not ($legacy -or $future)){
    throw 'Only original October 2026 or a complete future calendar month is allowed.'
}
if($end -gt (Get-Date).Date){throw 'Future data is unavailable; the month has not finished.'}
$styles='1,3,7,8'
Write-Host '=============================================================='
Write-Host 'QTS GOLD V2 - FOUR ARM RESEARCH ABLATION - REAL TICK TESTER'
Write-Host 'October 2026 was inspected; every new month is independently tracked.'
Write-Host 'Four styles separately. CONNECTED LIVE/DEMO ORDERS LOCKED.'
Write-Host '=============================================================='
$runLog=Join-Path $root 'RUN_STATUS.txt'
$outline=@('QTS Gold V2 A/B study - four independent strategies',
           'Four arms: BASELINE, ENTRY_FILTER, NEAR_TP, COMBINED',
           ('Native real-tick tester, 3000 USD simulated, dates '+$from+' to '+$to),
           'No portfolio summation, no live account permission',
           ('Study root: '+$root))
[IO.File]::WriteAllLines($runLog,$outline,[Text.Encoding]::UTF8)
foreach($arm in @('BASELINE','ENTRY_FILTER','NEAR_TP','COMBINED')){
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
$report=Join-Path $root 'QTS_V2_ABLATION_COMPARISON.json'
$cmd=@((Join-Path $gold 'research\ablate_revised_variants.py'),
       '--root',$root,'--output',$report)
& $py @boot @cmd
if($LASTEXITCODE -ne 0){throw 'Independent four-arm monthly comparison failed.'}
$bundle=Join-Path $root 'QTS_V2_ABLATION_EVIDENCE.zip'
$stage=Join-Path $root 'evidence'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item -LiteralPath @($report,$runLog) -Destination $stage
foreach($arm in @('baseline','entry_filter','near_tp','combined')){
    $source=Join-Path $root $arm
    $dst=Join-Path $stage $arm
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    $files=@((Join-Path $source 'OPEN_RESULTS.json'),
             (Join-Path $source 'QTS_TRADE_BY_TRADE.json'))
    $files+=@(Get-ChildItem -LiteralPath $source -Filter 'QTS_Gold_Comparison_*.json' -File |
              Select-Object -ExpandProperty FullName)
    foreach($style in @(1,3,7,8)){
        $files+=,(Join-Path $source ('native\QTS_'+$style+'_trades.csv'))
        $files+=,(Join-Path $source ('native\QTS_'+$style+'.htm'))
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
Write-Host 'NO LIVE APPROVAL. Every monthly window requires independent review.'
if(-not $NoOpen){Start-Process -FilePath explorer.exe -ArgumentList ('/select,"'+$bundle+'"') | Out-Null}
