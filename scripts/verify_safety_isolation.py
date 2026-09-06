#!/usr/bin/env python3
"""Static Architecture and Safety Isolation Linter.

Enforces LLD §10, TRD-ARCH-3, HLD §8, and NFR-SAFE-5:
1. Zero import edges from src/risk/ or src/decision/ into src/agents/, ML frameworks,
   LLM clients, broker SDKs, or external message brokers.
2. Supervisor.decide() begins with kill-switch check as the very first executable statement.
3. Zero override/bypass parameters in Supervisor.decide() or RiskEngine.evaluate().
"""

import ast
import sys
from pathlib import Path

FORBIDDEN_IMPORT_PREFIXES = {
    # Agents roster
    "src.agents",
    "agents",
    # ML & DL frameworks
    "sklearn",
    "torch",
    "tensorflow",
    "keras",
    "xgboost",
    "lightgbm",
    "catboost",
    # LLM & Agentic AI client libraries
    "openai",
    "anthropic",
    "langchain",
    "llama_index",
    "chromadb",
    "transformers",
    # External message brokers & event buses
    "celery",
    "pika",
    "kafka",
    "kombu",
    # Broker direct SDKs (isolation per TRD-EXEC-4)
    "kiteconnect",
    "smartapi",
    "fyers_api",
}

FORBIDDEN_PARAMETER_TERMS = {
    "override",
    "force",
    "bypass",
    "ignore_risk",
    "skip_risk",
    "force_approve",
}


def check_file_imports(file_path: Path) -> list[str]:
    """Check that a file does not import any forbidden modules."""
    violations: list[str] = []
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception as e:
        return [f"Failed to parse {file_path}: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in FORBIDDEN_IMPORT_PREFIXES:
                    if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                        violations.append(
                            f"{file_path}:{node.lineno} - Forbidden import '{alias.name}' detected"
                        )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for forbidden in FORBIDDEN_IMPORT_PREFIXES:
                if node.module == forbidden or node.module.startswith(forbidden + "."):
                    violations.append(
                        f"{file_path}:{node.lineno} - Forbidden from-import "
                        f"'{node.module}' detected"
                    )

    return violations


def _check_decide_method(item: ast.FunctionDef, supervisor_file: Path) -> list[str]:
    """Verify parameters and first statement of Supervisor.decide()."""
    violations: list[str] = []

    # 1. Check parameters for bypass terms
    for arg in item.args.args:
        for forbidden_term in FORBIDDEN_PARAMETER_TERMS:
            if forbidden_term in arg.arg.lower():
                violations.append(
                    f"{supervisor_file}:{item.lineno} - Forbidden bypass parameter "
                    f"'{arg.arg}' found in Supervisor.decide()"
                )

    # 2. Check first executable statement in decide()
    first_stmt = None
    for stmt in item.body:
        # Skip docstrings
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            continue
        first_stmt = stmt
        break

    if first_stmt is None or not isinstance(first_stmt, ast.If):
        violations.append(
            f"{supervisor_file}:{item.lineno} - Supervisor.decide() first "
            "statement must be an 'if' checking the kill switch"
        )
    else:
        test_str = ast.unparse(first_stmt.test)
        if "kill_switch" not in test_str or "is_active" not in test_str:
            violations.append(
                f"{supervisor_file}:{first_stmt.lineno} - Supervisor.decide() "
                f"first statement must check kill switch (found: '{test_str}')"
            )

    return violations


def check_supervisor_precedence_and_signature(supervisor_file: Path) -> list[str]:
    """Verify Supervisor.decide() starts with kill-switch check and has no override args."""
    if not supervisor_file.exists():
        return [f"Supervisor file not found at {supervisor_file}"]

    content = supervisor_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(supervisor_file))

    found_supervisor = False
    found_decide = False
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Supervisor":
            found_supervisor = True
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "decide":
                    found_decide = True
                    violations.extend(_check_decide_method(item, supervisor_file))

    if not found_supervisor:
        violations.append(f"{supervisor_file} - Class 'Supervisor' not found")
    elif not found_decide:
        violations.append(f"{supervisor_file} - Method 'decide' not found in class Supervisor")

    return violations


def check_risk_engine_signature(engine_file: Path) -> list[str]:
    """Verify RiskEngine.evaluate() has no override/bypass parameters."""
    violations: list[str] = []
    if not engine_file.exists():
        return [f"RiskEngine file not found at {engine_file}"]

    content = engine_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(engine_file))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RiskEngine":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "evaluate":
                    for arg in item.args.args:
                        for forbidden_term in FORBIDDEN_PARAMETER_TERMS:
                            if forbidden_term in arg.arg.lower():
                                violations.append(
                                    f"{engine_file}:{item.lineno} - Forbidden bypass parameter "
                                    f"'{arg.arg}' found in RiskEngine.evaluate()"
                                )

    return violations


def verify_safety_isolation(repo_root: Path) -> list[str]:
    """Run all safety isolation audits across the codebase."""
    all_violations: list[str] = []

    # 1. Scan src/risk/ and src/decision/ for forbidden imports
    targets = [repo_root / "src" / "risk", repo_root / "src" / "decision"]
    for target_dir in targets:
        if target_dir.exists():
            for py_file in target_dir.rglob("*.py"):
                violations = check_file_imports(py_file)
                all_violations.extend(violations)

    # 2. Verify Supervisor precedence and signature
    supervisor_file = repo_root / "src" / "decision" / "supervisor.py"
    all_violations.extend(check_supervisor_precedence_and_signature(supervisor_file))

    # 3. Verify RiskEngine signature
    engine_file = repo_root / "src" / "risk" / "engine.py"
    all_violations.extend(check_risk_engine_signature(engine_file))

    return all_violations


def main() -> int:
    """CLI entrypoint for safety isolation verification."""
    repo_root = Path(__file__).resolve().parent.parent
    print(f"--> Running Safety Isolation & Precedence Linter on {repo_root}...")

    violations = verify_safety_isolation(repo_root)

    if violations:
        print("\n========================================================")
        print("  CRITICAL SAFETY ISOLATION VIOLATIONS DETECTED")
        print("========================================================")
        for v in violations:
            print(f"  [FAIL] {v}")
        print("========================================================")
        return 1

    print("[PASS] All safety isolation, minimal-dependency, and precedence checks passed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
