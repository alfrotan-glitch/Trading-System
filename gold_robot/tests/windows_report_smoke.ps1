# Windows-only deterministic smoke test of the local HTML/JSON reporter.
# Fake terminal + fake broker CSV only. No MetaTrader, API key or orders.
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$repo=Split-Path -Parent $gold
$runner=Join-Path $gold 'research\MakeWindowsReport.ps1'
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('qts-win-smoke-'+[guid]::NewGuid().ToString('N'))
$mql5=Join-Path $fixture 'MQL5'
$exp=Join-Path $mql5 'Experts'
$scripts=Join-Path $mql5 'Scripts'
$files=Join-Path $mql5 'Files'
$output=Join-Path $fixture 'output'
New-Item -ItemType Directory -Path $exp,$scripts,$files,$output -Force | Out-Null
try{
    $pairs=@(
        @('QTS_Gold_Robot.mq5','QTS_Gold_Robot.mq5'),
        @('ExecutionPolicy.mqh','ExecutionPolicy.mqh'),
        @('StructureResearch.mqh','StructureResearch.mqh')
    )
    foreach($pair in $pairs){
        Copy-Item -LiteralPath (Join-Path $gold ('mt5_robot\'+$pair[0])) -Destination (Join-Path $exp $pair[1])
    }
    Copy-Item -LiteralPath (Join-Path $gold 'research\QTS_Broker_Preflight.mq5') -Destination (Join-Path $scripts 'QTS_Broker_Preflight.mq5')
    [IO.File]::WriteAllText((Join-Path $scripts 'QTS_Broker_Preflight.ex5'), ('V'*2200))
    [IO.File]::WriteAllText((Join-Path $scripts 'QTS_Broker_Preflight.log'), 'Result: 0 errors, 0 warnings, 600 ms elapsed')
    [IO.File]::WriteAllText((Join-Path $exp 'QTS_Gold_Robot.ex5'), ('Z'*2200))
    [IO.File]::WriteAllText((Join-Path $exp 'QTS_Gold_Robot.log'), "Result: 0 errors, 0 warnings, 800 ms elapsed")
    $now=(Get-Date).ToUniversalTime()
    foreach($p in @('QTS_Gold_Robot.ex5','QTS_Gold_Robot.log')){
        (Get-Item -LiteralPath (Join-Path $exp $p)).LastWriteTimeUtc=$now
    }
    foreach($p in @('QTS_Broker_Preflight.ex5','QTS_Broker_Preflight.log')){
        (Get-Item -LiteralPath (Join-Path $scripts $p)).LastWriteTimeUtc=$now
    }
    $csv=Join-Path $files 'QTS_Broker_Preflight.csv'
    $rows=@(
        'metric;value',
        'MODE;READ_ONLY_NO_ORDERS',
        'BrokerServer;<script>alert(1)</script>',
        'Symbol;XAUUSD@',
        'OrdersSubmitted;0',
        'Verdict;BLOCKED_MIN_LOT_EXCEEDS_MODELED_RISK_OR_MARGIN'
    )
    [IO.File]::WriteAllLines($csv,$rows)
    & $runner -DataFolder $mql5 -OutputDirectory $output -NoOpen
    $a=Get-ChildItem -LiteralPath $output -Filter '*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if(-not $a){throw 'JSON report missing'}
    $first=Get-Content -LiteralPath $a.FullName -Raw | ConvertFrom-Json
    if($first.source_status -ne 'SOURCE_HASH_OK'){throw "Source manifest failed: $($first.source_status)"}
    if($first.install_status -ne 'COMPILED_VERIFIED'){throw "Compiled fixture invalid: $($first.install_status)"}
    if($first.preflight_install_status -ne 'COMPILED_VERIFIED'){
        throw "Broker Preflight source/EX5 is not verified: $($first.preflight_install_status)"
    }
    if($first.preflight_status -notlike 'BLOCKED*'){throw 'Risk BLOCK not shown'}
    if($first.readiness -ne 'ACTION_REQUIRED'){throw 'Blocked broker was marked ready'}
    $report=Get-ChildItem -LiteralPath $output -Filter '*.html' | Select-Object -First 1
    $html=Get-Content -LiteralPath $report.FullName -Raw
    if($html.Contains('<script>alert(1)</script>')){throw 'Broker content was not escaped'}
    if(-not $html.Contains('&lt;script&gt;')){throw 'Missing encoded broker data'}
    Write-Host 'Blocked, read-only case: PASS'

    (Get-Item -LiteralPath $csv).LastWriteTimeUtc=$now.AddMinutes(-10)
    & $runner -DataFolder $mql5 -OutputDirectory $output -NoOpen
    $staleJson=Get-ChildItem -LiteralPath $output -Filter '*.json' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $stale=Get-Content -LiteralPath $staleJson.FullName -Raw | ConvertFrom-Json
    if($stale.preflight_status -ne 'STALE_AUDIT' -or $stale.readiness -ne 'ACTION_REQUIRED'){
        throw 'Old broker audit was not rejected with actionable stale status'
    }
    if($stale.preflight_detail -notlike '*predates*'){
        throw 'Old broker audit did not include a meaningful diagnostic'
    }
    Write-Host 'Old broker CSV: STALE_AUDIT, no trading permission: PASS'

    [IO.File]::WriteAllLines($csv,@(
        'metric;value',
        'MODE;READ_ONLY_NO_ORDERS',
        'BrokerServer;WMMarkets-Demo',
        'Symbol;XAUUSD@',
        'OrdersSubmitted;0',
        'Verdict;ENGINEERING_PRECHECK_OK_NOT_TRADE_PERMISSION'
    ))
    & $runner -DataFolder $mql5 -OutputDirectory $output -NoOpen
    $a=Get-ChildItem -LiteralPath $output -Filter '*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $data=Get-Content -LiteralPath $a.FullName -Raw | ConvertFrom-Json
    if($data.preflight_status -ne 'ENGINEERING_PRECHECK_OK_NOT_TRADE_PERMISSION'){
        throw "Unexpected broker status: $($data.preflight_status)"
    }
    if($data.readiness -ne 'READY_FOR_TESTER_ONLY'){throw "Expected tester-only: $($data.readiness)"}
    if($data.live -ne 'LOCKED' -or $data.validated_profitable_edge){
        throw 'Trading safety was misrepresented'
    }
    Write-Host 'All verified, tester-only case: PASS'

    # If a different/older preflight source is substituted, a green CSV cannot certify readiness.
    [IO.File]::AppendAllText((Join-Path $scripts 'QTS_Broker_Preflight.mq5'),'// TAMPERED')
    & $runner -DataFolder $mql5 -OutputDirectory $output -NoOpen
    $testJson=Get-ChildItem -LiteralPath $output -Filter '*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $tampered=Get-Content -LiteralPath $testJson.FullName -Raw | ConvertFrom-Json
    if($tampered.readiness -ne 'ACTION_REQUIRED' -or
       $tampered.preflight_install_status -eq 'COMPILED_VERIFIED'){
        throw 'A mismatched installed broker diagnostic was mistakenly marked READY'
    }
    Write-Host 'Preflight tampering rejection: PASS'

}finally{
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
