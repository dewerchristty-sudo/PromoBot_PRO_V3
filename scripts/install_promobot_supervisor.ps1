param(
    [Parameter(Mandatory = $true)]
    [string]$PromoBotExe
)

$ErrorActionPreference = "Stop"
$TaskName = "PromoBot_PRO_V3 Supervisor"
$SourceSupervisor = Join-Path $PSScriptRoot "promobot_supervisor.ps1"

if (-not (Test-Path -LiteralPath $PromoBotExe -PathType Leaf)) {
    throw "Executavel do PromoBot nao encontrado: $PromoBotExe"
}

if (-not (Test-Path -LiteralPath $SourceSupervisor -PathType Leaf)) {
    throw "Supervisor nao encontrado: $SourceSupervisor"
}

$PromoBotExe = (Resolve-Path -LiteralPath $PromoBotExe).Path
$PromoBotDirectory = Split-Path -Parent $PromoBotExe
$EvolutionDirectory = Join-Path $PromoBotDirectory "docker\evolution"

if (-not (Test-Path -LiteralPath (Join-Path $EvolutionDirectory "docker-compose.yml"))) {
    throw "Evolution API nao encontrada em: $EvolutionDirectory"
}

$InstallDirectory = Join-Path $env:LOCALAPPDATA "PromoBot_PRO_V3\supervisor"
New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
$InstalledSupervisor = Join-Path $InstallDirectory "promobot_supervisor.ps1"
$HiddenRunner = Join-Path $InstallDirectory "run_supervisor_hidden.vbs"
Copy-Item -LiteralPath $SourceSupervisor -Destination $InstalledSupervisor -Force

$PowerShellExe = (Get-Command powershell.exe).Source
$powerShellArguments = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy Bypass",
    "-File `"$InstalledSupervisor`"",
    "-PromoBotExe `"$PromoBotExe`"",
    "-EvolutionDirectory `"$EvolutionDirectory`""
) -join " "

# O Windows Terminal pode ignorar -WindowStyle Hidden. O VBScript inicia o
# PowerShell com visibilidade zero, evitando qualquer janela no logon.
$hiddenCommand = "`"$PowerShellExe`" $powerShellArguments"
$escapedCommand = $hiddenCommand.Replace('"', '""')
$vbsContent = "CreateObject(""WScript.Shell"").Run ""$escapedCommand"", 0, False"
Set-Content -LiteralPath $HiddenRunner -Value $vbsContent -Encoding ASCII

$WscriptExe = Join-Path $env:SystemRoot "System32\wscript.exe"
$action = New-ScheduledTaskAction `
    -Execute $WscriptExe `
    -Argument "`"$HiddenRunner`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Mantem PromoBot e Evolution API funcionando e recupera quedas automaticamente." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Supervisor instalado e iniciado."
Write-Host "Tarefa: $TaskName"
Write-Host "Logs: $InstallDirectory\supervisor.log"
