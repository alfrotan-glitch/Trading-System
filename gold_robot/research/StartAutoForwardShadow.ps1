# No-input QTS Forward Shadow Windows supervisor. WMMarkets DEMO ONLY, NO orders.
# Uses official MT5 startup config with unarmed native one-chart dual-style EA.
[CmdletBinding()]
param([switch]$ValidateOnly,[switch]$RunOnce,[switch]$NoAutostart)
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$repo=Split-Path -Parent $gold
$out=Join-Path $gold 'reports_local\forward_shadow'
$report=Join-Path $out 'QTS_FORWARD_AUTO_STATUS.json'
$start=(Get-Date).ToUniversalTime()
# One Windows logon session may own one read-only Shadow supervisor.
$lock=New-Object System.Threading.Mutex($false,'Local\QTS_DEMO_FORWARD_SHADOW_SUPERVISOR')
if(-not $lock.WaitOne(0)){Write-Host 'QTS Shadow is already running; no second process needed.';exit 0}
New-Item -Path $out -ItemType Directory -Force|Out-Null
function Save([string]$status,[string]$reason,[hashtable]$facts=@{}){
    $obj=[ordered]@{
        schema='qts.mt5.forward_auto_status.v1';status=$status;reason=$reason
        at_utc=(Get-Date).ToUniversalTime().ToString('o')
        live='LOCKED';validated_edge=$false;connected_orders_authorized=$false
        no_operator_prompts=$true;facts=$facts
    }
    $tmp="$report.tmp"
    $obj|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $report -Force
    Write-Host ("QTS {0}: {1}" -f $status,$reason)
}
function Health([string]$common,[datetime]$since){
    $file=Join-Path $common 'QTS_ForwardShadowV2_HEALTH.csv'
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){return $false}
    $info=Get-Item -LiteralPath $file
    if($info.Length -lt 25 -or $info.Length -gt 4096 -or
       $info.LastWriteTimeUtc -lt $since.AddSeconds(-30)){return $false}
    $rows=@(Import-Csv -LiteralPath $file -Delimiter ';')
    if($rows.Count -ne 1){return $false}
    $h=$rows[0]
    if($h.schema -ne 'qts.mt5.forward_shadow_health.v1' -or
       $h.symbol -ne 'XAUUSD@' -or $h.timeframe -ne 'M15' -or
       $h.mode -ne 'ONE_CHART_TWO_STYLES' -or
       $h.orders_authorized -ne '0' -or $h.connected -ne '1'){return $false}
    $seconds=[long]0
    if(-not [long]::TryParse($h.utc_s,[ref]$seconds)){return $false}
    $now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    return ($seconds -le $now -and ($now-$seconds) -le 90)
}
try{
    $needed=@(
      (Join-Path $gold 'mt5_robot\Install_MT5_Canonical.ps1'),
      (Join-Path $gold 'mt5_robot\QTS_Gold_Robot.mq5'),
      (Join-Path $gold 'research\forward_shadow_observer.py'),
      (Join-Path $gold 'research\forward_shadow_paths.py'),
      (Join-Path $gold 'docs\SOURCE_CHECKSUMS.json')
    )
    foreach($p in $needed){if(-not (Test-Path -LiteralPath $p -PathType Leaf)){
        throw ("PACKAGE_INCOMPLETE_NO_GO: "+$p)
    }}
    $src=Get-Content -LiteralPath (Join-Path $gold 'mt5_robot\QTS_Gold_Robot.mq5') -Raw
    if(-not $src.Contains('ForwardShadowObserveBothStyles') -or
       -not $src.Contains('QTS_ForwardShadowV2_HEALTH.csv')){
        throw 'OBSERVER_SOURCE_MISSING_NO_GO'
    }
    if($ValidateOnly){
        Save 'STATIC_PRECHECK_OK_NOT_BROKER_VERIFIED' 'No terminal, credentials, EX5 or broker accessed.'
        exit 0
    }
    if(-not $env:APPDATA){throw 'NO_APPDATA_NO_GO'}
    $parent=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if(-not (Test-Path -LiteralPath $parent -PathType Container)){throw 'NO_MT5_DATA_NO_GO'}
    $candidate=@()
    foreach($dir in (Get-ChildItem -LiteralPath $parent -Directory)){
        $mql=Join-Path $dir.FullName 'MQL5'
        $origin=Join-Path $dir.FullName 'origin.txt'
        if(-not (Test-Path -LiteralPath (Join-Path $mql 'Experts') -PathType Container) -or
           -not (Test-Path -LiteralPath (Join-Path $mql 'Scripts') -PathType Container) -or
           -not (Test-Path -LiteralPath $origin -PathType Leaf)){continue}
        $lines=@(Get-Content -LiteralPath $origin|Where-Object {$_.Trim()}|Select-Object -First 1)
        if($lines.Count -ne 1){continue}
        $base=$lines[0].Trim().Trim('"')
        if($base -match '(?i)\.exe$'){$base=Split-Path -Parent $base}
        $terminal=Join-Path $base 'terminal64.exe'
        $editor=Join-Path $base 'metaeditor64.exe'
        if((Test-Path -LiteralPath $terminal -PathType Leaf) -and
           (Test-Path -LiteralPath $editor -PathType Leaf)){
            $candidate+=,[pscustomobject]@{
                mql=$mql;terminal=$terminal;editor=$editor
                existingEa=(Test-Path -LiteralPath (Join-Path $mql 'Experts\QTS_Gold_Robot.ex5') -PathType Leaf)
            }
        }
    }
    $previous=@($candidate|Where-Object {$_.existingEa})
    $eligible=if($previous.Count -gt 0){$previous}else{$candidate}
    if(@($eligible).Count -ne 1){
        throw ("AMBIGUOUS_MT5_NO_GO: {0} possible native terminal(s); no guessed account or target" -f @($eligible).Count)
    }
    $target=@($eligible)[0]
    $common=Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files'
    New-Item -Path $common -ItemType Directory -Force|Out-Null
    # Never kill/restart an already-running terminal (it may manage other EAs).
    $running=@(Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'"|
       Where-Object {$_.ExecutablePath -and $_.ExecutablePath -ieq $target.terminal})
    if($running.Count -gt 0){
        if(-not (Health $common $start.AddMinutes(-1))){
            throw 'ACTIVE_TERMINAL_WITHOUT_NATIVE_HEALTH_NO_GO: refused unsafe MT5 restart'
        }
    }else{
        $installer=Join-Path $gold 'mt5_robot\Install_MT5_Canonical.ps1'
        $power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $args=@('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',
                $installer,'-TerminalDataFolder',(Split-Path -Parent $target.mql),
                '-MetaEditorPath',$target.editor)
        & $power @args
        if($LASTEXITCODE -ne 0){throw 'CANONICAL_COMPILE_NO_GO: native MetaEditor evidence unavailable'}
        $compiled=Join-Path $target.mql 'Experts\QTS_Gold_Robot.ex5'
        if(-not (Test-Path -LiteralPath $compiled -PathType Leaf)){
            throw 'NO_COMPILED_EA_NO_GO'
        }
        $preset=Join-Path $target.mql 'Presets\QTS_ForwardShadow_Auto.set'
        New-Item -Path (Split-Path -Parent $preset) -ItemType Directory -Force|Out-Null
        @(
          'EnableDemoOrders=false',
          'EnableDemoForwardOrders=false',
          'ForwardShadowObserveBothStyles=true',
          'EntryStyle=1',
          'SignalTimeframe=15',
          'EnableEntryDiagnostics=true',
          'ResetExecutionHalt=false',
          'EmergencyFlattenOwned=false'
        )|Set-Content -LiteralPath $preset -Encoding Unicode
        $config=Join-Path $out 'QTS_ForwardShadow_Auto.ini'
        @(
          '[Experts]','AllowLiveTrading=0','AllowDllImport=0','Enabled=1',
          'Account=1','Profile=1',
          '[StartUp]','Expert=QTS_Gold_Robot',
          'ExpertParameters=QTS_ForwardShadow_Auto.set',
          'Symbol=XAUUSD@','Period=M15'
        )|Set-Content -LiteralPath $config -Encoding Unicode
        $arg='/config:"{0}"' -f $config
        Start-Process -FilePath $target.terminal -ArgumentList $arg|Out-Null
        Save 'START_REQUESTED_NOT_YET_VERIFIED' 'Waiting for a verified native DEMO heartbeat.'
        $healthy=$false
        for($i=0;$i -lt 45;$i++){
            Start-Sleep -Seconds 2
            if(Health $common $start){$healthy=$true;break}
        }
        if(-not $healthy){throw 'NO_HEALTH_AFTER_STARTUP_NO_GO: no proof that DEMO EA attached'}
    }
    Save 'NATIVE_UNARMED_DEMO_HEALTH_OK' 'Single-chart dual-style research, no broker orders; not an edge.'
    if(-not $NoAutostart){
        $bat=Join-Path $repo 'QTS_AUTO_FORWARD.bat'
        if(Test-Path -LiteralPath $bat -PathType Leaf){
            $key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
            New-Item -Path $key -Force|Out-Null
            New-ItemProperty -Path $key -Name 'QTS_Demo_Shadow' -PropertyType String -Value ('"{0}"' -f $bat) -Force|Out-Null
        }
    }
    $venv=Join-Path $gold 'reports_local\mt5_quote_bridge_env'
    $python=Join-Path $venv 'Scripts\python.exe'
    if(-not (Test-Path -LiteralPath $python -PathType Leaf)){
        if(Get-Command py.exe -ErrorAction SilentlyContinue){
            & py.exe -3 -m venv $venv
        }else{
            & python.exe -m venv $venv
        }
        if($LASTEXITCODE -ne 0){throw 'NO_ISOLATED_PYTHON_NO_GO'}
    }
    & $python -c 'import MetaTrader5'
    if($LASTEXITCODE -ne 0){
        & $python -m pip install --no-input --only-binary=:all: MetaTrader5
        if($LASTEXITCODE -ne 0){throw 'NO_OFFICIAL_MT5_READER_NO_GO'}
    }
    do{
        if(-not (Health $common (Get-Date).ToUniversalTime())){
            throw 'NATIVE_HEARTBEAT_LOST_NO_GO: research is not operational'
        }
        & $python (Join-Path $gold 'research\forward_shadow_observer.py') --report-dir $out
        $observerCode=$LASTEXITCODE
        & $python (Join-Path $gold 'research\forward_shadow_paths.py') --report-dir $out
        $pathCode=$LASTEXITCODE
        Save 'FORWARD_REPORT_CYCLE_FINISHED_UNVALIDATED' 'Native signal/price reports updated; no P&L or live orders.' @{
            observer_exit=$observerCode;price_path_exit=$pathCode
        }
        if($RunOnce){break}
        Start-Sleep -Seconds 300
    }while($true)
    exit 0
}catch{
    Save 'AUTO_FORWARD_BLOCKED_NO_GO' ([string]$_.Exception.Message)
    exit 2
}finally{
    if($lock){$lock.ReleaseMutex();$lock.Dispose()}
}
