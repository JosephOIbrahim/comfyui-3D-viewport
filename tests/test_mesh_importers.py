"""Tests for src/mesh_importers.py -- dispatch, color extraction.

trimesh and numpy are mocked for unit testing.
"""

import sys
import os
import types
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# We need numpy to be available (mesh_importers imports it at module level)
import numpy as np

# ---------------------------------------------------------------------------
# Mock pxr if not available (needed for usd_loader.MeshData import)
# ---------------------------------------------------------------------------

if "pxr" not in sys.modules:
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
    sys.modules["pxr"] = _mock_pxr
    sys.modules["pxr.Gf"] = _mock_Gf
    sys.modules["pxr.Usd"] = _mock_Usd
    sys.modules["pxr.UsdGeom"] = _mock_UsdGeom
    sys.modules["pxr.UsdShade"] = _mock_UsdShade
    sys.modules["pxr.Sdf"] = _mock_Sdf

# Mock trimesh before importing mesh_importers
_mock_trimesh = MagicMock()
_mock_trimesh.Trimesh = type("Trimesh", (), {})
_mock_trimesh.Scene = type("Scene", (), {})
sys.modules.setdefault("trimesh", _mock_trimesh)

from mesh_importers import (
    _SUPPORTED_EXTENSIONS,
    _DEFAULT_COLOR,
    _extract_color,
    _mesh_name,
    load_mesh_file,
)
from usd_loader import MeshData


# ---------------------------------------------------------------------------
# _extract_color
# ---------------------------------------------------------------------------

class TestExtractColor:
    def test_default_color_no_visual(self):
        mesh = MagicMock()
        mesh.visual = None
        assert _extract_color(mesh) == _DEFAULT_COLOR

    def test_vertex_colors(self):
        mesh = MagicMock()
        mesh.visual.kind = "vertex"
        # 3 vertices, RGBA uint8
        mesh.visual.vertex_colors = np.array([
            [255, 0, 0, 255],
            [0, 255, 0, 255],
            [0, 0, 255, 255],
        ], dtype=np.uint8)
        r, g, b = _extract_color(mesh)
        assert r == pytest.approx(255 / 3 / 255, rel=1e-2)

    def test_material_base_color_factor(self):
        mesh = MagicMock()
        mesh.visual.kind = "face"
        mesh.visual.material.baseColorFactor = np.array([200, 100, 50, 255])
        mesh.visual.material.diffuse = None
        mesh.visual.material.main_color = None
        r, g, b = _extract_color(mesh)
        assert r == pytest.approx(200 / 255, rel=1e-2)

    def test_material_diffuse_float(self):
        mesh = MagicMock()
        mesh.visual.kind = "face"
        mesh.visual.material.baseColorFactor = None
        mesh.visual.material.diffuse = np.array([0.5, 0.6, 0.7, 1.0])
        mesh.visual.material.main_color = None
        r, g, b = _extract_color(mesh)
        assert r == pytest.approx(0.5, rel=1e-2)


# ---------------------------------------------------------------------------
# _mesh_name
# ---------------------------------------------------------------------------

class TestMeshName:
    def test_basic(self):
        name = _mesh_name("/path/to/model.glb", 0)
        assert name == "/model/mesh_0"

    def test_index(self):
        name = _mesh_name("/path/to/scene.gltf", 3)
        assert name == "/scene/mesh_3"


# ---------------------------------------------------------------------------
# _SUPPORTED_EXTENSIONS
# ---------------------------------------------------------------------------

class TestSupportedExtensions:
    def test_glb(self):
        assert ".glb" in _SUPPORTED_EXTENSIONS

    def test_obj(self):
        assert ".obj" in _SUPPORTED_EXTENSIONS

    def test_ply(self):
        assert ".ply" in _SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# load_mesh_file dispatch
# ---------------------------------------------------------------------------

class TestLoadMeshFileDispatch:
    def test_unsupported_extension(self, tmp_path):
        fake = tmp_path / "model.fbx"
        fake.write_text("fake")
        with pytest.raises(ValueError, match="Unsupported"):
            load_mesh_file(str(fake))

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_mesh_file("/nonexistent/model.glb")
