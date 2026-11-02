# QTS Gold: one-click retrospective dual ATR audit. READ ONLY.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$gold=Join-Path $repo 'gold_robot'
$tool=Join-Path $gold 'research\dual_atr_market_audit.py'
$root=Join-Path $gold 'reports_local\dual_research'
if(-not (Test-Path -LiteralPath $tool)){throw 'Dual ATR tool missing: update main.'}
$recent=@(Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop | Where-Object {
    (Test-Path -LiteralPath (Join-Path $_.FullName 'DUAL_BOTH\QTS_TRADE_BY_TRADE.json')) -and
    (Test-Path -LiteralPath (Join-Path $_.FullName 'DUAL_DIRECTIONAL\QTS_TRADE_BY_TRADE.json')) -and
    (Test-Path -LiteralPath (Join-Path $_.FullName 'DUAL_BOTH\OPEN_RESULTS.json')) -and
    (Test-Path -LiteralPath (Join-Path $_.FullName 'DUAL_DIRECTIONAL\OPEN_RESULTS.json'))
} | Sort-Object Name -Descending)
if($recent.Count -eq 0){throw 'No completed native dual evidence. Run option 9 first.'}
$run=$recent[0]
$venv=Join-Path $gold 'reports_local\mt5_quote_bridge_env'
$python=Join-Path $venv 'Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python)){
    if(-not (Get-Command py.exe -ErrorAction SilentlyContinue)){throw 'Python 3 missing'}
    & py -3 -m venv $venv
    if($LASTEXITCODE -ne 0){throw 'Isolated quote reader could not be prepared'}
}
& $python -c 'import MetaTrader5'
if($LASTEXITCODE -ne 0){
    & $python -m pip install --no-input --only-binary=:all: MetaTrader5
    if($LASTEXITCODE -ne 0){throw 'Official MetaTrader5 quote module not installed'}
}
$rootTerm=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
$terminals=@(Get-ChildItem -LiteralPath $rootTerm -Directory -ErrorAction Stop | Where-Object {
    Test-Path -LiteralPath (Join-Path $_.FullName 'MQL5\Experts\QTS_Gold_Robot.ex5')
})
if($terminals.Count -ne 1){throw 'Exactly one QTS MT5 terminal must be identified; no guessing'}
$terminal=$terminals[0].FullName
$origin=Join-Path $terminal 'origin.txt'
if(-not (Test-Path -LiteralPath $origin)){throw 'MT5 terminal origin missing'}
$loc=@(Get-Content -LiteralPath $origin | Where-Object {$_.Trim()} | Select-Object -First 1)
if($loc.Count -ne 1){throw 'Missing MT5 terminal executable location'}
$path=$loc[0].Trim().Trim('"')
$exe=if($path -match '\.exe$'){$path}else{Join-Path $path 'terminal64.exe'}
if(-not (Test-Path -LiteralPath $exe -PathType Leaf)){throw 'Could not verify terminal64.exe'}
$out=Join-Path $run.FullName 'atr_market_research'
New-Item -ItemType Directory -Path $out -Force | Out-Null
Write-Host ('Reading broker historical bars, tick quotes and ATR for '+$run.Name)
& $python $tool --both (Join-Path $run.FullName 'DUAL_BOTH') --directional (Join-Path $run.FullName 'DUAL_DIRECTIONAL') --out $out --terminal-data $terminal --terminal-path $exe
$code=$LASTEXITCODE
$html=Join-Path $out 'QTS_DUAL_ATR_REVIEW.html'
$zip=Join-Path $out 'QTS_DUAL_ATR_REVIEW.zip'
if(Test-Path -LiteralPath $html){try {Start-Process -FilePath $html} catch {Write-Warning 'Open the HTML report manually'}}
if(Test-Path -LiteralPath $zip){explorer.exe /select,"$zip"}
Write-Host ('REPORT ZIP: '+$zip)
if($code -ne 0){throw 'Historical broker evidence incomplete. Read-only review NO_GO; no orders sent.'}
Write-Host 'Review complete. This is not trade permission. LIVE LOCKED.'
