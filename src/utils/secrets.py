"""Secrets management and transport layer security (TLS) verification engine.

Adheres strictly to TRD-SEC-1, TRD-SEC-2, TRD-SEC-4, NFR-SEC-1, NFR-SEC-2, NFR-SEC-6, and TTD §12.
"""

import os
import re
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import SecretStr

logger = structlog.get_logger("utils.secrets")

INSECURE_DEFAULT_PATTERNS: tuple[str, ...] = (
    "change-me",
    "mock_key",
    "mock_secret",
    "test_secret",
    "password",
    "admin",
    "12345",
    "operator-secret-token",
)


class SecurityError(Exception):
    """Raised when security boundaries, secrets, or TLS invariants are violated."""


def mask_secret(
    secret: str | SecretStr | None,
    prefix_len: int = 2,
    suffix_len: int = 2,
) -> str:
    """Mask a sensitive credential for safe logging and telemetry display.

    Args:
        secret: String or SecretStr to mask.
        prefix_len: Number of unmasked leading characters.
        suffix_len: Number of unmasked trailing characters.

    Returns:
        str: Masked string representation (e.g. "ab...yz" or "[REDACTED]").
    """
    if secret is None:
        return "[NONE]"
    raw = secret.get_secret_value() if isinstance(secret, SecretStr) else str(secret)
    if not raw or len(raw) <= (prefix_len + suffix_len + 2):
        return "[REDACTED]"
    return f"{raw[:prefix_len]}...{raw[-suffix_len:]}"


def get_secret(
    key: str,
    default: str | None = None,
    required: bool = False,
    environment: str = "test",
) -> SecretStr:
    """Retrieve secret from environment variables with security and default policy checks.

    Args:
        key: Environment variable key name.
        default: Fallback default value if not set.
        required: If True, raises ValueError when missing.
        environment: Current execution environment ("test", "paper", "live", "research").

    Returns:
        SecretStr: Encapsulated secret value.

    Raises:
        ValueError: If required secret is missing.
        SecurityError: If an insecure default secret is used in live environment.
    """
    val = os.environ.get(key, default)
    if val is None or not val.strip():
        if required:
            msg = f"Required secret '{key}' is missing or empty in environment"
            raise ValueError(msg)
        val = ""

    val_str = val.strip()

    # In live execution environment, block known placeholder credentials (TRD-SEC-4, NFR-SEC-1)
    if environment.lower() == "live":
        for pattern in INSECURE_DEFAULT_PATTERNS:
            if pattern in val_str.lower():
                msg = (
                    f"Insecure placeholder credential detected for '{key}' "
                    f"in live trading environment"
                )
                raise SecurityError(msg)

    return SecretStr(val_str)


def validate_live_credentials(
    credentials: dict[str, SecretStr | str],
    environment: str = "live",
) -> None:
    """Audit a dictionary of credentials for insecure placeholder values in live mode.

    Args:
        credentials: Dictionary of credential names to secret values.
        environment: Target execution environment.

    Raises:
        SecurityError: If any credential matches insecure placeholder patterns.
    """
    if environment.lower() != "live":
        return

    for name, secret in credentials.items():
        raw = secret.get_secret_value() if isinstance(secret, SecretStr) else str(secret)
        raw_lower = raw.lower().strip()
        for pattern in INSECURE_DEFAULT_PATTERNS:
            if pattern in raw_lower:
                msg = (
                    f"Live credential audit failed: '{name}' contains insecure "
                    f"placeholder value '{pattern}'"
                )
                raise SecurityError(msg)


def enforce_tls_transport(
    url: str,
    verify: bool = True,
    environment: str = "live",
) -> None:
    """Enforce TLS transport security invariants on network connection requests.

    Adheres strictly to TRD-SEC-2 and NFR-SEC-2:
    - Rejects verify=False in production/live environments.
    - Rejects unencrypted http:// and ws:// schemes in production/live environments.

    Args:
        url: Target network endpoint URL.
        verify: TLS certificate verification flag.
        environment: Execution environment ("live", "paper", "test", "research").

    Raises:
        SecurityError: If TLS certificate verification is disabled or transport
            is unencrypted in live.
    """
    # 1. Unconditionally reject disabling TLS verification in live/production environments
    if environment.lower() == "live" and not verify:
        msg = (
            "TLS certificate verification (verify=True) cannot be disabled "
            "in live production environment (TRD-SEC-2, NFR-SEC-2)"
        )
        raise SecurityError(msg)

    # 2. In live environment, reject unencrypted schemes
    if environment.lower() == "live":
        parsed_scheme = url.split("://", maxsplit=1)[0].lower() if "://" in url else ""
        if parsed_scheme in ("http", "ws") and not re.search(
            r"://(127\.0\.0\.1|localhost)(:\d+)?", url
        ):
            msg = (
                f"Insecure plaintext transport scheme '{parsed_scheme}://' "
                f"is forbidden in live environment: {url}"
            )
            raise SecurityError(msg)


class SecretsManager:
    """Thread-safe secrets store and rotation tracking manager per TTD §12."""

    def __init__(self, environment: str = "test") -> None:
        self.environment = environment
        self._secrets: dict[str, SecretStr] = {}
        self._rotation_timestamps: dict[str, datetime] = {}
        self._log = logger.bind(component="SecretsManager")

    def register_secret(self, key: str, value: str | SecretStr) -> None:
        """Register or update a secret with current rotation timestamp."""
        secret_obj = value if isinstance(value, SecretStr) else SecretStr(value)
        if self.environment == "live":
            validate_live_credentials({key: secret_obj}, environment=self.environment)

        self._secrets[key] = secret_obj
        now = datetime.now(UTC)
        self._rotation_timestamps[key] = now
        self._log.info("Secret registered into manager", key=key, timestamp=now.isoformat())

    def get(self, key: str) -> SecretStr:
        """Retrieve registered secret by key name."""
        if key not in self._secrets:
            msg = f"Secret '{key}' not found in SecretsManager"
            raise KeyError(msg)
        return self._secrets[key]

    def get_rotation_age_days(self, key: str) -> float:
        """Calculate age in days since last secret rotation."""
        if key not in self._rotation_timestamps:
            msg = f"Secret '{key}' has no recorded rotation timestamp"
            raise KeyError(msg)
        delta = datetime.now(UTC) - self._rotation_timestamps[key]
        return delta.total_seconds() / 86400.0

    def audit_inventory(self) -> dict[str, dict[str, Any]]:
        """Return masked audit summary of all registered secrets."""
        summary: dict[str, dict[str, Any]] = {}
        for k, v in self._secrets.items():
            summary[k] = {
                "masked": mask_secret(v),
                "last_rotated": self._rotation_timestamps[k].isoformat(),
                "age_days": round(self.get_rotation_age_days(k), 4),
            }
        return summary
