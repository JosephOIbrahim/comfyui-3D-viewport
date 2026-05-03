from pathlib import Path

from review_harness.state import (
    Finding,
    FindingStore,
    PassEntry,
    make_finding_id,
)


def _mk_finding(**overrides) -> Finding:
    base = dict(
        id=make_finding_id("src/comfy_bridge.py", "ComfyBridge.send_camera",
                           "BROAD_EXCEPT", "except Exception:\n    pass"),
        file="src/comfy_bridge.py",
        line=327,
        symbol="ComfyBridge.send_camera",
        rule_kind="BROAD_EXCEPT",
        severity="MEDIUM",
        severity_justification="user-visible defect",
        title="Broad except masks bugs",
        description="...",
        evidence_quote="except Exception:\n    pass",
        proposed_change="catch (RequestException, JSONDecodeError) only",
        cost="TRIVIAL",
        confidence=0.9,
        expert="moe-correctness",
    )
    base.update(overrides)
    return Finding(**base)


def test_finding_id_is_deterministic():
    a = make_finding_id("a.py", "f", "X", "  hello\nWORLD ")
    b = make_finding_id("a.py", "f", "X", "hello world")
    assert a == b, "ID must normalize whitespace and case"


def test_finding_id_is_content_stable():
    a = _mk_finding()
    b = _mk_finding(line=999)
    assert a.id == b.id, "line drift should not change id (R10)"


def test_evidence_quote_max_3_lines():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _mk_finding(evidence_quote="a\nb\nc\nd")


def test_jsonl_roundtrip(tmp_path: Path):
    store = FindingStore(tmp_path / "findings.jsonl")
    f = _mk_finding()
    f.pass_history.append(PassEntry(pass_num=1, expert="moe-correctness", action="NEW"))
    store.upsert(f)

    store2 = FindingStore(tmp_path / "findings.jsonl")
    loaded = store2.get(f.id)
    assert loaded is not None
    assert loaded.title == f.title
    assert len(loaded.pass_history) == 1


def test_upsert_dedupes_and_merges_history(tmp_path: Path):
    store = FindingStore(tmp_path / "findings.jsonl")
    f1 = _mk_finding()
    f1.pass_history.append(PassEntry(pass_num=1, expert="moe-correctness", action="NEW"))
    store.upsert(f1)

    f2 = _mk_finding()
    f2.pass_history.append(PassEntry(pass_num=2, expert="moe-correctness", action="UPHOLD"))
    store.upsert(f2)

    assert len(store) == 1
    merged = store.get(f1.id)
    assert merged is not None
    actions = [e.action for e in merged.pass_history]
    assert actions == ["NEW", "UPHOLD"]


def test_self_skeptic_capped_at_three():
    f = _mk_finding(self_skeptic=["a", "b", "c", "d", "e"])
    assert len(f.self_skeptic) == 3
