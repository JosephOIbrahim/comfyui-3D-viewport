"""Tests for src/selection.py -- ray-AABB, picking, selection manager."""

import math
from types import SimpleNamespace

import pytest

from selection import (
    SceneObject,
    SelectionManager,
    get_highlight_color,
    get_highlight_scale,
    _ray_aabb_intersect,
    _compute_world_aabb,
)


# ---------------------------------------------------------------------------
# Highlight constants
# ---------------------------------------------------------------------------

class TestHighlightConstants:
    def test_highlight_color(self):
        c = get_highlight_color()
        assert len(c) == 3
        assert all(0.0 <= v <= 1.0 for v in c)

    def test_highlight_scale(self):
        s = get_highlight_scale()
        assert s > 1.0


# ---------------------------------------------------------------------------
# _ray_aabb_intersect
# ---------------------------------------------------------------------------

class TestRayAABBIntersect:
    def test_hit_centered_box(self):
        origin = (0, 0, -5)
        direction = (0, 0, 1)
        t = _ray_aabb_intersect(origin, direction, (-1, -1, -1), (1, 1, 1))
        assert t is not None
        assert t == pytest.approx(4.0, abs=0.01)

    def test_miss(self):
        origin = (0, 0, -5)
        direction = (0, 1, 0)  # pointing up, not at box
        t = _ray_aabb_intersect(origin, direction, (-1, -1, -1), (1, 1, 1))
        assert t is None

    def test_behind_ray(self):
        origin = (0, 0, 5)
        direction = (0, 0, 1)  # looking away from box
        t = _ray_aabb_intersect(origin, direction, (-1, -1, -1), (1, 1, 1))
        assert t is None

    def test_ray_parallel_to_slab_outside(self):
        origin = (5, 0, 0)
        direction = (0, 0, 1)
        t = _ray_aabb_intersect(origin, direction, (-1, -1, -1), (1, 1, 1))
        assert t is None

    def test_ray_inside_box(self):
        origin = (0, 0, 0)
        direction = (1, 0, 0)
        t = _ray_aabb_intersect(origin, direction, (-1, -1, -1), (1, 1, 1))
        assert t is not None
        assert t >= 0.0


# ---------------------------------------------------------------------------
# _compute_world_aabb
# ---------------------------------------------------------------------------

class TestComputeWorldAABB:
    def test_identity_transform(self):
        verts = [(-1, -2, -3), (4, 5, 6)]
        identity = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
        lo, hi = _compute_world_aabb(verts, identity)
        assert lo == pytest.approx((-1, -2, -3))
        assert hi == pytest.approx((4, 5, 6))

    def test_translation_offset(self):
        verts = [(0, 0, 0), (1, 1, 1)]
        t = [1,0,0,0, 0,1,0,0, 0,0,1,0, 10,20,30,1]
        lo, hi = _compute_world_aabb(verts, t)
        assert lo == pytest.approx((10, 20, 30))
        assert hi == pytest.approx((11, 21, 31))

    def test_empty_vertices(self):
        identity = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
        lo, hi = _compute_world_aabb([], identity)
        assert lo == (0.0, 0.0, 0.0)
        assert hi == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# SelectionManager
# ---------------------------------------------------------------------------

def _make_mesh_data(name="mesh", vertices=None, indices=None, transform=None, color=(0.6, 0.6, 0.6)):
    if vertices is None:
        vertices = [(-1, -1, -1), (1, 1, 1)]
    if indices is None:
        indices = [0, 1, 0]
    if transform is None:
        transform = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    return SimpleNamespace(name=name, vertices=vertices, indices=indices, transform=transform, color=color)


class TestSelectionManager:
    def test_register(self):
        mgr = SelectionManager()
        md = _make_mesh_data()
        obj = mgr.register(md, vao=1, index_count=3)
        assert obj.id == 0
        assert obj.name == "mesh"
        assert len(mgr.objects) == 1

    def test_select_and_get(self):
        mgr = SelectionManager()
        md = _make_mesh_data()
        obj = mgr.register(md, vao=1, index_count=3)
        mgr.select(obj.id)
        assert mgr.get_selected() is obj

    def test_deselect(self):
        mgr = SelectionManager()
        md = _make_mesh_data()
        obj = mgr.register(md, vao=1, index_count=3)
        mgr.select(obj.id)
        mgr.select(None)
        assert mgr.get_selected() is None

    def test_cycle_selection(self):
        mgr = SelectionManager()
        md1 = _make_mesh_data("a")
        md2 = _make_mesh_data("b")
        o1 = mgr.register(md1, 1, 3)
        o2 = mgr.register(md2, 2, 3)

        mgr.cycle_selection()
        assert mgr.selected_id == o1.id

        mgr.cycle_selection()
        assert mgr.selected_id == o2.id

        mgr.cycle_selection()
        assert mgr.selected_id == o1.id  # wraps

    def test_cycle_empty(self):
        mgr = SelectionManager()
        mgr.cycle_selection()
        assert mgr.selected_id is None

    def test_clear(self):
        mgr = SelectionManager()
        mgr.register(_make_mesh_data(), 1, 3)
        mgr.select(0)
        mgr.clear()
        assert len(mgr.objects) == 0
        assert mgr.selected_id is None
