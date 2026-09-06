"""CLI utility for querying and inspecting trading decision explainability reports.

Conforms to FRD-EVAL-4, FRD-EVAL-6, and NFR-AUDIT-2. Answers the 5 core operator queries
grounded strictly in the immutable audit trail.
"""

import argparse
import json
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.audit.decision_logger import DecisionAuditService
from src.audit.explain import DecisionExplainer
from src.config.models import DatabaseConfig


def parse_args() -> argparse.Namespace:
    """Parse CLI command line arguments."""
    parser = argparse.ArgumentParser(
        description="Explainability Query Tool for AI Trader decisions (FRD-EVAL-4)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--id",
        type=str,
        help="UUID or string identifier of the DecisionRecord to explain",
    )
    group.add_argument(
        "--recent",
        type=int,
        metavar="N",
        help="List and explain the N most recent decisions",
    )

    parser.add_argument(
        "--instrument",
        type=str,
        default=None,
        help="Optional instrument filter (e.g. NSE:RELIANCE)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database connection URL (e.g. sqlite:///trades.db or postgresql://...)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of formatted text",
    )
    return parser.parse_args()


def run_cli() -> int:
    """Execute decision explanation CLI query."""
    args = parse_args()

    db_url = args.db_url
    if not db_url:
        db_config = DatabaseConfig()
        db_url = db_config.get_connection_url(async_driver=False)

    try:
        engine = create_engine(db_url)
    except Exception as exc:
        print(f"Error connecting to database at {db_url}: {exc}", file=sys.stderr)
        return 1

    audit_service = DecisionAuditService()
    explainer = DecisionExplainer(audit_service=audit_service)

    with Session(engine) as session:
        if args.id:
            report = explainer.explain_decision_sync(args.id, session=session)
            if args.json:
                print(report.model_dump_json(indent=2))
            else:
                print(report.to_text_report())
            return 0 if report.found else 2

        if args.recent:
            recent_models = audit_service.get_recent_decisions_sync(
                session=session,
                limit=args.recent,
                instrument=args.instrument,
            )

            if not recent_models:
                print("No decision records found in database.", file=sys.stderr)
                return 0

            reports: list[dict[str, Any]] = []
            for model in recent_models:
                report = explainer.explain_from_model(model)
                if args.json:
                    reports.append(report.model_dump())
                else:
                    print(report.to_text_report())
                    print()

            if args.json:
                print(json.dumps(reports, indent=2, default=str))

            return 0

    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
