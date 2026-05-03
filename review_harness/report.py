"""Final Markdown report generation.

Produces:
  - reports/run_<sha>_<ts>/final_report.md
  - executive summary, severity counts, ranked top findings,
    lifecycle table, per-expert contribution, cost breakdown.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .state import CallLog, Finding, FindingStore, RunState


SEVERITY_WEIGHT = {"BLOCKER": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 0.5, "INFO": 0.1}
COST_WEIGHT = {"TRIVIAL": 1, "SMALL": 2, "MEDIUM": 4, "LARGE": 8}


def priority(f: Finding) -> float:
    sev = SEVERITY_WEIGHT.get(f.severity, 0.5)
    cst = COST_WEIGHT.get(f.cost, 4)
    return sev * f.confidence / cst


def _sev_order(f: Finding) -> int:
    order = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    return order.get(f.severity, 5)


def render(
    *,
    run_dir: Path,
    findings: list[Finding],
    run_state: RunState,
    call_log: CallLog,
    pass_summaries: list[dict],
) -> str:
    accepted = [f for f in findings if f.verified]
    retracted = [f for f in findings if not f.verified]

    sev_counts = Counter(f.severity for f in accepted)
    expert_counts = Counter(f.expert for f in accepted)

    parts: list[str] = []
    parts.append(_header(run_state, accepted, retracted, sev_counts))
    parts.append(_executive_summary(accepted, sev_counts, run_state))
    parts.append(_pass_lifecycle_table(pass_summaries))
    parts.append(_top_findings_section(accepted))
    parts.append(_full_findings_section(accepted))
    if retracted:
        parts.append(_retracted_section(retracted))
    parts.append(_expert_contribution_section(expert_counts, run_state))
    parts.append(_cost_section(call_log))
    parts.append(_footer(run_state))
    return "\n\n".join(parts).strip() + "\n"


def _header(state: RunState, accepted: list[Finding], retracted: list[Finding], sev: Counter) -> str:
    return (
        f"# Code Review Report — `{state.target_dir}`\n\n"
        f"- **Run started:** {state.started_at}\n"
        f"- **Model:** `{state.model}`\n"
        f"- **Git SHA:** `{state.git_sha}`\n"
        f"- **Passes completed:** {state.last_pass_completed} / {state.rounds_planned}\n"
        f"- **Findings:** {len(accepted)} accepted · {len(retracted)} retracted\n"
        f"- **Severity counts:** "
        f"BLOCKER={sev.get('BLOCKER', 0)} · HIGH={sev.get('HIGH', 0)} · "
        f"MEDIUM={sev.get('MEDIUM', 0)} · LOW={sev.get('LOW', 0)} · INFO={sev.get('INFO', 0)}\n"
        f"- **Aborted:** {state.aborted}"
        + (f" — {state.abort_reason}" if state.abort_reason else "")
    )


def _executive_summary(findings: list[Finding], sev: Counter, state: RunState) -> str:
    high_or_above = [f for f in findings if f.severity in ("BLOCKER", "HIGH")]
    parts = ["## Executive Summary\n"]
    if not findings:
        parts.append(
            "No accepted findings. Either the codebase is in good shape, the "
            "harness is mis-tuned, or the run aborted early — see the cost "
            "and lifecycle sections below before drawing conclusions."
        )
        return "".join(parts)
    parts.append(
        f"The MOE panel completed {state.last_pass_completed} pass(es) and produced "
        f"{len(findings)} verified findings, of which **{len(high_or_above)} are "
        f"HIGH or BLOCKER**.\n\n"
    )
    if high_or_above:
        parts.append("**Top concerns:**\n")
        for f in sorted(high_or_above, key=priority, reverse=True)[:5]:
            parts.append(f"- `{f.file}:{f.line}` — *{f.title}* ({f.severity}, {f.cost})\n")
    return "".join(parts)


def _pass_lifecycle_table(summaries: list[dict]) -> str:
    if not summaries:
        return "## Pass Lifecycle\n\n_No passes completed._"
    rows = ["| Pass | Panel | Raw | Accepted | Retracted | Store size | New | Spent USD |",
            "|---|---|---:|---:|---:|---:|---:|---:|"]
    for s in summaries:
        panel = ", ".join(p.replace("moe-", "") for p in s.get("panel", []))
        rows.append(
            f"| {s['pass_num']}{' (blind)' if s.get('blind') else ''} | {panel} | "
            f"{s['raw_count']} | {s['accepted']} | {s['retracted']} | "
            f"{s['store_size']} | {s['new_this_pass']} | "
            f"${s['spent_usd']:.4f} |"
        )
    return "## Pass Lifecycle\n\n" + "\n".join(rows)


def _top_findings_section(findings: list[Finding]) -> str:
    ranked = sorted(findings, key=priority, reverse=True)[:10]
    if not ranked:
        return "## Top Findings\n\n_None._"
    out = ["## Top 10 Findings (by priority)\n"]
    out.append("| # | Severity | Cost | File | Title |")
    out.append("|---|---|---|---|---|")
    for i, f in enumerate(ranked, 1):
        out.append(f"| {i} | {f.severity} | {f.cost} | `{f.file}:{f.line}` | {f.title} |")
    return "\n".join(out)


def _full_findings_section(findings: list[Finding]) -> str:
    out = ["## All Accepted Findings\n"]
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        grouped[f.severity].append(f)
    for sev in ("BLOCKER", "HIGH", "MEDIUM", "LOW", "INFO"):
        bucket = grouped.get(sev, [])
        if not bucket:
            continue
        out.append(f"\n### {sev} ({len(bucket)})\n")
        for f in sorted(bucket, key=priority, reverse=True):
            out.append(_render_finding(f))
    return "\n".join(out)


def _render_finding(f: Finding) -> str:
    history = " → ".join(
        f"{e.pass_num}:{e.expert.replace('moe-', '')}:{e.action}"
        for e in f.pass_history
    ) or "—"
    skeptic = "\n".join(f"  - {s}" for s in f.self_skeptic) or "  _(none)_"
    related = ", ".join(f"`{r}`" for r in f.related_findings) or "—"
    return (
        f"#### `{f.id}` — {f.title}\n\n"
        f"- **Where:** `{f.file}:{f.line}` · symbol `{f.symbol}` · rule `{f.rule_kind}`\n"
        f"- **Severity:** {f.severity} ({f.severity_justification})\n"
        f"- **Cost:** {f.cost} · **Confidence:** {f.confidence:.2f} · **Expert:** {f.expert}\n"
        f"- **Lifecycle:** {history}\n"
        f"- **Related:** {related}\n\n"
        f"{f.description}\n\n"
        f"**Evidence:**\n```\n{f.evidence_quote}\n```\n\n"
        f"**Proposed change:**\n{f.proposed_change}\n\n"
        f"**Self-skeptic:**\n{skeptic}\n"
        + (f"\n**Rewrite rationale (R5):** {f.rationale_rewrite}\n" if f.rationale_rewrite else "")
        + "\n---\n"
    )


def _retracted_section(retracted: list[Finding]) -> str:
    out = [f"## Retracted Findings ({len(retracted)})\n"]
    out.append("These findings were filed but failed verification (R11) or were "
               "vetoed by the Devil's Advocate. They are kept in the audit log "
               "for transparency but are not actionable.\n")
    out.append("| File | Title | Reason |")
    out.append("|---|---|---|")
    for f in retracted:
        out.append(f"| `{f.file}:{f.line}` | {f.title} | {f.verification_note} |")
    return "\n".join(out)


def _expert_contribution_section(counts: Counter, state: RunState) -> str:
    out = ["## Expert Contribution\n"]
    out.append("| Expert | Accepted findings |")
    out.append("|---|---:|")
    for name, n in counts.most_common():
        out.append(f"| `{name}` | {n} |")
    return "\n".join(out)


def _cost_section(call_log: CallLog) -> str:
    if not call_log.path.exists():
        return "## Cost\n\n_No call log._"
    by_expert: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cost": 0.0})
    for line in call_log.path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        b = by_expert[r["expert"]]
        b["calls"] += 1
        b["input"] += r.get("input_tokens", 0)
        b["output"] += r.get("output_tokens", 0)
        b["cost"] += r.get("cost_usd", 0.0)
    rows = ["| Expert | Calls | Input tokens | Output tokens | Cost USD |",
            "|---|---:|---:|---:|---:|"]
    total_cost = 0.0
    for name in sorted(by_expert):
        b = by_expert[name]
        total_cost += b["cost"]
        rows.append(f"| `{name}` | {b['calls']} | {b['input']:,} | {b['output']:,} | ${b['cost']:.4f} |")
    rows.append(f"| **TOTAL** | | | | **${total_cost:.4f}** |")
    return "## Cost\n\n" + "\n".join(rows)


def _footer(state: RunState) -> str:
    now = datetime.now(timezone.utc).isoformat()
    return (
        "## Provenance\n\n"
        f"- Generated: {now}\n"
        f"- Constitution: `.claude/CONSTITUTION.md` (R1–R13)\n"
        f"- Harness: `review_harness/` v0.1.0\n"
        f"- Reproduce: `python -m review_harness --rounds {state.rounds_planned} "
        f"--model {state.model} --seed {state.seed}`\n"
    )
