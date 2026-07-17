$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias." }

$env:PLAYWRIGHT_BROWSERS_PATH = "0"
python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar browsers do Playwright." }

python -m PyInstaller PromoBot_PRO_V3.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar executavel." }

Write-Host ""
Write-Host "Build concluido. Executavel em: dist\PromoBot_PRO_V3\PromoBot_PRO_V3.exe"
