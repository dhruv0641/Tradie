#!/usr/bin/env bash
# scripts/restore_db.sh — Database disaster recovery restore wrapper script
# Enforces TRD-DR-1, TRD-DATA-5, NFR-REL-6, and TTD §15

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup-archive.sql.gz> [manifest.sha256]"
  exit 1
fi

ARCHIVE="$1"
MANIFEST="${2:-}"

DB_HOST="${DATABASE_HOST:-localhost}"
DB_PORT="${DATABASE_PORT:-5432}"
DB_NAME="${DATABASE_NAME:-aitrader}"
DB_USER="${DATABASE_USER:-postgres}"

echo "[INFO] Running AI Trader Disaster Recovery Database Restoration from ${ARCHIVE}..."

if [ -n "${MANIFEST}" ]; then
  python -m scripts.restore_db \
    --archive "${ARCHIVE}" \
    --manifest "${MANIFEST}" \
    --database "${DB_NAME}" \
    --host "${DB_HOST}" \
    --port "${DB_PORT}" \
    --user "${DB_USER}"
else
  python -m scripts.restore_db \
    --archive "${ARCHIVE}" \
    --database "${DB_NAME}" \
    --host "${DB_HOST}" \
    --port "${DB_PORT}" \
    --user "${DB_USER}"
fi

echo "[INFO] Database disaster recovery restore completed successfully."
