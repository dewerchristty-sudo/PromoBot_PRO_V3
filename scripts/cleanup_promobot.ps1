param(
    [int]$BuildRetentionDays = 7,
    [int]$LogRetentionDays = 30,
    [int]$BackupsToKeep = 3
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$ProjectPrefix = $ProjectRoot.TrimEnd("\") + "\"
$cutoffBuild = (Get-Date).AddDays(-[math]::Max($BuildRetentionDays, 1))
$cutoffLog = (Get-Date).AddDays(-[math]::Max($LogRetentionDays, 1))
$removed = 0

function Remove-SafeItem {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return
    }

    $resolved = (Resolve-Path -LiteralPath $LiteralPath).Path
    if (-not $resolved.StartsWith(
        $ProjectPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Limpeza recusada fora do projeto: $resolved"
    }

    Remove-Item -LiteralPath $resolved -Recurse -Force
    $script:removed++
}

# Pastas build_* sao intermediarias de compilacao e nunca sao usadas
# pelo executavel instalado.
Get-ChildItem -LiteralPath $ProjectRoot -Directory -Filter "build_*" |
    Where-Object { $_.LastWriteTime -lt $cutoffBuild } |
    ForEach-Object { Remove-SafeItem -LiteralPath $_.FullName }

# Caches Python podem ser recriados automaticamente.
Get-ChildItem -LiteralPath $ProjectRoot -Directory -Filter "__pycache__" -Recurse |
    ForEach-Object { Remove-SafeItem -LiteralPath $_.FullName }

# Logs antigos, mantendo os arquivos recentes para diagnostico.
$logsDirectory = Join-Path $ProjectRoot "logs"
if (Test-Path -LiteralPath $logsDirectory) {
    Get-ChildItem -LiteralPath $logsDirectory -File |
        Where-Object { $_.LastWriteTime -lt $cutoffLog } |
        ForEach-Object { Remove-SafeItem -LiteralPath $_.FullName }
}

# Mantem os backups mais recentes em cada pasta de backup conhecida.
$backupDirectories = @(
    (Join-Path $ProjectRoot "backups")
)
Get-ChildItem -LiteralPath $ProjectRoot -Directory -Filter "dist_*" |
    ForEach-Object {
        $backupDirectories += Join-Path $_.FullName "PromoBot_PRO_V3\backups"
    }

foreach ($backupDirectory in ($backupDirectories | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $backupDirectory)) {
        continue
    }
    Get-ChildItem -LiteralPath $backupDirectory -File -Filter "*.db" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip ([math]::Max($BackupsToKeep, 1)) |
        ForEach-Object { Remove-SafeItem -LiteralPath $_.FullName }
}

Write-Output "Limpeza segura concluida. Itens removidos: $removed"
