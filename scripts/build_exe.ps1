$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$DistDir = Join-Path (Get-Location) "dist\PromoBot_PRO_V3"
$BackupDir = Join-Path $env:TEMP "PromoBot_PRO_V3_runtime_backup"

if (Test-Path $BackupDir) {
    Remove-Item $BackupDir -Recurse -Force
}

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

foreach ($FileName in @(".env", "promobot.db")) {
    $Source = Join-Path $DistDir $FileName

    if (Test-Path $Source) {
        Copy-Item $Source (Join-Path $BackupDir $FileName) -Force
    }
}

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias." }

$env:PLAYWRIGHT_BROWSERS_PATH = "0"
python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar browsers do Playwright." }

python -m PyInstaller PromoBot_PRO_V3.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar executavel." }

foreach ($FileName in @(".env", "promobot.db")) {
    $Backup = Join-Path $BackupDir $FileName

    if (Test-Path $Backup) {
        Copy-Item $Backup (Join-Path $DistDir $FileName) -Force
    }
}

Write-Host ""
Write-Host "Build concluido. Executavel em: dist\PromoBot_PRO_V3\PromoBot_PRO_V3.exe"
