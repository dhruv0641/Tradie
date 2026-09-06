"""Monte Carlo trade-sequence resampling engine and sequence-risk evaluation (BTD §8.5, RTLD §8)."""

import random
from decimal import Decimal

import structlog

from src.domain.backtest_result import BacktestTrade
from src.domain.validation import MonteCarloSimulationResult

logger = structlog.get_logger(__name__)


class MonteCarloSimulator:
    """Bootstrap trade-sequence resampler testing sequence risk and drawdown probabilities."""

    def __init__(
        self,
        simulation_count: int = 1000,
        initial_capital: Decimal = Decimal("10000.00"),
        halt_threshold_pct: Decimal = Decimal("8.00"),
        kill_switch_threshold_pct: Decimal = Decimal("10.00"),
        seed: int | None = None,
    ) -> None:
        """Initialize Monte Carlo simulator.

        Args:
            simulation_count: Number of bootstrap iterations (>= 1,000 paths per BTD-13).
            initial_capital: Starting capital in INR (₹10,000 baseline per PRD §9).
            halt_threshold_pct: Drawdown percentage triggering trading halt (8.0% per RTLD §8).
            kill_switch_threshold_pct: Drawdown % triggering kill switch (10.0% per RTLD §8).
            seed: Deterministic PRNG seed for exact reproducibility (BTD §10).

        Raises:
            ValueError: If simulation_count < 100 or initial_capital <= 0.
        """
        if simulation_count < 100:
            msg = (
                f"simulation_count must be at least 100 (proposed >= 1,000), got {simulation_count}"
            )
            raise ValueError(msg)
        if initial_capital <= Decimal("0"):
            msg = f"initial_capital must be strictly positive, got {initial_capital}"
            raise ValueError(msg)

        self.simulation_count = simulation_count
        self.initial_capital = initial_capital
        self.halt_threshold_pct = halt_threshold_pct
        self.kill_switch_threshold_pct = kill_switch_threshold_pct
        self.seed = seed

    @staticmethod
    def _calculate_percentile(sorted_values: list[Decimal], percentile: float) -> Decimal:
        """Calculate empirical percentile from a sorted list of Decimal values."""
        if not sorted_values:
            return Decimal("0.00")
        k = (len(sorted_values) - 1) * (percentile / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_values) - 1)
        d = Decimal(str(k - f))
        return (sorted_values[f] + d * (sorted_values[c] - sorted_values[f])).quantize(
            Decimal("0.01")
        )

    def _simulate_single_path(
        self,
        rng: random.Random,
        trade_pnls: list[Decimal],
        n_trades: int,
    ) -> tuple[Decimal, Decimal, bool, bool, bool, list[Decimal]]:
        """Simulate a single bootstrap path of trade returns."""
        equity = self.initial_capital
        peak_equity = self.initial_capital
        max_dd_pct = Decimal("0.00")
        curve: list[Decimal] = [equity]

        sampled_pnls = rng.choices(trade_pnls, k=n_trades)
        hit_halt = False
        hit_kill_switch = False
        hit_ruin = False

        for pnl in sampled_pnls:
            equity += pnl
            curve.append(equity)

            peak_equity = max(peak_equity, equity)

            if peak_equity > Decimal("0"):
                current_dd = ((peak_equity - equity) / peak_equity) * Decimal("100")
                max_dd_pct = max(max_dd_pct, current_dd)

            if max_dd_pct >= self.halt_threshold_pct:
                hit_halt = True
            if max_dd_pct >= self.kill_switch_threshold_pct:
                hit_kill_switch = True
            if equity <= Decimal("0"):
                hit_ruin = True

        return equity, max_dd_pct, hit_halt, hit_kill_switch, hit_ruin, curve

    def run_from_trades(
        self,
        trades: list[BacktestTrade],
    ) -> MonteCarloSimulationResult:
        """Execute bootstrap resampling from a list of completed BacktestTrade entities.

        Args:
            trades: List of realized BacktestTrade objects.

        Returns:
            MonteCarloSimulationResult with percentile equity, drawdowns, and breach probabilities.
        """
        pnls = [t.net_pnl for t in trades]
        return self.run_from_pnls(pnls)

    def run_from_pnls(
        self,
        trade_pnls: list[Decimal],
    ) -> MonteCarloSimulationResult:
        """Execute bootstrap resampling from trade PnL amounts.

        Args:
            trade_pnls: Realized PnL amounts in INR for each completed trade.

        Returns:
            MonteCarloSimulationResult domain entity.
        """
        rng = random.Random(self.seed)

        if not trade_pnls:
            logger.warning(
                "monte_carlo_empty_trades", strategy_initial_capital=str(self.initial_capital)
            )
            return MonteCarloSimulationResult(
                simulation_count=self.simulation_count,
                initial_capital=self.initial_capital,
                trade_count=0,
                seed=self.seed,
                equity_p5=self.initial_capital,
                equity_p50=self.initial_capital,
                equity_p95=self.initial_capital,
                max_drawdown_p5=Decimal("0.00"),
                max_drawdown_p50=Decimal("0.00"),
                max_drawdown_p95=Decimal("0.00"),
                worst_case_drawdown=Decimal("0.00"),
                prob_drawdown_halt_8pct=Decimal("0.0000"),
                prob_kill_switch_10pct=Decimal("0.0000"),
                prob_ruin=Decimal("0.0000"),
                sample_equity_curves=[[self.initial_capital]],
            )

        n_trades = len(trade_pnls)
        final_equities: list[Decimal] = []
        max_drawdowns: list[Decimal] = []
        sample_curves: list[list[Decimal]] = []

        halt_breaches = 0
        kill_switch_breaches = 0
        ruin_events = 0

        for sim_idx in range(self.simulation_count):
            eq, max_dd, hit_halt, hit_kill, hit_ruin, curve = self._simulate_single_path(
                rng, trade_pnls, n_trades
            )
            final_equities.append(eq)
            max_drawdowns.append(max_dd)

            if hit_halt:
                halt_breaches += 1
            if hit_kill:
                kill_switch_breaches += 1
            if hit_ruin:
                ruin_events += 1

            if sim_idx < 10:
                sample_curves.append(curve)

        final_equities.sort()
        max_drawdowns.sort()

        sim_count_dec = Decimal(str(self.simulation_count))
        prob_halt = (Decimal(str(halt_breaches)) / sim_count_dec).quantize(Decimal("0.0001"))
        prob_kill = (Decimal(str(kill_switch_breaches)) / sim_count_dec).quantize(Decimal("0.0001"))
        prob_ruin = (Decimal(str(ruin_events)) / sim_count_dec).quantize(Decimal("0.0001"))

        eq_p5 = self._calculate_percentile(final_equities, 5.0)
        eq_p50 = self._calculate_percentile(final_equities, 50.0)
        eq_p95 = self._calculate_percentile(final_equities, 95.0)

        dd_p5 = self._calculate_percentile(max_drawdowns, 5.0)
        dd_p50 = self._calculate_percentile(max_drawdowns, 50.0)
        dd_p95 = self._calculate_percentile(max_drawdowns, 95.0)
        worst_dd = max_drawdowns[-1].quantize(Decimal("0.01"))

        logger.info(
            "monte_carlo_resampling_completed",
            simulation_count=self.simulation_count,
            seed=self.seed,
            trades_count=n_trades,
            median_equity=str(eq_p50),
            median_drawdown=str(dd_p50),
            prob_halt_8pct=str(prob_halt),
            prob_kill_switch_10pct=str(prob_kill),
        )

        return MonteCarloSimulationResult(
            simulation_count=self.simulation_count,
            initial_capital=self.initial_capital,
            trade_count=n_trades,
            seed=self.seed,
            equity_p5=eq_p5,
            equity_p50=eq_p50,
            equity_p95=eq_p95,
            max_drawdown_p5=dd_p5,
            max_drawdown_p50=dd_p50,
            max_drawdown_p95=dd_p95,
            worst_case_drawdown=worst_dd,
            prob_drawdown_halt_8pct=prob_halt,
            prob_kill_switch_10pct=prob_kill,
            prob_ruin=prob_ruin,
            sample_equity_curves=sample_curves,
        )
