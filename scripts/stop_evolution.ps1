$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$evolutionDir = Join-Path $root "docker\evolution"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker nao encontrado."
    exit 1
}

Push-Location $evolutionDir
try {
    docker compose down
    Write-Host "Evolution API parada."
}
finally {
    Pop-Location
}
