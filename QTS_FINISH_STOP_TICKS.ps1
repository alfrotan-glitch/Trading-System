# QTS: confirm bounded MT5 quote export and run read-only post-SL analysis.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$runs=Join-Path $repo 'gold_robot\reports_local\auto_runs'
$run=@(Get-ChildItem -LiteralPath $runs -Directory | Where-Object {
    Test-Path -LiteralPath (Join-Path $_.FullName 'QTS_STOP_EXPORT_PATH.txt')
} | Sort-Object Name -Descending | Select-Object -First 1)
if($run.Count -ne 1){throw 'No prepared MT5 quote export found. Run QTS_PREPARE_STOP_TICKS.bat.'}
$dir=(Get-Content -LiteralPath (Join-Path $run[0].FullName 'QTS_STOP_EXPORT_PATH.txt') -Raw).Trim()
if(-not (Test-Path -LiteralPath $dir -PathType Container)){
    throw 'MT5 has not written the quote folder. In MT5 run QTS_Export_Stop_Ticks first.'
}
$statusFile=Join-Path $dir 'export_status.csv'
if(-not (Test-Path -LiteralPath $statusFile -PathType Leaf)){
    throw 'No export_status.csv. Run script from MT5, then check the Experts tab.'
}
$status=@(Import-Csv -LiteralPath $statusFile)
if($status.Count -ne 1 -or $status[0].state -ne 'COMPLETE' -or
   [int]$status[0].failures -ne 0 -or [long]$status[0].quotes -le 0){
    throw 'MT5 export incomplete: inspect the script Experts log and original tick availability.'
}
$quotes=@(Get-ChildItem -LiteralPath $dir -File -Filter 'ticks_*.csv')
if($quotes.Count -ne [int]$status[0].windows -or $quotes.Count -eq 0){
    throw 'Missing native tick CSV files: exported count differs from the run manifest.'
}
$env:QTS_BROKER_TICKS_DIR=$dir
$env:QTS_NO_PAUSE='1'
Write-Host ('Verifying '+$quotes.Count+' native tick windows against original SL events...')
& $env:ComSpec /d /c ('call "'+(Join-Path $repo 'QTS_POST_STOP_REVIEW.bat')+'"')
if($LASTEXITCODE -ne 0){throw 'Post-stop replay audit failed. No trading orders submitted.'}
$output=Join-Path $run[0].FullName 'post_stop_review'
$json=Join-Path $output 'QTS_POST_STOP_REAL_TICK_REVIEW.json'
if(-not (Test-Path -LiteralPath $json -PathType Leaf)){
    throw 'Quote-path replay result JSON is missing.'
}
$zip=Join-Path $run[0].FullName 'QTS_POST_STOP_REVIEW.zip'
$include=@($json,(Join-Path $output 'QTS_STOP_INPUT_AUDIT.json'),
          (Join-Path $output 'QTS_STOP_CASES.csv'),$statusFile)
Compress-Archive -LiteralPath $include -DestinationPath $zip -Force
Write-Host ('SUCCESS: '+$json)
Write-Host ('SEND THIS ZIP FOR REVIEW: '+$zip)
Write-Host 'Read only; never approves live trading or proves an edge.'
