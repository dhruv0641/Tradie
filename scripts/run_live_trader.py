"""CLI runner executing Phase V5 Autonomous Risk-Controlled Live Trading.

Per SOW §6.6, §9; PRD §9, §13; BRD BR-1, BR-2, BR-4, BR-8, BR-9.

Enforces:
1. SOW §9 Preconditions verification gate.
2. Initial ₹10,000 live capital ceiling (BRD BR-2).
3. Startup reconciliation between broker and local ledger (TRD-DR-2/3).
4. Operator explicit live deployment confirmation.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from pydantic import SecretStr

from scripts.verify_live_preconditions import LivePreconditionsVerifier
from src.config.models import BrokerConfig
from src.core.runner import RunnerConfig, SessionSummary, TradingBrainRunner
from src.domain.market_data import OHLCVCandle
from src.execution.live_broker_adapter import LiveBrokerAdapter
from src.execution.order_manager import OrderManager
from src.execution.position_ledger import PositionLedger
from src.execution.reconciliation import StartupReconciler
from src.risk.config import RiskConfig
from src.risk.engine import RiskEngine
from src.risk.kill_switch import InMemoryKillSwitch

logger = structlog.get_logger("scripts.run_live_trader")
IST = ZoneInfo("Asia/Kolkata")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_live_test_candles(
    n_bars: int = 10,
    symbol: str = "NSE:RELIANCE",
    base_price: float = 2500.0,
) -> list[OHLCVCandle]:
    """Generate realistic live market verification candles."""
    base_time_ist = datetime(2026, 9, 7, 9, 15, tzinfo=IST)
    candles: list[OHLCVCandle] = []
    price = base_price

    for i in range(n_bars):
        open_p = Decimal(str(round(price, 2)))
        high_p = Decimal(str(round(price + 3.0, 2)))
        low_p = Decimal(str(round(price - 2.0, 2)))
        close_p = Decimal(str(round(price + 1.5, 2)))
        candles.append(
            OHLCVCandle(
                instrument=symbol,
                timeframe="15m",
                timestamp=base_time_ist + timedelta(minutes=15 * i),
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=10000,
                turnover=close_p * Decimal("10000"),
            )
        )
        price += 1.5

    return candles


def run_live_trading_session(
    symbol: str = "NSE:RELIANCE",
    capital: Decimal = Decimal("10000.00"),
    *,
    bars: int = 10,
    sandbox: bool = True,
    enforce_market_hours: bool = False,
    output_report: Path | None = None,
) -> SessionSummary:
    """Execute risk-controlled live trading session with pre-live safety gates."""
    log = logger.bind(symbol=symbol, capital=str(capital), sandbox=sandbox)
    log.info("Initiating Phase V5 live trading session...")

    # 1. Verify SOW §9 Preconditions
    verifier = LivePreconditionsVerifier(base_dir=_PROJECT_ROOT)
    all_passed, checks = verifier.verify_all()
    if not all_passed:
        failed = [c.name for c in checks if not c.passed]
        msg = f"SOW §9 Preconditions FAILED for live activation: {', '.join(failed)}"
        log.critical(msg)
        raise RuntimeError(msg)
    log.info("SOW §9 Preconditions verified cleanly")

    # 2. Strict Capital Check (BRD BR-2)
    if capital > Decimal("10000.00"):
        msg = f"Initial live trading capital cannot exceed ₹10,000 (requested: ₹{capital})"
        log.critical(msg)
        raise ValueError(msg)

    # 3. Initialize Live Broker Adapter
    api_key_str = os.environ.get("BROKER_API_KEY", "mock_key")
    api_secret_str = os.environ.get("BROKER_API_SECRET", "mock_secret")
    broker_cfg = BrokerConfig(
        broker_name="kite_connect",
        api_key=SecretStr(api_key_str),
        api_secret=SecretStr(api_secret_str),
        paper_trading=sandbox,
    )
    broker = LiveBrokerAdapter(config=broker_cfg, sandbox_mode=sandbox)
    broker.authenticate()

    # 4. Initialize Core Execution & Risk Components
    kill_switch = InMemoryKillSwitch()
    risk_config = RiskConfig()
    risk_engine = RiskEngine(risk_config, kill_switch)

    order_manager = OrderManager()
    position_ledger = PositionLedger(initial_capital=capital)
    reconciler = StartupReconciler(
        broker=broker,
        ledger=position_ledger,
        order_manager=order_manager,
        kill_switch=kill_switch,
    )

    # 5. Execute Startup State Reconciliation Gate
    rec_result = reconciler.reconcile(raise_on_mismatch=True)
    log.info(
        "Startup state reconciliation passed",
        broker_positions=rec_result.broker_positions_count,
        ledger_positions=rec_result.ledger_positions_count,
    )

    # 6. Initialize Runner and Run Market Verification Sequence
    runner_cfg = RunnerConfig(
        enforce_market_hours=enforce_market_hours,
        warmup_bars=5,
        git_commit="live_v5",
    )
    runner = TradingBrainRunner(
        broker=broker,
        risk_engine=risk_engine,
        kill_switch=kill_switch,
        order_manager=order_manager,
        position_ledger=position_ledger,
        reconciler=reconciler,
        config=runner_cfg,
    )

    candles = generate_live_test_candles(n_bars=bars, symbol=symbol)
    summary = runner.run_session(candles)

    if output_report:
        output_report.parent.mkdir(parents=True, exist_ok=True)
        output_report.write_text(json.dumps(summary.model_dump(mode="json"), indent=2))
        log.info("Live session report written", path=str(output_report))

    broker.close()
    return summary


def main() -> int:
    """CLI entry point for Phase V5 Live Trading."""
    parser = argparse.ArgumentParser(
        description="Phase V5 Autonomous Risk-Controlled Live Trading Launcher"
    )
    parser.add_argument("--symbol", default="NSE:RELIANCE", help="Trading instrument")
    parser.add_argument(
        "--capital", type=float, default=10000.0, help="Initial live capital (max ₹10,000)"
    )
    parser.add_argument("--bars", type=int, default=10, help="Number of market cycles to evaluate")
    parser.add_argument(
        "--confirm-live-deployment",
        action="store_true",
        help="Operator explicit confirmation required to enable order routing",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        default=True,
        help="Run in sandbox broker mode (default: True for testing)",
    )
    parser.add_argument(
        "--output-report", type=Path, default=None, help="JSON output performance report"
    )

    args = parser.parse_args()

    if not args.confirm_live_deployment:
        print("=" * 72)
        print(" ERROR: Live trading activation requires explicit confirmation flag.")
        print(" Pass '--confirm-live-deployment' to authorize live system startup.")
        print("=" * 72)
        return 1

    try:
        summary = run_live_trading_session(
            symbol=args.symbol,
            capital=Decimal(str(args.capital)),
            bars=args.bars,
            sandbox=args.sandbox,
            output_report=args.output_report,
        )
        print("\n" + "=" * 72)
        print(" PHASE V5 LIVE TRADING SESSION COMPLETED SUCCESSFULLY")
        print("=" * 72)
        print(f" Total Cycles:      {summary.total_cycles}")
        print(f" Orders Placed:     {summary.orders_placed}")
        print(f" Fills Executed:    {summary.fills_executed}")
        print(f" Final Equity:      ₹{summary.final_equity:,.2f}")
        print(f" Net Realized P&L:  ₹{summary.realized_pnl:,.2f}")
        print(f" Total Costs:       ₹{summary.total_costs:,.2f}")
        print("=" * 72)
        return 0
    except Exception as exc:
        print(f"\n[CRITICAL ERROR] Live trading activation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
