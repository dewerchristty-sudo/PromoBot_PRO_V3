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

$DockerEnv = Join-Path $DistDir "docker\evolution\.env"
if (Test-Path $DockerEnv) {
    Copy-Item $DockerEnv (Join-Path $BackupDir "docker-evolution.env") -Force
}

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias." }

python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar browsers do Playwright." }

python -m PyInstaller PromoBot_PRO_V3.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar executavel." }

$DockerDistDir = Join-Path $DistDir "docker\evolution"
New-Item -ItemType Directory -Path $DockerDistDir -Force | Out-Null
Copy-Item "docker\evolution\docker-compose.yml" $DockerDistDir -Force
$DockerEnvBackup = Join-Path $BackupDir "docker-evolution.env"
if (Test-Path $DockerEnvBackup) {
    Copy-Item $DockerEnvBackup (Join-Path $DockerDistDir ".env") -Force
} else {
    Copy-Item "docker\evolution\.env" $DockerDistDir -Force
}

foreach ($FileName in @(".env", "promobot.db")) {
    $Backup = Join-Path $BackupDir $FileName

    if (Test-Path $Backup) {
        Copy-Item $Backup (Join-Path $DistDir $FileName) -Force
    }
}

$ShortcutResult = & ".\scripts\ensure_desktop_shortcut.ps1" `
    -TargetPath (Join-Path $DistDir "PromoBot_PRO_V3.exe") `
    -WorkingDirectory $DistDir `
    -IconLocation "$(Join-Path $DistDir 'PromoBot_PRO_V3.exe'),0"

Write-Host ""
Write-Host "Build concluido. Executavel em: dist\PromoBot_PRO_V3\PromoBot_PRO_V3.exe"
Write-Host "Atalho PromoBot_PRO_V3.lnk: $ShortcutResult"
