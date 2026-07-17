$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$evolutionDir = Join-Path $root "docker\evolution"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker nao encontrado. Instale o Docker Desktop e abra ele antes de rodar este script."
    exit 1
}

Push-Location $evolutionDir
try {
    docker compose up -d
    Write-Host "Evolution API iniciada em http://localhost:8080"
}
finally {
    Pop-Location
}
