$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExePath = Join-Path $ProjectRoot "dist\PromoBot_PRO_V3\PromoBot_PRO_V3.exe"

if (-not (Test-Path $ExePath)) {
    throw "Executavel nao encontrado. Rode .\scripts\build_exe.ps1 primeiro."
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "PromoBot_PRO_V3.lnk"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
$Shortcut.Description = "PromoBot_PRO V3"
$Shortcut.Save()

Write-Host "Atalho criado em: $ShortcutPath"
