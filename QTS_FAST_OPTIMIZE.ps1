# Fast MT5 screening: 9 M15 EntryStyle optimization passes on local agents,
# followed by a separate M1 scalp pass. Research only, never live orders.
[CmdletBinding()]
param(
    [string]$OutputDirectory = '',
    [int]$TimeoutMinutesPerJob = 180,
    [switch]$PrepareOnly
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $root 'gold_robot\research\RunAutomaticTester.ps1'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw 'Missing canonical MT5 runner.' }
if ($TimeoutMinutesPerJob -lt 1 -or $TimeoutMinutesPerJob -gt 480) { throw 'Invalid timeout.' }
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $root ('gold_robot\reports_local\fast_screen\'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

# This source-verified preparation compiles if needed and produces ten
# immutable safety-on presets. No MT5 trading process is started here.
& $runner -OutputDirectory $OutputDirectory -PrepareOnly -NoOpen
if ($LASTEXITCODE -ne 0) { throw 'Canonical MT5 preparation failed. Reinstall and compile before screening.' }
$prepared = Get-Content -LiteralPath (Join-Path $OutputDirectory 'OPEN_RESULTS.json') -Raw | ConvertFrom-Json
if ($prepared.state -ne 'PREPARED_ONLY' -or $prepared.live -ne 'LOCKED' -or $prepared.validated_edge -ne $false) {
    throw 'Canonical prepared-state controls did not pass.'
}
$config0 = Join-Path $OutputDirectory 'configs\style_0.ini'
$config9 = Join-Path $OutputDirectory 'configs\style_9.ini'
$ini0 = @(Get-Content -LiteralPath $config0 -Encoding Unicode)
$ini9 = @(Get-Content -LiteralPath $config9 -Encoding Unicode)
foreach ($required in @('Model=4','Symbol=XAUUSD@','Period=M15','Optimization=0',
                        'AllowLiveTrading=0','Enabled=0','UseLocal=1',
                        'UseRemote=0','UseCloud=0','ForwardMode=0')) {
    if ($required -notin $ini0) { throw "M15 safety setting missing: $required" }
}
foreach ($required in @('Model=4','Symbol=XAUUSD@','Period=M1',
                        'AllowLiveTrading=0','Enabled=0','UseRemote=0',
                        'UseCloud=0','Optimization=0')) {
    if ($required -notin $ini9) { throw "M1 safety setting missing: $required" }
}
$p = @($ini0 | Where-Object { $_ -match '^ExpertParameters=' })
if ($p.Count -ne 1) { throw 'Missing one canonical style-0 profile identifier.' }
$originalName = $p[0].Substring('ExpertParameters='.Length)
$targets = @()
$terminalRoot = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
foreach ($candidate in @(Get-ChildItem -LiteralPath $terminalRoot -Directory -ErrorAction SilentlyContinue)) {
    $profile = Join-Path $candidate.FullName ('MQL5\Profiles\Tester\'+$originalName)
    if (Test-Path -LiteralPath $profile -PathType Leaf) { $targets += ,$candidate.FullName }
}
if ($targets.Count -ne 1) { throw 'Cannot identify exactly one source-verified MT5 profile folder.' }
$data = $targets[0]
$origin = Join-Path $data 'origin.txt'
if (-not (Test-Path -LiteralPath $origin -PathType Leaf)) { throw 'MT5 installation origin is missing.' }
$installation = (Get-Content -LiteralPath $origin -Raw).Trim().Trim('"')
$exe = Join-Path $installation 'terminal64.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Native MT5 executable not found.' }

$setPath = Join-Path $data ('MQL5\Profiles\Tester\'+$originalName)
$lines = @(Get-Content -LiteralPath $setPath -Encoding Unicode)
$styleLine = @($lines | Where-Object {$_ -match '^EntryStyle='})
if ($styleLine.Count -ne 1 -or $styleLine[0] -ne 'EntryStyle=0') {
    throw 'Expected unchanged safety-on Style 0 preset, no optimization applied.'
}
foreach ($needed in @('EnableDemoOrders=true','EnableDemoForwardOrders=false',
                      'TesterIgnoreDailyAndPeakStops=false','RiskPerTradePct=0.50',
                      'SignalTimeframe=15')) {
    if ($needed -notin $lines) { throw "Safety-on preset missing: $needed" }
}
# The only optimized input is the categorical strategy identity: 0..8.
# Do not optimize capital risk, SL, TP, session hours or other parameters.
$optLines = @($lines | ForEach-Object {
    if ($_ -eq 'EntryStyle=0') { 'EntryStyle=0||0||1||8||Y' } else { $_ }
})
if (@($optLines | Where-Object {$_ -match '\|\|Y$'}).Count -ne 1) {
    throw 'Exactly one optimized input is required.'
}
$tag = Split-Path -Leaf $OutputDirectory
$optName = 'QTS_FAST_M15_'+$tag+'.set'
$optFile = Join-Path $data ('MQL5\Profiles\Tester\'+$optName)
[IO.File]::WriteAllLines($optFile,$optLines,[Text.Encoding]::Unicode)
$installProfileParent = Join-Path $installation 'MQL5\Profiles'
if (Test-Path -LiteralPath $installProfileParent -PathType Container) {
    $otherDir = Join-Path $installProfileParent 'Tester'
    New-Item -ItemType Directory -Path $otherDir -Force | Out-Null
    Copy-Item -LiteralPath $optFile -Destination (Join-Path $otherDir $optName) -Force
}
$reportName = 'QTS_FAST_OPT_M15_'+$tag
$optIni = @($ini0 | ForEach-Object {
    if ($_ -eq 'Optimization=0') { 'Optimization=1' }
    elseif ($_ -like 'ExpertParameters=*') { 'ExpertParameters='+$optName }
    elseif ($_ -like 'Report=*') { 'Report='+$reportName }
    else { $_ }
})
$optIni += 'OptimizationCriterion=4'
# Some MT5 builds read optimization ranges from the INI rather than
# ExpertParameters. The two copies agree and are both fail-closed.
$optIni += ''
$optIni += '[TesterInputs]'
$optIni += @($optLines | Where-Object { $_ -match '^[A-Za-z_][A-Za-z_0-9]*=' })
$optIniPath = Join-Path $OutputDirectory 'FAST_M15_OPTIMIZATION.ini'
[IO.File]::WriteAllLines($optIniPath,$optIni,[Text.Encoding]::Unicode)

$statusPath = Join-Path $OutputDirectory 'FAST_SCREEN_STATUS.json'
function SaveStatus([string]$state,[string]$note) {
    [ordered]@{
        state=$state; message=$note; live='LOCKED'; profitable_edge_validated=$false;
        full_trade_forensics_complete=$false; scope='SCREENING_ONLY';
        optimized_styles=@(0,1,2,3,4,5,6,7,8); separate_m1_style=9;
        m15_config=$optIniPath; m1_config=$config9;
        output_directory=$OutputDirectory
    } | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $statusPath -Encoding UTF8
}
SaveStatus 'PREPARED_ONLY' '9 M15 cases are locally parallelizable. Style 9 is a separate M1 pass.'
Write-Host "M15 parallel optimization configuration: $optIniPath"
Write-Host "M1 scalp single-test configuration: $config9"
Write-Host 'No cloud/remote agents. No real money orders. Only preliminary screening.'

if ($PrepareOnly) { exit 0 }

$active = @(Get-Process -Name terminal64 -ErrorAction SilentlyContinue |
    Where-Object {$_.Path -eq $exe})
if ($active.Count -ne 0) {
    throw 'Close the WMMarkets MT5 terminal or ongoing tester first. Nothing started.'
}
function RunJob([string]$cfg,[string]$label) {
    Write-Host ('Native MT5 '+$label+' starting. Only LOCAL agents are enabled.')
    $started=[datetime]::UtcNow
    $proc = Start-Process -FilePath $exe -ArgumentList ('/config:"{0}"' -f $cfg) -PassThru
    try {
        if (-not $proc.WaitForExit($TimeoutMinutesPerJob*60000)) {
            throw ('MT5 '+$label+' exceeded safety timeout.')
        }
        $found=@()
        foreach($base in @($installation,$data)) {
            foreach($ext in @('.xml','.htm','.html')) {
                $stem=if ($label -eq 'M15 optimization') {$reportName} else {
                    $match=@($ini9 | Where-Object {$_ -like 'Report=*'})
                    if($match.Count -ne 1){throw 'No style 9 report identifier.'}
                    $match[0].Substring(7)
                }
                $candidate=Join-Path $base ($stem+$ext)
                if ((Test-Path -LiteralPath $candidate -PathType Leaf) -and
                    (Get-Item -LiteralPath $candidate).LastWriteTimeUtc -ge $started.AddSeconds(-3)) {
                    $found += ,$candidate
                }
            }
        }
        if ($found.Count -eq 0) {
            throw ('No fresh native '+$label+' report; check the MT5 tester Journal. No results certified.')
        }
        foreach ($source in $found) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $OutputDirectory (Split-Path -Leaf $source)) -Force
            Write-Host ('Saved report: '+$source)
        }
    } finally {
        $proc.Refresh()
        if(-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
}
try {
    SaveStatus 'RUNNING' 'Nine M15 categorical passes via local agents, then one M1 pass.'
    RunJob $optIniPath 'M15 optimization'
    RunJob $config9 'M1 scalp'
    SaveStatus 'SCREENING_FINISHED_REVIEW_REQUIRED' 'Optimization results are a first-pass screen, NOT complete trade-by-trade evidence or a validated profit claim.'
    Write-Host 'FAST SCREEN FINISHED. Inspect local optimization and scalp reports, then fully retest finalists with native trade forensics.'
} catch {
    SaveStatus 'FAILED' $_.Exception.Message
    Write-Error $_.Exception.Message
    exit 2
}
exit 0
