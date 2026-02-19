"""Tests for src/projection.py -- physical camera math."""

import math
import json
from pathlib import Path

import pytest

from projection import (
    SensorGate,
    Lens,
    PhysicalProjection,
    SENSOR_PRESETS,
    LENS_PRESETS,
    load_database,
    sensor_from_database,
    lens_from_database,
    preset_from_database,
)


# ---------------------------------------------------------------------------
# SensorGate
# ---------------------------------------------------------------------------

class TestSensorGate:
    def test_aspect_ratio(self):
        s = SensorGate(36.0, 24.0)
        assert s.aspect_ratio == pytest.approx(1.5)

    def test_diagonal(self):
        s = SensorGate(3.0, 4.0)
        assert s.diagonal_mm == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Lens
# ---------------------------------------------------------------------------

class TestLens:
    def test_spherical(self):
        l = Lens(50.0)
        assert not l.is_anamorphic

    def test_anamorphic(self):
        l = Lens(50.0, squeeze_ratio=2.0)
        assert l.is_anamorphic


# ---------------------------------------------------------------------------
# PhysicalProjection
# ---------------------------------------------------------------------------

class TestPhysicalProjection:
    def test_fov_v(self):
        sensor = SensorGate(36.0, 24.0)
        lens = Lens(50.0)
        proj = PhysicalProjection(sensor, lens)
        expected = math.degrees(2 * math.atan(12.0 / 50.0))
        assert proj.fov_v_deg == pytest.approx(expected, rel=1e-4)

    def test_fov_h_spherical(self):
        sensor = SensorGate(36.0, 24.0)
        lens = Lens(50.0)
        proj = PhysicalProjection(sensor, lens)
        expected = math.degrees(2 * math.atan(18.0 / 50.0))
        assert proj.fov_h_deg == pytest.approx(expected, rel=1e-4)

    def test_fov_h_anamorphic(self):
        sensor = SensorGate(24.0, 18.0)
        lens = Lens(40.0, squeeze_ratio=2.0)
        proj = PhysicalProjection(sensor, lens)
        expected = math.degrees(2 * math.atan((12.0 * 2.0) / 40.0))
        assert proj.fov_h_deg == pytest.approx(expected, rel=1e-4)

    def test_effective_aspect(self):
        sensor = SensorGate(24.0, 18.0)
        lens = Lens(40.0, squeeze_ratio=2.0)
        proj = PhysicalProjection(sensor, lens)
        assert proj.effective_aspect == pytest.approx((24.0 / 18.0) * 2.0, rel=1e-4)

    def test_projection_matrix_length(self):
        proj = PhysicalProjection(SensorGate(36, 24), Lens(50))
        m = proj.projection_matrix()
        assert len(m) == 16

    def test_fov_perspective_matrix_length(self):
        proj = PhysicalProjection(SensorGate(36, 24), Lens(50))
        m = proj.fov_perspective_matrix(1.5)
        assert len(m) == 16

    def test_to_load3d_camera(self):
        proj = PhysicalProjection(
            SensorGate(36, 24, "Test Sensor"),
            Lens(50, 1.0, "Test Lens"),
        )
        data = proj.to_load3d_camera((0, 0, 5), (0, 0, 0))
        assert data["carwash_version"] == "2.0"
        assert data["carwash_sensor_body"] == "Test Sensor"
        assert data["focal_length"] == 50.0


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

class TestDatabase:
    def test_load_database(self):
        db = load_database()
        assert "cameras" in db
        assert "lenses" in db
        assert "presets" in db

    def test_sensor_from_database(self):
        db = load_database()
        cam_id = db["cameras"][0]["id"]
        sensor = sensor_from_database(cam_id, db)
        assert isinstance(sensor, SensorGate)
        assert sensor.width_mm > 0

    def test_preset_from_database(self):
        db = load_database()
        preset_id = db["presets"][0]["id"]
        proj = preset_from_database(preset_id, db)
        assert isinstance(proj, PhysicalProjection)
