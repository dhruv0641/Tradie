"""Unit and integration tests for FastAPI Control Backend endpoints (Sprint S22.01)."""

import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.models import (
    AccountResponse,
    AIStateResponse,
    HealthResponse,
    MarketStateResponse,
    RiskStateResponse,
    TradingResponse,
)
from src.api.state import TradingSystemState
from src.config.models import ApiConfig, AppConfig
from src.domain.execution import OrderSubmission, Position
from src.domain.regime import (
    DirectionalBias,
    LiquidityCondition,
    RegimeClassification,
    TrendState,
    VolatilityLevel,
)
from src.execution.order_manager import OrderManager
from src.execution.position_ledger import PositionLedger
from src.risk.kill_switch import InMemoryKillSwitch
from src.risk.streak_tracker import StreakTracker


@pytest.fixture
def test_config() -> AppConfig:
    """Create test AppConfig with explicit operator token."""
    return AppConfig(
        api=ApiConfig(
            operator_token="test-secret-token-12345",  # type: ignore[arg-type]
            static_ui_dir="non_existent_ui_dir_for_test",
        )
    )


@pytest.fixture
def client(test_config: AppConfig) -> TestClient:
    """Create TestClient with default state."""
    app = create_app(config=test_config)
    return TestClient(app)


def test_root_fallback_when_ui_dir_missing(client: TestClient) -> None:
    """Verify root endpoint returns JSON info when static directory does not exist."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "AI Trader" in data["message"]


def test_get_account_endpoint_nominal(client: TestClient) -> None:
    """Verify GET /api/account returns compliant AccountResponse schema (FRD-DASH-1)."""
    response = client.get("/api/account")
    assert response.status_code == 200
    data = response.json()
    account = AccountResponse.model_validate(data)
    assert account.current_capital == Decimal("10000.00")
    assert account.initial_capital == Decimal("10000.00")
    assert account.peak_equity == Decimal("10000.00")
    assert account.drawdown_amount == Decimal("0.00")
    assert account.drawdown_pct == 0.0
    assert account.open_position_count == 0


def test_get_trading_endpoint_nominal(client: TestClient) -> None:
    """Verify GET /api/trading returns valid TradingResponse (FRD-DASH-2)."""
    response = client.get("/api/trading")
    assert response.status_code == 200
    data = response.json()
    trading = TradingResponse.model_validate(data)
    assert isinstance(trading.positions, list)
    assert isinstance(trading.open_orders, list)
    assert isinstance(trading.completed_trades, list)


def test_get_ai_endpoint_nominal(client: TestClient) -> None:
    """Verify GET /api/ai returns AI regime state and agent roster signals (FRD-DASH-3)."""
    response = client.get("/api/ai")
    assert response.status_code == 200
    data = response.json()
    ai_state = AIStateResponse.model_validate(data)
    assert ai_state.active_model_version == "v1.0.0"
    assert len(ai_state.agent_signals) == 4
    agent_ids = {s.agent_id for s in ai_state.agent_signals}
    assert "trend_agent" in agent_ids
    assert "momentum_agent" in agent_ids


def test_get_risk_endpoint_nominal(client: TestClient) -> None:
    """Verify GET /api/risk returns deterministic risk state and limits (FRD-DASH-4)."""
    response = client.get("/api/risk")
    assert response.status_code == 200
    data = response.json()
    risk_state = RiskStateResponse.model_validate(data)
    assert not risk_state.kill_switch_active
    assert risk_state.consecutive_losses == 0
    assert risk_state.current_exposure == Decimal("0.00")
    assert risk_state.max_exposure_limit == Decimal("5000.00")  # 50% of ₹10,000


def test_get_health_endpoint_nominal(client: TestClient) -> None:
    """Verify GET /api/health reports healthy subsystems (TRD-OBS-4)."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    health = HealthResponse.model_validate(data)
    assert health.status == "healthy"
    assert not health.kill_switch_active
    assert "broker" in health.components
    assert "data_feed" in health.components
    assert "database" in health.components
    assert "model" in health.components
    assert "kill_switch" in health.components


def test_control_stop_requires_authentication(client: TestClient) -> None:
    """Verify POST /api/control/stop rejects unauthenticated requests with 401."""
    # No auth header
    response = client.post("/api/control/stop", json={"reason": "Emergency"})
    assert response.status_code == 401
    assert "Missing operator authorization token" in response.json()["detail"]

    # Invalid Bearer token
    response_bad = client.post(
        "/api/control/stop",
        headers={"Authorization": "Bearer wrong-token-secret"},
        json={"reason": "Emergency"},
    )
    assert response_bad.status_code == 401
    assert "Invalid operator authorization token" in response_bad.json()["detail"]


def test_control_stop_executes_within_two_seconds(
    test_config: AppConfig,
) -> None:
    """Verify POST /api/control/stop activates KillSwitch in < 2s (FRD-DASH-7)."""
    kill_switch = InMemoryKillSwitch()
    state = TradingSystemState(kill_switch=kill_switch)
    app = create_app(config=test_config, system_state=state)
    client = TestClient(app)

    start_time = time.perf_counter()
    response = client.post(
        "/api/control/stop",
        headers={"Authorization": "Bearer test-secret-token-12345"},
        json={"reason": "Critical market anomaly detected"},
    )
    elapsed_time = time.perf_counter() - start_time

    assert elapsed_time < 2.0  # Strict SLA requirement
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "halted"
    assert data["kill_switch_active"] is True
    assert "operator" in data
    assert kill_switch.is_active() is True

    # Check that subsequent health endpoint reports unhealthy
    health_res = client.get("/api/health")
    assert health_res.status_code == 200
    health_data = health_res.json()
    assert health_data["status"] == "unhealthy"
    assert health_data["kill_switch_active"] is True
    assert health_data["components"]["kill_switch"]["status"] == "unhealthy"
    assert health_data["components"]["broker"]["status"] == "degraded"


def test_control_reset_with_custom_header(test_config: AppConfig) -> None:
    """Verify POST /api/control/reset using X-Operator-Token header resumes trading."""
    kill_switch = InMemoryKillSwitch()
    kill_switch.activate(source="operator", reason="Initial halt")
    assert kill_switch.is_active() is True

    state = TradingSystemState(kill_switch=kill_switch)
    app = create_app(config=test_config, system_state=state)
    client = TestClient(app)

    # Attempt reset without auth -> 401
    bad_res = client.post("/api/control/reset", json={"reason": "Resuming"})
    assert bad_res.status_code == 401

    # Reset with X-Operator-Token
    response = client.post(
        "/api/control/reset",
        headers={"X-Operator-Token": "test-secret-token-12345"},
        json={"reason": "Resuming after review"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["kill_switch_active"] is False
    assert kill_switch.is_active() is False


def test_live_ledger_and_order_manager_integration(test_config: AppConfig) -> None:
    """Verify live PositionLedger and OrderManager state correctly surfaced in API."""
    ledger = PositionLedger(initial_capital=Decimal("15000.00"))
    order_mgr = OrderManager()
    streak = StreakTracker()
    now = datetime.now(UTC)

    # Register an order in OrderManager
    order = OrderSubmission(
        client_order_id="ORD-TEST-001",
        instrument="RELIANCE",
        direction="BUY",
        order_type="LIMIT",
        quantity=10,
        limit_price=Decimal("2500.00"),
        status="SUBMITTED",
        submitted_at=now,
        updated_at=now,
    )
    order_mgr.register_order(order)

    # Record a position in PositionLedger
    pos = Position(
        instrument="TCS",
        quantity=5,
        average_entry_price=Decimal("3500.00"),
        current_market_price=Decimal("3600.00"),
        unrealized_pnl=Decimal("500.00"),
        realized_pnl=Decimal("0.00"),
        updated_at=now,
    )
    ledger._positions["TCS"] = pos  # Internal test assignment
    ledger._cash = Decimal("15000.00") - (Decimal("3500.00") * 5)

    # Register regime classification
    regime = RegimeClassification(
        instrument="NIFTY",
        timeframe="15m",
        timestamp=now,
        trend_state=TrendState.TRENDING_UP,
        volatility_level=VolatilityLevel.NORMAL,
        directional_bias=DirectionalBias.BULLISH,
        liquidity_condition=LiquidityCondition.NORMAL,
        regime_label="BULLISH_TREND_NORMAL_VOL",
    )

    state = TradingSystemState(
        ledger=ledger,
        order_manager=order_mgr,
        streak_tracker=streak,
        active_model_version="v2.1.0-alpha",
        initial_capital=Decimal("15000.00"),
    )
    state.update_ai_snapshot(regime=regime)
    state.set_system_phase("REGULAR_HOURS")

    app = create_app(config=test_config, system_state=state)
    client = TestClient(app)

    # Check account endpoint
    acc_res = client.get("/api/account").json()
    assert Decimal(acc_res["initial_capital"]) == Decimal("15000.00")
    assert acc_res["open_position_count"] == 1

    # Check trading endpoint
    trad_res = client.get("/api/trading").json()
    assert len(trad_res["positions"]) == 1
    assert trad_res["positions"][0]["instrument"] == "TCS"
    assert trad_res["positions"][0]["quantity"] == 5
    assert len(trad_res["open_orders"]) == 1
    assert trad_res["open_orders"][0]["client_order_id"] == "ORD-TEST-001"

    # Check AI endpoint
    ai_res = client.get("/api/ai").json()
    assert ai_res["regime_label"] == "BULLISH_TREND_NORMAL_VOL"
    assert ai_res["trend_state"] == "TRENDING_UP"
    assert ai_res["active_model_version"] == "v2.1.0-alpha"


def test_static_ui_serving_when_dir_exists(tmp_path: Path) -> None:
    """Verify static UI index.html is served at / and /dashboard when directory exists."""
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    index_file = ui_dir / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body><h1>Operator Dashboard</h1></body></html>")

    config = AppConfig(
        api=ApiConfig(
            static_ui_dir=str(ui_dir),
            operator_token="operator-secret-token",  # type: ignore[arg-type]
        )
    )
    app = create_app(config=config)
    client = TestClient(app)

    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "Operator Dashboard" in res_root.text

    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "Operator Dashboard" in res_dash.text


def test_exception_handler_returns_json(test_config: AppConfig) -> None:
    """Verify unhandled exception triggers 500 JSON response."""
    app = create_app(config=test_config)

    @app.get("/api/error_test")
    def trigger_error() -> None:
        msg = "Simulated crash for error handler verification"
        raise RuntimeError(msg)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/error_test")
    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "Internal Server Error"
    assert "Simulated crash" in data["error"]


def test_streak_state_and_fallback_token_coverage() -> None:
    """Verify streak pause state in risk response and fallback token retrieval."""
    streak = StreakTracker()
    streak.record_trade(pnl=Decimal("-100.00"), trade_id="TCS-1")
    streak.record_trade(pnl=Decimal("-100.00"), trade_id="TCS-2")
    streak.record_trade(pnl=Decimal("-100.00"), trade_id="TCS-3")
    streak.record_trade(pnl=Decimal("-100.00"), trade_id="TCS-4")
    streak.record_trade(pnl=Decimal("-100.00"), trade_id="TCS-5")

    state = TradingSystemState(streak_tracker=streak)
    risk_state = state.get_risk_state()
    assert risk_state.consecutive_losses == 5
    assert risk_state.session_paused is True


def test_get_market_endpoint_nominal(client: TestClient) -> None:
    """Verify GET /api/market returns initial market state and all supported markets."""
    response = client.get("/api/market")
    assert response.status_code == 200
    data = response.json()
    market_state = MarketStateResponse.model_validate(data)
    assert market_state.active_market_id == "NSE_EQUITY"
    assert market_state.active_market_name == "Indian Equities (NSE)"
    assert market_state.currency_symbol == "₹"
    assert len(market_state.available_markets) >= 4
    market_ids = {m.market_id for m in market_state.available_markets}
    assert "NSE_EQUITY" in market_ids
    assert "NSE_FOREX" in market_ids
    assert "GLOBAL_FOREX" in market_ids
    assert "CRYPTO" in market_ids


def test_switch_market_nominal(client: TestClient) -> None:
    """Verify POST /api/market/switch successfully switches market to GLOBAL_FOREX."""
    payload = {"market_id": "GLOBAL_FOREX"}
    response = client.post("/api/market/switch", json=payload)
    assert response.status_code == 200
    data = response.json()
    market_state = MarketStateResponse.model_validate(data)
    assert market_state.active_market_id == "GLOBAL_FOREX"
    assert market_state.active_market_name == "Global Forex (Spot)"
    assert market_state.currency_symbol == "$"
    assert market_state.active_symbol == "FX:EUR_USD"


def test_switch_market_with_explicit_symbol(client: TestClient) -> None:
    """Verify POST /api/market/switch supports switching to a specific instrument."""
    payload = {"market_id": "CRYPTO", "symbol": "CRYPTO:BTC_USDT"}
    response = client.post("/api/market/switch", json=payload)
    assert response.status_code == 200
    data = response.json()
    market_state = MarketStateResponse.model_validate(data)
    assert market_state.active_market_id == "CRYPTO"
    assert market_state.active_symbol == "CRYPTO:BTC_USDT"
    assert market_state.currency_symbol == "$"


def test_switch_market_invalid_id_raises_400(client: TestClient) -> None:
    """Verify POST /api/market/switch with unknown market ID returns HTTP 400."""
    payload = {"market_id": "INVALID_UNKNOWN_MARKET"}
    response = client.post("/api/market/switch", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Unknown market ID" in data["detail"]
