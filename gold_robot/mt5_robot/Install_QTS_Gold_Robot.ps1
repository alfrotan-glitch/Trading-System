# QTS Gold Robot — initial-development Windows MT5 deployment and compilation.
# No admin rights, no credentials, and absolutely no broker-order API calls.
[CmdletBinding()]
param(
    [string]$TerminalDataFolder = "",
    [string]$MetaEditorPath = ""
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'QTS_Gold_Robot.mq5'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw 'The QTS robot source code is missing; extract the whole ZIP.'
}

# Validate the exact extracted package before touching the installed MT5 EA.
# The formerly distributed short-name archive still contained a Market
# version 0.00 directive and produced warning 68. Reject it at source.
$sourceText = Get-Content -LiteralPath $source -Raw -Encoding UTF8
if ($sourceText -match '(?im)^\s*#property\s+version\b') {
    throw 'STALE QTS ROBOT SOURCE: unexpected MQL5 Market version directive. Extract the CURRENT corrected ZIP into a NEW EMPTY FOLDER; do not run the older E:\QTS_Robot copy.'
}
$manifestPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'docs\SOURCE_CHECKSUMS.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw 'The robot package checksum manifest is missing. Extract the entire corrected ZIP.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$entries = @($manifest.sha256_files | Where-Object { $_.path -eq 'mt5_robot/QTS_Gold_Robot.mq5' })
if ($entries.Count -ne 1) {
    throw 'The robot checksum manifest is invalid. Extract the complete corrected ZIP.'
}
$expectedHash = [string]$entries[0].sha256
$actualHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
if ($expectedHash.ToUpperInvariant() -ne $actualHash.ToUpperInvariant()) {
    throw 'The extracted robot source does not match the package manifest. Stop using this mixed/old folder and extract the corrected ZIP into a NEW EMPTY FOLDER.'
}
$policy = Join-Path $PSScriptRoot 'ExecutionPolicy.mqh'
$policyRows = @($manifest.sha256_files | Where-Object { $_.path -eq 'mt5_robot/ExecutionPolicy.mqh' })
if ($policyRows.Count -ne 1 -or -not (Test-Path -LiteralPath $policy -PathType Leaf)) {
    throw 'Missing execution policy or manifest entry.'
}
$policyHash = (Get-FileHash -LiteralPath $policy -Algorithm SHA256).Hash
if ($policyHash -ne $policyRows[0].sha256) { throw 'Execution policy checksum mismatch.' }
Write-Host ('Package source validated: {0}' -f $source)
Write-Host ('Source SHA-256: {0}' -f $actualHash)
Write-Host 'Stale version 0.00 check: PASS; metadata warning 68 cannot originate from this source.' -ForegroundColor Green

Write-Host 'QTS GOLD ROBOT - INITIAL DEVELOPMENT - DEMO INSTALLER' -ForegroundColor Cyan
Write-Host 'This installation does not log in, enable Algo Trading, or place orders.'
Write-Host 'If an older QTS robot is attached to MT5, detach it before updating.'

function Test-MQL5Root([string]$candidate) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { return $false }
    return (Test-Path -LiteralPath (Join-Path $candidate 'Experts') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $candidate 'Indicators') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $candidate 'Include') -PathType Container)
}

function Resolve-MQL5Root([string]$candidate) {
    if (Test-MQL5Root $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    $nested = Join-Path $candidate 'MQL5'
    if (Test-MQL5Root $nested) { return (Resolve-Path -LiteralPath $nested).Path }
    return $null
}

$roots = @()
if ($TerminalDataFolder) {
    $exact = Resolve-MQL5Root $TerminalDataFolder
    if (-not $exact) { throw 'The specified MT5 data folder lacks an MQL5 installation.' }
    $roots = @($exact)
} else {
    $root = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if (Test-Path -LiteralPath $root -PathType Container) {
        foreach ($item in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
            $candidate = Resolve-MQL5Root $item.FullName
            if ($candidate) { $roots += $candidate }
        }
    }
}
$roots = @($roots | Sort-Object -Unique)
if ($roots.Count -eq 0) {
    Write-Host 'Open MT5 > File > Open Data Folder, then copy its path.' -ForegroundColor Yellow
    $manual = Read-Host 'Paste your exact MetaTrader 5 Data Folder'
    $candidate = Resolve-MQL5Root $manual
    if (-not $candidate) { throw 'No valid MetaTrader 5 data folder was selected.' }
    $roots = @($candidate)
}
if ($roots.Count -gt 1) {
    Write-Host 'Choose the MT5 data folder belonging to your currently used terminal:'
    for ($i = 0; $i -lt $roots.Count; $i++) {
        Write-Host ('  [{0}] {1}' -f ($i + 1), $roots[$i])
    }
    $answer = Read-Host ('Choose number 1-{0}' -f $roots.Count)
    $number = 0
    if (-not [int]::TryParse($answer, [ref]$number) -or $number -lt 1 -or $number -gt $roots.Count) {
        throw 'No valid MT5 data folder chosen; installation was not started.'
    }
    $mql5 = $roots[$number - 1]
} else {
    $mql5 = $roots[0]
}

$editors = @()
if ($MetaEditorPath) { $editors += $MetaEditorPath }
if (-not $MetaEditorPath) {
foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
    if (-not $base -or -not (Test-Path -LiteralPath $base -PathType Container)) { continue }
    $direct = Join-Path $base 'MetaTrader 5\metaeditor64.exe'
    if (Test-Path -LiteralPath $direct -PathType Leaf) { $editors += $direct }
    foreach ($dir in @(Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue)) {
        $path = Join-Path $dir.FullName 'metaeditor64.exe'
        if (Test-Path -LiteralPath $path -PathType Leaf) { $editors += $path }
    }
}
}
$editors = @($editors | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Sort-Object -Unique)
if ($editors.Count -eq 0) {
    Write-Host 'MetaEditor not located. MT5 > press F4; locate its metaeditor64.exe.' -ForegroundColor Yellow
    $manualEditor = Read-Host 'Paste full MetaEditor executable path'
    if (-not (Test-Path -LiteralPath $manualEditor -PathType Leaf)) { throw 'MetaEditor cannot be found.' }
    $editor = $manualEditor
} elseif ($editors.Count -gt 1) {
    Write-Host 'Multiple MetaEditors found; choose the one belonging to your MT5 terminal:'
    for ($i = 0; $i -lt $editors.Count; $i++) {
        Write-Host ('  [{0}] {1}' -f ($i + 1), $editors[$i])
    }
    $answer = Read-Host ('Choose compiler number 1-{0}' -f $editors.Count)
    $number = 0
    if (-not [int]::TryParse($answer, [ref]$number) -or $number -lt 1 -or $number -gt $editors.Count) {
        throw 'Invalid compiler choice; installation cancelled.'
    }
    $editor = $editors[$number - 1]
} else {
    $editor = $editors[0]
}

$experts = Join-Path $mql5 'Experts'
$dest = Join-Path $experts 'QTS_Gold_Robot.mq5'
$compiled = Join-Path $experts 'QTS_Gold_Robot.ex5'
$destPolicy = Join-Path $experts 'ExecutionPolicy.mqh'
$log = Join-Path $experts 'QTS_Gold_Robot.log'
$backupDir = Join-Path $experts 'QTS_Gold_Robot_Backups'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_ffff'
$backupSource = Join-Path $backupDir ($stamp + '_QTS_Gold_Robot.mq5')
$backupEX5 = Join-Path $backupDir ($stamp + '_QTS_Gold_Robot.ex5')
$backupPolicy = Join-Path $backupDir ($stamp + '_ExecutionPolicy.mqh')
$hadPolicy = Test-Path -LiteralPath $destPolicy -PathType Leaf
$hadSource = Test-Path -LiteralPath $dest -PathType Leaf
$hadEX5 = Test-Path -LiteralPath $compiled -PathType Leaf
$completed = $false

if ($hadSource -or $hadEX5 -or $hadPolicy) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    if ($hadSource) { Copy-Item -LiteralPath $dest -Destination $backupSource }
    if ($hadEX5) { Copy-Item -LiteralPath $compiled -Destination $backupEX5 }
    if ($hadPolicy) { Copy-Item -LiteralPath $destPolicy -Destination $backupPolicy }
}
Write-Host ('MT5 MQL5 location: {0}' -f $mql5)
Write-Host ('Compiler:          {0}' -f $editor)
Write-Host 'The existing robot is backed up. A failed compile triggers an automatic rollback.'

try {
    Copy-Item -LiteralPath $policy -Destination $destPolicy -Force
    Copy-Item -LiteralPath $source -Destination $dest -Force
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash) {
        throw 'The installed source hash does not match the ZIP source.'
    }
    # A stale EX5 is NOT evidence that newly edited source compiled.
    if (Test-Path -LiteralPath $compiled -PathType Leaf) {
        Remove-Item -LiteralPath $compiled -Force
    }
    if (Test-Path -LiteralPath $log -PathType Leaf) {
        Remove-Item -LiteralPath $log -Force
    }
    Write-Host 'Compiling in MetaEditor (must report ZERO errors and ZERO warnings)...'
    $arguments = '/compile:"{0}" /include:"{1}" /log' -f $dest, $mql5
    $compileStartedUtc = (Get-Date).ToUniversalTime()
    $proc = Start-Process -FilePath $editor -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if (-not (Test-Path -LiteralPath $log -PathType Leaf)) {
        throw 'MetaEditor did not create its compilation log. Refusing unverified install.'
    }
    $logText = Get-Content -LiteralPath $log -Raw
    Write-Host '--- Compile log ---'
    Write-Host $logText
    # MetaEditor CLI exit codes are NOT authoritative: some versions report 1
    # after a clean build. Require one unambiguous ZERO/ZERO Result line,
    # a newly generated EX5, a plausible binary size and unchanged source.
    # Never accept a warning, an error, a missing binary or a stale EX5.
    $summaries = [regex]::Matches($logText, '(?im)^\s*Result:\s*(\d+)\s+errors?\s*,\s*(\d+)\s+warnings?\b')
    if ($summaries.Count -ne 1) {
        throw 'Missing or ambiguous MetaEditor Result summary. Previous EA restored.'
    }
    $errorsCount = [int]$summaries[0].Groups[1].Value
    $warningsCount = [int]$summaries[0].Groups[2].Value
    if ($errorsCount -ne 0 -or $warningsCount -ne 0) {
        throw ('Compilation rejected: {0} errors and {1} warnings. Previous EA restored.' -f $errorsCount, $warningsCount)
    }
    if (-not (Test-Path -LiteralPath $compiled -PathType Leaf)) {
        throw 'No NEW EX5 file created by this compile. Previous EA restored.'
    }
    $binary = Get-Item -LiteralPath $compiled
    if ($binary.Length -lt 1000) {
        throw 'Generated EX5 file is unexpectedly small. Previous EA restored.'
    }
    if ($binary.LastWriteTimeUtc -lt $compileStartedUtc.AddSeconds(-2)) {
        throw 'The EX5 is older than the current compile attempt. Previous EA restored.'
    }
    if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -ne $actualHash) {
        throw 'The source changed during compilation; EX5 cannot be trusted. Previous EA restored.'
    }
    if ((Get-FileHash -LiteralPath $destPolicy -Algorithm SHA256).Hash -ne $policyHash) {
        throw 'Execution policy changed during compilation.'
    }
    # Verified anomalous exit code 1 is allowed ONLY after every compile
    # invariant above passed. Unexpected exit codes still fail closed.
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 1) {
        throw ('MetaEditor returned unexpected exit code {0}. Previous EA restored.' -f $proc.ExitCode)
    }
    if ($proc.ExitCode -eq 1) {
        Write-Host 'MetaEditor returned exit code 1, but the clean log and newly compiled EX5 are verified; accepting this build.' -ForegroundColor Yellow
    }
    $completed = $true
    Write-Host 'SUCCESS: QTS GOLD ROBOT development build compiled and installed.' -ForegroundColor Green
    Write-Host ('EX5 path: {0}' -f $compiled)
    Write-Host ('EX5 SHA-256: {0}' -f (Get-FileHash -LiteralPath $compiled -Algorithm SHA256).Hash)
    Write-Host 'MT5: Navigator > Expert Advisors > Refresh > QTS_Gold_Robot'
    Write-Host 'Attach to an XAUUSD@ M15 DEMO chart; defaults are OBSERVE ONLY.'
    Write-Host 'Strategy Tester research uses EnableDemoOrders=true. DEMO entries remain evidence-gated.'
    Write-Host 'No validated trading advantage; real-money trading is refused.'
} finally {
    if (-not $completed) {
        if ($hadPolicy -and (Test-Path -LiteralPath $backupPolicy -PathType Leaf)) {
            Copy-Item -LiteralPath $backupPolicy -Destination $destPolicy -Force
        } elseif (Test-Path -LiteralPath $destPolicy -PathType Leaf) {
            Remove-Item -LiteralPath $destPolicy -Force
        }
        Write-Host 'INSTALL FAILED; restoring the previous EA source and EX5, if any.' -ForegroundColor Yellow
        if ($hadSource -and (Test-Path -LiteralPath $backupSource -PathType Leaf)) {
            Copy-Item -LiteralPath $backupSource -Destination $dest -Force
        } elseif (Test-Path -LiteralPath $dest -PathType Leaf) {
            Remove-Item -LiteralPath $dest -Force
        }
        if ($hadEX5 -and (Test-Path -LiteralPath $backupEX5 -PathType Leaf)) {
            Copy-Item -LiteralPath $backupEX5 -Destination $compiled -Force
        } elseif (Test-Path -LiteralPath $compiled -PathType Leaf) {
            Remove-Item -LiteralPath $compiled -Force
        }
    }
}
