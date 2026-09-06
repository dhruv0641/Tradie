"""Integration tests verifying Research Brain physical and architectural boundary isolation.

Enforces:
- Research Brain vs Trading Brain Strict Separation (TRD-ARCH-2, FRD-X-4, BRD BR-6).
- Zero live execution credential leakage into research tasks.
- Zero import edges from research into live order execution routes.
"""

from pathlib import Path

from src.research.environment import (
    ResearchBrainConfig,
    ResearchBrainEnvironment,
    ResearchIsolationError,
    check_research_ast_isolation,
)


def test_research_brain_structural_isolation() -> None:
    """Verify entire src/research directory adheres to architectural isolation."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    research_dir = repo_root / "src" / "research"

    violations = check_research_ast_isolation(research_dir)
    assert violations == [], f"Found forbidden execution imports in research: {violations}"


def test_research_environment_sandbox_enforcement() -> None:
    """Verify ResearchBrainEnvironment cannot be coerced into placing live orders."""
    env = ResearchBrainEnvironment(
        ResearchBrainConfig(is_sandboxed=True, read_only_mode=True),
        scrub_credentials=True,
    )

    # Invariants
    assert env.can_place_orders() is False
    assert env.can_mutate_positions() is False

    # Attempting operations must fail
    try:
        env.attempt_order_placement(order_type="MARKET", side="BUY", quantity=100)
    except ResearchIsolationError as e:
        assert "zero execution authority" in str(e)
    else:
        msg = "ResearchBrainEnvironment must raise ResearchIsolationError on order placement"
        raise AssertionError(msg)

    try:
        env.attempt_position_mutation(instrument="NIFTY", quantity=50)
    except ResearchIsolationError as e:
        assert "read-only access" in str(e)
    else:
        msg = "ResearchBrainEnvironment must raise ResearchIsolationError on position mutation"
        raise AssertionError(msg)
