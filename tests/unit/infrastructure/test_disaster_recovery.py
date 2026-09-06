"""Unit tests for automated database backup and disaster recovery restoration (Sprint S23.02).

Adheres to TRD-DR-1, TRD-DATA-5, NFR-REL-6, and TTD §15.
"""

from __future__ import annotations

import gzip
from pathlib import Path  # noqa: TCH003

import pytest

from scripts.backup_db import (
    BackupError,
    compute_sha256,
    execute_backup,
    write_manifest,
)
from scripts.restore_db import (
    IntegrityError,
    RestoreError,
    execute_restore,
    verify_backup_integrity,
)


@pytest.fixture
def sample_sql_payload() -> bytes:
    """Provide sample PostgreSQL dump bytes."""
    return (
        b"-- PostgreSQL dump mock\n"
        b"CREATE TABLE test_table (id serial PRIMARY KEY, data text);\n"
        b"INSERT INTO test_table (data) VALUES ('active_position');\n"
    )


def test_compute_sha256_and_manifest(tmp_path: Path) -> None:
    """Verify SHA-256 calculation and manifest formatting."""
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"hello disaster recovery test")

    digest = compute_sha256(test_file)
    assert len(digest) == 64

    manifest_path = write_manifest(test_file, digest)
    assert manifest_path.is_file()
    assert manifest_path.name == "test.txt.sha256"

    content = manifest_path.read_text(encoding="utf-8")
    assert content == f"{digest}  test.txt\n"


def test_execute_backup_nominal_with_mock(tmp_path: Path, sample_sql_payload: bytes) -> None:
    """Verify execute_backup creates valid gzip archive and SHA-256 manifest."""
    backup_dir = tmp_path / "backups"
    archive, manifest, digest = execute_backup(
        output_dir=backup_dir,
        database="aitrader_test",
        mock_payload=sample_sql_payload,
    )

    assert archive.is_file()
    assert manifest.is_file()
    assert archive.suffix == ".gz"
    assert manifest.suffix == ".sha256"

    # Verify decompressed content
    with gzip.open(archive, "rb") as gz_in:
        uncompressed = gz_in.read()
    assert uncompressed == sample_sql_payload

    # Verify manifest hash matches computed hash
    recomputed = compute_sha256(archive)
    assert recomputed == digest


def test_execute_backup_dry_run(tmp_path: Path) -> None:
    """Verify dry_run does not write archive to disk."""
    backup_dir = tmp_path / "backups_dry"
    archive, manifest, digest = execute_backup(
        output_dir=backup_dir,
        database="aitrader_dry",
        dry_run=True,
    )
    assert not archive.exists()
    assert not manifest.exists()
    assert digest == "dry-run-hash-simulated"


def test_verify_backup_integrity_nominal_and_corrupt(
    tmp_path: Path, sample_sql_payload: bytes
) -> None:
    """Verify verify_backup_integrity passes on authentic and raises on corrupted archives."""
    backup_dir = tmp_path / "integrity_test"
    archive, manifest, digest = execute_backup(
        output_dir=backup_dir,
        database="aitrader_test",
        mock_payload=sample_sql_payload,
    )

    # 1. Authentic archive passes
    verified_hash = verify_backup_integrity(archive, manifest_path=manifest)
    assert verified_hash == digest

    # 2. Tampered / corrupted archive raises IntegrityError
    tampered_archive = backup_dir / "tampered.sql.gz"
    tampered_archive.write_bytes(archive.read_bytes() + b"\x00corrupt")
    with pytest.raises(IntegrityError, match="Cryptographic SHA-256 integrity mismatch"):
        verify_backup_integrity(tampered_archive, manifest_path=manifest)

    # 3. Missing file raises FileNotFoundError
    with pytest.raises(FileNotFoundError, match="Backup archive not found"):
        verify_backup_integrity(backup_dir / "non_existent.sql.gz")

    with pytest.raises(FileNotFoundError, match="Manifest file not found"):
        verify_backup_integrity(archive, manifest_path=backup_dir / "non_existent.sha256")

    # 4. Empty manifest raises IntegrityError
    empty_manifest = backup_dir / "empty.sha256"
    empty_manifest.write_text("")
    with pytest.raises(IntegrityError, match="Manifest file is empty"):
        verify_backup_integrity(archive, manifest_path=empty_manifest)


def test_execute_restore_nominal_and_modes(tmp_path: Path, sample_sql_payload: bytes) -> None:
    """Verify execute_restore succeeds in verify_only and mock_executor modes."""
    backup_dir = tmp_path / "restore_test"
    archive, manifest, _ = execute_backup(
        output_dir=backup_dir,
        database="aitrader_test",
        mock_payload=sample_sql_payload,
    )

    # 1. Verify-only mode validates checksum and returns True without restoration
    assert execute_restore(archive_path=archive, manifest_path=manifest, verify_only=True)

    # 2. Mock executor mode validates, decompresses, and simulates execution
    assert execute_restore(archive_path=archive, manifest_path=manifest, mock_executor=True)

    # 3. Empty decompressed payload raises RestoreError
    empty_archive = backup_dir / "empty.sql.gz"
    with gzip.open(empty_archive, "wb") as gz_out:
        gz_out.write(b"")
    empty_manifest = write_manifest(empty_archive, compute_sha256(empty_archive))

    with pytest.raises(RestoreError, match="Decompressed SQL payload is empty"):
        execute_restore(
            archive_path=empty_archive, manifest_path=empty_manifest, mock_executor=True
        )


def test_backup_error_handling_when_pg_dump_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify execute_backup raises BackupError when subprocess command fails."""
    # When pg_dump is not available and mock_payload is None
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    with pytest.raises(BackupError, match="pg_dump utility not found"):
        execute_backup(mock_payload=None)
