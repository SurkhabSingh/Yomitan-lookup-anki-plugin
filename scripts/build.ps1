[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Push-Location $Root
try {
    $Archive = python .\scripts\build_package.py
    if ($LASTEXITCODE -ne 0) {
        throw "Package build failed."
    }

    python .\scripts\verify_package.py $Archive
    if ($LASTEXITCODE -ne 0) {
        throw "Package verification failed."
    }
}
finally {
    Pop-Location
}

