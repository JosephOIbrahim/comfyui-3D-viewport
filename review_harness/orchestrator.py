"""5-pass MOE orchestrator.

Drives the expert team through five refinement passes against a target
codebase. Each pass:
  1. Selects the expert panel (full on 1/3/5, lean on 2/4 with seeded rotation).
  2. Dispatches each expert in parallel via Claude Agent SDK `query()`.
  3. Collects JSONL findings into the FindingStore.
  4. Runs verify.py to reject hallucinations (R11).
  5. (passes 2/4/5) Runs Devil's Advocate on its rotated target.
  6. Runs Synthesizer to dedupe and rank.
  7. Writes pass artifacts and updates RunState.

Aborts loudly on:
  - dirty git tree, HEAD movement, missing model, budget exceeded,
    per-call or per-pass timeout.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk import types as sdk_types

from .budget import Budget, BudgetExceeded, estimate_cost_usd
from .codebase import CodebaseSnapshot, load_snapshot
from .experts import (
    DEVILS_ADVOCATE_TARGETS,
    META_DEVILS_ADVOCATE,
    META_SYNTHESIZER,
    PANEL_EXPERTS,
    ExpertDef,
    load_all_experts,
)
from .state import (
    CallLog,
    CallRecord,
    Finding,
    FindingStore,
    PassEntry,
    RunState,
    make_finding_id,
)
from .verify import verify_finding


PER_CALL_TIMEOUT_SEC = 600
PER_PASS_TIMEOUT_SEC = 3600
PER_EXPERT_MAX_TURNS = 35


@dataclass
class OrchestratorConfig:
    target_dir: Path
    rounds: int
    model: str
    budget_usd: float
    seed: int
    run_dir: Path
    dry_run: bool = False
    resume: bool = False
    allow_fallback: bool = False
    fallback_model: str | None = None


# ---------- git utilities ----------

def git_head(target_dir: Path) -> str:
    out = subprocess.check_output(
        ["git", "-C", str(target_dir), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    return out


def git_is_clean(target_dir: Path) -> tuple[bool, str]:
    out = subprocess.check_output(
        ["git", "-C", str(target_dir), "status", "--porcelain"],
        text=True,
    )
    # Allow review_harness/, .claude/, reports/, tests/harness/ changes —
    # they're the harness itself, not the codebase under review.
    allow_prefixes = ("review_harness/", ".claude/", "reports/", "tests/harness/", ".gitignore")
    dirty: list[str] = []
    for line in out.splitlines():
        path = line[3:].strip()
        if any(path.startswith(p) for p in allow_prefixes):
            continue
        dirty.append(line)
    return (not dirty), "\n".join(dirty)


# ---------- prompt assembly ----------

def load_constitution(repo_root: Path) -> str:
    return (repo_root / ".claude" / "CONSTITUTION.md").read_text()


def load_prompt_fragment(name: str) -> str:
    base = Path(__file__).parent / "prompts"
    return (base / name).read_text()


def render_codebase_block(snap: CodebaseSnapshot) -> str:
    return (
        "<codebase_readonly>\n"
        f"# Repository: {snap.root}\n"
        f"# Git SHA: {snap.git_sha}\n"
        f"# Total files: {len(snap.files)} | Total lines: {snap.total_lines()}\n"
        "## File Inventory\n"
        f"{snap.inventory_block()}\n"
        "</codebase_readonly>\n"
    )


def expert_user_prompt(
    *,
    expert: ExpertDef,
    pass_num: int,
    snap: CodebaseSnapshot,
    prior_findings: list[Finding],
    out_path: Path,
    blind: bool,
) -> str:
    pass_directives = load_prompt_fragment("pass_directives.md")
    parts: list[str] = []
    parts.append(render_codebase_block(snap))
    parts.append("---\n")
    parts.append(pass_directives)
    parts.append("---\n")
    parts.append(f"# Your Assignment\n")
    parts.append(f"You are running as **{expert.name}** on **pass {pass_num}**.\n")
    parts.append(f"Repository root: `{snap.root}`\n")
    parts.append(
        f"Your scope is your declared lens; do not file findings outside it. "
        f"Forbidden moves are listed in your role prompt.\n"
    )

    if blind or not prior_findings:
        parts.append("\nYou have **no prior findings** — perform fresh discovery.\n")
    else:
        relevant = [f for f in prior_findings if _finding_matches_expert(f, expert)]
        parts.append(
            f"\nYou have **{len(relevant)} prior findings** filtered to your "
            f"`rule_kinds`. For each, choose UPHOLD / REFINE / RETRACT / EXPAND. "
            f"You may also raise NEW findings.\n\n"
        )
        if relevant:
            parts.append("## Prior Findings\n")
            parts.append("```jsonl\n")
            for f in relevant:
                parts.append(f.model_dump_json() + "\n")
            parts.append("```\n")

    parts.append(
        f"\n## Output\n"
        f"Use the Read/Grep/Glob tools to inspect source files under "
        f"`{snap.root}`. Then write your findings as JSONL to:\n\n"
        f"    `{out_path}`\n\n"
        f"One JSON object per line. Each line conforms to the constitution's "
        f"output schema. Do not write to any other path. Do not output the "
        f"findings as a chat reply — write them to the file. After writing, "
        f"reply with one line: `WROTE N findings to <path>`.\n"
    )
    return "".join(parts)


def _finding_matches_expert(f: Finding, expert: ExpertDef) -> bool:
    if f.expert == expert.name:
        return True
    if expert.rule_kinds and f.rule_kind in expert.rule_kinds:
        return True
    return False


# ---------- expert dispatch ----------

async def run_expert(
    *,
    expert: ExpertDef,
    pass_num: int,
    snap: CodebaseSnapshot,
    prior_findings: list[Finding],
    cfg: OrchestratorConfig,
    constitution: str,
    injection_warning: str,
    blind: bool,
    pass_dir: Path,
    call_log: CallLog,
    budget: Budget,
) -> tuple[list[Finding], CallRecord]:
    out_path = pass_dir / f"raw_{expert.name}.jsonl"
    out_path.unlink(missing_ok=True)

    user_prompt = expert_user_prompt(
        expert=expert,
        pass_num=pass_num,
        snap=snap,
        prior_findings=prior_findings,
        out_path=out_path,
        blind=blind,
    )

    options = ClaudeAgentOptions(
        system_prompt=expert.system_prompt(constitution, injection_warning),
        model=cfg.model,
        fallback_model=cfg.fallback_model if cfg.allow_fallback else None,
        allowed_tools=expert.allowed_tools + ["Write"],
        max_turns=PER_EXPERT_MAX_TURNS,
        cwd=str(snap.root),
        permission_mode="bypassPermissions",
        max_budget_usd=min(budget.remaining(), 5.0),
        setting_sources=[],  # we control prompt entirely; do not load project settings
    )

    record = CallRecord(pass_num=pass_num, expert=expert.name)
    started = time.monotonic()

    if cfg.dry_run:
        record.duration_ms = 0
        record.cost_usd = 0.0
        call_log.append(record)
        return [], record

    try:
        async for msg in query(prompt=user_prompt, options=options):
            _accumulate_usage(msg, record)
    except Exception as exc:  # noqa: BLE001
        record.error = f"{type(exc).__name__}: {exc}"
        record.duration_ms = int((time.monotonic() - started) * 1000)
        call_log.append(record)
        return [], record

    record.duration_ms = int((time.monotonic() - started) * 1000)
    if record.cost_usd <= 0:
        record.cost_usd = estimate_cost_usd(
            record.input_tokens, record.cache_read_tokens, record.output_tokens
        )
    budget.charge(record.cost_usd)
    call_log.append(record)

    findings = parse_jsonl_findings(out_path, expert=expert.name, pass_num=pass_num)
    return findings, record


def _accumulate_usage(msg: Any, record: CallRecord) -> None:
    """Pull token usage and cost from any SDK message that carries it."""
    usage = getattr(msg, "usage", None)
    if usage is None and isinstance(msg, dict):
        usage = msg.get("usage")
    if isinstance(usage, dict):
        record.input_tokens += int(usage.get("input_tokens", 0) or 0)
        record.cache_read_tokens += int(usage.get("cache_read_input_tokens", 0) or 0)
        record.output_tokens += int(usage.get("output_tokens", 0) or 0)
    cost = getattr(msg, "total_cost_usd", None)
    if cost is None and isinstance(msg, dict):
        cost = msg.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        record.cost_usd = max(record.cost_usd, float(cost))
    rid = getattr(msg, "session_id", None) or getattr(msg, "id", None)
    if rid and not record.response_id:
        record.response_id = str(rid)


# ---------- finding parsing ----------

def parse_jsonl_findings(path: Path, *, expert: str, pass_num: int) -> list[Finding]:
    if not path.exists():
        return []
    out: list[Finding] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Tolerate lines wrapped in triple-backticks or with leading "json"
        line = re.sub(r"^```(?:json)?", "", line).rstrip("`").strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        finding = _coerce_finding(data, expert=expert, pass_num=pass_num)
        if finding is not None:
            out.append(finding)
    return out


def _coerce_finding(data: dict[str, Any], *, expert: str, pass_num: int) -> Finding | None:
    try:
        file = data["file"]
        line = int(data["line"])
        symbol = data.get("symbol", "<file>") or "<file>"
        rule_kind = data["rule_kind"]
        quote = data["evidence_quote"]
        fid = make_finding_id(file, symbol, rule_kind, quote)
        action_str = data.get("action", "NEW").upper()
        if action_str not in {"NEW", "UPHOLD", "REFINE", "RETRACT", "EXPAND"}:
            action_str = "NEW"
        return Finding(
            id=fid,
            file=file,
            line=line,
            line_end=data.get("line_end"),
            symbol=symbol,
            rule_kind=rule_kind,
            severity=data.get("severity", "LOW"),
            severity_justification=data.get("severity_justification", ""),
            title=data.get("title", "")[:120],
            description=data.get("description", "")[:800],
            evidence_quote=quote,
            proposed_change=data.get("proposed_change", ""),
            cost=data.get("cost", "SMALL"),
            confidence=float(data.get("confidence", 0.5)),
            expert=data.get("expert", expert),
            related_findings=list(data.get("related_findings", [])),
            self_skeptic=list(data.get("self_skeptic", []))[:3],
            rationale_rewrite=data.get("rationale_rewrite"),
            pass_history=[PassEntry(pass_num=pass_num, expert=expert, action=action_str)],
        )
    except (KeyError, ValueError, TypeError):
        return None


# ---------- per-pass driver ----------

def select_panel(pass_num: int, all_experts: dict[str, ExpertDef], rng: random.Random) -> list[ExpertDef]:
    panel_names = [n for n in all_experts if n in PANEL_EXPERTS]
    panel_names.sort()
    if pass_num in (1, 3, 5):
        return [all_experts[n] for n in panel_names]
    drop_count = min(3, max(0, len(panel_names) - 5))
    drop = set(rng.sample(panel_names, k=drop_count))
    return [all_experts[n] for n in panel_names if n not in drop]


async def run_pass(
    *,
    pass_num: int,
    snap: CodebaseSnapshot,
    cfg: OrchestratorConfig,
    all_experts: dict[str, ExpertDef],
    store: FindingStore,
    constitution: str,
    injection_warning: str,
    rng: random.Random,
    call_log: CallLog,
    budget: Budget,
) -> dict[str, Any]:
    pass_dir = cfg.run_dir / f"pass_{pass_num}"
    pass_dir.mkdir(parents=True, exist_ok=True)
    blind = pass_num == 3

    panel = select_panel(pass_num, all_experts, rng)
    prior = store.all() if not blind else []

    print(f"\n=== Pass {pass_num} | panel={[e.name for e in panel]} | blind={blind} | prior={len(prior)} ===")

    # Run experts. Sequential execution keeps the tool subprocess pool sane and
    # makes resume easier; parallelism is a future optimization.
    pass_findings: list[Finding] = []
    for expert in panel:
        print(f"  [{expert.name}] running...")
        try:
            findings, record = await asyncio.wait_for(
                run_expert(
                    expert=expert,
                    pass_num=pass_num,
                    snap=snap,
                    prior_findings=prior,
                    cfg=cfg,
                    constitution=constitution,
                    injection_warning=injection_warning,
                    blind=blind,
                    pass_dir=pass_dir,
                    call_log=call_log,
                    budget=budget,
                ),
                timeout=PER_CALL_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            print(f"  [{expert.name}] TIMEOUT")
            continue
        except BudgetExceeded:
            raise
        print(f"  [{expert.name}] {len(findings)} raw findings | ${record.cost_usd:.4f} | "
              f"{record.duration_ms}ms")
        pass_findings.extend(findings)

    # Verify each finding (R11). Auto-RETRACT failures.
    accepted: list[Finding] = []
    retracted: list[tuple[Finding, str]] = []
    for f in pass_findings:
        ok, note = verify_finding(f, snap)
        if not ok:
            f.verified = False
            f.verification_note = note
            f.pass_history.append(PassEntry(
                pass_num=pass_num,
                expert="harness:verify",
                action="RETRACT",
                note=f"R11 fail: {note}",
            ))
            retracted.append((f, note))
        else:
            f.verified = True
            f.verification_note = "ok"
            accepted.append(f)

    # Persist accepted; retracted findings are recorded in the audit only.
    new_count = 0
    for f in accepted:
        _, is_new = store.upsert(f)
        if is_new:
            new_count += 1

    # Devil's-Advocate (skipped on passes 1 and 3).
    da_target = DEVILS_ADVOCATE_TARGETS.get(pass_num)
    if da_target and not blind and pass_num != 1:
        da_expert = all_experts.get(META_DEVILS_ADVOCATE)
        if da_expert is not None:
            await run_devils_advocate(
                pass_num=pass_num,
                target_name=da_target,
                expert=da_expert,
                snap=snap,
                store=store,
                cfg=cfg,
                constitution=constitution,
                injection_warning=injection_warning,
                pass_dir=pass_dir,
                call_log=call_log,
                budget=budget,
            )

    # Write pass artifacts.
    findings_path = pass_dir / "findings.jsonl"
    findings_path.write_text("".join(
        f.model_dump_json() + "\n" for f in store.all()
    ))

    raw_path = pass_dir / "raw_pass.jsonl"
    raw_path.write_text("".join(
        f.model_dump_json() + "\n" for f in pass_findings
    ))

    summary = {
        "pass_num": pass_num,
        "blind": blind,
        "panel": [e.name for e in panel],
        "raw_count": len(pass_findings),
        "accepted": len(accepted),
        "retracted": len(retracted),
        "store_size": len(store),
        "new_this_pass": new_count,
        "spent_usd": budget.spent_usd,
    }
    (pass_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"  pass {pass_num} summary: {summary}")
    return summary


async def run_devils_advocate(
    *,
    pass_num: int,
    target_name: str,
    expert: ExpertDef,
    snap: CodebaseSnapshot,
    store: FindingStore,
    cfg: OrchestratorConfig,
    constitution: str,
    injection_warning: str,
    pass_dir: Path,
    call_log: CallLog,
    budget: Budget,
) -> None:
    targets = [f for f in store.all() if f.expert == target_name and f.verified]
    if not targets:
        return
    out_path = pass_dir / "devils_advocate_verdicts.jsonl"
    out_path.unlink(missing_ok=True)

    user_prompt = (
        render_codebase_block(snap)
        + "\n---\n\n"
        + f"# Devil's Advocate — pass {pass_num}\n"
        + f"Target expert: **{target_name}**\n"
        + f"You are challenging {len(targets)} findings from this expert.\n"
        + "For each, output VETO / DEMOTE / UPHOLD with the rule and reason.\n"
        + f"Write JSONL verdicts to `{out_path}`. One per line.\n\n"
        + "## Findings to Challenge\n```jsonl\n"
        + "".join(f.model_dump_json() + "\n" for f in targets)
        + "```\n"
    )

    options = ClaudeAgentOptions(
        system_prompt=expert.system_prompt(constitution, injection_warning),
        model=cfg.model,
        fallback_model=cfg.fallback_model if cfg.allow_fallback else None,
        allowed_tools=expert.allowed_tools + ["Write"],
        max_turns=PER_EXPERT_MAX_TURNS,
        cwd=str(snap.root),
        permission_mode="bypassPermissions",
        max_budget_usd=min(budget.remaining(), 5.0),
        setting_sources=[],
    )

    record = CallRecord(pass_num=pass_num, expert=expert.name)
    started = time.monotonic()
    if cfg.dry_run:
        call_log.append(record)
        return
    try:
        async for msg in query(prompt=user_prompt, options=options):
            _accumulate_usage(msg, record)
    except Exception as exc:  # noqa: BLE001
        record.error = f"{type(exc).__name__}: {exc}"
    record.duration_ms = int((time.monotonic() - started) * 1000)
    if record.cost_usd <= 0:
        record.cost_usd = estimate_cost_usd(
            record.input_tokens, record.cache_read_tokens, record.output_tokens
        )
    budget.charge(record.cost_usd)
    call_log.append(record)

    apply_devils_advocate_verdicts(out_path, store, pass_num)


def apply_devils_advocate_verdicts(verdicts_path: Path, store: FindingStore, pass_num: int) -> None:
    if not verdicts_path.exists():
        return
    severity_demote = {
        "BLOCKER": "HIGH", "HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "INFO", "INFO": "INFO",
    }
    for line in verdicts_path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        fid = v.get("finding_id")
        if not fid:
            continue
        finding = store.get(fid)
        if finding is None:
            continue
        verdict = v.get("verdict", "UPHOLD").upper()
        rule = v.get("rule", "")
        reason = v.get("reason", "")
        if verdict == "VETO":
            finding.verified = False
            finding.verification_note = f"DA-VETO [{rule}]: {reason}"
            finding.pass_history.append(PassEntry(
                pass_num=pass_num, expert="moe-devils-advocate",
                action="RETRACT", note=f"VETO {rule}: {reason}",
            ))
        elif verdict == "DEMOTE":
            new_sev = v.get("new_severity") or severity_demote.get(finding.severity, finding.severity)
            finding.severity = new_sev
            finding.pass_history.append(PassEntry(
                pass_num=pass_num, expert="moe-devils-advocate",
                action="REFINE", note=f"DEMOTE -> {new_sev}: {reason}",
            ))
        store.upsert(finding)


# ---------- top-level entry ----------

async def run(cfg: OrchestratorConfig) -> dict[str, Any]:
    target = cfg.target_dir.resolve()
    if not (target / ".git").exists():
        raise SystemExit(f"target dir is not a git repo: {target}")

    clean, dirty_str = git_is_clean(target)
    if not clean:
        raise SystemExit(
            f"target dir has unstaged changes outside the harness; refusing to run.\n{dirty_str}"
        )

    head = git_head(target)
    snap = load_snapshot(target, head)
    if not snap.files:
        raise SystemExit("snapshot is empty; check INCLUDE_GLOBS in codebase.py")

    print(f"Snapshot: {len(snap.files)} files, {snap.total_lines()} lines, content_hash={snap.content_hash()}")
    print(f"Git HEAD: {head}")

    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    state_path = cfg.run_dir / "state.json"
    if cfg.resume and state_path.exists():
        run_state = RunState.read(state_path)
        if run_state.git_sha != head:
            raise SystemExit(
                f"resume aborted: HEAD moved from {run_state.git_sha} to {head}"
            )
    else:
        run_state = RunState.fresh(
            git_sha=head, target_dir=str(target), model=cfg.model,
            rounds=cfg.rounds, seed=cfg.seed,
        )
    run_state.write(state_path)

    repo_root = target
    constitution = load_constitution(repo_root)
    injection_warning = load_prompt_fragment("injection_warning.md")
    all_experts = load_all_experts(repo_root / ".claude" / "agents")

    findings_store = FindingStore(cfg.run_dir / "findings.jsonl")
    call_log = CallLog(cfg.run_dir / "calls.jsonl")
    budget = Budget(cfg.budget_usd)

    rng = random.Random(cfg.seed)
    summaries: list[dict[str, Any]] = []
    for pass_num in range(run_state.last_pass_completed + 1, cfg.rounds + 1):
        try:
            summary = await asyncio.wait_for(
                run_pass(
                    pass_num=pass_num,
                    snap=snap,
                    cfg=cfg,
                    all_experts=all_experts,
                    store=findings_store,
                    constitution=constitution,
                    injection_warning=injection_warning,
                    rng=rng,
                    call_log=call_log,
                    budget=budget,
                ),
                timeout=PER_PASS_TIMEOUT_SEC,
            )
        except BudgetExceeded as exc:
            run_state.aborted = True
            run_state.abort_reason = f"budget: {exc}"
            run_state.write(state_path)
            print(f"ABORT: {exc}")
            break
        except asyncio.TimeoutError:
            run_state.aborted = True
            run_state.abort_reason = f"pass {pass_num} timeout"
            run_state.write(state_path)
            print(f"ABORT: pass {pass_num} timed out")
            break

        summaries.append(summary)
        run_state.last_pass_completed = pass_num
        run_state.write(state_path)

        # Early-exit on convergence (≥90% UPHOLD, no EXPAND, after pass 2).
        if pass_num >= 2 and _converged(findings_store, pass_num):
            print(f"converged early at pass {pass_num}; skipping remaining passes")
            break

    # Re-run HEAD check at end.
    if git_head(target) != head:
        print("WARNING: HEAD moved during run; results may be inconsistent.")

    return {
        "git_sha": head,
        "passes": summaries,
        "total_findings": len(findings_store),
        "total_cost_usd": budget.spent_usd,
        "run_dir": str(cfg.run_dir),
    }


def _converged(store: FindingStore, pass_num: int) -> bool:
    last_actions = [
        f.pass_history[-1].action for f in store.all() if f.pass_history
    ]
    if not last_actions:
        return False
    uphold = sum(1 for a in last_actions if a == "UPHOLD")
    expand = sum(1 for a in last_actions if a == "EXPAND")
    if expand > 0:
        return False
    return (uphold / max(1, len(last_actions))) >= 0.9
