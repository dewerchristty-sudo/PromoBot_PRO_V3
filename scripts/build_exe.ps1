$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install -r requirements.txt
python -m playwright install chromium
python -m PyInstaller PromoBot_PRO_V3.spec --clean --noconfirm

Write-Host ""
Write-Host "Build concluido. Executavel em: dist\PromoBot_PRO_V3\PromoBot_PRO_V3.exe"
