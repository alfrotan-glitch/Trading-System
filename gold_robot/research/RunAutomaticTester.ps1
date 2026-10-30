# QTS Gold unattended native MT5 Strategy Tester. Simulation only; REAL locked.
[CmdletBinding()]
param([string]$TerminalExe="",[string]$TerminalDataFolder="",
      [string]$OutputDirectory="",[string]$FromDate="",[string]$ToDate="",
      [int]$TimeoutMinutesPerRun=90,[switch]$PrepareOnly,[switch]$NoOpen,
      [string]$OnlyStyles='')
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
if(-not $OutputDirectory){
    $OutputDirectory=Join-Path $gold ('reports_local\auto_runs\'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
}
New-Item -ItemType Directory -Path $OutputDirectory -Force|Out-Null
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$native=Join-Path $OutputDirectory 'native'
$configs=Join-Path $OutputDirectory 'configs'
New-Item -ItemType Directory -Path $native,$configs -Force|Out-Null
$results=New-Object System.Collections.ArrayList
$names=@('Former stop','Retest','Break and retest','Sweep and reclaim',
         'Trend impulse','Range rejection','Inside-bar breakout','Adaptive router','SMC FVG OB','M1 scalp')
# Targeted run is NOT a ten-strategy research certification.
$selectedStyles=@(0..9)
$targeted=($OnlyStyles -ne '')
if($targeted){
    if($OnlyStyles -notmatch '^[0-9](?:,[0-9])*
$today=(Get-Date).Date
$endMonth=[datetime]::new($today.Year,$today.Month,1)
if(-not $FromDate){$FromDate=$endMonth.AddMonths(-6).ToString('yyyy.MM.dd')}
if(-not $ToDate){$ToDate=$endMonth.ToString('yyyy.MM.dd')}
$startDate=[datetime]::MinValue
$endDate=[datetime]::MinValue
$ci=[Globalization.CultureInfo]::InvariantCulture
$ds=[Globalization.DateTimeStyles]::None
if(-not [datetime]::TryParseExact($FromDate,'yyyy.MM.dd',$ci,$ds,[ref]$startDate) -or
   -not [datetime]::TryParseExact($ToDate,'yyyy.MM.dd',$ci,$ds,[ref]$endDate) -or
   $startDate -ge $endDate -or $endDate -gt $today){
    throw 'Backtest dates must be yyyy.MM.dd, in the past, and in increasing order.'
}
if($TimeoutMinutesPerRun -lt 1 -or $TimeoutMinutesPerRun -gt 480){
    throw 'TimeoutMinutesPerRun must be between 1 and 480.'
}
function EscapeHtml([object]$value){
    return [System.Net.WebUtility]::HtmlEncode([string]$value)
}
function SaveOutcome([string]$state,[string]$message,[string]$comparison){
    $rows=@()
    foreach($item in $results){
        $href='Not available'
        if($item.report){
            $href='<a href="native/'+(EscapeHtml $item.report)+'">Open MT5 report</a>'
        }
        $rows+=('<tr><td>'+(EscapeHtml $item.style)+'</td><td>'+
            (EscapeHtml $item.status)+'</td><td>'+
            (EscapeHtml $item.detail)+'</td><td>'+$href+'</td></tr>')
    }
    if($rows.Count -eq 0){$rows=@('<tr><td colspan="4">No completed tests.</td></tr>')}
    $cmp='Not available'
    if($comparison){$cmp='<a href="'+(EscapeHtml $comparison)+'">Compare all ten reports</a>'}
    $tableRows=$rows -join [Environment]::NewLine
    $safeMessage=EscapeHtml $message
    $safeState=EscapeHtml $state
    $html=@"
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QTS Gold Automatic Tests</title>
<style>body{background:#f4f7fb;color:#172638;font:15px/1.7 "Segoe UI",Arial,sans-serif}
main{max-width:1040px;margin:30px auto;padding:15px}
header{background:#173954;color:white;border-radius:12px;padding:25px}
section{background:white;border:1px solid #dce4ee;border-radius:10px;margin-top:18px;padding:20px;overflow-x:auto}
table{width:100%;border-collapse:collapse}td,th{padding:12px;border-bottom:1px solid #dee6ed;text-align:left}
th{background:#edf2f9}.warning{border-left:4px solid #c28a25;padding-left:12px}</style></head><body>
<main><header><h1>QTS Gold | Automatic Strategy Tester</h1>
<p>WMMarkets · XAUUSD@ · M15 · Real ticks · USD 3000 simulated deposit</p>
<p>LIVE LOCKED · PROFITABLE EDGE NOT VALIDATED</p></header>
<section><h2>$safeState</h2><p>$safeMessage</p>
<p>Test period: $FromDate to $ToDate</p></section>
<section><h2>Seven fixed strategies plus adaptive router</h2><p><a href="QTS_TRADE_BY_TRADE.html">Individual trade forensics (each position, reason for exit)</a></p><table>
<tr><th>Strategy</th><th>State</th><th>Details</th><th>Native report</th></tr>
$tableRows
</table><p>$cmp</p></section>
<section class="warning"><h2>Limits</h2><p>Automated test reports do not authorize real-money trading.
The real-tick model, source identity, sufficient trades, actual commissions, spread,
drawdown and independent positive after-cost performance must still be verified.
An incomplete or missing report means NO-GO.</p></section></main></body></html>
"@
    $htmlPath=Join-Path $OutputDirectory 'OPEN_RESULTS.html'
    [IO.File]::WriteAllText($htmlPath,$html,([Text.UTF8Encoding]::new($false)))
    [ordered]@{
        schema='qts.mt5.auto_tester.v1';state=$state;message=$message;
        live='LOCKED';validated_edge=$false;real_money_orders=$false;
        symbol='XAUUSD@';model=4;timeframe='M15';deposit_usd=3000;
        from_date=$FromDate;to_date=$ToDate;comparison=$comparison;
        selected_styles=@($selectedStyles);targeted=$targeted;
        results=@($results.ToArray())
    } | ConvertTo-Json -Depth 7 |
        Set-Content -LiteralPath (Join-Path $OutputDirectory 'OPEN_RESULTS.json') -Encoding UTF8
    Write-Host ('RESULT: '+$htmlPath)
    if(-not $NoOpen){Invoke-Item -LiteralPath $htmlPath}
}
function IsMT5Data([string]$root){
    return (Test-Path -LiteralPath (Join-Path $root 'MQL5\Experts') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $root 'MQL5\Profiles') -PathType Container)
}
function FindTarget {
    if([bool]$TerminalExe -ne [bool]$TerminalDataFolder){
        throw 'Provide both terminal exe and data folder, or neither.'
    }
    if($TerminalExe){
        $e=(Resolve-Path -LiteralPath $TerminalExe -ErrorAction Stop).Path
        $d=(Resolve-Path -LiteralPath $TerminalDataFolder -ErrorAction Stop).Path
        if(-not (IsMT5Data $d)){throw 'Specified MT5 data folder is invalid.'}
        return @{exe=$e;data=$d}
    }
    $base=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    $targets=@()
    if(Test-Path -LiteralPath $base -PathType Container){
        foreach($dir in @(Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue)){
            $origin=Join-Path $dir.FullName 'origin.txt'
            if(-not (Test-Path -LiteralPath $origin -PathType Leaf) -or
               -not (IsMT5Data $dir.FullName)){continue}
            $folder=(Get-Content -LiteralPath $origin -Raw).Trim().Trim('"')
            $candidate=Join-Path $folder 'terminal64.exe'
            $ea=Join-Path $dir.FullName 'MQL5\Experts\QTS_Gold_Robot.mq5'
            if((Test-Path -LiteralPath $candidate -PathType Leaf) -and
               (Test-Path -LiteralPath $ea -PathType Leaf)){
                $targets+=,@{exe=$candidate;data=$dir.FullName}
            }
        }
    }
    if($targets.Count -ne 1){
        throw ('Found '+$targets.Count+' QTS MT5 installations. A unique installed WMMarkets terminal is required.')
    }
    return $targets[0]
}
function SameHash([string]$a,[string]$b){
    if(-not (Test-Path -LiteralPath $a -PathType Leaf) -or
       -not (Test-Path -LiteralPath $b -PathType Leaf)){return $false}
    return (Get-FileHash -LiteralPath $a -Algorithm SHA256).Hash -eq
           (Get-FileHash -LiteralPath $b -Algorithm SHA256).Hash
}
function CompiledCurrent([string]$data){
    $mql=Join-Path $data 'MQL5\Experts'
    foreach($name in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh','StructureResearch.mqh','OpportunityResearch.mqh','AdaptiveResearch.mqh','SmcResearch.mqh','ScalpResearch.mqh')){
        if(-not (SameHash (Join-Path $gold ('mt5_robot\'+$name)) (Join-Path $mql $name))){return $false}
    }
    $binary=Join-Path $mql 'QTS_Gold_Robot.ex5'
    if(-not (Test-Path -LiteralPath $binary -PathType Leaf)){return $false}
    if((Get-Item -LiteralPath $binary).Length -lt 1000){return $false}
    $binaryTime=(Get-Item -LiteralPath $binary).LastWriteTimeUtc
    foreach($name in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh','StructureResearch.mqh','OpportunityResearch.mqh','AdaptiveResearch.mqh','SmcResearch.mqh','ScalpResearch.mqh')){
        if($binaryTime -lt (Get-Item -LiteralPath (Join-Path $mql $name)).LastWriteTimeUtc.AddSeconds(-2)){return $false}
    }
    return $true
}
$state='FAILED'
$message=''
$comparison=''
try{
    $manifest=Get-Content -LiteralPath (Join-Path $gold 'docs\SOURCE_CHECKSUMS.json') -Raw | ConvertFrom-Json
    foreach($rel in @('mt5_robot/QTS_Gold_Robot.mq5','mt5_robot/ExecutionPolicy.mqh','mt5_robot/StructureResearch.mqh','mt5_robot/OpportunityResearch.mqh','mt5_robot/AdaptiveResearch.mqh','mt5_robot/SmcResearch.mqh','mt5_robot/ScalpResearch.mqh')){
        $entry=@($manifest.sha256_files|Where-Object {$_.path -eq $rel})
        if($entry.Count -ne 1){throw ('Manifest does not identify '+$rel)}
        $path=Join-Path $gold ($rel.Replace('/','\'))
        if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entry[0].sha256){
            throw ('Canonical source checksum mismatch '+$rel)
        }
    }
    $target=FindTarget
    $exe=$target.exe
    $data=$target.data
    $install=Split-Path -Parent $exe
    if((Split-Path -Leaf $exe) -ne 'terminal64.exe' -or
       -not (Test-Path -LiteralPath $exe -PathType Leaf)){throw 'Invalid MT5 terminal executable.'}
    $active=@(Get-Process -Name terminal64 -ErrorAction SilentlyContinue |
              Where-Object {$_.Path -eq $exe})
    if($active.Count -and -not $PrepareOnly){
        throw 'Close the open WMMarkets MT5 window and double-click QTS_AUTO_TEST.bat again; existing terminals cannot be reconfigured safely.'
    }
    if(-not (CompiledCurrent $data)){
        if($PrepareOnly){throw 'A current compiled EA is required even for prepare-only validation.'}
        $editor=Join-Path $install 'metaeditor64.exe'
        if(-not (Test-Path -LiteralPath $editor -PathType Leaf)){
            throw 'Cannot compile: MetaEditor missing next to terminal64.exe.'
        }
        & (Join-Path $gold 'mt5_robot\Install_QTS_Gold_Robot.ps1') -TerminalDataFolder $data -MetaEditorPath $editor
        if(-not (CompiledCurrent $data)){throw 'Native compilation did not verify the installed EA.'}
    }
    $presetDir=Join-Path $OutputDirectory 'presets'
    & (Join-Path $gold 'research\MakeTesterPresets.ps1') -OutputDirectory $presetDir -NoPrompt
    # MT5 builds/documentation differ on whether Tester profiles resolve
    # from the data folder or the installation folder. Support both when the
    # installation's MQL5 profile tree actually exists; never use an unverified
    # fallback to EA defaults because that silently tests EntryStyle=0 nine times.
    $testerProfiles=Join-Path $data 'MQL5\Profiles\Tester'
    $profileLocations=@($testerProfiles)
    $installProfileRoot=Join-Path $install 'MQL5\Profiles'
    if(Test-Path -LiteralPath $installProfileRoot -PathType Container){
        $profileLocations+=,(Join-Path $installProfileRoot 'Tester')
    }
    $profileLocations=@($profileLocations|Select-Object -Unique)
    foreach($root in $profileLocations){
        try{New-Item -ItemType Directory -Path $root -Force -ErrorAction Stop|Out-Null}
        catch{throw ('MT5 tester parameter folder not writable: '+$root)}
    }
    $codes=@('FORMER_STOP','RETEST','BREAK_ACCEPT_RETEST','SWEEP_RECLAIM',
            'TREND_IMPULSE','RANGE_REJECTION','INSIDE_BREAKOUT','ADAPTIVE_ROUTER','SMC_FVG_OB','M1_SCALP')
    for($i=0;$i -lt $names.Count;$i++){
        # REPAIR 2026-10-30: Style 9 presets are M1 (QTS_M1_M1_SCALP_*),
        # not M15. The old path silently missed Style 9's preset and the
        # old loop never ran it at all (nine styles, not ten).
        $tfLabel=$(if($i -eq 9){'M1'}else{'M15'})
        $preset=Join-Path $presetDir ('safety_on\QTS_'+$tfLabel+'_'+$codes[$i]+'_SAFETY_ON.set')
        if(-not (Test-Path -LiteralPath $preset -PathType Leaf)){throw ('Missing safety-on preset '+$i)}
        $setName='QTS_AUTO_'+(Split-Path -Leaf $OutputDirectory)+'_'+$i+'.set'
        foreach($root in $profileLocations){
            $setFile=Join-Path $root $setName
            try{Copy-Item -LiteralPath $preset -Destination $setFile -Force -ErrorAction Stop}
            catch{throw ('Cannot install this Strategy Tester .set file: '+$setFile)}
            if(-not (SameHash $preset $setFile)){
                throw ('Tester profile checksum mismatch: '+$setFile)
            }
        }
        $lines=Get-Content -LiteralPath (Join-Path $testerProfiles $setName) -Encoding Unicode
        $musts=@(('EntryStyle='+$i),'EnableDemoOrders=true',
                    'EnableDemoForwardOrders=false','TesterIgnoreDailyAndPeakStops=false',
                    'RiskPerTradePct=0.50')
        # Style 9 is M1-only with a 15-minute cap in the EA; a preset
        # without both is not Style 9 and must fail here, not in OnInit
        # after a wasted run (or worse, on the wrong timeframe).
        if($i -eq 9){ $musts+=@('SignalTimeframe=1','MaxPositionMinutes=15') }
        else { $musts+=@('SignalTimeframe=15') }
        foreach($must in $musts){
            if($must -notin $lines){throw ('Unsafe MT5 parameter set: '+$must)}
        }
        $reportName='QTS_AUTO_'+(Split-Path -Leaf $OutputDirectory)+'_'+$i
        $ini=Join-Path $configs ('style_'+$i+'.ini')
        $iniLines=@('[Common]','KeepPrivate=1','[Experts]','Enabled=0',
            'AllowLiveTrading=0','AllowDllImport=0','[Tester]',
            'Expert=QTS_Gold_Robot.ex5',('ExpertParameters='+$setName),
            'Symbol=XAUUSD@',('Period='+$(if($i -eq 9){'M1'}else{'M15'})),'Model=4','Optimization=0',
            'ForwardMode=0',('FromDate='+$FromDate),('ToDate='+$ToDate),
            'Deposit=3000','Currency=USD','Leverage=1:100',
            'UseLocal=1','UseRemote=0','UseCloud=0','Visual=0',
            ('Report='+$reportName),'ReplaceReport=1','ShutdownTerminal=1')
        [IO.File]::WriteAllLines($ini,$iniLines,[Text.Encoding]::Unicode)
    }
    if($PrepareOnly){
        $state='PREPARED_ONLY'
        $message='Ten configurations with risk stops active. MT5 was not launched.'
    }else{
        $runningIndex=0
        foreach($i in $selectedStyles){
            $runningIndex++
            $item=[ordered]@{style=$names[$i];style_id=$i;status='PENDING';detail='';report=''}
            $null=$results.Add($item)
            $reportName='QTS_AUTO_'+(Split-Path -Leaf $OutputDirectory)+'_'+$i
            $ini=Join-Path $configs ('style_'+$i+'.ini')
            $began=[datetime]::UtcNow
            $process=$null
            try{
                Write-Host ("Running native MT5 test {0}/{1}: {2} (Style {3})" -f $runningIndex,$selectedStyles.Count,$names[$i],$i)
                $process=Start-Process -FilePath $exe -ArgumentList ('/config:"{0}"' -f $ini) -PassThru
                $deadline=(Get-Date).AddMinutes($TimeoutMinutesPerRun)
                while(-not $process.HasExited){
                    Start-Sleep -Seconds 5
                    $process.Refresh()
                    if((Get-Date) -gt $deadline){throw ('Native MT5 test timed out for style '+$i)}
                }
                $candidates=@((Join-Path $install ($reportName+'.htm')),
                              (Join-Path $data ($reportName+'.htm')))
                $fresh=@($candidates|Where-Object{
                    (Test-Path -LiteralPath $_ -PathType Leaf) -and
                    (Get-Item -LiteralPath $_).LastWriteTimeUtc -ge $began.AddSeconds(-2)
                })
                if($fresh.Count -ne 1){
                    throw ('No fresh native MT5 HTML report for style '+$i+'. Check broker tick history and report write permissions.')
                }
                $reportText=Get-Content -LiteralPath $fresh[0] -Raw
                if($reportText -notmatch '(?i)<html|<!doctype'){throw 'MT5 did not create a native HTML report.'}
                $destination=Join-Path $native ('QTS_'+$i+'.htm')
                Copy-Item -LiteralPath $fresh[0] -Destination $destination
                $item.report='QTS_'+$i+'.htm'
                # OnTester exports each broker deal with position ID, entry/exit,
                # exit reason and original/current SL/TP into MT5 Common/Files.
                # Do not certify individual trades without this native evidence.
                $common=Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files'
                $pattern='QTS_FORENSIC_STYLE_'+$i+'_*.csv'
                $forensic=@(Get-ChildItem -LiteralPath $common -Filter $pattern -File -ErrorAction SilentlyContinue |
                    Where-Object {$_.LastWriteTimeUtc -ge $began.AddSeconds(-2)} |
                    Sort-Object LastWriteTimeUtc -Descending)
                # Never overwrite a missing forensic export with REPORT_SAVED.
                # A native HTML file is not a position-by-position audit.
                $hasForensics=$forensic.Count -eq 1
                if($hasForensics){
                    $forensicTarget=Join-Path $native ('QTS_'+$i+'_trades.csv')
                    Copy-Item -LiteralPath $forensic[0].FullName -Destination $forensicTarget
                    if((Get-Item -LiteralPath $forensicTarget).Length -le 0){
                        $hasForensics=$false
                    }
                }
                if(-not $hasForensics){
                    $item.status='FORENSIC_MISSING'
                    $item.detail='Native MT5 HTML exists, but exactly one fresh nonempty broker position/deal CSV is required.'
                }elseif($reportText -notmatch '(?i)real ticks'){
                    $item.status='MODEL_UNVERIFIED'
                    $item.detail='Broker deal CSV captured, but report did not verify real-tick model.'
                }else{
                    $item.status='REPORT_AND_FORENSICS_SAVED'
                    $item.detail='Fresh report and broker deal evidence saved; costs and profitability remain unverified.'
                }
            }catch{
                $item.status='FAILED'
                $item.detail=$_.Exception.Message
                throw
            }finally{
                if($process){
                    $process.Refresh()
                    if(-not $process.HasExited){
                        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                    }
                }
            }
        }
        & (Join-Path $gold 'research\CompareMT5Reports.ps1') -ReportDirectory $native -OutputDirectory $OutputDirectory -NoOpen
        & (Join-Path $gold 'research\BuildTradeForensics.ps1') -InputDirectory $native -OutputDirectory $OutputDirectory -NoOpen
        $latest=Get-ChildItem -LiteralPath $OutputDirectory -Filter 'QTS_Gold_Comparison_*.html' |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if($latest){$comparison=$latest.Name}
        $forensicSummary=Get-Content -LiteralPath (Join-Path $OutputDirectory 'QTS_TRADE_BY_TRADE.json') -Raw | ConvertFrom-Json
        # Both independent controls must pass. A completed test with missing
        # original input identity, missing deal evidence or unverified model
        # must remain an explicit research failure, never an approval.
        $badRuns=@($results | Where-Object {$_.status -ne 'REPORT_AND_FORENSICS_SAVED'})
        $nativeSummary=Get-ChildItem -LiteralPath $OutputDirectory -Filter 'QTS_Gold_Comparison_*.json' |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if(-not $nativeSummary){
            throw 'No native MT5 comparison JSON was produced.'
        }
        $nativeResult=Get-Content -LiteralPath $nativeSummary.FullName -Raw | ConvertFrom-Json
        if($targeted){
            # Check every selected style independently. Non-selected files
            # are expected to be absent and cannot be counted as failed runs.
            $selectedVerified=$true
            foreach($style in $selectedStyles){
                $matchedReport=@($nativeResult.results | Where-Object {
                    $_.style -eq $style -and $_.state -eq 'PARSED'
                })
                $matchedDeals=@($forensicSummary.evidence | Where-Object {
                    $_.style -eq $style -and $_.status -eq 'IMPORTED' -and $_.deals -gt 0
                })
                if($matchedReport.Count -ne 1 -or $matchedDeals.Count -ne 1){
                    $selectedVerified=$false
                }
            }
            if($badRuns.Count -eq 0 -and $results.Count -eq $selectedStyles.Count -and $selectedVerified){
                $state='SELECTED_TESTS_FINISHED_REVIEW_REQUIRED'
            }else{
                $state='SELECTED_TESTS_WITH_EVIDENCE_GAPS'
            }
            $message='Selected native tests and deal forensics checked; positive edge unvalidated.'
        }else{
            $allInputStylesVerified=($nativeResult.reports_parsed -eq $names.Count -and
                                     $nativeResult.all_styles_identified -eq $true)
            if($forensicSummary.status -eq 'IMPORTED_FOR_REVIEW' -and
               $badRuns.Count -eq 0 -and $allInputStylesVerified){
                $state='TESTS_FINISHED_REVIEW_REQUIRED'
            }else{
                $state='TESTS_FINISHED_WITH_EVIDENCE_GAPS'
            }
            $message='Ten native reports collected. Position-by-position evidence checked; positive after-cost expectancy unvalidated.'
        }
    }
}catch{
    $message=$_.Exception.Message
    Write-Warning $message
}finally{
    SaveOutcome $state $message $comparison
}
# A run missing native evidence must fail the caller even when some
# HTML reports exist. Preserve the diagnostic JSON/HTML for inspection.
if($state -notin @('PREPARED_ONLY','TESTS_FINISHED_REVIEW_REQUIRED',
                   'SELECTED_TESTS_FINISHED_REVIEW_REQUIRED')){exit 2}
exit 0
){throw 'Invalid OnlyStyles.'}
    $selectedStyles=@($OnlyStyles.Split(',') | ForEach-Object {[int]$_})
    if(@($selectedStyles | Sort-Object -Unique).Count -ne $selectedStyles.Count){
        throw 'Duplicate selected strategy IDs.'
    }
}

$today=(Get-Date).Date
$endMonth=[datetime]::new($today.Year,$today.Month,1)
if(-not $FromDate){$FromDate=$endMonth.AddMonths(-6).ToString('yyyy.MM.dd')}
if(-not $ToDate){$ToDate=$endMonth.ToString('yyyy.MM.dd')}
$startDate=[datetime]::MinValue
$endDate=[datetime]::MinValue
$ci=[Globalization.CultureInfo]::InvariantCulture
$ds=[Globalization.DateTimeStyles]::None
if(-not [datetime]::TryParseExact($FromDate,'yyyy.MM.dd',$ci,$ds,[ref]$startDate) -or
   -not [datetime]::TryParseExact($ToDate,'yyyy.MM.dd',$ci,$ds,[ref]$endDate) -or
   $startDate -ge $endDate -or $endDate -gt $today){
    throw 'Backtest dates must be yyyy.MM.dd, in the past, and in increasing order.'
}
if($TimeoutMinutesPerRun -lt 1 -or $TimeoutMinutesPerRun -gt 480){
    throw 'TimeoutMinutesPerRun must be between 1 and 480.'
}
function EscapeHtml([object]$value){
    return [System.Net.WebUtility]::HtmlEncode([string]$value)
}
function SaveOutcome([string]$state,[string]$message,[string]$comparison){
    $rows=@()
    foreach($item in $results){
        $href='Not available'
        if($item.report){
            $href='<a href="native/'+(EscapeHtml $item.report)+'">Open MT5 report</a>'
        }
        $rows+=('<tr><td>'+(EscapeHtml $item.style)+'</td><td>'+
            (EscapeHtml $item.status)+'</td><td>'+
            (EscapeHtml $item.detail)+'</td><td>'+$href+'</td></tr>')
    }
    if($rows.Count -eq 0){$rows=@('<tr><td colspan="4">No completed tests.</td></tr>')}
    $cmp='Not available'
    if($comparison){$cmp='<a href="'+(EscapeHtml $comparison)+'">Compare all ten reports</a>'}
    $tableRows=$rows -join [Environment]::NewLine
    $safeMessage=EscapeHtml $message
    $safeState=EscapeHtml $state
    $html=@"
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QTS Gold Automatic Tests</title>
<style>body{background:#f4f7fb;color:#172638;font:15px/1.7 "Segoe UI",Arial,sans-serif}
main{max-width:1040px;margin:30px auto;padding:15px}
header{background:#173954;color:white;border-radius:12px;padding:25px}
section{background:white;border:1px solid #dce4ee;border-radius:10px;margin-top:18px;padding:20px;overflow-x:auto}
table{width:100%;border-collapse:collapse}td,th{padding:12px;border-bottom:1px solid #dee6ed;text-align:left}
th{background:#edf2f9}.warning{border-left:4px solid #c28a25;padding-left:12px}</style></head><body>
<main><header><h1>QTS Gold | Automatic Strategy Tester</h1>
<p>WMMarkets · XAUUSD@ · M15 · Real ticks · USD 3000 simulated deposit</p>
<p>LIVE LOCKED · PROFITABLE EDGE NOT VALIDATED</p></header>
<section><h2>$safeState</h2><p>$safeMessage</p>
<p>Test period: $FromDate to $ToDate</p></section>
<section><h2>Seven fixed strategies plus adaptive router</h2><p><a href="QTS_TRADE_BY_TRADE.html">Individual trade forensics (each position, reason for exit)</a></p><table>
<tr><th>Strategy</th><th>State</th><th>Details</th><th>Native report</th></tr>
$tableRows
</table><p>$cmp</p></section>
<section class="warning"><h2>Limits</h2><p>Automated test reports do not authorize real-money trading.
The real-tick model, source identity, sufficient trades, actual commissions, spread,
drawdown and independent positive after-cost performance must still be verified.
An incomplete or missing report means NO-GO.</p></section></main></body></html>
"@
    $htmlPath=Join-Path $OutputDirectory 'OPEN_RESULTS.html'
    [IO.File]::WriteAllText($htmlPath,$html,([Text.UTF8Encoding]::new($false)))
    [ordered]@{
        schema='qts.mt5.auto_tester.v1';state=$state;message=$message;
        live='LOCKED';validated_edge=$false;real_money_orders=$false;
        symbol='XAUUSD@';model=4;timeframe='M15';deposit_usd=3000;
        from_date=$FromDate;to_date=$ToDate;comparison=$comparison;
        results=@($results.ToArray())
    } | ConvertTo-Json -Depth 7 |
        Set-Content -LiteralPath (Join-Path $OutputDirectory 'OPEN_RESULTS.json') -Encoding UTF8
    Write-Host ('RESULT: '+$htmlPath)
    if(-not $NoOpen){Invoke-Item -LiteralPath $htmlPath}
}
function IsMT5Data([string]$root){
    return (Test-Path -LiteralPath (Join-Path $root 'MQL5\Experts') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $root 'MQL5\Profiles') -PathType Container)
}
function FindTarget {
    if([bool]$TerminalExe -ne [bool]$TerminalDataFolder){
        throw 'Provide both terminal exe and data folder, or neither.'
    }
    if($TerminalExe){
        $e=(Resolve-Path -LiteralPath $TerminalExe -ErrorAction Stop).Path
        $d=(Resolve-Path -LiteralPath $TerminalDataFolder -ErrorAction Stop).Path
        if(-not (IsMT5Data $d)){throw 'Specified MT5 data folder is invalid.'}
        return @{exe=$e;data=$d}
    }
    $base=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    $targets=@()
    if(Test-Path -LiteralPath $base -PathType Container){
        foreach($dir in @(Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue)){
            $origin=Join-Path $dir.FullName 'origin.txt'
            if(-not (Test-Path -LiteralPath $origin -PathType Leaf) -or
               -not (IsMT5Data $dir.FullName)){continue}
            $folder=(Get-Content -LiteralPath $origin -Raw).Trim().Trim('"')
            $candidate=Join-Path $folder 'terminal64.exe'
            $ea=Join-Path $dir.FullName 'MQL5\Experts\QTS_Gold_Robot.mq5'
            if((Test-Path -LiteralPath $candidate -PathType Leaf) -and
               (Test-Path -LiteralPath $ea -PathType Leaf)){
                $targets+=,@{exe=$candidate;data=$dir.FullName}
            }
        }
    }
    if($targets.Count -ne 1){
        throw ('Found '+$targets.Count+' QTS MT5 installations. A unique installed WMMarkets terminal is required.')
    }
    return $targets[0]
}
function SameHash([string]$a,[string]$b){
    if(-not (Test-Path -LiteralPath $a -PathType Leaf) -or
       -not (Test-Path -LiteralPath $b -PathType Leaf)){return $false}
    return (Get-FileHash -LiteralPath $a -Algorithm SHA256).Hash -eq
           (Get-FileHash -LiteralPath $b -Algorithm SHA256).Hash
}
function CompiledCurrent([string]$data){
    $mql=Join-Path $data 'MQL5\Experts'
    foreach($name in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh','StructureResearch.mqh','OpportunityResearch.mqh','AdaptiveResearch.mqh','SmcResearch.mqh','ScalpResearch.mqh')){
        if(-not (SameHash (Join-Path $gold ('mt5_robot\'+$name)) (Join-Path $mql $name))){return $false}
    }
    $binary=Join-Path $mql 'QTS_Gold_Robot.ex5'
    if(-not (Test-Path -LiteralPath $binary -PathType Leaf)){return $false}
    if((Get-Item -LiteralPath $binary).Length -lt 1000){return $false}
    $binaryTime=(Get-Item -LiteralPath $binary).LastWriteTimeUtc
    foreach($name in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh','StructureResearch.mqh','OpportunityResearch.mqh','AdaptiveResearch.mqh','SmcResearch.mqh','ScalpResearch.mqh')){
        if($binaryTime -lt (Get-Item -LiteralPath (Join-Path $mql $name)).LastWriteTimeUtc.AddSeconds(-2)){return $false}
    }
    return $true
}
$state='FAILED'
$message=''
$comparison=''
try{
    $manifest=Get-Content -LiteralPath (Join-Path $gold 'docs\SOURCE_CHECKSUMS.json') -Raw | ConvertFrom-Json
    foreach($rel in @('mt5_robot/QTS_Gold_Robot.mq5','mt5_robot/ExecutionPolicy.mqh','mt5_robot/StructureResearch.mqh','mt5_robot/OpportunityResearch.mqh','mt5_robot/AdaptiveResearch.mqh','mt5_robot/SmcResearch.mqh','mt5_robot/ScalpResearch.mqh')){
        $entry=@($manifest.sha256_files|Where-Object {$_.path -eq $rel})
        if($entry.Count -ne 1){throw ('Manifest does not identify '+$rel)}
        $path=Join-Path $gold ($rel.Replace('/','\'))
        if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entry[0].sha256){
            throw ('Canonical source checksum mismatch '+$rel)
        }
    }
    $target=FindTarget
    $exe=$target.exe
    $data=$target.data
    $install=Split-Path -Parent $exe
    if((Split-Path -Leaf $exe) -ne 'terminal64.exe' -or
       -not (Test-Path -LiteralPath $exe -PathType Leaf)){throw 'Invalid MT5 terminal executable.'}
    $active=@(Get-Process -Name terminal64 -ErrorAction SilentlyContinue |
              Where-Object {$_.Path -eq $exe})
    if($active.Count -and -not $PrepareOnly){
        throw 'Close the open WMMarkets MT5 window and double-click QTS_AUTO_TEST.bat again; existing terminals cannot be reconfigured safely.'
    }
    if(-not (CompiledCurrent $data)){
        if($PrepareOnly){throw 'A current compiled EA is required even for prepare-only validation.'}
        $editor=Join-Path $install 'metaeditor64.exe'
        if(-not (Test-Path -LiteralPath $editor -PathType Leaf)){
            throw 'Cannot compile: MetaEditor missing next to terminal64.exe.'
        }
        & (Join-Path $gold 'mt5_robot\Install_QTS_Gold_Robot.ps1') -TerminalDataFolder $data -MetaEditorPath $editor
        if(-not (CompiledCurrent $data)){throw 'Native compilation did not verify the installed EA.'}
    }
    $presetDir=Join-Path $OutputDirectory 'presets'
    & (Join-Path $gold 'research\MakeTesterPresets.ps1') -OutputDirectory $presetDir -NoPrompt
    # MT5 builds/documentation differ on whether Tester profiles resolve
    # from the data folder or the installation folder. Support both when the
    # installation's MQL5 profile tree actually exists; never use an unverified
    # fallback to EA defaults because that silently tests EntryStyle=0 nine times.
    $testerProfiles=Join-Path $data 'MQL5\Profiles\Tester'
    $profileLocations=@($testerProfiles)
    $installProfileRoot=Join-Path $install 'MQL5\Profiles'
    if(Test-Path -LiteralPath $installProfileRoot -PathType Container){
        $profileLocations+=,(Join-Path $installProfileRoot 'Tester')
    }
    $profileLocations=@($profileLocations|Select-Object -Unique)
    foreach($root in $profileLocations){
        try{New-Item -ItemType Directory -Path $root -Force -ErrorAction Stop|Out-Null}
        catch{throw ('MT5 tester parameter folder not writable: '+$root)}
    }
    $codes=@('FORMER_STOP','RETEST','BREAK_ACCEPT_RETEST','SWEEP_RECLAIM',
            'TREND_IMPULSE','RANGE_REJECTION','INSIDE_BREAKOUT','ADAPTIVE_ROUTER','SMC_FVG_OB','M1_SCALP')
    for($i=0;$i -lt $names.Count;$i++){
        # REPAIR 2026-10-30: Style 9 presets are M1 (QTS_M1_M1_SCALP_*),
        # not M15. The old path silently missed Style 9's preset and the
        # old loop never ran it at all (nine styles, not ten).
        $tfLabel=$(if($i -eq 9){'M1'}else{'M15'})
        $preset=Join-Path $presetDir ('safety_on\QTS_'+$tfLabel+'_'+$codes[$i]+'_SAFETY_ON.set')
        if(-not (Test-Path -LiteralPath $preset -PathType Leaf)){throw ('Missing safety-on preset '+$i)}
        $setName='QTS_AUTO_'+(Split-Path -Leaf $OutputDirectory)+'_'+$i+'.set'
        foreach($root in $profileLocations){
            $setFile=Join-Path $root $setName
            try{Copy-Item -LiteralPath $preset -Destination $setFile -Force -ErrorAction Stop}
            catch{throw ('Cannot install this Strategy Tester .set file: '+$setFile)}
            if(-not (SameHash $preset $setFile)){
                throw ('Tester profile checksum mismatch: '+$setFile)
            }
        }
        $lines=Get-Content -LiteralPath (Join-Path $testerProfiles $setName) -Encoding Unicode
        $musts=@(('EntryStyle='+$i),'EnableDemoOrders=true',
                    'EnableDemoForwardOrders=false','TesterIgnoreDailyAndPeakStops=false',
                    'RiskPerTradePct=0.50')
        # Style 9 is M1-only with a 15-minute cap in the EA; a preset
        # without both is not Style 9 and must fail here, not in OnInit
        # after a wasted run (or worse, on the wrong timeframe).
        if($i -eq 9){ $musts+=@('SignalTimeframe=1','MaxPositionMinutes=15') }
        else { $musts+=@('SignalTimeframe=15') }
        foreach($must in $musts){
            if($must -notin $lines){throw ('Unsafe MT5 parameter set: '+$must)}
        }
        $reportName='QTS_AUTO_'+(Split-Path -Leaf $OutputDirectory)+'_'+$i
        $ini=Join-Path $configs ('style_'+$i+'.ini')
        $iniLines=@('[Common]','KeepPrivate=1','[Experts]','Enabled=0',
            'AllowLiveTrading=0','AllowDllImport=0','[Tester]',
            'Expert=QTS_Gold_Robot.ex5',('ExpertParameters='+$setName),
            'Symbol=XAUUSD@',('Period='+$(if($i -eq 9){'M1'}else{'M15'})),'Model=4','Optimization=0',
            'ForwardMode=0',('FromDate='+$FromDate),('ToDate='+$ToDate),
            'Deposit=3000','Currency=USD','Leverage=1:100',
            'UseLocal=1','UseRemote=0','UseCloud=0','Visual=0',
            ('Report='+$reportName),'ReplaceReport=1','ShutdownTerminal=1')
        [IO.File]::WriteAllLines($ini,$iniLines,[Text.Encoding]::Unicode)
    }
    if($PrepareOnly){
        $state='PREPARED_ONLY'
        $message='Ten configurations with risk stops active. MT5 was not launched.'
    }else{
        for($i=0;$i -lt $names.Count;$i++){
            $item=[ordered]@{style=$names[$i];status='PENDING';detail='';report=''}
            $null=$results.Add($item)
            $reportName='QTS_AUTO_'+(Split-Path -Leaf $OutputDirectory)+'_'+$i
            $ini=Join-Path $configs ('style_'+$i+'.ini')
            $began=[datetime]::UtcNow
            $process=$null
            try{
                Write-Host ("Running native MT5 test {0}/10: {1}" -f ($i+1),$names[$i])
                $process=Start-Process -FilePath $exe -ArgumentList ('/config:"{0}"' -f $ini) -PassThru
                $deadline=(Get-Date).AddMinutes($TimeoutMinutesPerRun)
                while(-not $process.HasExited){
                    Start-Sleep -Seconds 5
                    $process.Refresh()
                    if((Get-Date) -gt $deadline){throw ('Native MT5 test timed out for style '+$i)}
                }
                $candidates=@((Join-Path $install ($reportName+'.htm')),
                              (Join-Path $data ($reportName+'.htm')))
                $fresh=@($candidates|Where-Object{
                    (Test-Path -LiteralPath $_ -PathType Leaf) -and
                    (Get-Item -LiteralPath $_).LastWriteTimeUtc -ge $began.AddSeconds(-2)
                })
                if($fresh.Count -ne 1){
                    throw ('No fresh native MT5 HTML report for style '+$i+'. Check broker tick history and report write permissions.')
                }
                $reportText=Get-Content -LiteralPath $fresh[0] -Raw
                if($reportText -notmatch '(?i)<html|<!doctype'){throw 'MT5 did not create a native HTML report.'}
                $destination=Join-Path $native ('QTS_'+$i+'.htm')
                Copy-Item -LiteralPath $fresh[0] -Destination $destination
                $item.report='QTS_'+$i+'.htm'
                # OnTester exports each broker deal with position ID, entry/exit,
                # exit reason and original/current SL/TP into MT5 Common/Files.
                # Do not certify individual trades without this native evidence.
                $common=Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files'
                $pattern='QTS_FORENSIC_STYLE_'+$i+'_*.csv'
                $forensic=@(Get-ChildItem -LiteralPath $common -Filter $pattern -File -ErrorAction SilentlyContinue |
                    Where-Object {$_.LastWriteTimeUtc -ge $began.AddSeconds(-2)} |
                    Sort-Object LastWriteTimeUtc -Descending)
                # Never overwrite a missing forensic export with REPORT_SAVED.
                # A native HTML file is not a position-by-position audit.
                $hasForensics=$forensic.Count -eq 1
                if($hasForensics){
                    $forensicTarget=Join-Path $native ('QTS_'+$i+'_trades.csv')
                    Copy-Item -LiteralPath $forensic[0].FullName -Destination $forensicTarget
                    if((Get-Item -LiteralPath $forensicTarget).Length -le 0){
                        $hasForensics=$false
                    }
                }
                if(-not $hasForensics){
                    $item.status='FORENSIC_MISSING'
                    $item.detail='Native MT5 HTML exists, but exactly one fresh nonempty broker position/deal CSV is required.'
                }elseif($reportText -notmatch '(?i)real ticks'){
                    $item.status='MODEL_UNVERIFIED'
                    $item.detail='Broker deal CSV captured, but report did not verify real-tick model.'
                }else{
                    $item.status='REPORT_AND_FORENSICS_SAVED'
                    $item.detail='Fresh report and broker deal evidence saved; costs and profitability remain unverified.'
                }
            }catch{
                $item.status='FAILED'
                $item.detail=$_.Exception.Message
                throw
            }finally{
                if($process){
                    $process.Refresh()
                    if(-not $process.HasExited){
                        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                    }
                }
            }
        }
        & (Join-Path $gold 'research\CompareMT5Reports.ps1') -ReportDirectory $native -OutputDirectory $OutputDirectory -NoOpen
        & (Join-Path $gold 'research\BuildTradeForensics.ps1') -InputDirectory $native -OutputDirectory $OutputDirectory -NoOpen
        $latest=Get-ChildItem -LiteralPath $OutputDirectory -Filter 'QTS_Gold_Comparison_*.html' |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if($latest){$comparison=$latest.Name}
        $forensicSummary=Get-Content -LiteralPath (Join-Path $OutputDirectory 'QTS_TRADE_BY_TRADE.json') -Raw | ConvertFrom-Json
        # Both independent controls must pass. A completed test with missing
        # original input identity, missing deal evidence or unverified model
        # must remain an explicit research failure, never an approval.
        $badRuns=@($results | Where-Object {$_.status -ne 'REPORT_AND_FORENSICS_SAVED'})
        $nativeSummary=Get-ChildItem -LiteralPath $OutputDirectory -Filter 'QTS_Gold_Comparison_*.json' |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if(-not $nativeSummary){
            throw 'No native MT5 comparison JSON was produced.'
        }
        $nativeResult=Get-Content -LiteralPath $nativeSummary.FullName -Raw | ConvertFrom-Json
        $allInputStylesVerified=($nativeResult.reports_parsed -eq $names.Count -and
                                 $nativeResult.all_styles_identified -eq $true)
        if($forensicSummary.status -eq 'IMPORTED_FOR_REVIEW' -and
           $badRuns.Count -eq 0 -and $allInputStylesVerified){
            $state='TESTS_FINISHED_REVIEW_REQUIRED'
        }else{
            $state='TESTS_FINISHED_WITH_EVIDENCE_GAPS'
        }
        $message='Ten native reports collected. Position-by-position evidence checked; positive after-cost expectancy unvalidated.'
    }
}catch{
    $message=$_.Exception.Message
    Write-Warning $message
}finally{
    SaveOutcome $state $message $comparison
}
# A run missing native evidence must fail the caller even when some
# HTML reports exist. Preserve the diagnostic JSON/HTML for inspection.
if($state -notin @('PREPARED_ONLY','TESTS_FINISHED_REVIEW_REQUIRED')){exit 2}
exit 0
