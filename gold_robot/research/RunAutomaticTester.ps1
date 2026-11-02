# QTS Gold unattended native MT5 Strategy Tester. Simulation only; REAL locked.
[CmdletBinding()]
param([string]$TerminalExe="",[string]$TerminalDataFolder="",
      [string]$OutputDirectory="",[string]$FromDate="",[string]$ToDate="",
      [int]$TimeoutMinutesPerRun=90,[switch]$PrepareOnly,[switch]$NoOpen,
      [string]$OnlyStyles='',
      [ValidateSet('BASELINE','ENTRY_FILTER','NEAR_TP','COMBINED','CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO','DUAL_BOTH','DUAL_DIRECTIONAL')]
      [string]$ResearchVariant='BASELINE',[int]$VetoStyle=-1,[int]$VetoRegime=-1)
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$sourceManifestFile=Join-Path $gold 'docs\SOURCE_CHECKSUMS.json'
if(-not (Test-Path -LiteralPath $sourceManifestFile -PathType Leaf)){
    throw 'Cannot attest test build source: canonical source checksum manifest missing.'
}
$sourceManifestSha256=(Get-FileHash -LiteralPath $sourceManifestFile -Algorithm SHA256).Hash.ToLowerInvariant()

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
# A selected native run never counts as ten-style acceptance.
$selectedStyles=@(0..9)
$targeted=($OnlyStyles -ne '')
if($targeted){
    if($OnlyStyles -notmatch '^[0-9](?:,[0-9])*$'){throw 'Invalid OnlyStyles.'}
    $selectedStyles=@($OnlyStyles.Split(',') | ForEach-Object {[int]$_})
    if(@($selectedStyles | Sort-Object -Unique).Count -ne $selectedStyles.Count){
        throw 'Duplicate selected strategy IDs.'
    }
}

# V3 is a NEW strategy hypothesis, never a hidden replacement for V2 or the baseline.
# Only Style 7 / M15 is allowed to use the opt-in V3 native market-context filter.
if($ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO') -and ($OnlyStyles -ne '7')){
    throw 'Adaptive V3/V4/V5 variants require -OnlyStyles 7 (M15 research only).'
}
if($ResearchVariant -in @('DUAL_BOTH','DUAL_DIRECTIONAL') -and ($OnlyStyles -ne '7')){
    throw 'Dual Retest/Sweep requires -OnlyStyles 7 (M15 research only).'
}
if($ResearchVariant -eq 'ADAPTIVE_V5_VETO'){
    if($VetoStyle -lt 0 -or $VetoStyle -gt 8 -or $VetoStyle -eq 7 -or
       $VetoRegime -lt 0 -or $VetoRegime -gt 2){
        throw 'V5 challenger requires the exact frozen veto style (0-6,8) and regime (0-2).'
    }
}elseif($VetoStyle -ne -1 -or $VetoRegime -ne -1){
    throw 'V5 veto parameters cannot contaminate another research arm.'
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
$script:verifiedEx5Sha256=''
$script:verifiedTerminalSha256=''
$script:timeframeScope=if(9 -in $selectedStyles){
    if($selectedStyles.Count -eq 1){'M1'}else{'M15+M1'}
}else{'M15'}
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
<p>WMMarkets · XAUUSD@ · $script:timeframeScope · Real ticks · USD 3000 simulated deposit</p>
<p>LIVE LOCKED · PROFITABLE EDGE NOT VALIDATED</p></header>
<section><h2>$safeState</h2><p>$safeMessage</p>
<p>Test period: $FromDate to $ToDate</p></section>
<section><h2>Selected native MT5 strategy styles</h2><p><a href="QTS_TRADE_BY_TRADE.html">Individual trade forensics (each position, reason for exit)</a></p><table>
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
        symbol='XAUUSD@';model=4;timeframe=$script:timeframeScope;deposit_usd=3000;
        from_date=$FromDate;to_date=$ToDate;comparison=$comparison;
        selected_styles=@($selectedStyles);targeted=$targeted;
        research_variant=$ResearchVariant;
        challenger_veto_style=$(if($ResearchVariant -eq 'ADAPTIVE_V5_VETO'){$VetoStyle}else{$null});
        challenger_veto_regime=$(if($ResearchVariant -eq 'ADAPTIVE_V5_VETO'){$VetoRegime}else{$null});
        source_manifest_sha256=$sourceManifestSha256;
        compiled_ex5_sha256=$script:verifiedEx5Sha256;
        terminal_exe_sha256=$script:verifiedTerminalSha256;
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
    foreach($name in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh','StructureResearch.mqh','OpportunityResearch.mqh','AdaptiveResearch.mqh','MarketContextV3.mqh','AdaptiveV4Research.mqh','DualResearch.mqh','SmcResearch.mqh','ScalpResearch.mqh')){
        if(-not (SameHash (Join-Path $gold ('mt5_robot\'+$name)) (Join-Path $mql $name))){return $false}
    }
    $binary=Join-Path $mql 'QTS_Gold_Robot.ex5'
    if(-not (Test-Path -LiteralPath $binary -PathType Leaf)){return $false}
    if((Get-Item -LiteralPath $binary).Length -lt 1000){return $false}
    $binaryTime=(Get-Item -LiteralPath $binary).LastWriteTimeUtc
    foreach($name in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh','StructureResearch.mqh','OpportunityResearch.mqh','AdaptiveResearch.mqh','MarketContextV3.mqh','AdaptiveV4Research.mqh','DualResearch.mqh','SmcResearch.mqh','ScalpResearch.mqh')){
        if($binaryTime -lt (Get-Item -LiteralPath (Join-Path $mql $name)).LastWriteTimeUtc.AddSeconds(-2)){return $false}
    }
    return $true
}
$state='FAILED'
$message=''
$comparison=''
try{
    $manifest=Get-Content -LiteralPath (Join-Path $gold 'docs\SOURCE_CHECKSUMS.json') -Raw | ConvertFrom-Json
    foreach($rel in @('mt5_robot/QTS_Gold_Robot.mq5','mt5_robot/ExecutionPolicy.mqh','mt5_robot/StructureResearch.mqh','mt5_robot/OpportunityResearch.mqh','mt5_robot/AdaptiveResearch.mqh','mt5_robot/MarketContextV3.mqh','mt5_robot/AdaptiveV4Research.mqh','mt5_robot/DualResearch.mqh','mt5_robot/SmcResearch.mqh','mt5_robot/ScalpResearch.mqh')){
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
    $script:verifiedEx5Sha256=(Get-FileHash -LiteralPath (Join-Path $data 'MQL5\Experts\QTS_Gold_Robot.ex5') -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:verifiedTerminalSha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    if($script:verifiedEx5Sha256 -notmatch '^[0-9a-f]{64}$' -or
       $script:verifiedTerminalSha256 -notmatch '^[0-9a-f]{64}$'){
        throw 'Native EA/terminal binary provenance incomplete.'
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
        # Native A/B comparison: mutate a new, isolated tester preset.
        # The untouched baseline and compiled EA are the same in both arms.
        $flags=[ordered]@{
            'TesterUseEntryQualityV2'=($ResearchVariant -in @('ENTRY_FILTER','COMBINED'))
            'TesterProtectNearTPV2'=($ResearchVariant -in @('NEAR_TP','COMBINED'))
            'TesterUseMarketContextV3'=($ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO'))
            'TesterUseAdaptiveRouterV4'=($ResearchVariant -in @('ADAPTIVE_V4','ADAPTIVE_V5_VETO'))
            'TesterUsePreregisteredVetoV5'=($ResearchVariant -eq 'ADAPTIVE_V5_VETO')
        }
        $profileLines=@(Get-Content -LiteralPath $preset -Encoding Unicode)
        if($ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO')){
            # Research feasibility, NOT an in-sample profitable parameter:
            # 1.0 original TP RR is mathematically below V3 >=1.25
            # gross and after-cost threshold for fixed-RR candidates.
            # Freeze 1.50 in each V3-enabled research arm, never baseline.
            if(@($profileLines | Where-Object {$_ -match '^RewardToRisk='}).Count -ne 1){
                throw 'Native V3 research target reward/risk missing or duplicated.'
            }
            $profileLines=@($profileLines | ForEach-Object {
                if($_ -match '^RewardToRisk='){'RewardToRisk=1.50'}else{$_}
            })
        }
        if(@($profileLines | Where-Object {$_ -match '^TesterVetoStyleV5='}).Count -ne 1 -or
           @($profileLines | Where-Object {$_ -match '^TesterVetoRegimeV5='}).Count -ne 1){
            throw 'Missing unique veto inputs in native MT5 safety-on preset.'
        }
        $profileLines=@($profileLines | ForEach-Object {
            if($_ -match '^TesterVetoStyleV5='){ 'TesterVetoStyleV5='+$VetoStyle }
            elseif($_ -match '^TesterVetoRegimeV5='){ 'TesterVetoRegimeV5='+$VetoRegime }
            else{$_}
        })
        $dualMode=if($ResearchVariant -eq 'DUAL_BOTH'){1}
                  elseif($ResearchVariant -eq 'DUAL_DIRECTIONAL'){2}else{0}
        if(@($profileLines | Where-Object {$_ -match '^TesterDualStrategyMode='}).Count -ne 1){
            throw 'Missing unique dual research input in native MT5 safety-on preset.'
        }
        $profileLines=@($profileLines | ForEach-Object {
            if($_ -match '^TesterDualStrategyMode='){'TesterDualStrategyMode='+$dualMode}
            else{$_}
        })
        foreach($key in $flags.Keys){
            if(@($profileLines | Where-Object {$_ -match ('^'+$key+'=')}).Count -ne 1){
                throw ('Research flag missing or duplicated: '+$key)
            }
            $value=if($flags[$key]){'true'}else{'false'}
            $profileLines=@($profileLines | ForEach-Object {
                if($_ -match ('^'+$key+'=')){ $key+'='+$value }else{ $_ }
            })
        }
        $variantPreset=Join-Path $presetDir ('research_'+$ResearchVariant+'_'+$i+'.set')
        [IO.File]::WriteAllLines($variantPreset,$profileLines,[Text.Encoding]::Unicode)
        $preset=$variantPreset
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
        $musts=@(('EntryStyle='+$i),'EnableDemoOrders=true',('TesterDualStrategyMode='+$dualMode),
                    'EnableDemoForwardOrders=false','TesterIgnoreDailyAndPeakStops=false',
                    'RiskPerTradePct=0.50')
        foreach($key in $flags.Keys){
            $expect=if($flags[$key]){'true'}else{'false'}
            $musts+=@($key+'='+$expect)
        }
        if($ResearchVariant -in @('CONTEXT_V3','ADAPTIVE_V4','ADAPTIVE_V5_VETO')){
            $musts+=@('RewardToRisk=1.50')
        }
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
                }elseif(@(Import-Csv -LiteralPath $forensicTarget -Delimiter ';').Count -eq 0){
                    # A header-only CSV is NOT completed broker deal evidence.
                    # The MT5 run can be valid and still produce zero trades.
                    # Do not call it REPORT_AND_FORENSICS_SAVED or profitable.
                    $item.status='ZERO_NATIVE_DEALS_NO_GO'
                    $item.detail='MT5 tester finished but exported ZERO executed QTS broker deals. Inspect MT5 Experts/Tester QTS ENTRY AUDIT reasons and pending-order history; no economic conclusion.'
                }elseif($ResearchVariant -in @('DUAL_BOTH','DUAL_DIRECTIONAL') -and
                         $i -eq 7 -and
                         ($reportText -notmatch ('TesterDualStrategyMode\s*=\s*'+[string]$dualMode) -or
                          $reportText -notmatch 'EntryStyle\s*=\s*7')){
                    $item.status='NATIVE_DUAL_INPUT_UNVERIFIED_NO_GO'
                    $item.detail='MT5 native report did not confirm exact dual mode and Style 7. No strategy identity or profit claim.'
                }elseif($reportText -notmatch '(?i)real ticks'){
                    $item.status='MODEL_UNVERIFIED'
                    $item.detail='Broker deal CSV captured, but report did not verify real-tick model.'
                }else{
                    $item.status='REPORT_AND_FORENSICS_SAVED'
                    $item.detail='Fresh report and broker deal evidence saved; costs and profitability remain unverified.'
                }
                if($ResearchVariant -in @('DUAL_BOTH','DUAL_DIRECTIONAL') -and $i -eq 7){
                    # Native observation is required in ADDITION to fills.
                    # Source: MQL5 tester FILE_COMMON, not a simulated Python signal.
                    $opportunities=@(Get-ChildItem -LiteralPath $common -Filter 'QTS_DUAL_OPPORTUNITY_STYLE_7_*.csv' -File -ErrorAction SilentlyContinue |
                        Where-Object {$_.LastWriteTimeUtc -ge $began.AddSeconds(-2)})
                    if($opportunities.Count -ne 1){
                        $item.status='DUAL_OPPORTUNITY_MISSING_NO_GO'
                        $item.detail='Dual tester did not produce exactly one fresh native opportunity CSV.'
                    }else{
                        $nativeOpportunity=Join-Path $native 'QTS_7_opportunities.csv'
                        Copy-Item -LiteralPath $opportunities[0].FullName -Destination $nativeOpportunity
                        $verify=Join-Path $gold 'research\verify_dual_opportunity.py'
                        $summary=Join-Path $OutputDirectory 'QTS_DUAL_OPPORTUNITY_SUMMARY.json'
                        $py=Get-Command py -ErrorAction SilentlyContinue
                        if($py){
                            & $py.Source -3 $verify --input $nativeOpportunity --mode $dualMode --output $summary
                        }else{
                            $py=Get-Command python -ErrorAction SilentlyContinue
                            if(-not $py){throw 'Python 3 required for native opportunity evidence verification.'}
                            & $py.Source $verify --input $nativeOpportunity --mode $dualMode --output $summary
                        }
                        $verifyCode=$LASTEXITCODE
                        if($verifyCode -ne 0 -or -not (Test-Path -LiteralPath $summary -PathType Leaf)){
                            $item.status='DUAL_OPPORTUNITY_INVALID_NO_GO'
                            $item.detail='Native opportunity ledger could not be verified; open QTS_DUAL_OPPORTUNITY_SUMMARY.json.'
                        }else{
                            $facts=Get-Content -LiteralPath $summary -Raw | ConvertFrom-Json
                            if($facts.status -ne 'NATIVE_OPPORTUNITIES_VERIFIED_RESEARCH_ONLY' -or
                               $facts.live -ne 'LOCKED' -or $facts.edge_validated -ne $false -or
                               [int]$facts.rows -ne 2*[int]$facts.bars -or [int]$facts.bars -le 0){
                                $item.status='DUAL_OPPORTUNITY_INVALID_NO_GO'
                                $item.detail='Native opportunities failed coverage or safety invariant.'
                            }else{
                                $item.detail+=(' Both strategies observed for '+$facts.bars+' closed bars. No missed-fill profitability inference.')
                            }
                        }
                    }
                }
                if($ResearchVariant -in @('ADAPTIVE_V4','ADAPTIVE_V5_VETO') -and $i -eq 7){
                    # Native agent evidence: decision counts exist even when no
                    # entry order was ever placed. Never mistake a header-only
                    # deal CSV for an executed trade or a successful signal.
                    $decisionExports=@(Get-ChildItem -LiteralPath $common -Filter 'QTS_V4_DIAGNOSTICS_STYLE_7_*.csv' -File -ErrorAction SilentlyContinue |
                        Where-Object {$_.LastWriteTimeUtc -ge $began.AddSeconds(-2)})
                    if($decisionExports.Count -ne 1){
                        $item.status='DECISION_DIAGNOSTICS_MISSING_NO_GO'
                        $item.detail='Native V4 gate-count export missing or ambiguous; inspect Tester Experts/Journal, cannot explain zero deals.'
                    }else{
                        $decisionDest=Join-Path $native 'QTS_7_decisions.csv'
                        Copy-Item -LiteralPath $decisionExports[0].FullName -Destination $decisionDest
                        $decisions=@(Import-Csv -LiteralPath $decisionDest -Delimiter ';')
                        # A .set copied to disk is NOT proof that native MT5
                        # loaded its settings. Read them from inside OnTester.
                        $expectedInputs=[ordered]@{
                            EntryStyle='7'
                            SignalTimeframe='15'
                            RewardToRisk='1.50'
                            EnableDemoOrders='1'
                            TesterUseMarketContextV3='1'
                            TesterUseAdaptiveRouterV4='1'
                            TesterUsePreregisteredVetoV5=$(if($ResearchVariant -eq 'ADAPTIVE_V5_VETO'){'1'}else{'0'})
                            TesterVetoStyleV5=$(if($ResearchVariant -eq 'ADAPTIVE_V5_VETO'){[string]$VetoStyle}else{'-1'})
                            TesterVetoRegimeV5=$(if($ResearchVariant -eq 'ADAPTIVE_V5_VETO'){[string]$VetoRegime}else{'-1'})
                        }
                        foreach($key in $expectedInputs.Keys){
                            $original=@($decisions | Where-Object {$_.scope -eq 'INPUT' -and $_.verdict -eq $key})
                            if($original.Count -ne 1 -or [string]$original[0].count -ne [string]$expectedInputs[$key]){
                                throw ('MT5 tester native INPUT MISMATCH '+$key+
                                       '; expected '+$expectedInputs[$key]+
                                       '; actual '+$(if($original.Count -eq 1){$original[0].count}else{'MISSING_OR_DUPLICATED'})+
                                       '. Stop: native tester profile was not applied. Zero trades cannot be attributed to a strategy.')
                            }
                        }
                        $totals=@($decisions | Where-Object {$_.scope -eq 'CLOSED_BAR' -and $_.verdict -eq 'TOTAL_CLOSED_BARS'})
                        $barCount=0
                        if($totals.Count -ne 1 -or
                           -not [int]::TryParse([string]$(if($totals.Count -eq 1){$totals[0].count}else{''}),[ref]$barCount) -or
                           $barCount -le 0){
                            $item.status='DECISION_DIAGNOSTICS_INVALID_NO_GO'
                            $item.detail='Native V4 decision export has no valid evaluated closed bars.'
                        }else{
                            $gateSum=0
                            foreach($gate in @($decisions | Where-Object {
                                $_.scope -eq 'CLOSED_BAR' -and $_.verdict -ne 'TOTAL_CLOSED_BARS'
                            })){
                                $gateCount=0
                                if(-not [int]::TryParse([string]$gate.count,[ref]$gateCount) -or $gateCount -lt 0){
                                    $gateSum=-1
                                    break
                                }
                                $gateSum+=$gateCount
                            }
                            if($gateSum -ne $barCount){
                                $item.status='DECISION_DIAGNOSTICS_INVALID_NO_GO'
                                $item.detail='Native V4 decision stage counts do not reconcile with closed-bar evaluations.'
                            }else{
                                $topGates=@($decisions | Where-Object {
                                    $_.scope -eq 'CLOSED_BAR' -and
                                    $_.verdict -ne 'TOTAL_CLOSED_BARS' -and
                                    [int]$_.count -gt 0
                                } | Sort-Object {[int]$_.count} -Descending |
                                    Select-Object -First 4 |
                                    ForEach-Object {$_.verdict+'='+$_.count})
                                $topCandidateVetoes=@($decisions | Where-Object {
                                    $_.scope -eq 'CANDIDATE' -and
                                    $_.verdict -ne 'ELIGIBLE' -and [int]$_.count -gt 0
                                } | Sort-Object {[int]$_.count} -Descending |
                                    Select-Object -First 3 |
                                    ForEach-Object {'S'+$_.style+':'+$_.verdict+'='+$_.count})
                                # Individual V3 reasons answer WHY no router candidate
                                # was eligible, without logs or weakening any veto.
                                $v3Rows=@($decisions | Where-Object {$_.scope -eq 'V3_VETO'})
                                $v3Accepted=@($decisions | Where-Object {
                                    $_.scope -eq 'V3_ACCEPT' -and $_.verdict -eq 'TOTAL'
                                })
                                if($v3Rows.Count -ne 25 -or $v3Accepted.Count -ne 1 -or
                                   @($v3Rows | Select-Object -ExpandProperty verdict -Unique).Count -ne 25){
                                    throw 'V3 native reason export missing/duplicated; cannot certify the market-context veto causes.'
                                }
                                $v3Total=0
                                foreach($record in @($v3Rows)+@($v3Accepted)){
                                    $count=0
                                    if(-not [int]::TryParse([string]$record.count,[ref]$count) -or $count -lt 0){
                                        throw 'Invalid negative/non-numeric V3 reason count; no quality claim.'
                                    }
                                    $v3Total+=$count
                                }
                                $requiredV3=@($decisions | Where-Object {
                                    $_.scope -eq 'CANDIDATE' -and
                                    $_.verdict -in @('REJECT_MARKET_CONTEXT','ELIGIBLE')
                                } | Measure-Object -Property count -Sum).Sum
                                if($v3Total -lt [int]$requiredV3){
                                    throw 'Native V3 diagnostic counters do not cover all V4 context decisions.'
                                }
                                $topV3=@($v3Rows | Where-Object {[int]$_.count -gt 0} |
                                    Sort-Object {[int]$_.count} -Descending |
                                    Select-Object -First 5 |
                                    ForEach-Object {$_.verdict+'='+$_.count})
                                $item.detail+=(' Native V4 bars='+$barCount+
                                    '; top gates: '+($topGates -join ', ')+
                                    '; candidate vetoes: '+($topCandidateVetoes -join ', ')+
                                    '; exact V3 veto reasons: '+$(if($topV3.Count){$topV3 -join ', '}else{'NONE'})+
                                    '; V3 accepts='+$v3Accepted[0].count+
                                    '. The full decision CSV is saved locally.')
                            }
                        }
                    }
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
        if($targeted){
            & (Join-Path $gold 'research\BuildTradeForensics.ps1') -InputDirectory $native -OutputDirectory $OutputDirectory -SelectedStyles $selectedStyles -NoOpen
        }else{
            & (Join-Path $gold 'research\BuildTradeForensics.ps1') -InputDirectory $native -OutputDirectory $OutputDirectory -NoOpen
        }
        if($ResearchVariant -in @('ADAPTIVE_V4','ADAPTIVE_V5_VETO')){
            # Attach the actual selected sub-strategy and frozen market regime
            # from the broker's ORIGINAL entry-order comment to every V4 fill.
            # Never silently mark the tester run as reviewed when any native
            # order comment has been lost, clipped or has an unknown style.
            $interpreter=Get-Command py -ErrorAction SilentlyContinue
            $attr=Join-Path $OutputDirectory 'QTS_V4_POSITION_ATTRIBUTION.json'
            $entrypoint=Join-Path $gold 'research\v4_position_attribution.py'
            $sourcePositions=Join-Path $OutputDirectory 'QTS_TRADE_BY_TRADE.json'
            # An empty broker deal CSV has no trade identity to attribute.
            # Stop with a distinct, actionable ZERO-DEALS result instead
            # of misleading BROKER_ORDER_COMMENT_MISSING / attribution gaps.
            $nativePositions=Get-Content -LiteralPath $sourcePositions -Raw -Encoding UTF8 | ConvertFrom-Json
            if(@($nativePositions.trades).Count -eq 0){
                $selected=@($nativePositions.evidence | Where-Object {$_.style -eq 7})
                $details=if($selected.Count -eq 1){[string]$selected[0].status}else{'MISSING_STYLE_7_EVIDENCE'}
                throw ('V4 ZERO_EXECUTED_BROKER_DEALS_NO_GO: no completed or attributed MT5 QTS trades, source='+$details+
                       '. A zero-trade report is NOT breakeven evidence. Inspect native Tester Experts/Journal QTS ENTRY AUDIT rejection reasons, broker order history and symbol execution permissions. No strategy threshold was relaxed.')
            }
            if($interpreter){
                & $interpreter.Source -3 $entrypoint --input $sourcePositions --output $attr
            }else{
                $interpreter=Get-Command python -ErrorAction SilentlyContinue
                if(-not $interpreter){
                    throw 'V4 attribution needs Python 3 to check every original broker order identity.'
                }
                & $interpreter.Source $entrypoint --input $sourcePositions --output $attr
            }
            # The Python validator always writes per-position issues when
            # broker records were readable. Surface the exact evidence gap;
            # never replace an unavailable/mutated identity with a guess.
            $attributionExitCode=$LASTEXITCODE
            if($attributionExitCode -ne 0 -or -not (Test-Path -LiteralPath $attr -PathType Leaf)){
                $detail='Native source could not be validated. Check QTS_TRADE_BY_TRADE.json.'
                if(Test-Path -LiteralPath $attr -PathType Leaf){
                    try{
                        $failedAttribution=Get-Content -LiteralPath $attr -Raw -Encoding UTF8 | ConvertFrom-Json
                        $grouped=@($failedAttribution.issues | Group-Object reason |
                            Sort-Object Count -Descending | Select-Object -First 5 |
                            ForEach-Object { '{0}={1}' -f $_.Name,$_.Count })
                        $detail=('Attributed {0}/{1}; {2}' -f
                                 $failedAttribution.native_positions_attributed,
                                 $failedAttribution.native_positions_seen,
                                 $(if($grouped.Count){$grouped -join '; '}else{'UNKNOWN_ISSUE'}))
                    }catch{
                        $detail='Cannot parse the broker attribution audit JSON; original native file preserved.'
                    }
                }elseif(Test-Path -LiteralPath $sourcePositions -PathType Leaf){
                    try{
                        $sourceFact=Get-Content -LiteralPath $sourcePositions -Raw -Encoding UTF8 | ConvertFrom-Json
                        $missingTags=@($sourceFact.trades | Where-Object {
                            [string]$_.setup_reason -notmatch '^QTSV4-S[0-68]-R[0-2]$'
                        })
                        $incomplete=@($sourceFact.trades | Where-Object {
                            $_.status -notin @('COMPLETE','COMPLETE_MULTI_EXIT')
                        })
                        $detail=('Source={0}; positions={1}; unrecognized_original_tags={2}; incomplete_positions={3}' -f
                                 $sourceFact.status,@($sourceFact.trades).Count,
                                 $missingTags.Count,$incomplete.Count)
                    }catch{
                        $detail='Broker deal/position source not parseable; preserve original JSON and CSV.'
                    }
                }
                throw ('V4 native broker strategy attribution has gaps. No trade-quality claim is allowed. '+
                       $detail+'; diagnostics: QTS_V4_POSITION_ATTRIBUTION.json and QTS_TRADE_BY_TRADE.json')
            }
            $v4Fact=Get-Content -LiteralPath $attr -Raw -Encoding UTF8 | ConvertFrom-Json
            if($v4Fact.status -ne 'ATTRIBUTED_FOR_RESEARCH_ONLY' -or
               $v4Fact.live -ne 'LOCKED' -or $v4Fact.edge_validated -ne $false){
                throw 'V4 broker attribution is incomplete, inconsistent or unsafe.'
            }
            # Real-tick MT5 tester fills alone do not contain a continuous
            # 120-minute AFTER-STOP bid/ask series. Publish UNKNOWN explicitly
            # until a separately matched native tick export is available.
            $stopAudit=Join-Path $gold 'research\v4_post_stop_cohorts.py'
            $stopSummary=Join-Path $OutputDirectory 'QTS_V4_POST_STOP_STRATEGY_COHORTS.json'
            if(Get-Command py -ErrorAction SilentlyContinue){
                & $interpreter.Source -3 $stopAudit --attribution $attr --output $stopSummary --allow-missing-ticks
            }else{
                & $interpreter.Source $stopAudit --attribution $attr --output $stopSummary --allow-missing-ticks
            }
            if($LASTEXITCODE -ne 0 -or
               -not (Test-Path -LiteralPath $stopSummary -PathType Leaf)){
                throw 'V4 post-stop UNKNOWN/coverage diagnostics could not be verified.'
            }
            $stopFact=Get-Content -LiteralPath $stopSummary -Raw -Encoding UTF8 | ConvertFrom-Json
            if($stopFact.status -notin @('TICKS_MISSING_NO_GO','NO_BROKER_STOPS_TO_REPLAY') -or
               $stopFact.live -ne 'LOCKED' -or $stopFact.edge_validated -ne $false){
                throw 'V4 automatic stop-path report made an unsupported price-outcome claim.'
            }
            # Every ten completed broker positions, write an automatic trader
            # critique and PRE-REGISTERABLE SHADOW alternative. This learner
            # never writes back to a .set, MQL5, broker or trade permissions.
            $tenTradeScript=Join-Path $gold 'research\ten_trade_learning.py'
            $tenTradeReport=Join-Path $OutputDirectory 'QTS_TEN_TRADE_REFLECTION.json'
            if(Get-Command py -ErrorAction SilentlyContinue){
                & $interpreter.Source -3 $tenTradeScript --attribution $attr --post-stop $stopSummary --output $tenTradeReport
            }else{
                & $interpreter.Source $tenTradeScript --attribution $attr --post-stop $stopSummary --output $tenTradeReport
            }
            if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $tenTradeReport -PathType Leaf)){
                throw 'Native 10-position research reflection could not be verified.'
            }
            $reflection=Get-Content -LiteralPath $tenTradeReport -Raw -Encoding UTF8 | ConvertFrom-Json
            if($reflection.live -ne 'LOCKED' -or $reflection.edge_validated -ne $false -or
               $reflection.can_send_orders -ne $false -or $reflection.can_edit_ea -ne $false -or
               $reflection.can_self_promote_strategy -ne $false -or
               $reflection.status -notin @('WAITING_FOR_TEN_COMPLETE_TRADES','TEN_TRADE_CHECKPOINTS_READY_RESEARCH_ONLY')){
                throw 'Ten-trade auto-reflection attempted unsupported orders, mutation or promotion.'
            }
        }
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
            $verified=$true
            foreach($style in $selectedStyles){
                $r=@($nativeResult.results | Where-Object {
                    $_.style -eq $style -and $_.state -eq 'PARSED'
                })
                $d=@($forensicSummary.evidence | Where-Object {
                    $_.style -eq $style -and $_.status -eq 'IMPORTED' -and $_.deals -gt 0
                })
                if($r.Count -ne 1 -or $d.Count -ne 1){$verified=$false}
            }
            if($badRuns.Count -eq 0 -and $results.Count -eq $selectedStyles.Count -and $verified -and
               $forensicSummary.status -eq 'SELECTED_IMPORTED_FOR_REVIEW' -and
               $forensicSummary.targeted -eq $true){
                $state='SELECTED_TESTS_FINISHED_REVIEW_REQUIRED'
            }else{
                $state='SELECTED_TESTS_WITH_EVIDENCE_GAPS'
            }
            $message='Selected native reports and individual deal evidence checked. Profitability unvalidated.'
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
