"""Automated database backup and cryptographic snapshot generation script.

Adheres strictly to TRD-DR-1, TRD-DATA-5, NFR-REL-6, and TTD §15.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

logger = structlog.get_logger("scripts.backup_db")

DEFAULT_BACKUP_DIR = Path("backups")
CRITICAL_TABLES: tuple[str, ...] = (
    "decision_records",
    "positions",
    "orders",
    "trade_evaluations",
    "model_governance",
    "ohlcv_candles",
)


class BackupError(Exception):
    """Raised when backup generation, compression, or manifest hashing fails."""


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA-256 cryptographic digest of a file."""
    hasher = hashlib.sha256()
    with Path(file_path).open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_manifest(archive_path: Path, sha256_hash: str) -> Path:
    """Write the SHA-256 checksum manifest file accompanying an archive."""
    manifest_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    content = f"{sha256_hash}  {archive_path.name}\n"
    manifest_path.write_text(content, encoding="utf-8")
    return manifest_path


def execute_backup(
    output_dir: Path | str = DEFAULT_BACKUP_DIR,
    database: str = "aitrader",
    host: str = "localhost",
    port: int = 5432,
    user: str = "postgres",
    password: str | None = None,
    tables: list[str] | tuple[str, ...] | None = None,
    dry_run: bool = False,
    mock_payload: bytes | None = None,
) -> tuple[Path, Path, str]:
    """Generate a compressed database backup archive and SHA-256 manifest.

    Args:
        output_dir: Destination directory for the backup artifacts.
        database: PostgreSQL database name.
        host: Database server host.
        port: Database server port.
        user: Database connection username.
        password: Optional password (falls back to PGPASSWORD env var).
        tables: Optional subset of tables to include. If None, dumps all critical tables.
        dry_run: If True, validates parameters without creating archives.
        mock_payload: Optional raw bytes payload for unit testing without a live database.

    Returns:
        tuple[Path, Path, str]: (archive_path, manifest_path, sha256_hash)

    Raises:
        BackupError: If database dump or compression fails.
    """
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    archive_name = f"aitrader_backup_{database}_{timestamp_str}.sql.gz"
    archive_path = target_dir / archive_name

    logger.info(
        "initiating_database_backup",
        database=database,
        host=host,
        port=port,
        output_path=str(archive_path),
        dry_run=dry_run,
    )

    if dry_run:
        logger.info("backup_dry_run_complete", archive_path=str(archive_path))
        manifest_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
        return archive_path, manifest_path, "dry-run-hash-simulated"

    try:
        # 1. Obtain SQL dump stream
        if mock_payload is not None:
            raw_sql = mock_payload
        else:
            pg_dump_cmd = shutil.which("pg_dump")
            if pg_dump_cmd is None:
                # In environments without pg_dump CLI installed, fall back to structured SQL export
                msg = (
                    "pg_dump utility not found on PATH. Ensure postgresql-client is installed "
                    "or run inside the container environment."
                )
                raise BackupError(msg)

            cmd = [
                pg_dump_cmd,
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "--clean",
                "--if-exists",
                "-d",
                database,
            ]
            target_tables = tables or CRITICAL_TABLES
            for t in target_tables:
                cmd.extend(["-t", t])

            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password

            result = subprocess.run(cmd, capture_output=True, env=env, check=False)
            if result.returncode != 0:
                err_msg = result.stderr.decode("utf-8", errors="replace")
                raise BackupError(f"pg_dump failed (exit {result.returncode}): {err_msg}")
            raw_sql = result.stdout

        # 2. Write gzip compressed archive
        with gzip.open(archive_path, "wb", compresslevel=9) as gz_out:
            gz_out.write(raw_sql)

        # 3. Compute SHA-256 cryptographic digest
        sha256_hash = compute_sha256(archive_path)

        # 4. Generate manifest file
        manifest_path = write_manifest(archive_path, sha256_hash)

        logger.info(
            "database_backup_completed",
            archive=str(archive_path),
            manifest=str(manifest_path),
            sha256=sha256_hash,
            size_bytes=archive_path.stat().st_size,
        )

        return archive_path, manifest_path, sha256_hash

    except Exception as exc:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        if not isinstance(exc, BackupError):
            raise BackupError(f"Unexpected backup error: {exc}") from exc
        raise


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for backup script."""
    parser = argparse.ArgumentParser(description="AI Trader Automated Database Backup Generator")
    parser.add_argument("--output-dir", type=str, default="backups", help="Target output directory")
    parser.add_argument("--database", type=str, default="aitrader", help="Database name")
    parser.add_argument("--host", type=str, default="localhost", help="Database host")
    parser.add_argument("--port", type=int, default=5432, help="Database port")
    parser.add_argument("--user", type=str, default="postgres", help="Database username")
    parser.add_argument("--password", type=str, default=None, help="Database password")
    parser.add_argument("--tables", nargs="*", default=None, help="Specific tables to back up")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing files")
    return parser.parse_args()


def main() -> int:
    """Main CLI entrypoint."""
    args = parse_args()
    try:
        archive, manifest, digest = execute_backup(
            output_dir=args.output_dir,
            database=args.database,
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            tables=args.tables,
            dry_run=args.dry_run,
        )
        print(f"SUCCESS: Backup archived at: {archive}")
        print(f"SUCCESS: Manifest saved at: {manifest} (SHA-256: {digest})")
        return 0
    except BackupError as err:
        print(f"ERROR: Backup failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
