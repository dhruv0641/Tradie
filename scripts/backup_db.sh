#!/usr/bin/env bash
# scripts/backup_db.sh — Automated database backup wrapper script
# Enforces TRD-DR-1, TRD-DATA-5, NFR-REL-6, and TTD §15

set -euo pipefail

DB_HOST="${DATABASE_HOST:-localhost}"
DB_PORT="${DATABASE_PORT:-5432}"
DB_NAME="${DATABASE_NAME:-aitrader}"
DB_USER="${DATABASE_USER:-postgres}"
BACKUP_DIR="${BACKUP_DIR:-backups}"

echo "[INFO] Running AI Trader Database Backup..."
python -m scripts.backup_db \
  --output-dir "${BACKUP_DIR}" \
  --database "${DB_NAME}" \
  --host "${DB_HOST}" \
  --port "${DB_PORT}" \
  --user "${DB_USER}"

echo "[INFO] Database backup completed successfully."
