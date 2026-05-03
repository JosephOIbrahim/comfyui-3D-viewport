from pathlib import Path

from review_harness.codebase import load_snapshot
from review_harness.state import Finding, make_finding_id
from review_harness.verify import verify_finding

REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_finding(file: str, symbol: str, line: int, quote: str) -> Finding:
    return Finding(
        id=make_finding_id(file, symbol, "TEST_RULE", quote),
        file=file,
        line=line,
        symbol=symbol,
        rule_kind="TEST_RULE",
        severity="LOW",
        severity_justification="test",
        title="t",
        description="d",
        evidence_quote=quote,
        proposed_change="p",
        cost="TRIVIAL",
        confidence=0.5,
        expert="test",
    )


def test_real_quote_verifies():
    snap = load_snapshot(REPO_ROOT, git_sha="x")
    f = _build_finding("src/comfy_bridge.py", "ComfyBridge", 1, "class ComfyBridge")
    ok, note = verify_finding(f, snap)
    assert ok, note


def test_fake_quote_rejected():
    snap = load_snapshot(REPO_ROOT, git_sha="x")
    f = _build_finding("src/comfy_bridge.py", "ComfyBridge", 1,
                       "this exact phrase is not in the source code zzqxq")
    ok, note = verify_finding(f, snap)
    assert not ok
    assert "not found" in note


def test_unknown_file_rejected():
    snap = load_snapshot(REPO_ROOT, git_sha="x")
    f = _build_finding("src/does_not_exist.py", "x", 1, "anything")
    ok, note = verify_finding(f, snap)
    assert not ok
    assert "not in snapshot" in note


def test_unknown_symbol_rejected():
    snap = load_snapshot(REPO_ROOT, git_sha="x")
    f = _build_finding("src/comfy_bridge.py", "TotallyMadeUpClassXYZ", 1, "class ComfyBridge")
    ok, note = verify_finding(f, snap)
    assert not ok
    assert "symbol" in note


def test_line_out_of_range_rejected():
    snap = load_snapshot(REPO_ROOT, git_sha="x")
    f = _build_finding("src/comfy_bridge.py", "ComfyBridge", 999_999, "class ComfyBridge")
    ok, note = verify_finding(f, snap)
    assert not ok
    assert "out of range" in note
