---
name: security-auditor
description: >-
  Use this skill to audit repository security, scan for secrets,
  verify TLS transport configurations, and detect vulnerable dependencies.
---

# Security Auditor Runbook (Agent 13)

## Mission
Protect system credentials, live broker keys, and infrastructure against unauthorized access, leaks, and vulnerabilities. Enforce TRD-SEC-1 and NFR-SEC-1.

---

## 1. Security Audit Procedures

### 1.1 Secret Scanning
- Ensure zero plaintext credentials exist in:
  - Source code (`src/`, `tests/`, `scripts/`)
  - Configuration files (`.env`, `pyproject.toml`)
  - Commit history (all branches)
- Pre-commit scanning must be active via Gitleaks and detect-secrets.

### 1.2 Credential Masking in Memory & Logs
- All API keys, secrets, and database passwords must use Pydantic's `SecretStr`.
- Verify that calling `str(config)` or logging `AppConfig` yields `***` for sensitive attributes.

### 1.3 Transport Security
- Enforce TLS 1.3 verification for all external HTTP requests (`httpx.AsyncClient(verify=True)`).
- Enforce WSS (Secure WebSocket) for all real-time market data and broker order streams.

### 1.4 Dependency Auditing
- Regularly scan installed packages against known CVE vulnerability databases using `pip-audit`.

---

## 2. Security Audit Commands

```powershell
# 1. Run local secret detection scan across repository
gitleaks detect --verbose --redact

# 2. Run pre-commit hooks to verify staged files
pre-commit run gitleaks --all-files

# 3. Scan dependencies for known security vulnerabilities
pip-audit --desc

# 4. Check for insecure HTTP connections in source code
Select-String -Path .\src\*.py, .\scripts\*.py -Pattern "http://"
```

---

## 3. Security Incident & Rejection Protocol

If a secret or critical CVE is detected:
1. Immediately block the PR or commit.
2. Invalidate and rotate the affected API key or secret immediately.
3. Remove the secret from Git history using `git-filter-repo` or BFG Repo-Cleaner.
4. Issue an incident report detailing the root cause and mitigation.
