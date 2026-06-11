[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Push-Location $Root
try {
    python .\scripts\check_sources.py
    if ($LASTEXITCODE -ne 0) { throw "Source validation failed." }

    python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff linting failed." }

    python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff formatting check failed." }

    python -m mypy
    if ($LASTEXITCODE -ne 0) { throw "Mypy type checking failed." }

    python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }

    & .\scripts\build.ps1
}
finally {
    Pop-Location
}

