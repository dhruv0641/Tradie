"""CLI runner executing baseline quantitative strategies and producing PRD §10 audit reports."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.backtesting.reporting import BacktestReporter
from src.domain.market_data import OHLCVCandle
from src.strategies.base import BaseStrategy
from src.strategies.mean_reversion_baseline import BollingerBandsRSIMeanReversionStrategy
from src.strategies.trend_baseline import (
    DonchianBreakoutStrategy,
    DualEMACrossoverStrategy,
)

logger = structlog.get_logger(__name__)


def generate_benchmark_candles(
    n_bars: int = 250,
    symbol: str = "NSE:TCS",
) -> list[OHLCVCandle]:
    """Generate synthetic benchmark candle series with natural trends and pullbacks."""
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    candles: list[OHLCVCandle] = []
    price = 3500.0

    for i in range(n_bars):
        # Oscillating wave with upward secular drift
        cycle = (i // 25) % 4
        if cycle == 0:
            drift = 4.0  # trend up
        elif cycle == 1:
            drift = -2.5  # pullback
        elif cycle == 2:
            drift = 5.5  # strong trend up
        else:
            drift = -1.0  # consolidation

        open_p = Decimal(str(round(price, 2)))
        close_p = Decimal(str(round(price + drift + 0.5, 2)))
        high_p = max(open_p, close_p) + Decimal("8.00")
        low_p = min(open_p, close_p) - Decimal("8.00")
        price = float(close_p)

        candle = OHLCVCandle(
            instrument=symbol,
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=75000,
            turnover=Decimal(str(round(float(close_p) * 75000, 2))),
        )
        candles.append(candle)

    return candles


def run_baseline_strategy(
    strategy: BaseStrategy,
    candles: list[OHLCVCandle],
    output_dir: Path,
) -> dict[str, Any]:
    """Execute strategy backtest and write Markdown and JSON performance reports."""
    engine = BacktestEngine(
        BacktestConfig(strategy_id=strategy.name, initial_capital=Decimal("10000.00"))
    )
    result = engine.run(candles, strategy_callback=strategy)

    meta = {
        "strategy_name": strategy.name,
        "parameters": strategy.parameters,
        "instrument": candles[0].instrument,
        "bar_count": len(candles),
        "start_time": candles[0].timestamp.isoformat(),
        "end_time": candles[-1].timestamp.isoformat(),
    }

    md_report = BacktestReporter.generate_markdown_report(result, run_metadata=meta)
    json_report = BacktestReporter.generate_json_report(result, run_metadata=meta)

    output_dir.mkdir(parents=True, exist_ok=True)
    md_file = output_dir / f"{strategy.name}_report.md"
    json_file = output_dir / f"{strategy.name}_report.json"

    md_file.write_text(md_report, encoding="utf-8")
    json_file.write_text(json.dumps(json_report, indent=2), encoding="utf-8")

    logger.info(
        "strategy_backtest_completed",
        strategy=strategy.name,
        trades=result.metrics.total_trades,
        net_profit=str(result.metrics.net_profit),
        max_drawdown=str(result.metrics.max_drawdown_pct),
        report_path=str(md_file),
    )

    return json_report


def main() -> None:
    """CLI entrypoint for running baseline strategies."""
    parser = argparse.ArgumentParser(description="Run V1 Baseline Trading Strategies")
    parser.add_argument(
        "--strategy",
        choices=["dual_ema", "donchian", "bollinger_rsi", "all"],
        default="all",
        help="Strategy to execute (default: all)",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=250,
        help="Number of benchmark bars (default: 250)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/v1_baseline",
        help="Directory to save generated reports",
    )
    args = parser.parse_args()

    candles = generate_benchmark_candles(n_bars=args.bars)
    out_dir = Path(args.output_dir)

    strategies: list[BaseStrategy] = []
    if args.strategy in ("dual_ema", "all"):
        strategies.append(DualEMACrossoverStrategy(fast_span=10, slow_span=30))
    if args.strategy in ("donchian", "all"):
        strategies.append(DonchianBreakoutStrategy(lookback_period=20))
    if args.strategy in ("bollinger_rsi", "all"):
        strategies.append(BollingerBandsRSIMeanReversionStrategy(bb_window=20, rsi_period=14))

    print("=" * 60)
    print(" Running Phase V1 Baseline Strategies")
    print(f" Total Benchmark Bars: {len(candles)}")
    print(f" Target Output Directory: {out_dir}")
    print("=" * 60)

    for strat in strategies:
        print(f"--> Executing {strat.name}...")
        res = run_baseline_strategy(strat, candles, out_dir)
        print(
            f"    Trades: {res['trade_statistics']['total_trades']}, "
            f"Net Return: {res['capital']['return_pct']}%, "
            f"Max Drawdown: {res['performance']['max_drawdown_pct']}%"
        )

    print("\nAll baseline strategy runs completed successfully!")


if __name__ == "__main__":
    main()
