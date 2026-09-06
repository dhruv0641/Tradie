<#
.SYNOPSIS
    Automated pipeline runner for Sprint S18 through Sprint S20.
.DESCRIPTION
    Companion automation script for AUTONOMOUS_RUN_S18_TO_S20.md.
    Verifies S18 preconditions, monitors pipeline progress, and executes regression test suites.
.EXAMPLE
    .\scripts\run_sprints_18_to_20.ps1
#>

$ErrorActionPreference = "Stop"
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Autonomous Pipeline Runner: S18 -> S20" -ForegroundColor Cyan
Write-Host " Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# 1. Ensure on implementation-develop branch
$currentBranch = (git branch --show-current).Trim()
if ($currentBranch -ne "implementation-develop") {
    Write-Host "Switching to branch 'implementation-develop'..." -ForegroundColor Yellow
    git checkout implementation-develop
}

# Ensure simulation credentials for S18 precondition verification if unset
if (-not $env:BROKER_API_KEY) {
    $env:BROKER_API_KEY = "sandbox_sim_key"
}
if (-not $env:BROKER_API_SECRET) {
    $env:BROKER_API_SECRET = "sandbox_sim_secret"
}

# 2. Step 0: S18 Gate G5 Live Preconditions Verification
Write-Host "--> Step 0: Verifying S18 Live Preconditions & Safety Gate..." -ForegroundColor Green
uv run python scripts/verify_live_preconditions.py --json
if ($LASTEXITCODE -ne 0) {
    Write-Error "S18 Preconditions verification failed!"
    exit 1
}

Write-Host "--> Running S18 Live Activation Integration Tests..." -ForegroundColor Green
uv run pytest tests/integration/test_live_activation.py -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Live activation integration tests failed!"
    exit 1
}

# 3. Step 0 Full Suite Sanity
Write-Host "--> Running Full Regression Test Suite..." -ForegroundColor Green
uv run pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pytest regression suite failed!"
    exit 1
}

Write-Host "--> Running Safety Architecture Isolation Linter..." -ForegroundColor Green
uv run python scripts/verify_safety_isolation.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Safety isolation linter failed!"
    exit 1
}

Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Host " S18 GATE G5 VERIFIED HEALTHY & READY" -ForegroundColor Green
Write-Host " Proceeding with Autonomous Execution Directive" -ForegroundColor Green
Write-Host " File: AUTONOMOUS_RUN_S18_TO_S20.md" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
