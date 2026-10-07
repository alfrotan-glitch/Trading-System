# Creates Windows desktop shortcut for QTS Trading System
# Run in PowerShell: powershell -ExecutionPolicy Bypass -File scripts/create_shortcut.ps1
# This file MUST remain UTF-8 with BOM for Windows PowerShell 5.1 compatibility.

$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut("$Home\Desktop\QTS Trading System.lnk")
$Shortcut.TargetPath = "$PSScriptRoot\..\dist\QTS.exe"
$Shortcut.WorkingDirectory = "$PSScriptRoot\.."
$Shortcut.Description = "QTS Trading System — double-click to launch dashboard"
$Shortcut.IconLocation = "$PSScriptRoot\..\assets\qts.ico"
$Shortcut.Save()
Write-Host "Shortcut created at $Home\Desktop\QTS Trading System.lnk"
