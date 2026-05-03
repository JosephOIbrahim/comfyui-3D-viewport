"""Loads MOE expert definitions from .claude/agents/*.md frontmatter.

Single source of truth: the same files Claude Code uses as subagent
definitions are parsed by the orchestrator to drive expert calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ExpertDef:
    name: str
    model: str
    temperature: float
    allowed_tools: list[str]
    lens: str
    forbidden_moves: list[str]
    rule_kinds: list[str]
    body: str
    source_path: Path

    def system_prompt(self, constitution: str, injection_warning: str) -> str:
        return (
            f"{injection_warning}\n\n"
            f"# Role: {self.name}\n\n"
            f"{self.body}\n\n"
            "---\n\n"
            f"{constitution}"
        )


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def parse_agent_file(path: Path) -> ExpertDef:
    text = path.read_text()
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: missing YAML frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()
    return ExpertDef(
        name=fm["name"],
        model=fm.get("model", "claude-opus-4-7"),
        temperature=float(fm.get("temperature", 0.4)),
        allowed_tools=list(fm.get("allowed_tools", ["Read", "Grep", "Glob"])),
        lens=str(fm.get("lens", "")),
        forbidden_moves=list(fm.get("forbidden_moves", [])),
        rule_kinds=list(fm.get("rule_kinds", [])),
        body=body,
        source_path=path,
    )


def load_all_experts(agents_dir: Path) -> dict[str, ExpertDef]:
    if not agents_dir.is_dir():
        raise FileNotFoundError(f"agents dir not found: {agents_dir}")
    out: dict[str, ExpertDef] = {}
    for p in sorted(agents_dir.glob("moe-*.md")):
        e = parse_agent_file(p)
        out[e.name] = e
    if not out:
        raise RuntimeError(f"no moe-*.md files in {agents_dir}")
    return out


# Roster classification used by orchestrator.py to decide who runs when.
PANEL_EXPERTS = {
    "moe-architect",
    "moe-performance",
    "moe-security",
    "moe-correctness",
    "moe-concurrency",
    "moe-testing",
    "moe-build-integrity",
    "moe-graphics-gl",
}
META_SYNTHESIZER = "moe-synthesizer"
META_DEVILS_ADVOCATE = "moe-devils-advocate"

# Per-pass devil's-advocate target rotation (R12 anti-groupthink).
DEVILS_ADVOCATE_TARGETS = {
    1: None,            # nothing to challenge yet
    2: "moe-correctness",
    3: None,            # blind pass; no priors
    4: "moe-architect",
    5: META_SYNTHESIZER,
}
