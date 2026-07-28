$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExe = Join-Path $SourceDir "PromoBot_PRO_V3.exe"
$TargetDir = Join-Path $env:LOCALAPPDATA "Programs\PromoBot_PRO_V3"
$TargetExe = Join-Path $TargetDir "PromoBot_PRO_V3.exe"

if (-not (Test-Path -LiteralPath $SourceExe)) {
    throw "Coloque este instalador ao lado de PromoBot_PRO_V3.exe e da pasta _internal."
}

New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
$ResolvedSource = (Resolve-Path -LiteralPath $SourceDir).Path.TrimEnd("\")
$ResolvedTarget = (Resolve-Path -LiteralPath $TargetDir).Path.TrimEnd("\")
if (-not $ResolvedSource.Equals($ResolvedTarget, [StringComparison]::OrdinalIgnoreCase)) {
    Copy-Item -Path (Join-Path $SourceDir "*") -Destination $TargetDir -Recurse -Force
}

$Shell = New-Object -ComObject WScript.Shell
$StartMenu = [Environment]::GetFolderPath("Programs")

$EnsureScript = Join-Path $PSScriptRoot "ensure_desktop_shortcut.ps1"
$ShortcutResult = & $EnsureScript `
    -TargetPath $TargetExe `
    -WorkingDirectory $TargetDir `
    -IconLocation "$TargetExe,0"

$StartMenuShortcut = Join-Path $StartMenu "PromoBot_PRO_V3.lnk"
$Shortcut = $Shell.CreateShortcut($StartMenuShortcut)
$Shortcut.TargetPath = $TargetExe
$Shortcut.Arguments = ""
$Shortcut.WorkingDirectory = $TargetDir
$Shortcut.IconLocation = "$TargetExe,0"
$Shortcut.Description = "PromoBot_PRO V3"
$Shortcut.Save()

Write-Host "PromoBot instalado em: $TargetDir"
Write-Host "Atalho da Area de Trabalho: $ShortcutResult"
Write-Host "Atalho do Menu Iniciar atualizado."
Write-Host "Copie seu arquivo .env para essa pasta antes de ativar notificacoes."
