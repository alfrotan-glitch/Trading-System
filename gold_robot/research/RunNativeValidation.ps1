[CmdletBinding()]
param([int]$TimeoutSeconds=1800, [string]$DemoLogin="", [ValidateSet(100,200,10000)][int]$DepositUsd=200)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$terminal=(Resolve-Path (Join-Path $root 'runtime\terminal\terminal64.exe')).Path
$experts=Join-Path $root 'runtime\terminal\MQL5\Experts'
$reportName="native_replay_${DepositUsd}_2025"
$report=Join-Path $root ("runtime\terminal\$reportName.htm")
$config=Join-Path $env:TEMP ('qts-native-'+[guid]::NewGuid().ToString('N')+'.ini')
if(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $terminal }) { throw 'Close the isolated research terminal before running the test.' }
foreach($f in @('QTS_Gold_Robot.ex5','ExecutionPolicy.mqh')) { if(-not (Test-Path (Join-Path $experts $f))) { throw "Missing compiled EA dependency: $f" } }
# Reject a stale EX5 or a source/policy mismatch after an incomplete install.
$canonical=Join-Path $root 'mt5_robot'
foreach($file in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh')) {
 $expected=Join-Path $canonical $file
 $installed=Join-Path $experts $file
 if(-not (Test-Path -LiteralPath $expected -PathType Leaf) -or -not (Test-Path -LiteralPath $installed -PathType Leaf)) { throw "Missing canonical/installed source: $file" }
 if((Get-FileHash -LiteralPath $expected -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash) { throw "Installed source differs from repository: $file" }
}
$binaryTime=(Get-Item -LiteralPath (Join-Path $experts 'QTS_Gold_Robot.ex5')).LastWriteTimeUtc
foreach($file in @('QTS_Gold_Robot.mq5','ExecutionPolicy.mqh')) {
 $installed=Join-Path $experts $file
 if($binaryTime -lt (Get-Item -LiteralPath $installed).LastWriteTimeUtc.AddSeconds(-2)) { throw "Compiled EX5 predates current source: $file" }
}
$configText="[Common]`r`nServer=WMMarkets-Demo`r`nKeepPrivate=1`r`n[Experts]`r`nEnabled=0`r`nAllowLiveTrading=0`r`nAllowDllImport=0`r`n[Tester]`r`nExpert=QTS_Gold_Robot.ex5`r`nSymbol=XAUUSD_QTS_AUDIT`r`nPeriod=M15`r`nModel=4`r`nExecutionMode=100`r`nOptimization=0`r`nFromDate=2025.01.01`r`nToDate=2025.07.01`r`nDeposit=$DepositUsd`r`nCurrency=USD`r`nLeverage=1:100`r`nUseLocal=1`r`nUseRemote=0`r`nUseCloud=0`r`nVisual=0`r`nReport=$reportName`r`nReplaceReport=1`r`n[TesterInputs]`r`nEnableDemoOrders=true`r`n"
if ($DemoLogin -and $DemoLogin -notmatch '^\d{1,20}$') { throw 'DemoLogin must contain digits only.' }
if ($DemoLogin) {
 $configText=$configText.Replace("Server=WMMarkets-Demo`r`n", "Server=WMMarkets-Demo`r`nLogin=$DemoLogin`r`n")
}
Set-Content -LiteralPath $config -Value $configText -Encoding Unicode
$started=(Get-Date).ToUniversalTime(); $proc=$null
try {
 $proc=Start-Process -FilePath $terminal -ArgumentList ('/portable /config:"{0}"' -f $config) -WindowStyle Hidden -PassThru
 while(-not $proc.HasExited) {
  Start-Sleep -Seconds 30; $proc.Refresh(); Write-Host 'Native real-tick test continues...'
  if(((Get-Date).ToUniversalTime()-$started).TotalSeconds -gt $TimeoutSeconds) { throw 'Tester timed out. Inspect MT5 logs.' }
 }
 if(-not (Test-Path $report) -or (Get-Item $report).LastWriteTimeUtc -lt $started) { throw 'New native test report missing.' }
 $html=Get-Content $report -Raw -Encoding Unicode
 if($html -notmatch 'real ticks') { throw 'Tester report does not confirm real ticks.' }
 $evidenceDir=Join-Path $root 'evidence\native'
 New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
 Copy-Item -LiteralPath $report -Destination (Join-Path $evidenceDir "$reportName.htm") -Force
 Write-Host 'Native tester finished. Check its trade count; a completed test does not establish edge.'
}
finally {
 if($proc) { $proc.Refresh(); $own=Get-Process -Id $proc.Id -ErrorAction SilentlyContinue; if($own -and $own.Path -eq $terminal) { Stop-Process -Id $proc.Id -Force } }
 Remove-Item -LiteralPath $config -Force -ErrorAction SilentlyContinue
}
