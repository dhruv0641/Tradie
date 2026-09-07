"""FastAPI API routes implementing Dashboard and Control endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api.auth import verify_operator_token
from src.api.models import (
    AccountResponse,
    AIStateResponse,
    ControlResetRequest,
    ControlResetResponse,
    ControlStopRequest,
    ControlStopResponse,
    HealthResponse,
    MarketStateResponse,
    MarketSwitchRequest,
    RiskStateResponse,
    TradingResponse,
)
from src.api.state import TradingSystemState

router = APIRouter(prefix="/api", tags=["Operator Dashboard & Control"])


def get_system_state(request: Request) -> TradingSystemState:
    """Retrieve or lazily initialize the TradingSystemState singleton on the app."""
    if not hasattr(request.app.state, "system_state") or request.app.state.system_state is None:
        request.app.state.system_state = TradingSystemState()
    return request.app.state.system_state  # type: ignore[no-any-return]


@router.get(
    "/account",
    response_model=AccountResponse,
    summary="Get Account Capital & P&L State",
    description=(
        "Returns current capital, session P&L, cumulative P&L, and drawdown metrics (FRD-DASH-1)."
    ),
)
async def get_account(
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> AccountResponse:
    """Fetch real-time account capital state."""
    return system_state.get_account_state()


@router.get(
    "/trading",
    response_model=TradingResponse,
    summary="Get Active Positions & Orders",
    description="Returns open positions, pending orders, and completed trades (FRD-DASH-2).",
)
async def get_trading(
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> TradingResponse:
    """Fetch active portfolio positions and working orders."""
    return system_state.get_trading_state()


@router.get(
    "/ai",
    response_model=AIStateResponse,
    summary="Get AI Market Regime & Agent Signals",
    description=(
        "Returns market regime classification, active model version, "
        "and agent signals (FRD-DASH-3)."
    ),
)
async def get_ai(
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> AIStateResponse:
    """Fetch AI market regime classification and consensus signals."""
    return system_state.get_ai_state()


@router.get(
    "/risk",
    response_model=RiskStateResponse,
    summary="Get Risk Limits & Exposure Status",
    description=(
        "Returns current exposure, daily risk used, streak state, "
        "and kill switch status (FRD-DASH-4)."
    ),
)
async def get_risk(
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> RiskStateResponse:
    """Fetch deterministic risk boundary compliance status."""
    return system_state.get_risk_state()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Get Subsystem Health Diagnostics",
    description=(
        "Returns comprehensive health status for broker, feed, "
        "database, model, and kill switch (TRD-OBS-4)."
    ),
)
async def get_health(
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> HealthResponse:
    """Fetch overall and component-level health status."""
    return system_state.get_health_state()


@router.post(
    "/control/stop",
    response_model=ControlStopResponse,
    status_code=status.HTTP_200_OK,
    summary="1-Click Emergency STOP",
    description=(
        "Immediately activates the emergency Kill Switch halting all trading (FRD-DASH-7). "
        "Requires token auth."
    ),
)
async def trigger_stop(
    stop_request: ControlStopRequest,
    operator: Annotated[str, Depends(verify_operator_token)],
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> ControlStopResponse:
    """Trigger emergency trading halt."""
    system_state.trigger_emergency_stop(operator=operator, reason=stop_request.reason)
    return ControlStopResponse(
        status="halted",
        kill_switch_active=True,
        operator=operator,
        reason=stop_request.reason,
    )


@router.post(
    "/control/reset",
    response_model=ControlResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset Emergency STOP",
    description=(
        "Resets the emergency Kill Switch resuming nominal trading capability. Requires token auth."
    ),
)
async def reset_stop(
    reset_request: ControlResetRequest,
    operator: Annotated[str, Depends(verify_operator_token)],
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> ControlResetResponse:
    """Reset emergency trading halt."""
    system_state.reset_emergency_stop(operator=operator)
    return ControlResetResponse(
        status="active",
        kill_switch_active=False,
        operator=operator,
        reason=reset_request.reason,
    )


@router.get(
    "/market",
    response_model=MarketStateResponse,
    summary="Get Active Market State & Supported Markets",
    description=(
        "Returns the currently active market, active instrument, "
        "and catalog of all supported markets."
    ),
)
async def get_market(
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> MarketStateResponse:
    """Fetch active market and available markets catalog."""
    return system_state.get_market_state()


@router.post(
    "/market/switch",
    response_model=MarketStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Switch Active Market / Instrument",
    description="Switches the active trading market and instrument for the operator dashboard.",
)
async def switch_market(
    switch_request: MarketSwitchRequest,
    system_state: Annotated[TradingSystemState, Depends(get_system_state)],
) -> MarketStateResponse:
    """Switch the active market and symbol."""
    try:
        return system_state.switch_market(
            market_id=switch_request.market_id,
            symbol=switch_request.symbol,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
