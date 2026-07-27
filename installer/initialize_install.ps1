param(
    [Parameter(Mandatory = $true)]
    [string]$AppDirectory
)

$ErrorActionPreference = "Stop"

$AppDirectory = [IO.Path]::GetFullPath($AppDirectory)
$TemplateDirectory = Join-Path $AppDirectory "installer"
$AppEnv = Join-Path $AppDirectory ".env"
$EvolutionDirectory = Join-Path $AppDirectory "docker\evolution"
$EvolutionEnv = Join-Path $EvolutionDirectory ".env"

New-Item -ItemType Directory -Path $EvolutionDirectory -Force | Out-Null

$apiKey = ""
if (Test-Path -LiteralPath $AppEnv) {
    $configuredKey = Get-Content -LiteralPath $AppEnv |
        Where-Object { $_ -match "^EVOLUTION_API_KEY=" } |
        Select-Object -First 1
    if ($configuredKey) {
        $apiKey = ($configuredKey -split "=", 2)[1].Trim()
    }
}

if (-not $apiKey) {
    $apiKey = [Guid]::NewGuid().ToString("N")
}

if (-not (Test-Path -LiteralPath $AppEnv)) {
    $template = Get-Content -Raw -LiteralPath (
        Join-Path $TemplateDirectory "app.env.template"
    )
    $template = $template.Replace("__EVOLUTION_API_KEY__", $apiKey)
    Set-Content -LiteralPath $AppEnv -Value $template -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $EvolutionEnv)) {
    $template = Get-Content -Raw -LiteralPath (
        Join-Path $TemplateDirectory "evolution.env.template"
    )
    $template = $template.Replace("__EVOLUTION_API_KEY__", $apiKey)
    Set-Content -LiteralPath $EvolutionEnv -Value $template -Encoding UTF8
}
