"""Unit and integration tests for Operator Web Dashboard UI static assets (Sprint S22.02)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.state import TradingSystemState
from src.config.models import ApiConfig, AppConfig
from src.risk.kill_switch import InMemoryKillSwitch


@pytest.fixture
def ui_app_config() -> AppConfig:
    """Create AppConfig pointing to the repository's ui directory."""
    ui_dir = Path(__file__).resolve().parent.parent.parent.parent / "ui"
    return AppConfig(
        api=ApiConfig(
            static_ui_dir=str(ui_dir),
            operator_token="operator-secret-token",  # type: ignore[arg-type]
        )
    )


@pytest.fixture
def ui_client(ui_app_config: AppConfig) -> TestClient:
    """Create TestClient with UI directory enabled."""
    app = create_app(config=ui_app_config)
    return TestClient(app)


def test_ui_index_served_at_root_and_dashboard(ui_client: TestClient) -> None:
    """Verify GET / and /dashboard serve operator dashboard HTML (FRD-DASH-1..8)."""
    for endpoint in ("/", "/dashboard"):
        response = ui_client.get(endpoint)
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        html = response.text

        # Verify prominent 1-click Emergency STOP button per FRD-DASH-7
        assert 'id="btn-emergency-stop"' in html
        assert "EMERGENCY STOP" in html

        # Verify Option modal per FRD-DASH-8
        assert 'id="modal-emergency-stop"' in html
        assert "Halt New Entries Only" in html
        assert "Immediate Emergency Liquidation" in html

        # Verify Risk, AI, and Portfolio Panels
        assert 'id="badge-kill-switch"' in html
        assert 'id="val-capital"' in html
        assert 'id="tbody-positions"' in html
        assert 'id="tbody-orders"' in html
        assert 'id="grid-diagnostics"' in html

        # Verify Market Switcher Components (Sprint S22.02 Extension)
        assert 'id="select-market"' in html
        assert 'id="select-symbol"' in html
        assert 'id="badge-market-hours"' in html
        assert 'id="badge-target-symbol"' in html


def test_ui_static_assets_served_correctly(ui_client: TestClient) -> None:
    """Verify /static/style.css and /static/app.js are served correctly."""
    res_css = ui_client.get("/static/style.css")
    assert res_css.status_code == 200
    assert "emergency-stop-btn" in res_css.text

    res_js = ui_client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "triggerEmergencyStop" in res_js.text
    assert "triggerEmergencyReset" in res_js.text


def test_e2e_stop_button_flow_simulation(ui_app_config: AppConfig) -> None:
    """Simulate end-to-end operator STOP trigger from dashboard UI."""
    kill_switch = InMemoryKillSwitch()
    system_state = TradingSystemState(kill_switch=kill_switch)
    app = create_app(config=ui_app_config, system_state=system_state)
    client = TestClient(app)

    # Initial state: Kill switch inactive
    health_before = client.get("/api/health").json()
    assert health_before["kill_switch_active"] is False

    # Trigger emergency halt using Option 1 (Halt New Entries)
    stop_res = client.post(
        "/api/control/stop",
        headers={"Authorization": "Bearer operator-secret-token"},
        json={"reason": "MANUAL STOP: Halt new entries and cancel working orders"},
    )
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "halted"
    assert kill_switch.is_active() is True

    # Health diagnostic immediately reflects halted state
    health_after = client.get("/api/health").json()
    assert health_after["kill_switch_active"] is True
    assert health_after["status"] == "unhealthy"

    # Reset via operator token
    reset_res = client.post(
        "/api/control/reset",
        headers={"Authorization": "Bearer operator-secret-token"},
        json={"reason": "Operator authorized resume"},
    )
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "active"
    assert kill_switch.is_active() is False
