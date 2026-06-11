[CmdletBinding()]
param(
    [string]$AddonsDirectory = "$env:APPDATA\Anki2\addons21",
    [string]$PackageDirectoryName = "anki_lookup_dev",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Root "src\anki_lookup"
$Destination = Join-Path $AddonsDirectory $PackageDirectoryName

if (-not (Test-Path -LiteralPath $AddonsDirectory -PathType Container)) {
    throw "Anki add-ons directory not found: $AddonsDirectory"
}

$ResolvedAddonsDirectory = [System.IO.Path]::GetFullPath($AddonsDirectory).TrimEnd('\')
$ResolvedDestination = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
$ExpectedParent = [System.IO.Directory]::GetParent($ResolvedDestination).FullName.TrimEnd('\')

if ($ExpectedParent -ne $ResolvedAddonsDirectory) {
    throw "Refusing to install outside the configured add-ons directory: $ResolvedDestination"
}

if (Test-Path -LiteralPath $ResolvedDestination) {
    if (-not $Force) {
        throw "Development add-on already exists: $ResolvedDestination. Re-run with -Force to replace it."
    }

    Remove-Item -LiteralPath $ResolvedDestination -Recurse -Force
}

Copy-Item -LiteralPath $Source -Destination $ResolvedDestination -Recurse
Write-Host "Installed Anki Lookup development package at $ResolvedDestination"
Write-Host "Restart Anki to load the add-on."
