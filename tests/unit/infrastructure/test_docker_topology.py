"""Unit tests validating Docker Compose topology and systemd service supervision (Sprint S23.02).

Adheres to TRD-COMPUTE-1, TRD-COMPUTE-4, TRD-DEPLOY-1, TRD-DEPLOY-4, and TTD §15.
"""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_docker_compose_topology_spec() -> None:
    """Validate docker-compose.yml service topology, safety restart policies, and networking."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    assert compose_path.is_file(), "docker-compose.yml must exist at repository root"

    compose_data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    assert "services" in compose_data

    services = compose_data["services"]

    # 1. Validate PostgreSQL / TimescaleDB service
    assert "postgres" in services
    pg = services["postgres"]
    assert "timescale" in pg["image"] or "postgres" in pg["image"]
    assert pg.get("restart") == "unless-stopped"
    assert "healthcheck" in pg

    # 2. Validate Trading Brain service and CRITICAL safety restart policy (TRD-COMPUTE-4)
    assert "trading-brain" in services
    tb = services["trading-brain"]
    # Per TRD-COMPUTE-4 / BRD BR-1, Trading Brain must NOT automatically restart on crash
    assert (
        tb.get("restart") == "no"
    ), "TRD-COMPUTE-4 violation: Trading Brain restart policy must strictly be 'no'!"
    assert "postgres" in tb.get("depends_on", {})

    # 3. Validate Dashboard service
    assert "dashboard" in services
    dash = services["dashboard"]
    assert dash.get("restart") == "unless-stopped"
    assert any("8000" in port for port in dash.get("ports", []))

    # 4. Validate Research Brain container isolation (TRD-ARCH-2, TRD-COMPUTE-2)
    assert "research-brain" in services
    rb = services["research-brain"]
    assert rb.get("restart") == "no"
    assert "research" in rb.get("profiles", [])
    assert rb.get("environment", {}).get("RESEARCH_SANDBOX") == "1"
    assert rb.get("environment", {}).get("RESEARCH_READONLY") == "1"


def test_systemd_service_supervision_spec() -> None:
    """Validate deploy/systemd/aitrader.service configuration and safety invariants."""
    service_path = REPO_ROOT / "deploy" / "systemd" / "aitrader.service"
    assert (
        service_path.is_file()
    ), "deploy/systemd/aitrader.service must exist for process supervision"

    content = service_path.read_text(encoding="utf-8")

    # Verify critical safety setting (TRD-COMPUTE-4)
    msg = "TRD-COMPUTE-4 violation: Systemd unit must have Restart=no to prevent crash-looping!"
    assert "Restart=no" in content, msg

    # Verify execution commands
    assert "ExecStart=" in content
    assert "ExecStop=" in content
    assert "LimitNOFILE=" in content
