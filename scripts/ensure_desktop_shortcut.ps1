param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,
    [string]$Arguments = "",
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory,
    [string]$IconLocation = "",
    [string]$DesktopPath = ""
)

$ErrorActionPreference = "Stop"
$OfficialName = "PromoBot_PRO_V3.lnk"
$Description = "PromoBot_PRO V3"

Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class PromoBotShortcutPath {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    public static extern uint GetShortPathName(
        string longPath, StringBuilder shortPath, uint bufferLength
    );
}
"@

function Normalize-Path([string]$PathValue) {
    if (-not $PathValue) { return "" }
    try {
        $fullPath = [IO.Path]::GetFullPath($PathValue).TrimEnd("\")
        $buffer = New-Object Text.StringBuilder 32768
        $length = [PromoBotShortcutPath]::GetShortPathName(
            $fullPath,
            $buffer,
            $buffer.Capacity
        )
        if ($length -gt 0) {
            return $buffer.ToString().TrimEnd("\")
        }
        return $fullPath
    } catch {
        return $PathValue.Trim().TrimEnd("\")
    }
}

function Same-Text([string]$Left, [string]$Right) {
    return [string]::Equals(
        $Left,
        $Right,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Normalize-Icon([string]$IconValue) {
    if (-not $IconValue) { return "" }
    $parts = $IconValue -split ",", 2
    $path = Normalize-Path $parts[0]
    $index = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "0" }
    return "$path,$index"
}

function Icon-Matches([string]$CurrentIcon, [string]$ExpectedIcon, [string]$ExpectedTarget) {
    if (Same-Text (Normalize-Icon $CurrentIcon) (Normalize-Icon $ExpectedIcon)) {
        return $true
    }
    $currentParts = $CurrentIcon -split ",", 2
    $expectedParts = $ExpectedIcon -split ",", 2
    $currentIndex = if ($currentParts.Count -gt 1) { $currentParts[1].Trim() } else { "0" }
    $expectedIndex = if ($expectedParts.Count -gt 1) { $expectedParts[1].Trim() } else { "0" }
    return (
        (Same-Text $currentIndex $expectedIndex) -and
        (Same-Text ([IO.Path]::GetFileName($currentParts[0])) ([IO.Path]::GetFileName($ExpectedTarget)))
    )
}

function Is-PromoBotShortcut($Shortcut, [string]$ExpectedTarget, [string]$ExpectedWorkDir) {
    $target = Normalize-Path $Shortcut.TargetPath
    $workDir = Normalize-Path $Shortcut.WorkingDirectory
    $targetName = [IO.Path]::GetFileName($target)
    $description = [string]$Shortcut.Description
    $arguments = [string]$Shortcut.Arguments

    if (Same-Text $target (Normalize-Path $ExpectedTarget)) { return $true }
    if (Same-Text $targetName "PromoBot_PRO_V3.exe") { return $true }
    return (
        $description -match "(?i)PromoBot" -and
        $arguments -match "(?i)(^|[\\\""\s])main\.py([\\\""\s]|$)" -and
        (Same-Text $workDir (Normalize-Path $ExpectedWorkDir))
    )
}

if (-not $DesktopPath) {
    $registryDesktop = try {
        (Get-ItemProperty -LiteralPath (
            "HKCU:\Software\Microsoft\Windows\CurrentVersion\" +
            "Explorer\User Shell Folders"
        ) -Name Desktop -ErrorAction Stop).Desktop
    } catch {
        ""
    }
    if ($registryDesktop) {
        $registryDesktop = [Environment]::ExpandEnvironmentVariables(
            $registryDesktop
        )
    }
    $oneDriveDesktop = if ($env:OneDrive) {
        Join-Path $env:OneDrive "Desktop"
    } else { "" }
    $profileDesktop = if ($env:USERPROFILE) {
        Join-Path $env:USERPROFILE "Desktop"
    } else { "" }
    $DesktopPath = @(
        $registryDesktop,
        [Environment]::GetFolderPath("Desktop"),
        $oneDriveDesktop,
        $profileDesktop
    ) | Where-Object {
        $_ -and (Test-Path -LiteralPath $_ -PathType Container)
    } | Select-Object -First 1
}
if (-not $DesktopPath) {
    throw "A pasta da Area de Trabalho nao foi encontrada."
}

$DesktopPath = [IO.Path]::GetFullPath($DesktopPath).TrimEnd("\")
$TargetPath = [IO.Path]::GetFullPath($TargetPath).TrimEnd("\")
$WorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory).TrimEnd("\")
if ($Arguments) {
    $Arguments = '"' + $Arguments.Trim().Trim('"') + '"'
}
if (-not $IconLocation) {
    $IconLocation = "$TargetPath,0"
}

if (-not (Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    New-Item -ItemType Directory -Path $DesktopPath -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) {
    throw "Destino do PromoBot nao encontrado: $TargetPath"
}
if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
    throw "Diretorio de trabalho nao encontrado: $WorkingDirectory"
}

$shell = New-Object -ComObject WScript.Shell
$officialPath = Join-Path $DesktopPath $OfficialName
$officialExisted = Test-Path -LiteralPath $officialPath
$changed = $false

$legacyPaths = Get-ChildItem -LiteralPath $DesktopPath -Filter "*.lnk" -File |
    Where-Object { -not (Same-Text $_.FullName $officialPath) } |
    Where-Object {
        try {
            $candidate = $shell.CreateShortcut($_.FullName)
            Is-PromoBotShortcut $candidate $TargetPath $WorkingDirectory
        } catch {
            $false
        }
    }

if (-not $officialExisted -and $legacyPaths) {
    Move-Item -LiteralPath $legacyPaths[0].FullName -Destination $officialPath
    $officialExisted = $true
    $changed = $true
    $legacyPaths = $legacyPaths | Select-Object -Skip 1
}

foreach ($legacyPath in $legacyPaths) {
    Remove-Item -LiteralPath $legacyPath.FullName -Force
    $changed = $true
}

$shortcut = $shell.CreateShortcut($officialPath)
if ($officialExisted -and -not [string]$shortcut.TargetPath) {
    # Recria atalhos corrompidos no mesmo caminho oficial. Alguns atalhos
    # antigos sem TargetPath nao aceitam reparo confiavel via Save().
    Remove-Item -LiteralPath $officialPath -Force
    $shortcut = $shell.CreateShortcut($officialPath)
    $changed = $true
}
$iconParts = $IconLocation -split ",", 2
$iconPath = [IO.Path]::GetFullPath($iconParts[0])
$iconIndex = if ($iconParts.Count -gt 1) { $iconParts[1].Trim() } else { "0" }
$iconToSave = "$iconPath,$iconIndex"
$expectedIcon = Normalize-Icon $iconToSave
$targetMatches = Same-Text (Normalize-Path $shortcut.TargetPath) (Normalize-Path $TargetPath)
$argumentsMatch = Same-Text ([string]$shortcut.Arguments) ([string]$Arguments)
$workDirMatches = Same-Text (Normalize-Path $shortcut.WorkingDirectory) (Normalize-Path $WorkingDirectory)
$iconMatches = Icon-Matches $shortcut.IconLocation $expectedIcon $TargetPath
$descriptionMatches = Same-Text ([string]$shortcut.Description) $Description
$configurationChanged = -not (
    $targetMatches -and
    $argumentsMatch -and
    $workDirMatches -and
    $iconMatches -and
    $descriptionMatches
)
Write-Verbose (
    "target={0}; arguments={1}; workdir={2}; icon={3}; description={4}" -f
    $targetMatches, $argumentsMatch, $workDirMatches, $iconMatches,
    $descriptionMatches
)
Write-Verbose (
    "current_target={0}; expected_target={1}" -f
    (Normalize-Path $shortcut.TargetPath), $TargetPath
)

if (-not $officialExisted -or $configurationChanged) {
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = $iconToSave
    $shortcut.Description = $Description
    $shortcut.Save()
    $changed = $true
}

if (-not $officialExisted) {
    Write-Output "criado"
} elseif ($changed) {
    Write-Output "atualizado"
} else {
    Write-Output "inalterado"
}
