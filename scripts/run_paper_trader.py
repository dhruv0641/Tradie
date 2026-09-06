"""CLI runner executing the Trading Brain continuous paper trading market-hours harness."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from src.core.runner import RunnerConfig, TradingBrainRunner
from src.domain.market_data import OHLCVCandle
from src.execution.paper_adapter import PaperBrokerAdapter, PaperBrokerConfig

logger = structlog.get_logger("scripts.run_paper_trader")
IST = ZoneInfo("Asia/Kolkata")


def generate_market_candles(
    n_bars: int = 100,
    symbol: str = "NSE:RELIANCE",
    base_price: float = 2500.0,
    timeframe_minutes: int = 15,
) -> list[OHLCVCandle]:
    """Generate realistic synthetic candle series matching Indian equity market price ranges."""
    # Start at 09:15 IST on a weekday (Monday 2026-09-07)
    base_time_ist = datetime(2026, 9, 7, 9, 15, tzinfo=IST)
    candles: list[OHLCVCandle] = []
    price = base_price

    for i in range(n_bars):
        # Oscillating cycle to trigger various regime conditions and agent opportunities
        cycle = (i // 15) % 4
        if cycle == 0:
            drift = 3.5  # Bullish drift
        elif cycle == 1:
            drift = -2.0  # Mean-reverting pullback
        elif cycle == 2:
            drift = 4.0  # Strong momentum
        else:
            drift = -0.5  # Sideways consolidation

        open_p = Decimal(str(round(price, 2)))
        close_p = Decimal(str(round(price + drift + 0.25, 2)))
        high_p = max(open_p, close_p) + Decimal("4.50")
        low_p = min(open_p, close_p) - Decimal("4.50")
        price = float(close_p)

        candle_time = base_time_ist + timedelta(minutes=timeframe_minutes * i)
        candle_utc = candle_time.astimezone(UTC)

        candle = OHLCVCandle(
            instrument=symbol,
            timeframe=f"{timeframe_minutes}m",
            timestamp=candle_utc,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=50000,
            turnover=Decimal(str(round(float(close_p) * 50000, 2))),
        )
        candles.append(candle)

    return candles


def run_paper_trading_session(
    symbol: str,
    bars: int,
    capital: Decimal,
    slippage_bps: Decimal,
    *,
    enforce_market_hours: bool,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Execute paper trading harness session over synthetic market candles."""
    candles = generate_market_candles(n_bars=bars, symbol=symbol)

    broker = PaperBrokerAdapter(
        config=PaperBrokerConfig(
            initial_cash=capital,
            slippage_bps=slippage_bps,
        )
    )

    config = RunnerConfig(
        enforce_market_hours=enforce_market_hours,
        warmup_bars=20,
    )

    runner = TradingBrainRunner(
        broker=broker,
        config=config,
    )

    logger.info(
        "Starting paper trading harness session",
        symbol=symbol,
        bars=len(candles),
        capital=str(capital),
        slippage_bps=str(slippage_bps),
    )

    summary = runner.run_session(candles)

    result_dict = {
        "session_id": summary.session_id,
        "start_time": summary.start_time.isoformat(),
        "end_time": summary.end_time.isoformat(),
        "instrument": symbol,
        "bars_processed": len(candles),
        "total_cycles": summary.total_cycles,
        "orders_placed": summary.orders_placed,
        "fills_executed": summary.fills_executed,
        "initial_capital": str(summary.initial_capital),
        "final_equity": str(summary.final_equity),
        "realized_pnl": str(summary.realized_pnl),
        "unrealized_pnl": str(summary.unrealized_pnl),
        "net_pnl": str(summary.net_pnl),
        "total_costs": str(summary.total_costs),
        "net_return_pct": summary.net_return_pct,
        "open_positions_count": summary.open_positions_count,
        "closed_trades_count": summary.closed_trades_count,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result_dict, indent=2), encoding="utf-8")
        logger.info("Session report saved", path=str(output_path))

    return result_dict


def main() -> None:
    """CLI entrypoint for Paper Trading Harness execution."""
    parser = argparse.ArgumentParser(
        description="Run Trading Brain Continuous Paper Trading Harness (Phase V4)"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="NSE:RELIANCE",
        help="Target trading instrument (default: NSE:RELIANCE)",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=100,
        help="Number of synthetic market candles (default: 100)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial paper trading capital in INR (default: 10000.0)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=2.0,
        help="Simulated execution slippage in basis points (default: 2.0)",
    )
    parser.add_argument(
        "--enforce-market-hours",
        action="store_true",
        default=False,
        help="Strictly enforce Indian market hours (09:15-15:30 IST)",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default="reports/paper_trading/session_summary.json",
        help="Path to write JSON session summary report",
    )
    args = parser.parse_args()

    out_file = Path(args.output_report) if args.output_report else None

    print("=" * 65)
    print(" AI Trader — Continuous Paper Trading Market-Hours Harness")
    print(f" Symbol: {args.symbol} | Bars: {args.bars} | Initial Capital: ₹{args.capital:,.2f}")
    print(
        f" Slippage: {args.slippage_bps} bps | Market Hours Enforced: {args.enforce_market_hours}"
    )
    print("=" * 65)

    res = run_paper_trading_session(
        symbol=args.symbol,
        bars=args.bars,
        capital=Decimal(str(args.capital)),
        slippage_bps=Decimal(str(args.slippage_bps)),
        enforce_market_hours=args.enforce_market_hours,
        output_path=out_file,
    )

    print("\n--- Session Performance Summary ---")
    print(f" Session ID:           {res['session_id']}")
    print(f" Total Cycles:         {res['total_cycles']}")
    print(f" Orders Placed:        {res['orders_placed']}")
    print(f" Fills Executed:       {res['fills_executed']}")
    print(f" Initial Capital:      ₹{float(res['initial_capital']):,.2f}")
    print(f" Final Equity:         ₹{float(res['final_equity']):,.2f}")
    print(f" Net Realized PnL:     ₹{float(res['realized_pnl']):,.2f}")
    print(f" Net Unrealized PnL:   ₹{float(res['unrealized_pnl']):,.2f}")
    print(f" Total Trading Costs:  ₹{float(res['total_costs']):,.2f}")
    print(f" Net Return:           {res['net_return_pct']:.2f}%")
    print(f" Open Positions:       {res['open_positions_count']}")
    print(f" Closed Trades:        {res['closed_trades_count']}")
    if out_file:
        print(f" Report JSON Written:  {out_file.resolve()}")
    print("=" * 65)


if __name__ == "__main__":
    main()
