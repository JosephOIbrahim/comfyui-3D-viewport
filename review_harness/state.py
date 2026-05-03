"""Pydantic models and JSONL persistence for review findings.

Implements R10 (Idempotent ID) and R3/R7 vocabulary from the constitution.
Finding IDs are content-stable so they survive line-number drift across passes.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["BLOCKER", "HIGH", "MEDIUM", "LOW", "INFO"]
Cost = Literal["TRIVIAL", "SMALL", "MEDIUM", "LARGE"]
Action = Literal["NEW", "UPHOLD", "REFINE", "RETRACT", "EXPAND"]


def _normalize_quote(quote: str) -> str:
    return re.sub(r"\s+", " ", quote).strip().lower()


def make_finding_id(file: str, symbol: str, rule_kind: str, quote: str) -> str:
    payload = f"{file}|{symbol}|{rule_kind}|{_normalize_quote(quote)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class PassEntry(BaseModel):
    pass_num: int
    expert: str
    action: Action
    note: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Finding(BaseModel):
    id: str
    file: str
    line: int
    line_end: int | None = None
    symbol: str
    rule_kind: str
    severity: Severity
    severity_justification: str
    title: str = Field(max_length=120)
    description: str = Field(max_length=800)
    evidence_quote: str
    proposed_change: str
    cost: Cost
    confidence: float = Field(ge=0.0, le=1.0)
    expert: str
    related_findings: list[str] = Field(default_factory=list)
    self_skeptic: list[str] = Field(default_factory=list)
    rationale_rewrite: str | None = None
    pass_history: list[PassEntry] = Field(default_factory=list)
    verified: bool = False
    verification_note: str = ""

    @field_validator("evidence_quote")
    @classmethod
    def _quote_bounded(cls, v: str) -> str:
        lines = v.splitlines()
        if len(lines) > 3:
            raise ValueError("evidence_quote must be <=3 lines (R1)")
        return v

    @field_validator("self_skeptic")
    @classmethod
    def _skeptic_bounded(cls, v: list[str]) -> list[str]:
        return v[:3]

    def latest_action(self) -> Action:
        if not self.pass_history:
            return "NEW"
        return self.pass_history[-1].action


class FindingStore:
    """Append-only JSONL store with deduping by Finding.id."""

    def __init__(self, path: Path):
        self.path = path
        self._index: dict[str, Finding] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                f_obj = Finding.model_validate_json(line)
                self._index[f_obj.id] = f_obj

    def upsert(self, finding: Finding) -> tuple[Finding, bool]:
        existing = self._index.get(finding.id)
        if existing is None:
            self._index[finding.id] = finding
            self._append(finding)
            return finding, True
        merged = self._merge(existing, finding)
        self._index[finding.id] = merged
        self._rewrite()
        return merged, False

    @staticmethod
    def _merge(existing: Finding, incoming: Finding) -> Finding:
        merged_history = list(existing.pass_history) + list(incoming.pass_history)
        latest_severity = incoming.severity if incoming.pass_history else existing.severity
        return existing.model_copy(update={
            "pass_history": merged_history,
            "severity": latest_severity,
            "severity_justification": incoming.severity_justification or existing.severity_justification,
            "description": incoming.description or existing.description,
            "proposed_change": incoming.proposed_change or existing.proposed_change,
            "confidence": max(existing.confidence, incoming.confidence),
            "related_findings": sorted(set(existing.related_findings) | set(incoming.related_findings)),
            "verified": existing.verified or incoming.verified,
            "verification_note": incoming.verification_note or existing.verification_note,
        })

    def _append(self, finding: Finding) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(finding.model_dump_json() + "\n")

    def _rewrite(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as f:
            for fid in sorted(self._index):
                f.write(self._index[fid].model_dump_json() + "\n")

    def all(self) -> list[Finding]:
        return [self._index[fid] for fid in sorted(self._index)]

    def get(self, fid: str) -> Finding | None:
        return self._index.get(fid)

    def __len__(self) -> int:
        return len(self._index)

    def __iter__(self) -> Iterator[Finding]:
        return iter(self.all())


class CallRecord(BaseModel):
    pass_num: int
    expert: str
    response_id: str | None = None
    input_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: str | None = None


class CallLog:
    def __init__(self, path: Path):
        self.path = path

    def append(self, record: CallRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(record.model_dump_json() + "\n")

    def total_cost(self) -> float:
        if not self.path.exists():
            return 0.0
        total = 0.0
        with self.path.open() as f:
            for line in f:
                if line.strip():
                    total += json.loads(line).get("cost_usd", 0.0)
        return total


class RunState(BaseModel):
    git_sha: str
    started_at: str
    target_dir: str
    model: str
    rounds_planned: int
    seed: int
    last_pass_completed: int = 0
    aborted: bool = False
    abort_reason: str | None = None

    @classmethod
    def fresh(cls, *, git_sha: str, target_dir: str, model: str, rounds: int, seed: int) -> "RunState":
        return cls(
            git_sha=git_sha,
            started_at=datetime.now(timezone.utc).isoformat(),
            target_dir=target_dir,
            model=model,
            rounds_planned=rounds,
            seed=seed,
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def read(cls, path: Path) -> "RunState":
        return cls.model_validate_json(path.read_text())
