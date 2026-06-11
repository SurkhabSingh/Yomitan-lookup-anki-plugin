[CmdletBinding()]
param(
    [string]$AnkiPython = "$env:LOCALAPPDATA\AnkiProgramFiles\.venv\Scripts\python.exe",
    [string]$AddonsDirectory = "$env:APPDATA\Anki2\addons21",
    [string]$PackageDirectoryName = "anki_lookup_dev"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath $AnkiPython -PathType Leaf)) {
    throw "Anki Python runtime not found: $AnkiPython"
}

if (-not (Test-Path -LiteralPath (Join-Path $AddonsDirectory $PackageDirectoryName))) {
    throw "Development add-on not found. Run .\scripts\install-dev.ps1 first."
}

$env:QT_QPA_PLATFORM = "offscreen"
& $AnkiPython "$Root\scripts\smoke_test_anki_runtime.py" `
    --addons-directory $AddonsDirectory `
    --package $PackageDirectoryName

if ($LASTEXITCODE -ne 0) {
    throw "Anki runtime smoke test failed."
}

