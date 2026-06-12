[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TemporaryRoot = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("anki-lookup-install-test-" + [guid]::NewGuid().ToString("N"))
$ResolvedTemporaryRoot = [System.IO.Path]::GetFullPath($TemporaryRoot)

New-Item -ItemType Directory -Path $ResolvedTemporaryRoot | Out-Null
try {
    & "$PSScriptRoot\install-dev.ps1" `
        -AddonsDirectory $ResolvedTemporaryRoot `
        -PackageDirectoryName "test_addon"

    $Marker = Join-Path $ResolvedTemporaryRoot "test_addon\user_files\marker.bin"
    [System.IO.File]::WriteAllBytes($Marker, [byte[]](1, 2, 3, 4))

    & "$PSScriptRoot\install-dev.ps1" `
        -AddonsDirectory $ResolvedTemporaryRoot `
        -PackageDirectoryName "test_addon" `
        -Force

    $MarkerBytes = [System.IO.File]::ReadAllBytes($Marker)
    if (($MarkerBytes -join ",") -ne "1,2,3,4") {
        throw "Forced development installation did not preserve user_files."
    }
    Write-Host "Verified development installation preserves user_files."
}
finally {
    $ResolvedTarget = [System.IO.Path]::GetFullPath($ResolvedTemporaryRoot)
    $ResolvedSystemTemp = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    ).TrimEnd("\")
    if (-not $ResolvedTarget.StartsWith("$ResolvedSystemTemp\")) {
        throw "Refusing to remove an install test directory outside the system temp path."
    }
    if (Test-Path -LiteralPath $ResolvedTarget) {
        Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
    }
}
