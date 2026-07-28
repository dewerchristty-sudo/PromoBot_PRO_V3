$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExePath = Join-Path $ProjectRoot "dist\PromoBot_PRO_V3\PromoBot_PRO_V3.exe"

if (-not (Test-Path $ExePath)) {
    throw "Executavel nao encontrado. Rode .\scripts\build_exe.ps1 primeiro."
}

$EnsureScript = Join-Path $PSScriptRoot "ensure_desktop_shortcut.ps1"
$Result = & $EnsureScript `
    -TargetPath $ExePath `
    -WorkingDirectory (Split-Path -Parent $ExePath) `
    -IconLocation "$ExePath,0"

Write-Host "Atalho PromoBot_PRO_V3.lnk: $Result"
