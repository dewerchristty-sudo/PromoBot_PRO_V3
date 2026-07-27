param(
    [Parameter(Mandatory = $true)]
    [string]$PromoBotExe,

    [Parameter(Mandatory = $true)]
    [string]$EvolutionDirectory,

    [int]$CheckIntervalSeconds = 30,

    [string]$LogDirectory = ""
)

$ErrorActionPreference = "Stop"

if (-not $LogDirectory) {
    $LogDirectory = Join-Path $env:LOCALAPPDATA "PromoBot_PRO_V3\supervisor"
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$LogFile = Join-Path $LogDirectory "supervisor.log"
$Mutex = New-Object System.Threading.Mutex($false, "Local\PromoBot_PRO_V3_Supervisor")
$HasMutex = $false

function Write-SupervisorLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogFile -Value "[$timestamp] $Message" -Encoding UTF8

    if ((Get-Item -LiteralPath $LogFile).Length -gt 2MB) {
        $archive = Join-Path $LogDirectory "supervisor.previous.log"
        Copy-Item -LiteralPath $LogFile -Destination $archive -Force
        Clear-Content -LiteralPath $LogFile
    }
}

function Get-PromoBotProcess {
    $expectedPath = [IO.Path]::GetFullPath($PromoBotExe)
    return Get-Process -Name "PromoBot_PRO_V3" -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                [IO.Path]::GetFullPath($_.Path).Equals(
                    $expectedPath,
                    [StringComparison]::OrdinalIgnoreCase
                )
            }
            catch {
                $false
            }
        } |
        Select-Object -First 1
}

function Start-PromoBotIfNeeded {
    if (Get-PromoBotProcess) {
        return
    }

    if (-not (Test-Path -LiteralPath $PromoBotExe -PathType Leaf)) {
        Write-SupervisorLog "ERRO: executavel nao encontrado: $PromoBotExe"
        return
    }

    $workingDirectory = Split-Path -Parent $PromoBotExe
    Start-Process -FilePath $PromoBotExe -WorkingDirectory $workingDirectory
    Write-SupervisorLog "PromoBot iniciado automaticamente."
}

function Test-EvolutionApi {
    try {
        $response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "http://localhost:8080" `
            -TimeoutSec 5
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Test-InternetConnection {
    $client = $null
    try {
        # Test-NetConnection exibe uma tela de progresso no Windows Terminal.
        # TcpClient faz o mesmo teste silenciosamente e com timeout curto.
        $client = New-Object System.Net.Sockets.TcpClient
        $connection = $client.BeginConnect("1.1.1.1", 443, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(3000, $false)) {
            return $false
        }
        $client.EndConnect($connection)
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        if ($client) {
            $client.Close()
        }
    }
}

function Start-DockerDesktopIfNeeded {
    if (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue) {
        return $true
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe")
    )
    $dockerDesktop = $candidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1

    if (-not $dockerDesktop) {
        Write-SupervisorLog "ERRO: Docker Desktop nao encontrado."
        return $false
    }

    # O backend precisa estar ativo, mas o painel nao precisa aparecer.
    Start-Process `
        -FilePath $dockerDesktop `
        -ArgumentList "--minimized" `
        -WindowStyle Minimized
    Write-SupervisorLog "Docker Desktop iniciado automaticamente em segundo plano."
    return $true
}

function Start-EvolutionIfNeeded {
    if (Test-EvolutionApi) {
        return
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-SupervisorLog "ERRO: comando docker nao encontrado."
        return
    }

    if (-not (Test-Path -LiteralPath (Join-Path $EvolutionDirectory "docker-compose.yml"))) {
        Write-SupervisorLog "ERRO: docker-compose.yml nao encontrado em $EvolutionDirectory"
        return
    }

    $dockerReady = $false
    try {
        docker info *> $null
        $dockerReady = $LASTEXITCODE -eq 0
    }
    catch {
        $dockerReady = $false
    }

    if (-not $dockerReady) {
        if (-not (Start-DockerDesktopIfNeeded)) {
            return
        }
        Write-SupervisorLog "Aguardando o Docker ficar pronto."
        return
    }

    try {
        docker compose --project-directory $EvolutionDirectory up -d *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-SupervisorLog "Evolution API recuperada automaticamente."
        }
        else {
            Write-SupervisorLog "ERRO: docker compose retornou codigo $LASTEXITCODE."
        }
    }
    catch {
        Write-SupervisorLog "ERRO ao recuperar Evolution API: $($_.Exception.Message)"
    }
}

try {
    $HasMutex = $Mutex.WaitOne(0, $false)
    if (-not $HasMutex) {
        exit 0
    }

    Write-SupervisorLog "Supervisor iniciado."
    $internetWasDown = $false

    while ($true) {
        try {
            Start-PromoBotIfNeeded

            $internetAvailable = Test-InternetConnection
            if (-not $internetAvailable) {
                if (-not $internetWasDown) {
                    Write-SupervisorLog "Internet indisponivel; aguardando reconexao."
                }
                $internetWasDown = $true
            }
            else {
                if ($internetWasDown) {
                    Write-SupervisorLog "Internet restabelecida; operacao retomada."
                }
                $internetWasDown = $false
                Start-EvolutionIfNeeded
            }
        }
        catch {
            Write-SupervisorLog "ERRO no ciclo do supervisor: $($_.Exception.Message)"
        }

        Start-Sleep -Seconds ([Math]::Max($CheckIntervalSeconds, 10))
    }
}
finally {
    if ($HasMutex) {
        $Mutex.ReleaseMutex()
    }
    $Mutex.Dispose()
}
