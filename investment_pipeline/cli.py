"""Command line entry point.

    python -m investment_pipeline run    --input examples/sample_input.json
    python -m investment_pipeline screen --input examples/sample_input.json --ideas ideas.json
    python -m investment_pipeline verify --log audit/pipeline.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .audit import AuditLog, verify_log
from .config import PipelineConfig, RiskLimits, resolve_model_tiers
from .schemas import PipelineInput, TradeIdea


def _load_input(path: str) -> PipelineInput:
    with open(path, "r", encoding="utf-8") as fh:
        return PipelineInput.model_validate(json.load(fh))


def _limits_from_args(args: argparse.Namespace) -> RiskLimits:
    kwargs = {}
    if args.max_position_pct is not None:
        kwargs["max_position_weight_pct"] = args.max_position_pct
    if args.max_gross_pct is not None:
        kwargs["max_gross_exposure_pct"] = args.max_gross_pct
    if args.restricted:
        kwargs["restricted_symbols"] = frozenset(s.strip().upper() for s in args.restricted.split(","))
    return RiskLimits(**kwargs)


def _add_limit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-position-pct", type=float, default=None)
    parser.add_argument("--max-gross-pct", type=float, default=None)
    parser.add_argument("--restricted", default=None, help="Comma-separated restricted symbols.")


def cmd_run(args: argparse.Namespace) -> int:
    from .llm import AnthropicStageClient  # imported here so `verify` needs no SDK
    from .pipeline import run

    data = _load_input(args.input)
    config = PipelineConfig(
        limits=_limits_from_args(args),
        model_tiers=resolve_model_tiers(),
        audit_log_path=args.audit_log,
    )
    log = AuditLog(path=args.audit_log)
    result = run(data, AnthropicStageClient(), config=config, log=log)

    if args.json:
        json.dump(result.to_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    report = result.report
    print(f"run {result.run_id}  |  model spend ${result.cost_usd():.4f}")
    if report:
        print(f"\n{report.headline}\n{'-' * len(report.headline)}")
        print(report.executive_summary)
        if report.decisions:
            print("\nDecisions:")
            for d in report.decisions:
                print(f"  {d.symbol:<8} {d.outcome:<9} {d.detail}")
        if report.risk_highlights:
            print("\nRisk highlights:")
            for h in report.risk_highlights:
                print(f"  - {h}")
        if report.follow_ups:
            print("\nFollow-ups:")
            for f in report.follow_ups:
                print(f"  - {f}")
    print(f"\nOrders: {len(result.orders)}   Audit log: {args.audit_log}")
    if result.rejected_orders:
        print("Rejected by the post-execution check:")
        for r in result.rejected_orders:
            print(f"  {r['symbol']}: {r['code']} - {r['detail']}")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    """Run the deterministic engine alone -- no model calls, no credentials."""
    from .risk import screen

    data = _load_input(args.input)
    with open(args.ideas, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    ideas: List[TradeIdea] = [TradeIdea.model_validate(i) for i in raw]
    result = screen(ideas, data.portfolio, _limits_from_args(args))
    json.dump(result.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if result.has_hard_breach else 0


def cmd_verify(args: argparse.Namespace) -> int:
    ok, problem = verify_log(args.log)
    if ok:
        print(f"{args.log}: audit chain intact")
        return 0
    print(f"{args.log}: AUDIT CHAIN BROKEN - {problem}", file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run all four stages.")
    run_p.add_argument("--input", required=True)
    run_p.add_argument("--audit-log", default="audit/pipeline.jsonl")
    run_p.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    _add_limit_args(run_p)
    run_p.set_defaults(func=cmd_run)

    screen_p = sub.add_parser("screen", help="Deterministic limit check only (no API calls).")
    screen_p.add_argument("--input", required=True)
    screen_p.add_argument("--ideas", required=True, help="JSON array of TradeIdea objects.")
    _add_limit_args(screen_p)
    screen_p.set_defaults(func=cmd_screen)

    verify_p = sub.add_parser("verify", help="Verify an audit log's hash chain.")
    verify_p.add_argument("--log", required=True)
    verify_p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
