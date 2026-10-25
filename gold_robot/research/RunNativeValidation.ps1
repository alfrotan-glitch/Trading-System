[CmdletBinding()]
param([int]$TimeoutSeconds=1800, [string]$DemoLogin="")
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$terminal=(Resolve-Path (Join-Path $root 'runtime\terminal\terminal64.exe')).Path
$experts=Join-Path $root 'runtime\terminal\MQL5\Experts'
$report=Join-Path $root 'runtime\terminal\native_development_2025.htm'
$config=Join-Path $env:TEMP ('qts-native-'+[guid]::NewGuid().ToString('N')+'.ini')
if(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $terminal }) { throw 'Close the isolated research terminal before running the test.' }
foreach($f in @('QTS_Gold_Robot.ex5','ExecutionPolicy.mqh')) { if(-not (Test-Path (Join-Path $experts $f))) { throw "Missing compiled EA dependency: $f" } }
$configText="[Common]`r`nServer=WMMarkets-Demo`r`nKeepPrivate=1`r`n[Experts]`r`nEnabled=0`r`nAllowLiveTrading=0`r`nAllowDllImport=0`r`n[Tester]`r`nExpert=QTS_Gold_Robot.ex5`r`nSymbol=XAUUSD_QTS_AUDIT`r`nPeriod=M15`r`nModel=4`r`nExecutionMode=100`r`nOptimization=0`r`nFromDate=2025.01.01`r`nToDate=2025.07.01`r`nDeposit=10000`r`nCurrency=USD`r`nLeverage=1:100`r`nUseLocal=1`r`nUseRemote=0`r`nUseCloud=0`r`nVisual=0`r`nReport=native_development_2025`r`nReplaceReport=1`r`n[TesterInputs]`r`nEnableDemoOrders=true`r`n"
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
 Copy-Item $report (Join-Path $root 'evidence\native\native_development_2025.htm') -Force
 Write-Host 'Native tester finished. Check its trade count; a completed test does not establish edge.'
}
finally {
 if($proc) { $proc.Refresh(); $own=Get-Process -Id $proc.Id -ErrorAction SilentlyContinue; if($own -and $own.Path -eq $terminal) { Stop-Process -Id $proc.Id -Force } }
 Remove-Item -LiteralPath $config -Force -ErrorAction SilentlyContinue
}
