# QTS Gold Broker Preflight - read-only diagnostic installer
# Does not log in, submit trades, or change account settings.
[CmdletBinding()]
param([string]$TerminalDataFolder="", [string]$MetaEditorPath="")
$ErrorActionPreference='Stop'
$goldRoot=Split-Path -Parent $PSScriptRoot
$source=Join-Path $goldRoot 'research\QTS_Broker_Preflight.mq5'
if(-not (Test-Path -LiteralPath $source -PathType Leaf)){throw 'Missing preflight source; update the gold_robot folder.'}
# Match the same signed-by-manifest source integrity gate as the Expert Advisor.
$manifestPath=Join-Path $goldRoot 'docs\SOURCE_CHECKSUMS.json'
if(-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)){throw 'Missing broker preflight source manifest.'}
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
$rows=@($manifest.sha256_files|Where-Object{$_.path -eq 'research/QTS_Broker_Preflight.mq5'})
if($rows.Count -ne 1){throw 'Missing or duplicate preflight source manifest entry.'}
$sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
if($sourceHash -ne ([string]$rows[0].sha256)){
  throw 'Preflight source does not match canonical main manifest. Installation refused.'
}

function Resolve-Mql5([string]$candidate) {
  if([string]::IsNullOrWhiteSpace($candidate)){return $null}
  foreach($path in @($candidate,(Join-Path $candidate 'MQL5'))) {
    if((Test-Path -LiteralPath (Join-Path $path 'Scripts') -PathType Container) -and
       (Test-Path -LiteralPath (Join-Path $path 'Experts') -PathType Container) -and
       (Test-Path -LiteralPath (Join-Path $path 'Include') -PathType Container)){
       return (Resolve-Path -LiteralPath $path).Path
    }
  }
  return $null
}
$roots=@()
if($TerminalDataFolder) {
  $mql5=Resolve-Mql5 $TerminalDataFolder
  if(-not $mql5){throw 'Specified MT5 folder is not valid.'}
  $roots=@($mql5)
}else{
  $root=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
  if(Test-Path -LiteralPath $root -PathType Container){
    foreach($dir in (Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)){
      $found=Resolve-Mql5 $dir.FullName
      if($found){$roots+=,$found}
    }
  }
}
$roots=@($roots|Sort-Object -Unique)
if($roots.Count -eq 0){
  Write-Host 'In MT5, choose File > Open Data Folder, then copy its path.' -ForegroundColor Yellow
  $mql5=Resolve-Mql5 (Read-Host 'Paste your MT5 Data Folder')
  if(-not $mql5){throw 'No valid MT5 folder selected.'}
}elseif($roots.Count -eq 1){$mql5=$roots[0]}
else{
  Write-Host 'Choose your WMMarkets MT5 terminal folder:' -ForegroundColor Yellow
  for($i=0;$i -lt $roots.Count;$i++){Write-Host ('[{0}] {1}' -f ($i+1),$roots[$i])}
  $n=0;$answer=Read-Host ('Choose number 1-{0}' -f $roots.Count)
  if(-not [int]::TryParse($answer,[ref]$n) -or $n -lt 1 -or $n -gt $roots.Count){throw 'Invalid MT5 selection.'}
  $mql5=$roots[$n-1]
}
$editors=@()
if($MetaEditorPath){$editors=@($MetaEditorPath)}
else{
  foreach($base in @($env:ProgramFiles,[Environment]::GetEnvironmentVariable("ProgramFiles(x86)"),$env:LOCALAPPDATA)){
    if(-not $base -or -not (Test-Path -LiteralPath $base -PathType Container)){continue}
    $direct=Join-Path $base 'MetaTrader 5\metaeditor64.exe'
    if(Test-Path -LiteralPath $direct -PathType Leaf){$editors+=,$direct}
    foreach($dir in (Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue)){
      $candidate=Join-Path $dir.FullName 'metaeditor64.exe'
      if(Test-Path -LiteralPath $candidate -PathType Leaf){$editors+=,$candidate}
    }
  }
}
$editors=@($editors|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}|Sort-Object -Unique)
if($editors.Count -eq 0){
  Write-Host 'Press F4 from WMMarkets MT5 to locate metaeditor64.exe' -ForegroundColor Yellow
  $editor=Read-Host 'Paste full path to metaeditor64.exe'
  if(-not (Test-Path -LiteralPath $editor -PathType Leaf)){throw 'MetaEditor not found.'}
}elseif($editors.Count -eq 1){$editor=$editors[0]}
else{
  Write-Host 'Choose the MetaEditor belonging to your WMMarkets terminal:'
  for($i=0;$i -lt $editors.Count;$i++){Write-Host ('[{0}] {1}' -f ($i+1),$editors[$i])}
  $n=0;$answer=Read-Host ('Choose number 1-{0}' -f $editors.Count)
  if(-not [int]::TryParse($answer,[ref]$n) -or $n -lt 1 -or $n -gt $editors.Count){throw 'Invalid compiler selection.'}
  $editor=$editors[$n-1]
}
$dir=Join-Path $mql5 'Scripts'
$target=Join-Path $dir 'QTS_Broker_Preflight.mq5'
$binary=Join-Path $dir 'QTS_Broker_Preflight.ex5'
$log=Join-Path $dir 'QTS_Broker_Preflight.log'
$backupDir=Join-Path $dir 'QTS_Preflight_Backups'
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss_ffff'
$hadSource=Test-Path -LiteralPath $target -PathType Leaf
$hadBinary=Test-Path -LiteralPath $binary -PathType Leaf
$priorSource=Join-Path $backupDir ($stamp+'_preflight.mq5')
$priorBinary=Join-Path $backupDir ($stamp+'_preflight.ex5')
if($hadSource -or $hadBinary){
  New-Item -ItemType Directory -Path $backupDir -Force|Out-Null
  if($hadSource){Copy-Item -LiteralPath $target -Destination $priorSource}
  if($hadBinary){Copy-Item -LiteralPath $binary -Destination $priorBinary}
}
$done=$false
Write-Host ('MT5 Scripts folder: {0}' -f $dir)
try{
  Copy-Item -LiteralPath $source -Destination $target -Force
  $sha=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $sha){throw 'Copied script checksum mismatch.'}
  if(Test-Path -LiteralPath $binary -PathType Leaf){Remove-Item -LiteralPath $binary -Force}
  if(Test-Path -LiteralPath $log -PathType Leaf){Remove-Item -LiteralPath $log -Force}
  $startedUtc=(Get-Date).ToUniversalTime()
  $argsText='/compile:"{0}" /include:"{1}" /log' -f $target,$mql5
  $proc=Start-Process -FilePath $editor -ArgumentList $argsText -WindowStyle Hidden -Wait -PassThru
  if(-not (Test-Path -LiteralPath $log -PathType Leaf)){throw 'MetaEditor log was not generated.'}
  $logText=Get-Content -LiteralPath $log -Raw
  Write-Host $logText
  $summaries=[regex]::Matches($logText,'(?im)^\s*Result:\s*(\d+)\s+errors?\s*,\s*(\d+)\s+warnings?\b')
  if($summaries.Count -ne 1){throw 'Missing or ambiguous MetaEditor result.'}
  if([int]$summaries[0].Groups[1].Value -ne 0 -or [int]$summaries[0].Groups[2].Value -ne 0){throw 'Compilation errors/warnings.'}
  if(-not (Test-Path -LiteralPath $binary -PathType Leaf)){throw 'No new EX5 generated.'}
  $item=Get-Item -LiteralPath $binary
  if($item.Length -lt 1000 -or $item.LastWriteTimeUtc -lt $startedUtc.AddSeconds(-2)){throw 'Compiled EX5 is stale or too small.'}
  if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $sha){throw 'Source changed during compile.'}
  if($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 1){throw 'Unexpected MetaEditor exit code.'}
  $done=$true
  Write-Host 'SUCCESS: Broker Preflight compiled and installed (READ ONLY).' -ForegroundColor Green
  Write-Host 'MT5 > XAUUSD@ chart > Navigator > Scripts > Refresh > QTS_Broker_Preflight'
  Write-Host 'Double click the script, confirm settings (3000 USD; 0.25% risk).'
  Write-Host ('Read-only report: {0}' -f (Join-Path $mql5 'Files\QTS_Broker_Preflight.csv'))
  Write-Host 'No trades are submitted. LIVE EA remains locked.'
}finally{
  if(-not $done){
    Write-Host 'Installation aborted. Restoring any previous script.' -ForegroundColor Yellow
    if($hadSource){Copy-Item -LiteralPath $priorSource -Destination $target -Force}
    elseif(Test-Path -LiteralPath $target -PathType Leaf){Remove-Item -LiteralPath $target -Force}
    if($hadBinary){Copy-Item -LiteralPath $priorBinary -Destination $binary -Force}
    elseif(Test-Path -LiteralPath $binary -PathType Leaf){Remove-Item -LiteralPath $binary -Force}
  }
}
