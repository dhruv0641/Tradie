<#
.SYNOPSIS
    Automates post-sprint verification, logging verification, and Git push to implementation-develop.
.DESCRIPTION
    Runs all quality tools (Ruff, Mypy, Pytest, Pre-commit), stages all changes, creates a standardized
    commit, and pushes to origin/implementation-develop.
.PARAMETER SprintId
    The ID of the completed sprint (e.g. "S01.01")
.PARAMETER SprintName
    The human-readable title of the sprint
.PARAMETER Summary
    Brief summary of changes implemented
.EXAMPLE
    .\scripts\deliver_sprint.ps1 -SprintId "S01.01" -SprintName "Repository Setup, Tooling & Quality Toolchain" -Summary "Setup Python 3.12, Ruff, Mypy, Pre-commit, Pytest"
#>
param (
    [Parameter(Mandatory=$true)]
    [string]$SprintId,

    [Parameter(Mandatory=$true)]
    [string]$SprintName,

    [Parameter(Mandatory=$false)]
    [string]$Summary = "Sprint completion"
)

$ErrorActionPreference = "Stop"
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Post-Sprint Delivery Pipeline: $SprintId" -ForegroundColor Cyan
Write-Host " Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# 1. Ensure on implementation-develop branch
$currentBranch = (git branch --show-current).Trim()
if ($currentBranch -ne "implementation-develop") {
    Write-Host "Switching to branch 'implementation-develop'..." -ForegroundColor Yellow
    git checkout implementation-develop
}

# 2. Run Ruff Lint & Format
Write-Host "--> Running Ruff Lint..." -ForegroundColor Green
uv run ruff check src tests
Write-Host "--> Running Ruff Format Check..." -ForegroundColor Green
uv run ruff format --check src tests

# 3. Run Mypy Strict Type Check
Write-Host "--> Running Mypy Strict Check..." -ForegroundColor Green
uv run mypy src tests

# 4. Verify Safety Architecture & Isolation
Write-Host "--> Running Safety Isolation & Precedence Linter..." -ForegroundColor Green
uv run python scripts/verify_safety_isolation.py

# 5. Run Pytest with Branch Coverage
Write-Host "--> Running Pytest with Branch Coverage..." -ForegroundColor Green
uv run pytest --cov=src --cov-branch --cov-report=term-missing

# 5. Run Pre-Commit Security & Secret Scans
Write-Host "--> Running Pre-Commit Hooks (including Gitleaks secret scan)..." -ForegroundColor Green
uv run pre-commit run --all-files

# 6. Stage All Changes
Write-Host "--> Staging changes in git..." -ForegroundColor Green
git add .

# 7. Commit
$commitMsg = "feat(sprint): complete $SprintId - $SprintName`n`nSummary: $Summary`nTimestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "--> Committing changes..." -ForegroundColor Green
git commit -m $commitMsg

# 8. Push to implementation-develop
Write-Host "--> Pushing to origin/implementation-develop..." -ForegroundColor Green
git push -u origin implementation-develop

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " SPRINT $SprintId SUCCESSFULLY DELIVERED & PUSHED" -ForegroundColor Green
Write-Host " Branch: implementation-develop" -ForegroundColor Green
Write-Host " Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Cyan
