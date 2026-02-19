"""Tests for src/undo.py -- command pattern and undo stack."""

import pytest

from undo import (
    SceneSnapshot,
    capture_snapshot,
    TransformCommand,
    LoadSceneCommand,
    SelectionCommand,
    DeleteObjectCommand,
    UndoStack,
)


# ---------------------------------------------------------------------------
# SceneSnapshot
# ---------------------------------------------------------------------------

class TestSceneSnapshot:
    def test_capture_deep_copies(self):
        draw_list = [(1, 2, 3)]
        snap = capture_snapshot(draw_list, [{"a": 1}])
        draw_list[0] = (9, 9, 9)
        assert snap.draw_list == [(1, 2, 3)]

    def test_fields(self):
        snap = capture_snapshot([], [], selection_id=5, file_path="/a.usd")
        assert snap.selection_id == 5
        assert snap.file_path == "/a.usd"


# ---------------------------------------------------------------------------
# TransformCommand
# ---------------------------------------------------------------------------

class TestTransformCommand:
    def test_execute_calls_apply_fn(self):
        calls = []
        cmd = TransformCommand(
            object_id=1,
            old_matrix=[0] * 16,
            new_matrix=[1] * 16,
            apply_fn=lambda oid, m: calls.append(("apply", oid, m)),
            description="Move",
        )
        cmd.execute()
        assert len(calls) == 1
        assert calls[0][1] == 1
        assert calls[0][2] == [1] * 16

    def test_undo_restores_old(self):
        calls = []
        cmd = TransformCommand(
            object_id=2,
            old_matrix=[0] * 16,
            new_matrix=[1] * 16,
            apply_fn=lambda oid, m: calls.append(m),
        )
        cmd.undo()
        assert calls[-1] == [0] * 16


# ---------------------------------------------------------------------------
# SelectionCommand
# ---------------------------------------------------------------------------

class TestSelectionCommand:
    def test_execute_selects_new(self):
        selected = []
        cmd = SelectionCommand(
            old_selection_id=None,
            new_selection_id=5,
            select_fn=lambda sid: selected.append(sid),
        )
        cmd.execute()
        assert selected[-1] == 5

    def test_undo_restores_old(self):
        selected = []
        cmd = SelectionCommand(
            old_selection_id=3,
            new_selection_id=5,
            select_fn=lambda sid: selected.append(sid),
        )
        cmd.undo()
        assert selected[-1] == 3


# ---------------------------------------------------------------------------
# LoadSceneCommand
# ---------------------------------------------------------------------------

class TestLoadSceneCommand:
    def test_execute_loads_new_file(self):
        loaded = []
        snap = capture_snapshot([], [])
        cmd = LoadSceneCommand(
            old_file_path=None,
            new_file_path="/b.usd",
            old_snapshot=snap,
            load_fn=lambda p: loaded.append(p),
            restore_fn=lambda s: None,
        )
        cmd.execute()
        assert loaded[-1] == "/b.usd"

    def test_undo_restores_snapshot(self):
        restored = []
        snap = capture_snapshot([("item",)], [])
        cmd = LoadSceneCommand(
            old_file_path="/a.usd",
            new_file_path="/b.usd",
            old_snapshot=snap,
            load_fn=lambda p: None,
            restore_fn=lambda s: restored.append(s),
        )
        cmd.undo()
        assert len(restored) == 1
        assert restored[0].draw_list == [("item",)]


# ---------------------------------------------------------------------------
# DeleteObjectCommand
# ---------------------------------------------------------------------------

class TestDeleteObjectCommand:
    def test_execute_deletes(self):
        deleted = []
        cmd = DeleteObjectCommand(
            object_snapshot={"id": 7},
            delete_fn=lambda s: deleted.append(s),
            restore_fn=lambda s: None,
        )
        cmd.execute()
        assert deleted[-1]["id"] == 7

    def test_undo_restores(self):
        restored = []
        cmd = DeleteObjectCommand(
            object_snapshot={"id": 7},
            delete_fn=lambda s: None,
            restore_fn=lambda s: restored.append(s),
        )
        cmd.undo()
        assert restored[-1]["id"] == 7


# ---------------------------------------------------------------------------
# UndoStack
# ---------------------------------------------------------------------------

class TestUndoStack:
    def _make_cmd(self, desc="test", calls=None):
        if calls is None:
            calls = []
        return TransformCommand(
            object_id=0,
            old_matrix=[0] * 16,
            new_matrix=[1] * 16,
            apply_fn=lambda oid, m: calls.append(("apply", m)),
            description=desc,
        )

    def test_push_executes(self):
        calls = []
        stack = UndoStack()
        stack.push(self._make_cmd(calls=calls))
        assert len(calls) == 1

    def test_undo_returns_description(self):
        stack = UndoStack()
        stack.push(self._make_cmd("Move Cube"))
        desc = stack.undo()
        assert desc == "Move Cube"

    def test_undo_empty_returns_none(self):
        stack = UndoStack()
        assert stack.undo() is None

    def test_redo(self):
        stack = UndoStack()
        stack.push(self._make_cmd("A"))
        stack.undo()
        desc = stack.redo()
        assert desc == "A"

    def test_redo_empty_returns_none(self):
        stack = UndoStack()
        assert stack.redo() is None

    def test_push_clears_redo(self):
        stack = UndoStack()
        stack.push(self._make_cmd("A"))
        stack.undo()
        assert stack.can_redo
        stack.push(self._make_cmd("B"))
        assert not stack.can_redo

    def test_max_size_trims(self):
        stack = UndoStack(max_size=3)
        for i in range(5):
            stack.push(self._make_cmd(f"cmd_{i}"))
        # Should only have 3 items
        count = 0
        while stack.undo():
            count += 1
        assert count == 3

    def test_clear(self):
        stack = UndoStack()
        stack.push(self._make_cmd())
        stack.clear()
        assert not stack.can_undo
        assert not stack.can_redo

    def test_undo_description_property(self):
        stack = UndoStack()
        assert stack.undo_description is None
        stack.push(self._make_cmd("X"))
        assert stack.undo_description == "X"

    def test_redo_description_property(self):
        stack = UndoStack()
        stack.push(self._make_cmd("Y"))
        stack.undo()
        assert stack.redo_description == "Y"
