# QTS: one-click, two-arm native MT5 prospective V5 study (simulation only).
# The preregistered study must be written BEFORE its unseen period begins.
# No parameter tuning, broker orders, production deployment or live switch.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PlanPath,
      [string]$OutputDirectory="",
      [string]$TerminalExe="",
      [string]$TerminalDataFolder="",
      [int]$TimeoutMinutesPerRun=90)
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$manifest=Join-Path $gold 'docs\SOURCE_CHECKSUMS.json'
$studyTool=Join-Path $gold 'research\v5_study.py'
$runner=Join-Path $gold 'research\RunAutomaticTester.ps1'
$planFile=(Resolve-Path -LiteralPath $PlanPath -ErrorAction Stop).Path
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){$interpreter=$py.Source;$prefix=@('-3')}
else{
    $py=Get-Command python -ErrorAction SilentlyContinue
    if(-not $py){throw 'Python 3 missing: cannot verify frozen prospective V5 study.'}
    $interpreter=$py.Source;$prefix=@()
}
& $interpreter @prefix $studyTool verify --plan $planFile --manifest $manifest --completed
if($LASTEXITCODE -ne 0){throw 'Frozen study is altered or evaluation window is not complete.'}
$plan=Get-Content -LiteralPath $planFile -Raw -Encoding UTF8 | ConvertFrom-Json
if($plan.schema -ne 'qts.mt5.v5.preregistered_study.v1' -or
   $plan.live -ne 'LOCKED' -or $plan.edge_validated -ne $false -or
   $plan.auto_promote -ne $false -or
   $plan.challenger -ne 'ADAPTIVE_V5_VETO' -or
   $plan.champion -ne 'ADAPTIVE_V4'){
    throw 'Frozen study schema/permissions/arms mismatch.'
}
$studyId=[string]$plan.study_id
if($studyId -notmatch '^[0-9a-f]{64}$'){throw 'Study identity is invalid.'}
if(-not $OutputDirectory){
    $OutputDirectory=Join-Path $gold ('reports_local\v5_studies\'+$studyId.Substring(0,16))
}
if(Test-Path -LiteralPath $OutputDirectory){
    throw 'Study output already exists. Never overwrite a native study or replay evidence.'
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$champion=Join-Path $OutputDirectory 'champion'
$challenger=Join-Path $OutputDirectory 'challenger'
$nativeArgs=@{OnlyStyles='7';FromDate=[string]$plan.from_date;
             ToDate=[string]$plan.to_date;NoOpen=$true;
             TimeoutMinutesPerRun=$TimeoutMinutesPerRun}
if($TerminalExe){$nativeArgs['TerminalExe']=$TerminalExe}
if($TerminalDataFolder){$nativeArgs['TerminalDataFolder']=$TerminalDataFolder}
try {
    # Exactly the SAME EA build, instrument, dates, risk stops and real-tick
    # broker test settings; only ONE prospective veto is different.
    & $runner @nativeArgs -OutputDirectory $champion -ResearchVariant ADAPTIVE_V4
    if($LASTEXITCODE -ne 0){throw 'Champion native tester failed. Challenger cannot be judged.'}
    & $runner @nativeArgs -OutputDirectory $challenger -ResearchVariant ADAPTIVE_V5_VETO -VetoStyle ([int]$plan.frozen_style) -VetoRegime ([int]$plan.frozen_regime_id)
    if($LASTEXITCODE -ne 0){throw 'Challenger native tester failed. No result or promotion.'}
    $output=Join-Path $OutputDirectory 'QTS_V5_NATIVE_STUDY_COMPARISON.json'
    & $interpreter @prefix $studyTool compare --plan $planFile --manifest $manifest --champion $champion --challenger $challenger --output $output
    if($LASTEXITCODE -ne 0){throw 'Two-arm native study evidence did not reconcile.'}
    Write-Host ('V5_NATIVE_STUDY='+$output)
    Write-Host 'RESEARCH ONLY. No REAL trading, positive edge, or auto-promotion.'
}catch{
    Write-Warning ('V5 study FAILED CLOSED: '+$_.Exception.Message)
    throw
}
