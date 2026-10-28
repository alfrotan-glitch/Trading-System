# QTS Gold Windows Status Reporter — read-only. Requires Windows PowerShell 5.1+.
[CmdletBinding()]
param([string]$DataFolder="", [string]$OutputDirectory="", [switch]$NoOpen)
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$manifestPath=Join-Path $gold 'docs\SOURCE_CHECKSUMS.json'
function HtmlEscape([object]$v){return [System.Net.WebUtility]::HtmlEncode([string]$v)}
function Resolve-Mql5([string]$path){
    if([string]::IsNullOrWhiteSpace($path)){return $null}
    foreach($p in @($path,(Join-Path $path 'MQL5'))){
        if((Test-Path -LiteralPath (Join-Path $p 'Experts') -PathType Container) -and
           (Test-Path -LiteralPath (Join-Path $p 'Scripts') -PathType Container)){
            return (Resolve-Path -LiteralPath $p).Path
        }
    }
    return $null
}
function Tr([string]$key,[object]$value){
    return ('<tr><th>{0}</th><td dir="ltr">{1}</td></tr>' -f (HtmlEscape $key),(HtmlEscape $value))
}
function Tile([string]$title,[string]$status,[string]$detail,[string]$kind){
    return ('<div class="tile {0}"><span>{1}</span><b dir="ltr">{2}</b><small>{3}</small></div>' -f $kind,(HtmlEscape $title),(HtmlEscape $status),(HtmlEscape $detail))
}
$repoFiles=@('mt5_robot/QTS_Gold_Robot.mq5','mt5_robot/ExecutionPolicy.mqh',
             'mt5_robot/StructureResearch.mqh','research/QTS_Broker_Preflight.mq5')
$sourceState='SOURCE_MISSING'
if(Test-Path -LiteralPath $manifestPath){
    $manifest=Get-Content -LiteralPath $manifestPath -Encoding UTF8 -Raw | ConvertFrom-Json
    $pass=$true
    foreach($relative in $repoFiles){
        $path=Join-Path $gold ($relative.Replace('/','\'))
        $found=@($manifest.sha256_files | Where-Object { $_.path -eq $relative })
        if($found.Count -ne 1 -or -not (Test-Path -LiteralPath $path)){
            $pass=$false;break
        }
        if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne [string]$found[0].sha256){
            $pass=$false;break
        }
    }
    $sourceState=if($pass){'SOURCE_HASH_OK'}else{'SOURCE_HASH_MISMATCH'}
}
$mql5=$null
if($DataFolder){
    $mql5=Resolve-Mql5 $DataFolder
    if(-not $mql5){throw 'Invalid specified MT5 data folder'}
}else{
    $candidates=@()
    $terminals=Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if(Test-Path -LiteralPath $terminals){
        foreach($item in (Get-ChildItem -LiteralPath $terminals -Directory -ErrorAction SilentlyContinue)){
            $found=Resolve-Mql5 $item.FullName
            if($found){$candidates+=,$found}
        }
    }
    $candidates=@($candidates | Sort-Object -Unique)
    if($candidates.Count -eq 1){$mql5=$candidates[0]}
    elseif($candidates.Count -gt 1){
        Write-Host 'Select your WMMarkets MT5 terminal:'
        for($i=0;$i -lt $candidates.Count;$i++){Write-Host ('[{0}] {1}' -f ($i+1),$candidates[$i])}
        $number=0
        $selection=Read-Host ('Choose number 1-{0}' -f $candidates.Count)
        if(-not [int]::TryParse($selection,[ref]$number) -or $number -lt 1 -or $number -gt $candidates.Count){
            throw 'MT5 selection is ambiguous; refused to guess'
        }
        $mql5=$candidates[$number-1]
    }
}
$installState='NOT_VERIFIED'
$preflightInstallState='NOT_VERIFIED'
$preflightCompileState='NOT_COMPILED'
$preflightCompiledAtUtc=[datetime]::MinValue
$compileState='NOT_COMPILED'
$preflightState='NOT_RUN'
$preflightAge=$null
$values=@{}
if($mql5){
    $sourcePairs=@(
        @((Join-Path $gold 'mt5_robot\QTS_Gold_Robot.mq5'),(Join-Path $mql5 'Experts\QTS_Gold_Robot.mq5')),
        @((Join-Path $gold 'mt5_robot\ExecutionPolicy.mqh'),(Join-Path $mql5 'Experts\ExecutionPolicy.mqh')),
        @((Join-Path $gold 'mt5_robot\StructureResearch.mqh'),(Join-Path $mql5 'Experts\StructureResearch.mqh'))
    )
    $matching=($sourceState -eq 'SOURCE_HASH_OK')
    $newestSource=[datetime]::MinValue
    foreach($pair in $sourcePairs){
        if(-not (Test-Path -LiteralPath $pair[1]) -or -not (Test-Path -LiteralPath $pair[0])){
            $matching=$false;continue
        }
        if((Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash -ne
           (Get-FileHash -LiteralPath $pair[1] -Algorithm SHA256).Hash){$matching=$false}
        $t=(Get-Item -LiteralPath $pair[1]).LastWriteTimeUtc
        if($t -gt $newestSource){$newestSource=$t}
    }
    $log=Join-Path $mql5 'Experts\QTS_Gold_Robot.log'
    $ex5=Join-Path $mql5 'Experts\QTS_Gold_Robot.ex5'
    if(Test-Path -LiteralPath $log){
        $result=[regex]::Matches((Get-Content -LiteralPath $log -Raw),
                   '(?im)^\s*Result:\s*(\d+)\s+errors?\s*,\s*(\d+)\s+warnings?\b')
        if($result.Count -eq 1){
            $compileState=('{0} errors / {1} warnings' -f $result[0].Groups[1].Value,$result[0].Groups[2].Value)
        }else{$compileState='INVALID_COMPILE_LOG'}
    }
    if($matching -and $compileState -eq '0 errors / 0 warnings' -and (Test-Path -LiteralPath $ex5)){
        $binary=Get-Item -LiteralPath $ex5
        if($binary.Length -gt 1000 -and $binary.LastWriteTimeUtc -ge $newestSource.AddSeconds(-2) -and
            (Get-Item -LiteralPath $log).LastWriteTimeUtc -ge $newestSource.AddSeconds(-2)){
            $installState='COMPILED_VERIFIED'
        }
    }
    # An old or separately installed Preflight must never make a current EA look ready.
    $preflightSource=Join-Path $gold 'research\QTS_Broker_Preflight.mq5'
    $installedPreflightSource=Join-Path $mql5 'Scripts\QTS_Broker_Preflight.mq5'
    $preflightBinary=Join-Path $mql5 'Scripts\QTS_Broker_Preflight.ex5'
    $preflightLog=Join-Path $mql5 'Scripts\QTS_Broker_Preflight.log'
    if($sourceState -eq 'SOURCE_HASH_OK' -and
       (Test-Path -LiteralPath $preflightSource -PathType Leaf) -and
       (Test-Path -LiteralPath $installedPreflightSource -PathType Leaf) -and
       (Test-Path -LiteralPath $preflightBinary -PathType Leaf) -and
       (Test-Path -LiteralPath $preflightLog -PathType Leaf)){
        $sourceMatches=(Get-FileHash -LiteralPath $preflightSource -Algorithm SHA256).Hash -eq
                        (Get-FileHash -LiteralPath $installedPreflightSource -Algorithm SHA256).Hash
        $compileSummary=[regex]::Matches((Get-Content -LiteralPath $preflightLog -Raw),
                     '(?im)^\s*Result:\s*(\d+)\s+errors?\s*,\s*(\d+)\s+warnings?\b')
        if($compileSummary.Count -eq 1){
            $preflightCompileState=('{0} errors / {1} warnings' -f
                $compileSummary[0].Groups[1].Value,$compileSummary[0].Groups[2].Value)
        }else{$preflightCompileState='INVALID_COMPILE_LOG'}
        $preflightArtifact=Get-Item -LiteralPath $preflightBinary
        $preflightCompiledAtUtc=$preflightArtifact.LastWriteTimeUtc
        if($sourceMatches -and $preflightCompileState -eq '0 errors / 0 warnings' -and
           $preflightArtifact.Length -gt 1000 -and
           $preflightArtifact.LastWriteTimeUtc -ge
                (Get-Item -LiteralPath $installedPreflightSource).LastWriteTimeUtc.AddSeconds(-2) -and
           (Get-Item -LiteralPath $preflightLog).LastWriteTimeUtc -ge
                (Get-Item -LiteralPath $installedPreflightSource).LastWriteTimeUtc.AddSeconds(-2)){
            $preflightInstallState='COMPILED_VERIFIED'
        }
    }
    $preflight=Join-Path $mql5 'Files\QTS_Broker_Preflight.csv'
    if(Test-Path -LiteralPath $preflight){
        try{
            if($preflightInstallState -ne 'COMPILED_VERIFIED'){
                throw 'Preflight script version/compile is unverified'
            }
            if((Get-Item -LiteralPath $preflight).LastWriteTimeUtc -lt $preflightCompiledAtUtc.AddSeconds(-2)){
                throw 'Broker CSV predates the current compiled preflight script'
            }
            foreach($entry in @(Import-Csv -LiteralPath $preflight -Delimiter ';' -Encoding Default)){
                if(-not [string]::IsNullOrWhiteSpace($entry.metric)){
                    $values[[string]$entry.metric]=[string]$entry.value
                }
            }
            if(-not $values.ContainsKey('Verdict') -or $values['OrdersSubmitted'] -ne '0' -or
                $values['MODE'] -ne 'READ_ONLY_NO_ORDERS'){
                $preflightState='INVALID_AUDIT'
            }else{
                $preflightAge=[math]::Round(((Get-Date).ToUniversalTime() -
                    (Get-Item -LiteralPath $preflight).LastWriteTimeUtc).TotalHours,1)
                $preflightState=if($preflightAge -gt 24 -or $preflightAge -lt -1){
                    'STALE_AUDIT'
                }else{[string]$values['Verdict']}
            }
        }catch{$preflightState='INVALID_AUDIT'}
    }
}
$ready=$sourceState -eq 'SOURCE_HASH_OK' -and
       $installState -eq 'COMPILED_VERIFIED' -and
       $preflightInstallState -eq 'COMPILED_VERIFIED' -and
       $preflightState -eq 'ENGINEERING_PRECHECK_OK_NOT_TRADE_PERMISSION'
$overall=if($ready){'READY_FOR_TESTER_ONLY'}else{'ACTION_REQUIRED'}
$next=if($sourceState -ne 'SOURCE_HASH_OK'){
    'Source files are missing or modified. Restore a clean main checkout.'
}elseif($installState -ne 'COMPILED_VERIFIED'){
    'Run START_HERE.bat option 1 to reinstall the current EA.'
}elseif($preflightInstallState -ne 'COMPILED_VERIFIED'){
    'Broker Preflight is not installed or compiled from current source. Run option 1.'
}elseif($preflightState -eq 'NOT_RUN' -or $preflightState -eq 'STALE_AUDIT'){
    'Run QTS_Broker_Preflight on the XAUUSD@ chart, then regenerate this report.'
}elseif(-not $ready){
    'Review the broker BLOCKED/INVALID result. Never reduce stops or risk checks just to force entry.'
}else{
    'Use Strategy Tester: XAUUSD@, USD 3,000 tester deposit, real ticks, and four independent EntryStyle runs.'
}
$rows=@()
foreach($name in @('BrokerServer','AccountType','Symbol','MinLot','LotStep','ContractSize',
    'SpreadPoints','StopsLevelPoints','MinStopGapPrice','ModeledRiskBudgetUSD',
    'WorstMinLotModeledLossUSD','MinimumLotModeledRiskPercent',
    'MinimumLotRiskBudgetMultiple','RiskBudgetExceededUSD',
    'RiskBudgetStatus','MinimumLotMarginStatus','ActualCommissionVerified',
    'OrdersSubmitted','Verdict')){
    if($values.ContainsKey($name)){$rows += (Tr $name $values[$name])}
}
if($rows.Count -eq 0){$rows=@('<tr><td colspan="2">No broker preflight data available.</td></tr>')}
$kindA=if($sourceState -eq 'SOURCE_HASH_OK'){'good'}else{'bad'}
$kindB=if($installState -eq 'COMPILED_VERIFIED'){'good'}else{'warn'}
$kindC=if($preflightState -eq 'ENGINEERING_PRECHECK_OK_NOT_TRADE_PERMISSION'){'good'}else{'warn'}
$cards=@(
    (Tile 'Source integrity' $sourceState 'SHA-256 of four critical source files' $kindA),
    (Tile 'MT5 compilation' $installState 'Fresh EX5 with zero errors and warnings' $kindB),
    (Tile 'Broker preflight' $preflightState 'Latest read-only WMMarkets report' $kindC),
    (Tile 'Permitted use' $overall 'Tester only; LIVE trading locked' 'neutral')
) -join [Environment]::NewLine
$rowsHtml=$rows -join [Environment]::NewLine
$created=(Get-Date).ToString('yyyy-MM-dd HH:mm')
$age=if($null -ne $preflightAge){"$preflightAge hours"}else{'unknown'}
$html=@"
<!DOCTYPE html><html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QTS Gold - Windows Readiness</title>
<style>
*{box-sizing:border-box}body{font-family:"Segoe UI",Tahoma,sans-serif;margin:0;background:#f3f6fa;color:#172234}
main{max-width:1000px;margin:30px auto;padding:0 20px 50px}
header{background:#143252;color:white;border-radius:18px;padding:28px 32px}
header h1{font-size:25px;margin:0 0 12px}header p{color:#d3dfee;line-height:1.7;margin:0}
.meta{color:#bcd0e3;font-size:13px;margin-top:16px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:20px 0}
.tile{background:white;border:1px solid #e1e8ef;border-top:4px solid #64748b;border-radius:12px;padding:20px}
.tile.good{border-top-color:#15803d}.tile.warn{border-top-color:#b45309}.tile.bad{border-top-color:#b91c1c}
.tile span,.tile small{display:block;color:#64748b;font-size:13px}
.tile b{display:block;font-size:15px;margin:12px 0;overflow-wrap:anywhere}
section{background:white;border:1px solid #e1e8ef;border-radius:14px;padding:23px;margin-top:16px}
h2{font-size:18px;margin:0 0 15px}table{width:100%;border-collapse:collapse}
td,th{padding:11px;border-bottom:1px solid #edf1f6;overflow-wrap:anywhere;font-size:14px}
th{text-align:left;color:#64748b;font-weight:500;width:42%}td{text-align:left
.next{border-left:4px solid #2563eb;background:#eff5fb;padding:15px;line-height:1.9}
footer{color:#64748b;font-size:12px;text-align:center;margin-top:22px}
@media(max-width:680px){.grid{grid-template-columns:1fr}main{margin:12px auto}}
</style></head><body><main>
<header><h1>QTS Gold | Windows Readiness Report</h1>
<p>Source integrity, installation, broker compatibility and Strategy Tester prerequisites.</p>
<div class="meta">Generated: $(HtmlEscape $created) | XAUUSD@ | LIVE: LOCKED | EDGE: UNVALIDATED</div>
</header><div class="grid">$cards</div>
<section><h2>Status summary</h2><table>
$(Tr 'EA compiler result' $compileState)
$(Tr 'Broker Preflight compiler result' $preflightCompileState)
$(Tr 'Broker Preflight installation' $preflightInstallState)
$(Tr 'Broker audit age' $age)
$(Tr 'Overall readiness' $overall)
</table></section>
<section><h2>Broker specifications</h2><table>$rowsHtml</table>
<p>This report reads broker diagnostics only. It does not verify realized profits, live costs or trading permission.</p></section>
<section><h2>Recommended next action</h2><p class="next">$(HtmlEscape $next)</p>
<p>Validate each strategy separately with native MT5 real-tick tester reports. Readiness is not evidence of profitability.</p></section>
<footer>QTS research workstation · No login / account key · No orders submitted by this tool</footer>
</main></body></html>
"@
if(-not $OutputDirectory){$OutputDirectory=Join-Path $gold 'reports_local'}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$timestamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$outFile=Join-Path $OutputDirectory ("QTS_Gold_Readiness_"+$timestamp+".html")
$jsonFile=Join-Path $OutputDirectory ("QTS_Gold_Readiness_"+$timestamp+".json")
[System.IO.File]::WriteAllText($outFile,$html,([System.Text.UTF8Encoding]::new($false)))
$summary=[ordered]@{
    mode='READ_ONLY';created=$created;symbol='XAUUSD@'
    source_status=$sourceState;install_status=$installState;compiler=$compileState
    preflight_install_status=$preflightInstallState;preflight_compiler=$preflightCompileState
    preflight_status=$preflightState;preflight_age_hours=$preflightAge
    readiness=$overall;live='LOCKED';validated_profitable_edge=$false
    orders_submitted_by_report=0;next_action=$next
}
$summary | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $jsonFile -Encoding UTF8
Write-Host ('HTML report: '+$outFile)
Write-Host ('JSON status: '+$jsonFile)
Write-Host ('READINESS: '+$overall+' | LIVE: LOCKED')
if(-not $NoOpen){Invoke-Item -LiteralPath $outFile}
