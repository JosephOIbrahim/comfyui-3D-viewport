"""Tests for src/camera.py -- OrbitCamera."""

import math
from types import SimpleNamespace

import pytest

from camera import OrbitCamera


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestOrbitCameraConstruction:
    def test_defaults(self):
        cam = OrbitCamera()
        assert cam.distance == 5.0
        assert cam.azimuth == 35.0
        assert cam.elevation == 25.0
        assert cam.fov == 45.0

    def test_custom_values(self):
        cam = OrbitCamera(target=(1, 2, 3), distance=10, azimuth=0, elevation=0)
        assert cam.target == [1, 2, 3]
        assert cam.distance == 10


# ---------------------------------------------------------------------------
# Eye position
# ---------------------------------------------------------------------------

class TestEyePosition:
    def test_eye_at_zero_angles(self):
        cam = OrbitCamera(target=(0, 0, 0), distance=5.0, azimuth=0, elevation=0)
        eye = cam.eye
        # At azimuth=0, elevation=0: eye should be at (0, 0, 5)
        assert eye[0] == pytest.approx(0.0, abs=1e-6)
        assert eye[1] == pytest.approx(0.0, abs=1e-6)
        assert eye[2] == pytest.approx(5.0, rel=1e-6)

    def test_eye_at_90_azimuth(self):
        cam = OrbitCamera(target=(0, 0, 0), distance=5.0, azimuth=90, elevation=0)
        eye = cam.eye
        assert eye[0] == pytest.approx(5.0, rel=1e-4)
        assert eye[2] == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Orbit
# ---------------------------------------------------------------------------

class TestOrbit:
    def test_orbit_clamps_elevation(self):
        cam = OrbitCamera(elevation=85)
        cam.orbit(0, 100)  # push elevation high
        assert cam.elevation <= cam.max_elevation

    def test_orbit_clamps_elevation_negative(self):
        cam = OrbitCamera(elevation=-85)
        cam.orbit(0, -100)
        assert cam.elevation >= cam.min_elevation


# ---------------------------------------------------------------------------
# Pan
# ---------------------------------------------------------------------------

class TestPan:
    def test_pan_moves_target(self):
        cam = OrbitCamera(target=(0, 0, 0), azimuth=0, elevation=0)
        old_target = list(cam.target)
        cam.pan(100, 0)
        assert cam.target != old_target


# ---------------------------------------------------------------------------
# Dolly
# ---------------------------------------------------------------------------

class TestDolly:
    def test_dolly_in(self):
        cam = OrbitCamera(distance=5.0)
        cam.dolly(0.5)  # zoom in
        assert cam.distance < 5.0

    def test_dolly_clamp_min(self):
        cam = OrbitCamera(distance=0.1)
        cam.dolly(10.0)
        assert cam.distance >= cam.min_distance

    def test_dolly_clamp_max(self):
        cam = OrbitCamera(distance=400.0)
        cam.dolly(-10.0)
        assert cam.distance <= cam.max_distance

    def test_dolly_scroll(self):
        cam = OrbitCamera(distance=5.0)
        cam.dolly_scroll(1.0)  # zoom in
        assert cam.distance < 5.0


# ---------------------------------------------------------------------------
# Frame scene
# ---------------------------------------------------------------------------

class TestFrameScene:
    def test_frame_resets(self):
        cam = OrbitCamera(target=(0, 0, 0), distance=5.0, azimuth=35, elevation=25)
        cam.azimuth = 180
        cam.distance = 100
        cam.frame_scene()
        assert cam.azimuth == 35
        assert cam.distance == 5.0


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class TestProjection:
    def test_simple_fov_matrix(self):
        cam = OrbitCamera(fov=45.0)
        m = cam.projection_matrix(aspect=1.0)
        assert len(m) == 16
        assert m[5] != 0  # f (1/tan(fov/2))

    def test_set_and_clear_projection(self):
        cam = OrbitCamera()
        proj = SimpleNamespace(
            near=0.01, far=1000.0,
            fov_perspective_matrix=lambda a: [0] * 16,
            sensor=SimpleNamespace(name="Test"),
            lens=SimpleNamespace(name="Lens", focal_mm=50),
            fov_v_deg=30,
            fov_h_deg=45,
        )
        cam.set_projection(proj)
        assert cam.sensor_name == "Test"

        cam.clear_projection()
        assert cam.sensor_name == "Simple FOV"
        assert cam.lens_name == "Pinhole"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestToLoad3dCamera:
    def test_simple_export(self):
        cam = OrbitCamera()
        data = cam.to_load3d_camera()
        assert "position" in data
        assert "target" in data
        assert "fov" in data
        assert data["fov"] == 45.0
        assert data["focal_length"] is None
