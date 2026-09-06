"""Unit tests for scripts/run_v1_baseline.py."""

from pathlib import Path
from unittest.mock import patch

from scripts.run_v1_baseline import (
    generate_benchmark_candles,
    main,
    run_baseline_strategy,
)
from src.strategies.trend_baseline import DualEMACrossoverStrategy


def test_generate_benchmark_candles() -> None:
    """Verify benchmark candle generator creates correct number of candles."""
    candles = generate_benchmark_candles(n_bars=50, symbol="NSE:INFY")
    assert len(candles) == 50
    assert candles[0].instrument == "NSE:INFY"
    assert candles[0].close > 0


def test_run_baseline_strategy_writes_reports(tmp_path: Path) -> None:
    """Verify run_baseline_strategy writes Markdown and JSON reports to disk."""
    candles = generate_benchmark_candles(n_bars=60)
    strat = DualEMACrossoverStrategy(fast_span=5, slow_span=15)

    report_json = run_baseline_strategy(strat, candles, tmp_path)

    assert (tmp_path / f"{strat.name}_report.md").exists()
    assert (tmp_path / f"{strat.name}_report.json").exists()
    assert report_json["strategy_id"] == strat.name


def test_main_cli_execution(tmp_path: Path) -> None:
    """Verify CLI main entrypoint executes across strategies."""
    test_args = [
        "run_v1_baseline.py",
        "--strategy",
        "dual_ema",
        "--bars",
        "50",
        "--output-dir",
        str(tmp_path),
    ]
    with patch("sys.argv", test_args):
        main()

    assert (tmp_path / "dual_ema_crossover_report.md").exists()
    assert (tmp_path / "dual_ema_crossover_report.json").exists()
