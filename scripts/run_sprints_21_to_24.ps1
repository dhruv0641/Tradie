<#
.SYNOPSIS
    Automated pipeline runner for Sprint S21 through Sprint S24.
.DESCRIPTION
    Companion automation script for AUTONOMOUS_RUN_S21_TO_S24.md.
    Verifies baseline health, monitors pipeline progress, and executes regression test suites.
.EXAMPLE
    .\scripts\run_sprints_21_to_24.ps1
#>

$ErrorActionPreference = "Stop"
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Autonomous Pipeline Runner: S21 -> S24" -ForegroundColor Cyan
Write-Host " Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# 1. Ensure on implementation-develop branch
$currentBranch = (git branch --show-current).Trim()
if ($currentBranch -ne "implementation-develop") {
    Write-Host "Switching to branch 'implementation-develop'..." -ForegroundColor Yellow
    git checkout implementation-develop
}

# 2. Baseline Quality and Regression Verification
Write-Host "--> Step 0: Baseline Regression Test Suite Verification..." -ForegroundColor Green
uv run pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Baseline regression suite failed!"
    exit 1
}

Write-Host "--> Running Safety Architecture Isolation Linter..." -ForegroundColor Green
uv run python scripts/verify_safety_isolation.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Safety isolation linter failed!"
    exit 1
}

Write-Host "--> Running Pre-Commit Hooks & Secret Scans..." -ForegroundColor Green
uv run pre-commit run --all-files
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pre-commit checks failed!"
    exit 1
}

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " BASELINE HEALTHY: READY TO EXECUTE S21 -> S24" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
