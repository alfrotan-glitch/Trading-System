# QTS Gold — local evidence handoff. Only explicitly allowlisted JSON and
# deal-level CSV are included; native MT5 HTML, journal, account and login files
# are NEVER included. No network/upload or broker orders.
[CmdletBinding()]
param([string]$RunDirectory="",[switch]$NoOpen)
$ErrorActionPreference='Stop'
$gold=Split-Path -Parent $PSScriptRoot
$root=Join-Path $gold 'reports_local\auto_runs'
if(-not (Test-Path -LiteralPath $root -PathType Container)){
    throw 'No automatic MT5 run folder found. Run QTS_AUTO_TEST.bat first.'
}
if(-not $RunDirectory){
    $runs=@(Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop |
        Where-Object {Test-Path -LiteralPath (Join-Path $_.FullName 'OPEN_RESULTS.json') -PathType Leaf} |
        Sort-Object Name -Descending)
    if($runs.Count -eq 0){
        throw 'No automatic tester result JSON found. The MT5 tester has not created a local research report.'
    }
    $RunDirectory=$runs[0].FullName
}
$RunDirectory=(Resolve-Path -LiteralPath $RunDirectory -ErrorAction Stop).Path
$root=(Resolve-Path -LiteralPath $root).Path.TrimEnd('\')
if(-not $RunDirectory.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){
    throw 'Refusing to package a folder outside QTS reports_local/auto_runs.'
}
$allowed=New-Object System.Collections.ArrayList
foreach($name in @('OPEN_RESULTS.json','QTS_TRADE_BY_TRADE.json','QTS_ADAPTIVE_REVIEW.json')){
    $p=Join-Path $RunDirectory $name
    if(Test-Path -LiteralPath $p -PathType Leaf){[void]$allowed.Add(@($p,$name))}
}
$comparisons=@(Get-ChildItem -LiteralPath $RunDirectory -Filter 'QTS_Gold_Comparison_*.json' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending)
if($comparisons.Count -gt 0){
    [void]$allowed.Add(@($comparisons[0].FullName,'comparison.json'))
}
# Select only the styles actually tested, never silently omit SMC 8/Scalp 9.
$outcomePath=Join-Path $RunDirectory 'OPEN_RESULTS.json'
if(-not (Test-Path -LiteralPath $outcomePath -PathType Leaf)){throw 'Missing test run manifest.'}
$outcome=Get-Content -LiteralPath $outcomePath -Raw | ConvertFrom-Json
$requiredStyles=@(0..9)
if($outcome.targeted -eq $true){
    $requiredStyles=@($outcome.selected_styles)
    if($requiredStyles.Count -eq 0 -or
       @($requiredStyles | Sort-Object -Unique).Count -ne $requiredStyles.Count -or
       @($requiredStyles | Where-Object {$_ -notin @(0..9)}).Count -gt 0){
        throw 'Invalid targeted-run strategy manifest.'
    }
}
$missing=@()
foreach($i in $requiredStyles){
    $file=('QTS_{0}_trades.csv' -f $i)
    $p=Join-Path (Join-Path $RunDirectory 'native') $file
    if(Test-Path -LiteralPath $p -PathType Leaf){
        [void]$allowed.Add(@($p,('native/'+$file)))
    }else{
        $missing+=,$file
    }
}
if($allowed.Count -eq 0){throw 'No allowlisted research evidence exists in the selected run folder.'}
$status=if($missing.Count -eq 0){
    if($outcome.targeted -eq $true){'SELECTED_CSV_FILES_PRESENT'}
    else{'TEN_CSV_FILES_PRESENT'}
}else{'INCOMPLETE_FORENSIC_EVIDENCE'}
$manifest=@(
    'QTS GOLD - LOCAL RESEARCH EVIDENCE',
    'LIVE LOCKED. NO PROFITABLE EDGE VERIFIED.',
    'Package state: '+$status,
    'Run folder name: '+(Split-Path -Leaf $RunDirectory),
    'Included: only QTS research JSON and trade-level CSV.',
    'Excluded: MT5 native HTML, logins, terminal history, account statements, journals, passwords.',
    'Important: included CSV files may contain trade and broker-order IDs and comments.',
    'Missing forensic CSV: '+($(if($missing.Count){$missing -join ', '}else{'none'})),
    'Broker exit reason identifies SL/TP, but does not establish signal quality.',
    'Never interpret missing trade data as zero trades or trading approval.'
) -join [Environment]::NewLine
$out=Join-Path $RunDirectory 'QTS_SHARE_RESULTS.zip'
$temporary=$out+'.tmp'
if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Force}
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=$null
try{
    $archive=[System.IO.Compression.ZipFile]::Open($temporary,[System.IO.Compression.ZipArchiveMode]::Create)
    $txt=$archive.CreateEntry('README_EVIDENCE.txt',[System.IO.Compression.CompressionLevel]::Optimal)
    $writer=[System.IO.StreamWriter]::new($txt.Open(),[Text.UTF8Encoding]::new($false))
    try{$writer.Write($manifest)}finally{$writer.Dispose()}
    foreach($pair in $allowed){
        $file=[string]$pair[0];$entry=[string]$pair[1]
        [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,$file,$entry,[System.IO.Compression.CompressionLevel]::Optimal)
    }
}finally{
    if($archive){$archive.Dispose()}
}
if((Get-Item -LiteralPath $temporary).Length -lt 100){
    throw 'Evidence ZIP is unexpectedly small; not publishing an empty package.'
}
Move-Item -LiteralPath $temporary -Destination $out -Force
Write-Host ('QTS_SHARE_RESULTS: '+$status)
Write-Host ('File: '+$out)
Write-Host ('Included evidence files: '+$allowed.Count)
if($missing.Count -gt 0){
    Write-Warning ('The following strategy deal files are MISSING: '+($missing -join ', '))
}
Write-Host 'Share only this ZIP for trade-by-trade review. It contains no native MT5 HTML/account report.'
if(-not $NoOpen){Invoke-Item -LiteralPath $RunDirectory}
