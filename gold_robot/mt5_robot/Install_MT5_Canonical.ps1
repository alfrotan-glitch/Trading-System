# QTS Gold MT5 single-target installer orchestration.
# One terminal and one compiler are selected and reused for BOTH installs.
# No broker login, no Algo Trading changes, and no orders in this script.
[CmdletBinding()]
param(
    [string]$TerminalDataFolder="",
    [string]$MetaEditorPath="",
    [switch]$ValidateOnly
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$robotScript=Join-Path $PSScriptRoot 'Install_QTS_Gold_Robot.ps1'
$brokerScript=Join-Path $PSScriptRoot 'Install_Broker_Preflight.ps1'
foreach($file in @($robotScript,$brokerScript,
                  (Join-Path $root 'mt5_robot\QTS_Gold_Robot.mq5'),
                  (Join-Path $root 'research\QTS_Broker_Preflight.mq5'),
                  (Join-Path $root 'docs\SOURCE_CHECKSUMS.json'))){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){
        throw "Missing canonical MT5 installer prerequisite: $file"
    }
}
function ResolveMql5([string]$candidate){
    if([string]::IsNullOrWhiteSpace($candidate)){return $null}
    foreach($path in @($candidate,(Join-Path $candidate 'MQL5'))){
        if((Test-Path -LiteralPath (Join-Path $path 'Experts') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $path 'Scripts') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $path 'Include') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $path 'Indicators') -PathType Container)){
           return (Resolve-Path -LiteralPath $path).Path
        }
    }
    return $null
}
if($TerminalDataFolder){
    $mql5=ResolveMql5 $TerminalDataFolder
    if(-not $mql5){throw 'Specified MT5 data folder is incomplete (requires Experts, Scripts, Include, Indicators).'}
}else{
    $options=@()
    $directory=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if(Test-Path -LiteralPath $directory -PathType Container){
        foreach($dir in (Get-ChildItem -LiteralPath $directory -Directory -ErrorAction SilentlyContinue)){
            $candidate=ResolveMql5 $dir.FullName
            if($candidate){$options+=,$candidate}
        }
    }
    $options=@($options|Sort-Object -Unique)
    if($options.Count -eq 1){$mql5=$options[0]}
    elseif($options.Count -eq 0){
        if($ValidateOnly){throw 'No MT5 terminal found; noninteractive validation needs -TerminalDataFolder.'}
        Write-Host 'In WMMarkets MT5: File > Open Data Folder. Copy its exact path.' -ForegroundColor Yellow
        $mql5=ResolveMql5 (Read-Host 'MT5 Data Folder')
        if(-not $mql5){throw 'No valid MT5 terminal selected.'}
    }else{
        if($ValidateOnly){throw 'Multiple MT5 terminals found; specify -TerminalDataFolder.'}
        Write-Host 'Choose the WMMarkets MT5 Data Folder. This ONE target is used for BOTH installers:'
        for($i=0;$i -lt $options.Count;$i++){
            Write-Host ('[{0}] {1}' -f ($i+1),$options[$i])
        }
        $number=0
        $choice=Read-Host ('Choose number 1-{0}' -f $options.Count)
        if(-not [int]::TryParse($choice,[ref]$number) -or $number -lt 1 -or $number -gt $options.Count){
            throw 'MT5 terminal selection cancelled.'
        }
        $mql5=$options[$number-1]
    }
}
if($MetaEditorPath){
    $editor=(Resolve-Path -LiteralPath $MetaEditorPath -ErrorAction Stop).Path
    if(-not (Test-Path -LiteralPath $editor -PathType Leaf)){throw 'Specified MetaEditor is not a file.'}
}else{
    $editors=@()
    foreach($base in @($env:ProgramFiles,[Environment]::GetEnvironmentVariable('ProgramFiles(x86)'),$env:LOCALAPPDATA)){
        if(-not $base -or -not (Test-Path -LiteralPath $base -PathType Container)){continue}
        $direct=Join-Path $base 'MetaTrader 5\metaeditor64.exe'
        if(Test-Path -LiteralPath $direct -PathType Leaf){$editors+=,$direct}
        foreach($dir in (Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue)){
            $candidate=Join-Path $dir.FullName 'metaeditor64.exe'
            if(Test-Path -LiteralPath $candidate -PathType Leaf){$editors+=,$candidate}
        }
    }
    $editors=@($editors|Sort-Object -Unique)
    if($editors.Count -eq 1){$editor=$editors[0]}
    elseif($editors.Count -eq 0){
        if($ValidateOnly){throw 'No MetaEditor found. Pass -MetaEditorPath.'}
        Write-Host 'In your WMMarkets MT5 press F4 to locate metaeditor64.exe.' -ForegroundColor Yellow
        $path=Read-Host 'Full path to metaeditor64.exe'
        if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw 'MetaEditor was not found.'}
        $editor=(Resolve-Path -LiteralPath $path).Path
    }else{
        if($ValidateOnly){throw 'Multiple MetaEditors found. Pass -MetaEditorPath.'}
        Write-Host 'Choose ONE MetaEditor for BOTH EA and preflight compiles:'
        for($i=0;$i -lt $editors.Count;$i++){
            Write-Host ('[{0}] {1}' -f ($i+1),$editors[$i])
        }
        $number=0
        $choice=Read-Host ('Choose compiler number 1-{0}' -f $editors.Count)
        if(-not [int]::TryParse($choice,[ref]$number) -or $number -lt 1 -or $number -gt $editors.Count){
            throw 'MetaEditor selection cancelled.'
        }
        $editor=$editors[$number-1]
    }
}
if(-not $editor -or -not $mql5){throw 'A single verified MT5 target and compiler are mandatory.'}
Write-Host ('CANONICAL MT5 TARGET: '+$mql5)
Write-Host ('CANONICAL METAEDITOR: '+$editor)
if($ValidateOnly){
    Write-Host 'SINGLE_TARGET_PATH_VALIDATED: both installers will receive these exact paths; nothing installed.'
    exit 0
}
$windowsPowerShell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if(-not (Test-Path -LiteralPath $windowsPowerShell -PathType Leaf)){
    throw 'Windows PowerShell interpreter is unavailable.'
}
function RunInstaller([string]$path,[string]$label){
    # Paths with spaces are passed as quoted single arguments to both child scripts.
    $args='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -TerminalDataFolder "{1}" -MetaEditorPath "{2}"' -f
         $path,$mql5,$editor
    $proc=Start-Process -FilePath $windowsPowerShell -ArgumentList $args -Wait -PassThru -NoNewWindow
    if($proc.ExitCode -ne 0){
        throw ('{0} failed with exit code {1}. The other installer is not retried.' -f $label,$proc.ExitCode)
    }
}
Write-Host 'STEP 1/2: source-check, back up, install and compile the QTS Gold EA.'
RunInstaller $robotScript 'Gold Expert Advisor'
Write-Host 'STEP 2/2: install/compile the read-only broker preflight in the SAME terminal.'
RunInstaller $brokerScript 'Broker Preflight'
$installedEa=Join-Path $mql5 'Experts\QTS_Gold_Robot.ex5'
$installedScript=Join-Path $mql5 'Scripts\QTS_Broker_Preflight.ex5'
if(-not (Test-Path -LiteralPath $installedEa -PathType Leaf) -or
   -not (Test-Path -LiteralPath $installedScript -PathType Leaf)){
    throw 'Both current EX5 files are required in the same verified terminal; install incomplete.'
}
Write-Host 'SINGLE_TARGET_INSTALL_COMPLETE: EA + READ-ONLY BROKER PREFLIGHT in the SAME MT5 Data Folder.' -ForegroundColor Green
Write-Host 'LIVE remains locked; Algo Trading was not enabled; no orders were submitted.'
