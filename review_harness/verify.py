"""Citation verification (R11 — No Hallucination).

Every Finding's evidence_quote must appear in the loaded codebase blob,
and the cited file must contain the symbol/quote. Findings that fail
verification are marked verified=False and are auto-RETRACTED by the
synthesizer before the final report.
"""
from __future__ import annotations

import re

from .codebase import CodebaseSnapshot
from .state import Finding


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_finding(finding: Finding, snapshot: CodebaseSnapshot) -> tuple[bool, str]:
    file_entry = snapshot.get(finding.file)
    if file_entry is None:
        return False, f"file '{finding.file}' not in snapshot"

    norm_haystack = _normalize(file_entry.content)
    norm_quote = _normalize(finding.evidence_quote)
    if not norm_quote:
        return False, "evidence_quote empty"
    if norm_quote not in norm_haystack:
        return False, "evidence_quote not found in file content"

    if finding.symbol and finding.symbol not in {"<module>", "<file>"}:
        if finding.symbol not in file_entry.content:
            return False, f"symbol '{finding.symbol}' not present in file"

    if finding.line < 1 or finding.line > max(1, file_entry.line_count):
        return False, f"line {finding.line} out of range 1..{file_entry.line_count}"

    return True, "ok"


def verify_all(findings: list[Finding], snapshot: CodebaseSnapshot) -> dict[str, tuple[bool, str]]:
    return {f.id: verify_finding(f, snapshot) for f in findings}
