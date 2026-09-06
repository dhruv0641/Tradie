"""Automated database restoration and integrity verification script.

Adheres strictly to TRD-DR-1, TRD-DATA-5, NFR-REL-6, and TTD §15.
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

import structlog

from scripts.backup_db import compute_sha256

logger = structlog.get_logger("scripts.restore_db")


class IntegrityError(Exception):
    """Raised when backup archive checksum verification fails or payload is corrupt."""


class RestoreError(Exception):
    """Raised when database restoration fails during decompression or execution."""


def verify_backup_integrity(
    archive_path: Path | str,
    manifest_path: Path | str | None = None,
) -> str:
    """Verify cryptographic SHA-256 integrity of a backup archive against its manifest.

    Args:
        archive_path: Path to the compressed backup file (.sql.gz).
        manifest_path: Path to the .sha256 manifest. Defaults to archive_path + '.sha256'.

    Returns:
        str: Verified SHA-256 hex digest.

    Raises:
        FileNotFoundError: If the archive or manifest file does not exist.
        IntegrityError: If computed hash differs from manifest or file is empty.
    """
    archive = Path(archive_path)
    if not archive.is_file():
        raise FileNotFoundError(f"Backup archive not found: {archive}")

    manifest = (
        Path(manifest_path) if manifest_path else archive.with_suffix(archive.suffix + ".sha256")
    )
    if not manifest.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest}")

    # Read manifest expected digest
    manifest_line = manifest.read_text(encoding="utf-8").strip()
    if not manifest_line:
        raise IntegrityError(f"Manifest file is empty: {manifest}")

    expected_hash = manifest_line.split()[0].lower()

    # Recompute archive digest
    actual_hash = compute_sha256(archive).lower()

    if actual_hash != expected_hash:
        logger.error(
            "backup_integrity_verification_failed",
            archive=str(archive),
            expected_hash=expected_hash,
            actual_hash=actual_hash,
        )
        msg = (
            f"Cryptographic SHA-256 integrity mismatch for {archive.name}!\n"
            f"Expected: {expected_hash}\n"
            f"Actual:   {actual_hash}\n"
            f"Potential data corruption or unauthorized tampering detected."
        )
        raise IntegrityError(msg)

    logger.info(
        "backup_integrity_verified",
        archive=str(archive),
        sha256=actual_hash,
    )
    return actual_hash


def execute_restore(
    archive_path: Path | str,
    manifest_path: Path | str | None = None,
    database: str = "aitrader",
    host: str = "localhost",
    port: int = 5432,
    user: str = "postgres",
    password: str | None = None,
    verify_only: bool = False,
    mock_executor: bool = False,
) -> bool:
    """Verify integrity and restore database from a compressed backup archive.

    Args:
        archive_path: Path to the backup archive (.sql.gz).
        manifest_path: Path to manifest file (optional).
        database: Target PostgreSQL database.
        host: Database host.
        port: Database port.
        user: Database user.
        password: Database password.
        verify_only: If True, performs cryptographic verification and stops.
        mock_executor: If True, decompress and validate without calling psql (for unit tests).

    Returns:
        bool: True if restore was successful.

    Raises:
        IntegrityError: If checksum verification fails.
        RestoreError: If decompressing or psql execution fails.
    """
    archive = Path(archive_path)

    # 1. Non-negotiable cryptographic integrity verification (TRD-DR-1, NFR-REL-6)
    verify_backup_integrity(archive, manifest_path=manifest_path)

    if verify_only:
        logger.info("backup_verification_passed_verify_only_mode", archive=str(archive))
        return True

    # 2. Decompress archive content
    try:
        with gzip.open(archive, "rb") as gz_in:
            sql_payload = gz_in.read()
    except Exception as exc:
        raise RestoreError(f"Failed to decompress archive {archive}: {exc}") from exc

    if not sql_payload:
        raise RestoreError(f"Decompressed SQL payload is empty from {archive}")

    # 3. Execute restore via psql
    if mock_executor:
        logger.info(
            "mock_database_restore_completed",
            archive=str(archive),
            payload_bytes=len(sql_payload),
        )
        return True

    psql_cmd = shutil.which("psql")
    if psql_cmd is None:
        raise RestoreError(
            "psql command line client not found on PATH. Ensure postgresql-client is installed."
        )

    cmd = [
        psql_cmd,
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
        "--single-transaction",
        "--set",
        "ON_ERROR_STOP=on",
    ]

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    result = subprocess.run(cmd, input=sql_payload, capture_output=True, env=env, check=False)
    if result.returncode != 0:
        err_msg = result.stderr.decode("utf-8", errors="replace")
        raise RestoreError(f"psql restore failed (exit {result.returncode}): {err_msg}")

    logger.info(
        "database_restore_completed",
        database=database,
        archive=str(archive),
        bytes_restored=len(sql_payload),
    )
    return True


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for restore script."""
    parser = argparse.ArgumentParser(description="AI Trader Automated Database Disaster Recovery")
    parser.add_argument("--archive", type=str, required=True, help="Path to .sql.gz archive")
    parser.add_argument("--manifest", type=str, default=None, help="Path to .sha256 manifest")
    parser.add_argument("--database", type=str, default="aitrader", help="Database name")
    parser.add_argument("--host", type=str, default="localhost", help="Database host")
    parser.add_argument("--port", type=int, default=5432, help="Database port")
    parser.add_argument("--user", type=str, default="postgres", help="Database username")
    parser.add_argument("--password", type=str, default=None, help="Database password")
    parser.add_argument(
        "--verify-only", action="store_true", help="Verify checksum without restoring"
    )
    return parser.parse_args()


def main() -> int:
    """Main CLI entrypoint."""
    args = parse_args()
    try:
        execute_restore(
            archive_path=args.archive,
            manifest_path=args.manifest,
            database=args.database,
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            verify_only=args.verify_only,
        )
        print("SUCCESS: Database disaster recovery restore completed successfully.")
        return 0
    except (IntegrityError, RestoreError, FileNotFoundError) as err:
        print(f"ERROR: Disaster recovery restore failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
