"""Tests for src/usd_loader.py -- triangulation, bounds, MeshData.

pxr is mocked in sys.modules so tests run without USD installed.
Internal functions that accept plain Python types are tested directly.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock pxr before importing usd_loader
# ---------------------------------------------------------------------------

_mock_pxr = types.ModuleType("pxr")
_mock_Gf = types.ModuleType("pxr.Gf")
_mock_Usd = types.ModuleType("pxr.Usd")
_mock_UsdGeom = types.ModuleType("pxr.UsdGeom")
_mock_UsdShade = types.ModuleType("pxr.UsdShade")
_mock_Sdf = types.ModuleType("pxr.Sdf")

_mock_Gf.Matrix4d = MagicMock
_mock_Usd.Stage = MagicMock
_mock_Usd.Prim = MagicMock
_mock_UsdGeom.XformCache = MagicMock
_mock_UsdGeom.Mesh = MagicMock
_mock_UsdGeom.Gprim = MagicMock
_mock_UsdGeom.Cube = MagicMock
_mock_UsdGeom.Sphere = MagicMock
_mock_UsdGeom.Cylinder = MagicMock
_mock_UsdGeom.Capsule = MagicMock
_mock_UsdGeom.Cone = MagicMock
_mock_UsdShade.MaterialBindingAPI = MagicMock
_mock_UsdShade.Shader = MagicMock

_mock_pxr.Gf = _mock_Gf
_mock_pxr.Usd = _mock_Usd
_mock_pxr.UsdGeom = _mock_UsdGeom
_mock_pxr.UsdShade = _mock_UsdShade
_mock_pxr.Sdf = _mock_Sdf

sys.modules.setdefault("pxr", _mock_pxr)
sys.modules.setdefault("pxr.Gf", _mock_Gf)
sys.modules.setdefault("pxr.Usd", _mock_Usd)
sys.modules.setdefault("pxr.UsdGeom", _mock_UsdGeom)
sys.modules.setdefault("pxr.UsdShade", _mock_UsdShade)
sys.modules.setdefault("pxr.Sdf", _mock_Sdf)

from usd_loader import _triangulate, compute_scene_bounds, MeshData


# ---------------------------------------------------------------------------
# _triangulate
# ---------------------------------------------------------------------------

class TestTriangulate:
    def test_single_triangle(self):
        result = _triangulate([3], [0, 1, 2])
        assert result == [0, 1, 2]

    def test_quad(self):
        result = _triangulate([4], [0, 1, 2, 3])
        assert result == [0, 1, 2, 0, 2, 3]

    def test_pentagon(self):
        result = _triangulate([5], [0, 1, 2, 3, 4])
        assert result == [0, 1, 2, 0, 2, 3, 0, 3, 4]

    def test_degenerate_face_skipped(self):
        result = _triangulate([2, 3], [0, 1, 0, 1, 2])
        assert result == [0, 1, 2]

    def test_multiple_faces(self):
        result = _triangulate([3, 3], [0, 1, 2, 3, 4, 5])
        assert result == [0, 1, 2, 3, 4, 5]

    def test_empty(self):
        result = _triangulate([], [])
        assert result == []

    def test_mixed_faces(self):
        # tri + quad
        result = _triangulate([3, 4], [0, 1, 2, 3, 4, 5, 6])
        assert len(result) == 3 + 6  # 1 tri + 2 tris from quad


# ---------------------------------------------------------------------------
# compute_scene_bounds
# ---------------------------------------------------------------------------

class TestComputeSceneBounds:
    def test_empty_meshes(self):
        lo, hi = compute_scene_bounds([])
        assert lo == (-1.0, -1.0, -1.0)
        assert hi == (1.0, 1.0, 1.0)

    def test_single_mesh_identity(self):
        identity = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
        mesh = MeshData(
            name="test",
            vertices=[(-1, -1, -1), (2, 3, 4)],
            normals=[],
            indices=[0, 1, 0],
            transform=identity,
        )
        lo, hi = compute_scene_bounds([mesh])
        assert lo == pytest.approx((-1, -1, -1))
        assert hi == pytest.approx((2, 3, 4))

    def test_mesh_with_translation(self):
        t = [1,0,0,0, 0,1,0,0, 0,0,1,0, 10,10,10,1]
        mesh = MeshData(
            name="test",
            vertices=[(0, 0, 0), (1, 1, 1)],
            normals=[],
            indices=[0, 1, 0],
            transform=t,
        )
        lo, hi = compute_scene_bounds([mesh])
        assert lo == pytest.approx((10, 10, 10))
        assert hi == pytest.approx((11, 11, 11))


# ---------------------------------------------------------------------------
# MeshData
# ---------------------------------------------------------------------------

class TestMeshData:
    def test_defaults(self):
        md = MeshData(name="x")
        assert md.vertices == []
        assert md.color == (0.6, 0.6, 0.6)
