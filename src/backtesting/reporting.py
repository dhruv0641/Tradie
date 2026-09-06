"""Comprehensive performance reporting engine conforming to PRD §10 and BTD §12."""

import json
from decimal import Decimal
from typing import Any

import structlog

from src.domain.backtest_result import BacktestResult

logger = structlog.get_logger(__name__)

SAMPLE_SIZE_THRESHOLD: int = 30


class BacktestReporter:
    """Reporter generating structured Markdown and JSON performance audits for backtest results."""

    @staticmethod
    def generate_markdown_report(
        result: BacktestResult,
        run_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate human-readable GitHub Flavored Markdown backtest evaluation report.

        Args:
            result: BacktestResult containing metrics, trade log, and equity curve.
            run_metadata: Optional contextual metadata (dataset name, timeframe, date range).

        Returns:
            Structured Markdown string.
        """
        meta = run_metadata or {}
        m = result.metrics

        # Sample size caveat per BTD §12
        if m.total_trades < SAMPLE_SIZE_THRESHOLD:
            sample_size_alert = (
                "> [!WARNING]\n"
                f"> **SAMPLE SIZE CAVEAT (BTD §12)**: Strategy completed only "
                f"**{m.total_trades} trades** (threshold: {SAMPLE_SIZE_THRESHOLD} trades).\n"
                "> Statistical metrics lack statistical significance and must NOT be used for "
                "production promotion without extended validation.\n"
            )
        else:
            sample_size_alert = (
                "> [!NOTE]\n"
                f"> **Sample Size Validation (BTD §12)**: Strategy completed "
                f"**{m.total_trades} trades**, satisfying the minimum statistical threshold "
                f"of {SAMPLE_SIZE_THRESHOLD} trades.\n"
            )

        # Indian cost drag attribution
        cost_drag_pct = (
            round((m.total_costs / m.gross_profit) * Decimal("100"), 2)
            if m.gross_profit > Decimal("0")
            else Decimal("0.00")
        )
        sharpe_str = f"{m.sharpe_ratio:.2f}" if m.sharpe_ratio is not None else "N/A"
        sortino_str = f"{m.sortino_ratio:.2f}" if m.sortino_ratio is not None else "N/A"
        spread_val = m.gross_profit - m.gross_loss - m.net_profit
        avg_trade = (
            (m.net_profit / Decimal(str(m.total_trades))) if m.total_trades > 0 else Decimal("0.00")
        )

        lines: list[str] = [
            f"# Backtest Performance Report: {result.strategy_id}",
            "",
            sample_size_alert,
            "## 1. Executive Summary & Core Return Metrics (PRD §10)",
            "",
            "| Metric | Value | Description |",
            "|---|---|---|",
            f"| **Initial Capital** | ₹{result.initial_capital:,.2f} | Starting capital (PRD §9) |",
            f"| **Final Equity** | ₹{result.final_equity:,.2f} | Ending capital balance |",
            f"| **Net Profit** | ₹{m.net_profit:,.2f} | Realized PnL net of friction |",
            f"| **Return on Capital** | {m.return_pct:.2f}% | Total percentage net return |",
            (
                f"| **Maximum Drawdown** | {m.max_drawdown_pct:.2f}% "
                "| Peak-to-trough capital decline |"
            ),
            f"| **Sharpe Ratio** | {sharpe_str} | Annualized risk-adjusted excess return |",
            (
                f"| **Sortino Ratio** | {sortino_str} "
                "| Annualized downside-deviation adjusted return |"
            ),
            f"| **Profit Factor** | {m.profit_factor:.2f} | Gross Profit / Gross Loss |",
            (
                f"| **Expectancy per Trade** | ₹{avg_trade:,.2f} "
                "| Mathematical average gain per closed trade |"
            ),
            "",
            "## 2. Trading Consistency & Win/Loss Breakdown",
            "",
            "| Trade Statistic | Value |",
            "|---|---|",
            f"| **Total Closed Trades** | {m.total_trades} |",
            f"| **Winning Trades** | {m.winning_trades} ({m.win_rate:.1f}%) |",
            f"| **Losing Trades** | {m.losing_trades} ({100 - m.win_rate:.1f}%) |",
            f"| **Average Trade Return** | ₹{avg_trade:,.2f} |",
            f"| **Gross Profit** | ₹{m.gross_profit:,.2f} |",
            f"| **Gross Loss** | ₹{m.gross_loss:,.2f} |",
            "",
            "## 3. Indian Market Cost Drag Attribution (BTD §6, §12)",
            "",
            "| Cost Category | Impact | Notes |",
            "|---|---|---|",
            (
                f"| **Total Transaction Friction** | ₹{m.total_costs:,.2f} "
                "| Statutory taxes, brokerage, and slippage |"
            ),
            (
                f"| **Cost Drag on Gross Profit** | {cost_drag_pct:.2f}% "
                "| Proportion of gross profit consumed |"
            ),
            (
                f"| **Gross vs Net Spread** | ₹{spread_val:,.2f} "
                "| Total difference between gross edge and net cash |"
            ),
            "",
            "## 4. Known Limitations & Bias Disclosures (BTD §12, §15)",
            "",
            (
                "1. **Slippage Calibration**: Frictional slippage uses the baseline Indian "
                "equity model (5-10 bps base + liquidity volume scaling tiers). Empirical "
                "calibration occurs in Phase V4 Paper Trading (BTD-8, BTD-9)."
            ),
            (
                "2. **Point-in-Time Data**: Assumes point-in-time OHLCV candles with zero "
                "look-ahead bias enforced via Next-Bar Open fill protocol (BTD §7)."
            ),
            (
                "3. **Capital Sizing**: Sizing strictly respects the initial ₹10,000 baseline "
                "with no leverage or margin borrowing (PRD §9, BRD BR-2)."
            ),
            "",
        ]

        if meta:
            lines.extend(
                [
                    "## 5. Execution Run Metadata",
                    "",
                    "| Parameter | Value |",
                    "|---|---|",
                ]
            )
            for k, v in meta.items():
                lines.append(f"| **{k}** | {v} |")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_json_report(
        result: BacktestResult,
        run_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate structured machine-readable JSON dictionary for audit storage and APIs.

        Args:
            result: BacktestResult instance.
            run_metadata: Optional contextual metadata.

        Returns:
            JSON-serializable dictionary.
        """
        m = result.metrics
        has_small_sample = m.total_trades < SAMPLE_SIZE_THRESHOLD
        avg_trade = (
            (m.net_profit / Decimal(str(m.total_trades))) if m.total_trades > 0 else Decimal("0.00")
        )

        report_dict: dict[str, Any] = {
            "strategy_id": result.strategy_id,
            "metadata": run_metadata or {},
            "capital": {
                "initial": float(result.initial_capital),
                "final": float(result.final_equity),
                "net_profit": float(m.net_profit),
                "return_pct": float(m.return_pct),
            },
            "performance": {
                "sharpe_ratio": float(m.sharpe_ratio) if m.sharpe_ratio is not None else None,
                "sortino_ratio": float(m.sortino_ratio) if m.sortino_ratio is not None else None,
                "profit_factor": float(m.profit_factor),
                "expectancy": float(avg_trade),
                "max_drawdown_pct": float(m.max_drawdown_pct),
            },
            "trade_statistics": {
                "total_trades": m.total_trades,
                "winning_trades": m.winning_trades,
                "losing_trades": m.losing_trades,
                "win_rate": float(m.win_rate),
                "gross_profit": float(m.gross_profit),
                "gross_loss": float(m.gross_loss),
                "average_trade": float(avg_trade),
            },
            "cost_attribution": {
                "total_costs": float(m.total_costs),
                "cost_drag_pct": (
                    float(round((m.total_costs / m.gross_profit) * Decimal("100"), 2))
                    if m.gross_profit > Decimal("0")
                    else 0.0
                ),
            },
            "caveats": {
                "sample_size_warning": has_small_sample,
                "sample_size_threshold": SAMPLE_SIZE_THRESHOLD,
                "trade_count": m.total_trades,
                "warning_message": (
                    f"Sample size {m.total_trades} is below threshold {SAMPLE_SIZE_THRESHOLD}"
                    if has_small_sample
                    else None
                ),
            },
            "parameters": result.parameters,
        }

        # Verify json-serializable
        json.dumps(report_dict)
        return report_dict
