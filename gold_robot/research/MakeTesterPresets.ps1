# Read-only generation of nine MT5 Strategy Tester parameter sets.
# Neither starts terminal.exe nor authorizes broker orders or passwords.
[CmdletBinding()]
param(
    [string]$OutputDirectory="",
    [double]$ResearchRiskPct=0.50,
    [switch]$NoPrompt
)
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$source=Join-Path $gold 'mt5_robot\QTS_Gold_Robot.mq5'
if(-not (Test-Path -LiteralPath $source -PathType Leaf)){
    throw 'Canonical EA source missing. Clone all files from main.'
}
if($ResearchRiskPct -le 0.0 -or $ResearchRiskPct -gt 0.5){
    throw 'Research-risk parameter must be above zero and no more than 0.5%.'
}
$src=Get-Content -LiteralPath $source -Raw -Encoding UTF8
$rx='(?m)^\s*input\s+([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*=\s*([^;]+);'
$found=[regex]::Matches($src,$rx)
$inputs=[ordered]@{}
foreach($m in $found){
    $name=$m.Groups[2].Value
    $value=$m.Groups[3].Value.Trim()
    if($inputs.Contains($name)){throw ('Duplicate EA input: '+$name)}
    switch($value){
        'QTS_FORMER_STOP_LIMIT' { $value='0';break }
        'QTS_RETEST_LIMIT' { $value='1';break }
        'QTS_BREAK_ACCEPT_RETEST' { $value='2';break }
        'QTS_SWEEP_RECLAIM' { $value='3';break }
        'QTS_TREND_IMPULSE' { $value='4';break }
        'QTS_RANGE_REJECTION' { $value='5';break }
        'QTS_INSIDE_BREAKOUT' { $value='6';break }
        'QTS_ADAPTIVE_ROUTER' { $value='7';break }
        'QTS_SMC_FVG_OB' { $value='8';break }
        'PERIOD_M5' { $value='5';break }
        'PERIOD_M15' { $value='15';break }
        'PERIOD_M30' { $value='30';break }
        'PERIOD_H1' { $value='16385';break }
    }
    # All inputs must be literal numeric/boolean; fail if EA adds unknown enum.
    if($value -notmatch '^(?:true|false|\d+(?:\.\d+)?)$'){
        throw ("Unexpected EA input value for {0}: {1}" -f $name,$value)
    }
    $inputs.Add($name,$value)
}
if($inputs.Count -lt 35){throw "Too few EA inputs parsed: $($inputs.Count)"}
foreach($name in @('EntryStyle','SignalTimeframe','EnableDemoOrders',
                  'EnableDemoForwardOrders','TesterIgnoreDailyAndPeakStops',
                  'EnableEntryDiagnostics','RiskPerTradePct')){
    if(-not $inputs.Contains($name)){throw ('Required test control absent: '+$name)}
}
if(-not $OutputDirectory){
    $OutputDirectory=Join-Path $gold 'reports_local\tester_presets'
}
New-Item -ItemType Directory -Path $OutputDirectory -Force|Out-Null
$safetyDirectory=Join-Path $OutputDirectory 'safety_on'
New-Item -ItemType Directory -Path $safetyDirectory -Force|Out-Null
$names=@('FORMER_STOP','RETEST','BREAK_ACCEPT_RETEST','SWEEP_RECLAIM',
         'TREND_IMPULSE','RANGE_REJECTION','INSIDE_BREAKOUT','ADAPTIVE_ROUTER','SMC_FVG_OB')
$created=@()
for($style=0;$style -lt $names.Count;$style++){
    $settings=[ordered]@{}
    foreach($key in $inputs.Keys){$settings[$key]=$inputs[$key]}
    $settings['EntryStyle']=[string]$style
    $settings['SignalTimeframe']='15'
    $settings['EnableDemoOrders']='true' # Strategy Tester simulated orders.
    $settings['EnableDemoForwardOrders']='false' # Never arm a connected DEMO.
    $settings['TesterIgnoreDailyAndPeakStops']='true'
    $settings['EnableEntryDiagnostics']='true'
    $settings['RiskPerTradePct']=$ResearchRiskPct.ToString('0.00',[Globalization.CultureInfo]::InvariantCulture)
    $settings['PauseNewEntries']='false'
    $settings['EmergencyFlattenOwned']='false'
    $settings['ResetExecutionHalt']='false'
    $lines=@(
        '; QTS Gold MT5 Strategy Tester preset (simulation only; no connected account orders)',
        '; WMMarkets XAUUSD@ / M15 / suggested tester deposit 3000 USD',
        '; Use Every tick based on real ticks; compare identical broker periods/costs.',
        '; The tester-only daily-stop bypass is NOT permission for DEMO or REAL.',
        ('; EntryStyle={0} {1}' -f $style,$names[$style])
    )
    foreach($key in $settings.Keys){
        $lines+=('{0}={1}' -f $key,$settings[$key])
    }
    $path=Join-Path $OutputDirectory ('QTS_M15_{0}.set' -f $names[$style])
    # MT5 on Windows accepts native Unicode .set parameter files.
    [IO.File]::WriteAllLines($path,$lines,[Text.Encoding]::Unicode)
    $created+=,$path
    $settings['TesterIgnoreDailyAndPeakStops']='false'
    $safeLines=@(
        '; QTS Gold MT5 Strategy Tester preset (risk stops ACTIVE; simulation only)',
        '; WMMarkets XAUUSD@ / M15 / suggested tester deposit 3000 USD',
        '; Real ticks; identical dates and costs; no connected broker orders.',
        ('; EntryStyle={0} {1} with normal daily/peak stops' -f $style,$names[$style])
    )
    foreach($key in $settings.Keys){
        $safeLines+=('{0}={1}' -f $key,$settings[$key])
    }
    $safePath=Join-Path $safetyDirectory ('QTS_M15_{0}_SAFETY_ON.set' -f $names[$style])
    [IO.File]::WriteAllLines($safePath,$safeLines,[Text.Encoding]::Unicode)
}
if($created.Count -ne $names.Count){throw 'Failed to produce all nine test profiles.'}
Write-Host 'QTS Gold MT5 Strategy Tester presets created (seven fixed hypotheses, one adaptive research router, one SMC hypothesis; no connected orders submitted):'
foreach($item in $created){Write-Host $item}
Write-Host ('Production-like TESTER variants (risk stops active): '+$safetyDirectory)
Write-Host 'MT5: Ctrl+R > Inputs > Load one .set file > start a native real-tick test.'
Write-Host 'Deposit=3000 USD is set in Tester SETTINGS, not in .set input profiles.'
Write-Host 'Save each Result/Deals/Orders/Journal separately. LIVE remains locked.'
