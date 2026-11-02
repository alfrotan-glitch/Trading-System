# Single-action upgrade of ONLY the QTS read-only Forward Shadow supervisor.
# Never stops, switches, configures or places orders in MetaTrader 5.
# Existing local evidence files and the customer's broker account are untouched.
[CmdletBinding()]
param([switch]$ValidateOnly)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$supervisor=Join-Path $root 'gold_robot\research\StartAutoForwardShadow.ps1'
$launcher=Join-Path $root 'QTS_AUTO_FORWARD.bat'
$out=Join-Path $root 'gold_robot\reports_local\forward_shadow'
New-Item -Path $out -ItemType Directory -Force | Out-Null
$statusFile=Join-Path $out 'QTS_FORWARD_REFRESH_STATUS.json'
function Status([string]$kind,[string]$detail){
    $data=[ordered]@{
        schema='qts.mt5.forward_refresh.v1'
        status=$kind
        detail=$detail
        at_utc=[DateTimeOffset]::UtcNow.ToString('o')
        mt5_processes_stopped=0
        broker_orders_sent=0
        live='LOCKED'
        new_supervisor_verified=$false
    }
    $data | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $statusFile -Encoding UTF8
    Write-Host "QTS REFRESH: $kind - $detail"
}
try{
    if(-not (Test-Path -LiteralPath $supervisor -PathType Leaf) -or
       -not (Test-Path -LiteralPath $launcher -PathType Leaf)){
        throw 'REPOSITORY_MISSING_NO_GO: canonical QTS launcher/source unavailable'
    }
    $git=Get-Command git.exe -ErrorAction Stop
    $branch=(& $git.Source -C $root branch --show-current).Trim()
    if($LASTEXITCODE -ne 0 -or $branch -ne 'main'){
        throw 'MAIN_REQUIRED_NO_GO: refusing to update a non-main working tree'
    }
    if($ValidateOnly){
        Status 'STATIC_CHECK_OK_NOT_RUNNING' 'No process terminated, Git pull not executed; only source inspected.'
        exit 0
    }
    # A previous supervisor is a research-only PowerShell process. Identify
    # it by full, unique script path; never match terminal64.exe/metaeditor.
    $escaped=[regex]::Escape($supervisor)
    $processes=@(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            $_.CommandLine -match ('(?i)(?:-File|/File)\s+"?' + $escaped + '(?:"|\s|$)')
        })
    if($processes.Count -gt 1){
        throw 'AMBIGUOUS_SUPERVISOR_NO_GO: refusing to stop multiple processes'
    }
    if($processes.Count -eq 1){
        # Exactly the older QTS reporting loop, not MT5, MetaEditor, or a
        # trading EA. No unrelated processes are terminated.
        Stop-Process -Id $processes[0].ProcessId -Force -ErrorAction Stop
        Start-Sleep -Seconds 1
        if(Get-Process -Id $processes[0].ProcessId -ErrorAction SilentlyContinue){
            throw 'SUPERVISOR_STOP_FAILED_NO_GO'
        }
    }
    & $git.Source -C $root pull --ff-only origin main
    if($LASTEXITCODE -ne 0){
        throw 'GIT_UPDATE_FAILED_NO_GO: local sources untouched if fast-forward refused'
    }
    # The refreshed supervisor performs the account/binary/heartbeat checks.
    # Never claim it is healthy just because the new process was requested.
    Start-Process -FilePath $launcher -WorkingDirectory $root | Out-Null
    Status 'REFRESH_REQUESTED_NOT_YET_VERIFIED' 'Old QTS reporting loop stopped if found; updated launcher started. Check its separate current status for readiness.'
    exit 0
}catch{
    Status 'REFRESH_BLOCKED_NO_GO' ([string]$_.Exception.Message)
    exit 2
}
