"""End-to-end harness pipeline test using synthetic JSONL.

Three known issues are planted as JSONL findings; we run them through the
parser, verifier, and store. All three must accept; a fourth obviously
hallucinated finding must reject.

This test runs without any API call and proves the harness's accept/reject
pipeline can find the known issues described in the plan's Verification §6.1.
"""
import json
from pathlib import Path

from review_harness.codebase import load_snapshot
from review_harness.orchestrator import parse_jsonl_findings
from review_harness.state import FindingStore
from review_harness.verify import verify_finding

REPO_ROOT = Path(__file__).resolve().parents[2]


PLANTED_FINDINGS = [
    # 1. Broad except masking errors at comfy_bridge.py:327
    {
        "file": "src/comfy_bridge.py",
        "line": 327,
        "symbol": "ComfyBridge",
        "rule_kind": "BROAD_EXCEPT_MASKS_BUGS",
        "severity": "MEDIUM",
        "severity_justification": "user-visible defect: failures are silent",
        "title": "Broad except in WebSocket handler swallows all errors",
        "description": "All exceptions during ComfyUI WS dispatch are caught generically.",
        "evidence_quote": "        except Exception:",
        "proposed_change": "Catch (RequestException, json.JSONDecodeError, OSError) only; log + re-raise others.",
        "cost": "TRIVIAL",
        "confidence": 0.95,
        "expert": "moe-correctness",
        "self_skeptic": ["caller may rely on silent failure"],
    },
    # 2. Hardcoded AOV output paths at viewport.py:694
    {
        "file": "src/viewport.py",
        "line": 694,
        "symbol": "StormViewport",
        "rule_kind": "HARDCODED_OUTPUT_PATH",
        "severity": "MEDIUM",
        "severity_justification": "user-visible defect: writes outside any sandbox / config",
        "title": "AOV PNG paths hardcoded to CWD",
        "description": "depth_aov.png and normal_aov.png are written to CWD with no config knob.",
        "evidence_quote": '            self._aov.save_depth_png("depth_aov.png", self._draw_scene_for_aov, near, far)',
        "proposed_change": "Move filenames to config.py AOV_DEPTH_PATH/AOV_NORMAL_PATH; resolve relative to a configurable export dir.",
        "cost": "SMALL",
        "confidence": 0.9,
        "expert": "moe-correctness",
    },
    # 3. Monolithic StormViewport class at viewport.py
    {
        "file": "src/viewport.py",
        "line": 1,
        "symbol": "StormViewport",
        "rule_kind": "GOD_OBJECT",
        "severity": "HIGH",
        "severity_justification": "design flaw: single class handles render, input, IO, bridge, animation",
        "title": "StormViewport is a 1,085-LOC god object",
        "description": "StormViewport mixes rendering, interaction, animation, file I/O, bridge calls.",
        "evidence_quote": "class StormViewport(QOpenGLWidget):",
        "proposed_change": "Split into ViewportRenderer, ViewportInteraction, ViewportBridgeAdapter; keep StormViewport as composition root only.",
        "cost": "LARGE",
        "rationale_rewrite": "1,085-LOC class cannot be partially refactored; cohesive split required.",
        "confidence": 0.85,
        "expert": "moe-architect",
    },
    # 4. HALLUCINATED — must be rejected by verify.py
    {
        "file": "src/comfy_bridge.py",
        "line": 1,
        "symbol": "ComfyBridge",
        "rule_kind": "FAKE_RULE",
        "severity": "BLOCKER",
        "severity_justification": "fabricated",
        "title": "Imaginary issue that does not exist",
        "description": "...",
        "evidence_quote": "this exact phrase is not in the source code XYZQQQ",
        "proposed_change": "n/a",
        "cost": "TRIVIAL",
        "confidence": 1.0,
        "expert": "test:hallucinator",
    },
]


def test_planted_bugs_pipeline(tmp_path: Path):
    """Drop synthetic JSONL into a 'raw' file, parse, verify, store."""
    raw = tmp_path / "raw_test.jsonl"
    raw.write_text("\n".join(json.dumps(f) for f in PLANTED_FINDINGS) + "\n")

    parsed = parse_jsonl_findings(raw, expert="moe-correctness", pass_num=1)
    assert len(parsed) == len(PLANTED_FINDINGS), \
        f"parser dropped findings: got {len(parsed)} of {len(PLANTED_FINDINGS)}"

    snap = load_snapshot(REPO_ROOT, git_sha="planted")
    accepted = []
    rejected = []
    for f in parsed:
        ok, note = verify_finding(f, snap)
        if ok:
            accepted.append(f)
        else:
            rejected.append((f, note))

    titles_accepted = {f.title for f in accepted}
    titles_rejected = {f.title for f, _ in rejected}

    assert "Broad except in WebSocket handler swallows all errors" in titles_accepted, \
        "harness must accept the comfy_bridge broad-except finding"
    assert "AOV PNG paths hardcoded to CWD" in titles_accepted, \
        "harness must accept the hardcoded-AOV-path finding"
    assert "StormViewport is a 1,085-LOC god object" in titles_accepted, \
        "harness must accept the StormViewport god-object finding"
    assert "Imaginary issue that does not exist" in titles_rejected, \
        "verify.py must reject hallucinated quotes (R11)"

    # Storing the accepted ones must dedupe & survive a re-parse.
    store = FindingStore(tmp_path / "findings.jsonl")
    for f in accepted:
        store.upsert(f)
    assert len(store) == 3
    # Replay: same JSONL produces identical IDs (R10 idempotence).
    for f in accepted:
        f2 = parse_jsonl_findings(raw, expert="moe-correctness", pass_num=1)
        ids = {x.id for x in f2 if x.title == f.title}
        assert f.id in ids, f"R10 finding ID drifted across re-parse: {f.title}"
