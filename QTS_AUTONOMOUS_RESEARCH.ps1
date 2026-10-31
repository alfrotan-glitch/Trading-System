# QTS Gold unattended evidence cycle. Research only, no broker order or code edits.
[CmdletBinding()]
param([switch]$Install, [switch]$RunCycle)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSCommandPath
$gold=Join-Path $repo 'gold_robot'
$evidence=Join-Path $gold 'reports_local\revised_comparison'
$store=Join-Path $gold 'reports_local\autonomous_learning'
$agent=Join-Path $gold 'research\autonomous_learning.py'
$ablation=Join-Path $repo 'QTS_V2_ABLATION.ps1'
$taskName='QTS Gold - Local Research Autopilot'
New-Item -ItemType Directory -Path $evidence,$store -Force | Out-Null

function InvokeCycle {
    $mutex=New-Object System.Threading.Mutex($false,'Local\QTS_AUTONOMOUS_RESEARCH')
    $owns=$false
    try {
        try {$owns=$mutex.WaitOne(0)}catch [System.Threading.AbandonedMutexException] {$owns=$true}
        if(-not $owns) {
            Write-Host 'A local QTS research cycle is already running. Skipping duplicate.'
            return
        }
        $python=Join-Path $gold 'reports_local\mt5_quote_bridge_env\Scripts\python.exe'
        $bootstrap=@()
        if(-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            if(Get-Command py.exe -ErrorAction SilentlyContinue) {
                $python='py.exe';$bootstrap=@('-3')
            } elseif(Get-Command python.exe -ErrorAction SilentlyContinue) {
                $python='python.exe'
            } else {
                throw 'Python 3 is required. Install Python 3 before enabling QTS local research.'
            }
        }
        $base=@($agent,'--evidence-root',$evidence,'--state-root',$store)
        & $python @bootstrap @base
        if($LASTEXITCODE -ne 0) {throw 'Native evidence scan failed closed.'}
        $status=Get-Content -LiteralPath (Join-Path $store 'QTS_AUTONOMOUS_STATUS.json') -Raw |
            ConvertFrom-Json
        if($status.live -ne 'LOCKED' -or $status.edge_validated -ne $false) {
            throw 'Unexpected research authority; no tester launched.'
        }
        $window=$status.next_monthly_test
        if($null -eq $window) {
            Write-Host 'No new completed, untested monthly window. Evidence lessons are up to date.'
            return
        }
        # Native MT5 tester must own the terminal. Avoid burning retries while
        # user trades or another tester is active.
        if(@(Get-Process -Name terminal64 -ErrorAction SilentlyContinue).Count -ne 0) {
            Write-Host 'MT5 already active. No research reservation; automatic retry on next scheduled day.'
            return
        }
        # Reserve BEFORE launching: a crash/reboot must not cause infinite
        # repeated backtests. Max two reserved attempts per month.
        & $python @bootstrap @base '--reserve' ([string]$window.from_date)
        if($LASTEXITCODE -ne 0) {throw 'Cannot reserve unique future research period.'}
        $name='autopilot_'+($window.from_date -replace '\.','')+'_'+(Get-Date -Format 'yyyyMMdd_HHmmss')
        $destination=Join-Path $evidence $name
        Write-Host ('Native future-month four-arm study: '+$window.from_date+' to '+$window.to_date)
        & $ablation -FromDate $window.from_date -ToDate $window.to_date -OutputDirectory $destination -NoOpen
        if($LASTEXITCODE -ne 0) {throw 'Native MT5 ablation failed.'}
        $zip=Join-Path $destination 'QTS_V2_ABLATION_EVIDENCE.zip'
        if(-not (Test-Path -LiteralPath $zip -PathType Leaf)) {
            throw 'Completed tester did not produce immutable evidence ZIP.'
        }
        & $python @bootstrap @base
        if($LASTEXITCODE -ne 0) {throw 'Post-test native journal audit failed.'}
        Write-Host 'New future-month evidence learned; results are only research hypotheses.'
    } finally {
        if($owns) {$mutex.ReleaseMutex()}
        $mutex.Dispose()
    }
}

if($Install) {
    # Interactive-token task needs no stored password. Runs only when this
    # Windows user is signed in; unavailable/offline machines cannot test.
    $executor=Join-Path $PSHOME 'powershell.exe'
    $cmd=('-NoProfile -ExecutionPolicy Bypass -File "{0}" -RunCycle' -f $PSCommandPath)
    $action=New-ScheduledTaskAction -Execute $executor -Argument $cmd -WorkingDirectory $repo
    $trigger=New-ScheduledTaskTrigger -Daily -At '04:00'
    $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 18)
    $user=([System.Security.Principal.WindowsIdentity]::GetCurrent()).Name
    $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Daily local research journal; native MT5 only after a new month; LIVE LOCKED.' -Force | Out-Null
    Write-Host 'QTS local daily research installed (04:00 while logged in).'
    InvokeCycle
} elseif($RunCycle) {
    InvokeCycle
} else {
    throw 'Use QTS_AUTONOMOUS_RESEARCH.bat to install the daily local research cycle.'
}
