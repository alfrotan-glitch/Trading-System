# QTS GOLD - one-click native post-stop investigation, READ ONLY.
# Uses the official MetaTrader5 quote API; never submits broker orders.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$gold=Join-Path $repo 'gold_robot'
$root=Join-Path $gold 'reports_local\auto_runs'
$env:PIP_DISABLE_PIP_VERSION_CHECK='1'
$env:PIP_NO_INPUT='1'

function RunPython([string]$exe,[string[]]$arguments,[string]$purpose){
    & $exe @arguments
    if($LASTEXITCODE -ne 0){throw ("FAILED: "+$purpose+" (exit "+$LASTEXITCODE+"). No orders submitted.")}
}
function LatestRun {
    if(-not (Test-Path -LiteralPath $root -PathType Container)){return $null}
    return @(Get-ChildItem -LiteralPath $root -Directory |
        Where-Object {Test-Path -LiteralPath (Join-Path $_.FullName 'QTS_SHARE_RESULTS.zip') -PathType Leaf} |
        Sort-Object Name -Descending | Select-Object -First 1)
}
Write-Host '======================================================='
Write-Host 'QTS GOLD ONE CLICK - MT5 POST-STOP RESEARCH'
Write-Host 'No real money orders. Only the recorded SL events.'
Write-Host '======================================================='

$run=@(LatestRun | Where-Object { $null -ne $_ })
if($run.Count -eq 0){
    Write-Host 'No saved four-style evidence: running the native four-style tester automatically.'
    & $env:ComSpec /d /c ('call "'+(Join-Path $repo 'QTS_FOUR_FINALISTS.bat')+'"')
    if($LASTEXITCODE -ne 0){throw 'Native four-style tester did not produce complete evidence.'}
    $run=@(LatestRun | Where-Object { $null -ne $_ })
}
if($run.Count -ne 1){throw 'No unique broker-test evidence run found.'}
$run=$run[0]
$tag=$run.Name
if($tag -notmatch '^\d{8}_\d{6}$'){throw 'Native run folder has an unexpected identity.'}
$review=Join-Path $run.FullName 'post_stop_review'
New-Item -ItemType Directory -Path $review -Force | Out-Null

# Work inside QTS-local Python venv, never install dependencies globally.
$envDir=Join-Path $gold 'reports_local\mt5_quote_bridge_env'
$python=Join-Path $envDir 'Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python)){
    Write-Host 'Preparing isolated Python MT5 quote reader automatically...'
    $boot='python.exe';$bootArgs=@()
    if(Get-Command py.exe -ErrorAction SilentlyContinue){$boot='py.exe';$bootArgs=@('-3')}
    elseif(-not (Get-Command python.exe -ErrorAction SilentlyContinue)){throw 'Python 3 is not installed.'}
    & $boot @bootArgs -m venv $envDir
    if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)){
        throw 'Python environment could not be created.'
    }
}
& $python -c "import MetaTrader5"
if($LASTEXITCODE -ne 0){
    Write-Host 'Installing official MetaTrader5 quote reader into private QTS environment...'
    RunPython -exe $python -arguments @('-m','pip','install','--no-input','--only-binary=:all:','MetaTrader5') -purpose 'MT5 data-only Python package'
}
$bundle=Join-Path $run.FullName 'QTS_SHARE_RESULTS.zip'
$cases=Join-Path $review 'QTS_STOP_CASES.csv'
$original=Join-Path $review 'QTS_STOP_INPUT_AUDIT.json'
if(-not (Test-Path -LiteralPath $cases -PathType Leaf) -or
   -not (Test-Path -LiteralPath $original -PathType Leaf)){
    RunPython -exe $python -arguments @((Join-Path $gold 'research\build_post_stop_inputs.py'),
                        '--bundle',$bundle,'--out',$review) -purpose 'original broker stop-case extraction'
}
if(-not (Test-Path -LiteralPath $cases -PathType Leaf)){throw 'No reconciled stop cases.'}
$plan=Join-Path $review 'QTS_AUTO_STOP_WINDOWS.csv'
RunPython -exe $python -arguments @((Join-Path $gold 'research\prepare_stop_tick_windows.py'),
                    '--stops',$cases,'--output',$plan,'--tag',$tag) -purpose 'bounded quote window plan'

# Only a single installed QTS MT5 terminal is accepted. Avoid accidental
# history downloads from the wrong broker or an unrelated MT5 installation.
$dataRoot=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
$installed=@(Get-ChildItem -LiteralPath $dataRoot -Directory -ErrorAction Stop |
    Where-Object {Test-Path -LiteralPath (Join-Path $_.FullName 'MQL5\Experts\QTS_Gold_Robot.ex5')})
if($installed.Count -ne 1){throw 'Could not identify exactly one QTS MT5 terminal installation.'}
$target=$installed[0].FullName
$bridgeArgs=@((Join-Path $gold 'research\auto_stop_ticks.py'),
        '--plan',$plan,'--tag',$tag,'--symbol','XAUUSD@',
        '--terminal-data',$target)
$quoteDir=Join-Path $review 'QTS_AUTO_BROKER_TICKS'
$bridgeArgs+=@('--output',$quoteDir)
$origin=Join-Path $target 'origin.txt'
if(Test-Path -LiteralPath $origin -PathType Leaf){
    $first=@(Get-Content -LiteralPath $origin | Where-Object {$_ -and $_.Trim() -ne ''} |
         Select-Object -First 1)
    if($first.Count -eq 1){
        $location=$first[0].Trim().Trim('"')
        $terminalExe=if($location -match '\.exe$'){$location}else{Join-Path $location 'terminal64.exe'}
        if(Test-Path -LiteralPath $terminalExe -PathType Leaf){
            $bridgeArgs+=@('--terminal-path',$terminalExe)
        }
    }
}
$statusPath=Join-Path $quoteDir 'export_status.json'
$audit=Join-Path $review 'QTS_POST_STOP_REAL_TICK_REVIEW.json'
if(Test-Path -LiteralPath $quoteDir){
    if(-not (Test-Path -LiteralPath $audit -PathType Leaf)){
        throw ('Previously interrupted quote export found at '+$quoteDir+'. Original partial data retained.')
    }
    Write-Host 'Existing quote-path audit found; not overwriting original broker ticks.'
}else{
    Write-Host 'Collecting historical Bid/Ask automatically from the connected MT5 terminal...'
    & $python @bridgeArgs
    $bridgeCode=$LASTEXITCODE
    if(-not (Test-Path -LiteralPath $statusPath)){
        throw 'Quote export failed before saving evidence status.'
    }
    $status=Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    if($status.ticks_written -le 0){
        throw 'MT5 has no matching historical bid/ask ticks. No reversal inference possible.'
    }
    if($bridgeCode -ne 0){
        Write-Warning 'One or more broker quote requests failed. The audit will mark missing intervals UNKNOWN.'
    }
    RunPython -exe $python -arguments @((Join-Path $gold 'research\stop_reversal_audit.py'),
                        '--stops',$cases,'--tick-dir',$quoteDir,'--output',$audit) -purpose 'quote-by-quote post-stop replay'
}
if(-not (Test-Path -LiteralPath $audit -PathType Leaf)){throw 'No post-stop quote audit generated.'}
if(-not (Test-Path -LiteralPath $statusPath -PathType Leaf)){throw 'Missing original broker tick status.'}

# Second-stage failure analysis: replay ENTRY to STOP, not just AFTER STOP.
# Original post-stop price records are preserved unchanged.
$prePlan=Join-Path $review 'QTS_PRE_STOP_WINDOWS.csv'
$preDir=Join-Path $review 'QTS_PRE_STOP_BROKER_TICKS'
$preStatus=Join-Path $preDir 'export_status.json'
$failureCsv=Join-Path $review 'QTS_LOSING_STOP_PATHS.csv'
$failureJson=Join-Path $review 'QTS_LOSING_STOP_SUMMARY.json'
if(-not (Test-Path -LiteralPath $prePlan -PathType Leaf)){
    RunPython -exe $python -arguments @((Join-Path $gold 'research\prepare_stop_tick_windows.py'),
        '--stops',$cases,'--output',$prePlan,'--tag',$tag,'--phase','pre') -purpose 'entry-to-SL quote intervals'
}
if(-not (Test-Path -LiteralPath $preDir)){
    Write-Host 'Analyzing losses before the stop: entry -> maximum TP progress -> SL...'
    $preArgs=@((Join-Path $gold 'research\auto_stop_ticks.py'),
        '--plan',$prePlan,'--tag',$tag,'--symbol','XAUUSD@',
        '--terminal-data',$target,'--output',$preDir)
    if($bridgeArgs -contains '--terminal-path'){
        $ix=[array]::IndexOf($bridgeArgs,'--terminal-path')
        $preArgs+=@('--terminal-path',$bridgeArgs[$ix+1])
    }
    & $python @preArgs
    if(-not (Test-Path -LiteralPath $preStatus -PathType Leaf)){
        throw 'Entry-to-SL tick export did not save its evidence status.'
    }
    $preResult=Get-Content -LiteralPath $preStatus -Raw | ConvertFrom-Json
    if($preResult.ticks_written -le 0){
        throw 'No executable pre-stop quotes are available. Never guess entry-to-SL paths.'
    }
    if($LASTEXITCODE -ne 0){
        Write-Warning 'Some pre-stop quotes are missing; incomplete intervals will be UNKNOWN.'
    }
}elseif(-not (Test-Path -LiteralPath $preStatus -PathType Leaf)){
    throw 'An interrupted pre-stop export exists. Original quote files retained for inspection.'
}
RunPython -exe $python -arguments @((Join-Path $gold 'research\analyze_stop_failure_paths.py'),
    '--cases',$cases,'--post',$audit,'--pre-ticks',$preDir,'--out',$review) -purpose 'all stopped-trade failure and pre-SL audit'
if(-not (Test-Path -LiteralPath $failureJson -PathType Leaf) -or
   -not (Test-Path -LiteralPath $failureCsv -PathType Leaf)){
    throw 'Detailed failure report missing; do not claim completed analysis.'
}

# Keep both quote-export manifests with unique names inside the ZIP.
# Compress-Archive otherwise collides on two export_status.json basenames.
$preStatusForZip=Join-Path $review 'QTS_PRE_STOP_EXPORT_STATUS.json'
Copy-Item -LiteralPath $preStatus -Destination $preStatusForZip -Force
$zip=Join-Path $run.FullName 'QTS_POST_STOP_REVIEW.zip'
$files=@($audit,$original,$cases,$statusPath,$preStatusForZip,$failureJson,$failureCsv)
foreach($file in $files){if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw ('Missing review evidence: '+$file)}}
Compress-Archive -LiteralPath $files -DestinationPath $zip -Force
$summary=Get-Content -LiteralPath $audit -Raw | ConvertFrom-Json
Write-Host ('DONE: '+$summary.stop_trades+' recorded SL cases, '+$summary.ticks_scanned+' broker ticks checked.')
Write-Host ('REPORT ZIP: '+$zip)
Write-Host 'Incomplete price horizons are UNKNOWN; no real orders were submitted.'
Start-Process -FilePath explorer.exe -ArgumentList @('/select,',('"' + $zip + '"')) | Out-Null
