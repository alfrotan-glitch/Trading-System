# QTS: prepare ONLY recorded post-stop quote windows in the canonical local MT5.
# Read-only; never connects to an account or submits orders.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$runs=Join-Path $repo 'gold_robot\reports_local\auto_runs'
$run=@(Get-ChildItem -LiteralPath $runs -Directory | Where-Object {
    (Test-Path -LiteralPath (Join-Path $_.FullName 'QTS_SHARE_RESULTS.zip')) -and
    (Test-Path -LiteralPath (Join-Path $_.FullName 'post_stop_review\QTS_STOP_CASES.csv'))
} | Sort-Object Name -Descending | Select-Object -First 1)
if($run.Count -ne 1){throw 'No native run with stop cases. Run QTS_POST_STOP_REVIEW.bat first.'}
$tag=$run[0].Name
if($tag -notmatch '^\d{8}_\d{6}$'){throw 'Unexpected native tester run name.'}
$dataRoot=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
$terminals=@(Get-ChildItem -LiteralPath $dataRoot -Directory | Where-Object {
    Test-Path -LiteralPath (Join-Path $_.FullName 'MQL5\Experts\QTS_Gold_Robot.ex5')
})
if($terminals.Count -ne 1){
    throw 'Expected exactly one canonical MT5 terminal with the QTS robot. Check MT5 installation.'
}
$files=Join-Path $terminals[0].FullName 'MQL5\Files'
$scripts=Join-Path $terminals[0].FullName 'MQL5\Scripts'
$quoteDir=Join-Path $files ('QTS_STOP_TICKS_'+$tag)
if(Test-Path -LiteralPath (Join-Path $quoteDir 'export_status.csv')){
    throw 'This run was already exported. Do not overwrite an existing quote audit.'
}
$plan=Join-Path $files 'QTS_STOP_WINDOWS.csv'
$generator=Join-Path $repo 'gold_robot\research\prepare_stop_tick_windows.py'
$cases=Join-Path $run[0].FullName 'post_stop_review\QTS_STOP_CASES.csv'
New-Item -ItemType Directory -Path $files,$scripts -Force | Out-Null
if(Get-Command py.exe -ErrorAction SilentlyContinue){
    & py.exe -3 $generator --stops $cases --output $plan --tag $tag
}else{
    if(-not (Get-Command python.exe -ErrorAction SilentlyContinue)){throw 'Python 3 is not installed.'}
    & python.exe $generator --stops $cases --output $plan --tag $tag
}
if($LASTEXITCODE -ne 0){throw 'Stop-window generation failed.'}
$expected=@(Get-Content -LiteralPath $plan | Where-Object {$_ -match '^\d+;\d+;'}).Count
if($expected -le 0){throw 'No stop quote windows in generated plan.'}
$src=Join-Path $repo 'gold_robot\research\QTS_Export_Stop_Ticks.mq5'
$dest=Join-Path $scripts 'QTS_Export_Stop_Ticks.mq5'
Copy-Item -LiteralPath $src -Destination $dest -Force
$editor='C:\Program Files\MetaTrader 5\metaeditor64.exe'
if(-not (Test-Path -LiteralPath $editor)){throw 'MetaEditor missing. Cannot compile exporter.'}
$log=Join-Path $run[0].FullName 'QTS_STOP_TICK_COMPILE.log'
$start=Get-Date
$arguments='/compile:"'+$dest+'" /log:"'+$log+'"'
$compile=Start-Process -FilePath $editor -ArgumentList $arguments -Wait -PassThru
$ex5=[IO.Path]::ChangeExtension($dest,'.ex5')
if(-not (Test-Path -LiteralPath $log) -or -not (Test-Path -LiteralPath $ex5)){
    throw 'MetaEditor did not produce both compile log and EX5. Check local MetaEditor.'
}
$logText=Get-Content -LiteralPath $log -Raw
if($logText -notmatch 'Result:\s*0 errors,\s*0 warnings' -or
   (Get-Item -LiteralPath $ex5).LastWriteTime -lt $start.AddSeconds(-2)){
    throw ('Exporter compile invalid. Inspect '+$log)
}
$pathFile=Join-Path $run[0].FullName 'QTS_STOP_EXPORT_PATH.txt'
[IO.File]::WriteAllText($pathFile,$quoteDir,([Text.UTF8Encoding]::new($false)))
Write-Host ('READY: '+$expected+' merged stop-quote windows, not six months of ticks.')
Write-Host ('MT5 script: '+$dest)
Write-Host ('Output folder: '+$quoteDir)
Write-Host 'NEXT: Open MT5 XAUUSD@ chart, Navigator > Scripts > Refresh, run QTS_Export_Stop_Ticks.'
Write-Host 'After its Experts log confirms COMPLETE, run QTS_FINISH_STOP_TICKS.bat.'
Write-Host 'LIVE LOCKED. No connected orders.'
