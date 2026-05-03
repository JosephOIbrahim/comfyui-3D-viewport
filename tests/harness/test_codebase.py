from pathlib import Path

from review_harness.codebase import load_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_snapshot_loads_real_repo():
    snap = load_snapshot(REPO_ROOT, git_sha="test")
    assert len(snap.files) > 10, "should load source files"
    paths = {f.rel_path for f in snap.files}
    assert "src/viewport.py" in paths
    assert "src/comfy_bridge.py" in paths
    assert "tests/conftest.py" in paths
    assert "CLAUDE.md" in paths


def test_snapshot_content_hash_stable():
    snap1 = load_snapshot(REPO_ROOT, git_sha="x")
    snap2 = load_snapshot(REPO_ROOT, git_sha="x")
    assert snap1.content_hash() == snap2.content_hash()


def test_inventory_block_has_table():
    snap = load_snapshot(REPO_ROOT, git_sha="x")
    block = snap.inventory_block()
    assert "| path | lines | sha |" in block
    assert "`src/viewport.py`" in block


def test_get_returns_file_entry():
    snap = load_snapshot(REPO_ROOT, git_sha="x")
    entry = snap.get("src/viewport.py")
    assert entry is not None
    assert entry.line_count > 100
    assert "class" in entry.content
