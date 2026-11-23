[CmdletBinding()]
param(
    [ValidateSet("all", "fase0", "selfcheck", "tier1", "tier2", "tier3", "tier4", "collect")]
    [string]$Tier = "all",
    [switch]$InProcess,
    [switch]$SkipLint
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PytestExe = Join-Path $RepoRoot "backend\.venv\Scripts\pytest.exe"
$RuffExe = Join-Path $RepoRoot "backend\.venv\Scripts\ruff.exe"
$PytestIni = Join-Path $PSScriptRoot "pytest.ini"

if (-not (Test-Path $PytestExe)) {
    throw "pytest not found at $PytestExe. Ensure backend\.venv is created."
}
if (-not (Test-Path $RuffExe)) {
    throw "ruff not found at $RuffExe. Ensure backend\.venv is created."
}

Push-Location $RepoRoot
try {
    if (-not $SkipLint) {
        Write-Host "==> Running ruff check on tests_e2e..." -ForegroundColor Cyan
        & $RuffExe check tests_e2e
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    if ($InProcess) {
        $env:SAPEF_E2E_INPROCESS = "1"
    }

    $PytestArgs = @("-c", $PytestIni)
    switch ($Tier) {
        "collect"   { $PytestArgs += @("tests_e2e", "--collect-only") }
        "selfcheck" { $PytestArgs += @("tests_e2e/test_harness_selfcheck.py", "-v") }
        "fase0"     { $PytestArgs += @("tests_e2e/test_fase0_live_contract.py", "-v") }
        "tier1"     { $PytestArgs += @("tests_e2e", "-m", "tier1", "-v") }
        "tier2"     { $PytestArgs += @("tests_e2e", "-m", "tier2", "-v") }
        "tier3"     { $PytestArgs += @("tests_e2e", "-m", "tier3", "-v") }
        "tier4"     { $PytestArgs += @("tests_e2e", "-m", "tier4", "-v") }
        "all"       { $PytestArgs += @("tests_e2e", "-v") }
    }

    Write-Host "==> Running pytest ($Tier)..." -ForegroundColor Cyan
    & $PytestExe @PytestArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
