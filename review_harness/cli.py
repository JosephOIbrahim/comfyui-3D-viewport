"""CLI entry: `python -m review_harness ...`"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .codebase import load_snapshot
from .orchestrator import OrchestratorConfig, run, git_head, git_is_clean
from .report import render
from .state import CallLog, FindingStore, RunState


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review_harness",
        description="MOE 5-pass code review harness.",
    )
    p.add_argument("--target", type=Path, default=Path.cwd(), help="Target repository root")
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--model", default="claude-opus-4-7")
    p.add_argument("--fallback-model", default="claude-sonnet-4-6")
    p.add_argument("--allow-fallback", action="store_true", help="Permit fallback model on unavailability")
    p.add_argument("--budget-usd", type=float, default=50.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--run-dir", type=Path, default=None,
                   help="Override run directory; default reports/run_<sha>_<ts>")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan calls and show estimated cost; no API calls")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--report-only", action="store_true",
                   help="Skip review; render final_report.md from existing run-dir")
    p.add_argument("--version", action="version", version=f"review_harness {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = args.target.resolve()

    run_dir = args.run_dir
    if run_dir is None:
        head = git_head(target)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = target / "reports" / f"run_{head[:8]}_{ts}"
    run_dir = run_dir.resolve()

    cfg = OrchestratorConfig(
        target_dir=target,
        rounds=args.rounds,
        model=args.model,
        budget_usd=args.budget_usd,
        seed=args.seed,
        run_dir=run_dir,
        dry_run=args.dry_run,
        resume=args.resume,
        allow_fallback=args.allow_fallback,
        fallback_model=args.fallback_model,
    )

    if args.report_only:
        return _render_only(cfg)

    if args.dry_run:
        return _dry_run(cfg)

    summary = asyncio.run(run(cfg))
    print("\n=== Run complete ===")
    print(f"  run dir: {summary['run_dir']}")
    print(f"  total findings: {summary['total_findings']}")
    print(f"  total cost: ${summary['total_cost_usd']:.4f}")

    _render_only(cfg)
    return 0


def _dry_run(cfg: OrchestratorConfig) -> int:
    target = cfg.target_dir
    clean, dirty = git_is_clean(target)
    if not clean:
        print(f"WARNING: dirty tree (would refuse in real run):\n{dirty}")
    head = git_head(target)
    snap = load_snapshot(target, head)
    print(f"DRY RUN  --  would execute {cfg.rounds}-pass review on {target}")
    print(f"  model: {cfg.model} | seed: {cfg.seed} | budget: ${cfg.budget_usd:.2f}")
    print(f"  files in scope: {len(snap.files)} | total lines: {snap.total_lines()}")
    print(f"  content hash: {snap.content_hash()}")
    print(f"  run dir: {cfg.run_dir}")
    panel_calls = 8
    meta_calls = 1  # devils advocate runs on ~3 of 5 passes
    expected_calls = panel_calls * cfg.rounds + meta_calls * 3
    print(f"  expected expert calls: ~{expected_calls}")
    print(f"  est. cost (rough): ${expected_calls * 0.25:.2f}–${expected_calls * 1.0:.2f}")
    return 0


def _render_only(cfg: OrchestratorConfig) -> int:
    state_path = cfg.run_dir / "state.json"
    if not state_path.exists():
        print(f"no state.json at {cfg.run_dir}; nothing to render")
        return 1
    run_state = RunState.read(state_path)
    store = FindingStore(cfg.run_dir / "findings.jsonl")
    call_log = CallLog(cfg.run_dir / "calls.jsonl")

    pass_summaries: list[dict] = []
    import json as _json
    for p in sorted(cfg.run_dir.glob("pass_*/summary.json")):
        try:
            pass_summaries.append(_json.loads(p.read_text()))
        except _json.JSONDecodeError:
            continue

    md = render(
        run_dir=cfg.run_dir,
        findings=store.all(),
        run_state=run_state,
        call_log=call_log,
        pass_summaries=pass_summaries,
    )
    out = cfg.run_dir / "final_report.md"
    out.write_text(md)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
