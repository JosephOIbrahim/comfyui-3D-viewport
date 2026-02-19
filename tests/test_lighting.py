"""Tests for src/lighting.py -- Light, LightRig, uniforms."""

import math

import pytest

from lighting import Light, LightRig, MAX_LIGHTS, _MAX_EFFECTIVE_INTENSITY


# ---------------------------------------------------------------------------
# Light
# ---------------------------------------------------------------------------

class TestLight:
    def test_intensity_clamped_high(self):
        light = Light(name="over", intensity=5.0)
        assert light.intensity == 1.0

    def test_intensity_clamped_low(self):
        light = Light(name="under", intensity=-2.0)
        assert light.intensity == 0.0

    def test_direction_normalized(self):
        light = Light(name="d", direction=(3, 4, 0))
        dx, dy, dz = light.direction
        length = math.sqrt(dx**2 + dy**2 + dz**2)
        assert length == pytest.approx(1.0, rel=1e-6)

    def test_effective_intensity_no_exposure(self):
        light = Light(name="e", intensity=1.0, exposure=0.0)
        assert light.effective_intensity == pytest.approx(1.0)

    def test_effective_intensity_with_exposure(self):
        light = Light(name="e", intensity=1.0, exposure=2.0)
        assert light.effective_intensity == pytest.approx(4.0)

    def test_effective_intensity_negative_exposure(self):
        light = Light(name="e", intensity=1.0, exposure=-1.0)
        assert light.effective_intensity == pytest.approx(0.5)

    def test_effective_intensity_clamped(self):
        light = Light(name="e", intensity=1.0, exposure=100.0)
        assert light.effective_intensity == _MAX_EFFECTIVE_INTENSITY

    def test_default_values(self):
        light = Light(name="def")
        assert light.color == (1.0, 1.0, 1.0)
        assert light.enabled is True


# ---------------------------------------------------------------------------
# LightRig
# ---------------------------------------------------------------------------

class TestLightRig:
    def test_default_preset(self):
        rig = LightRig()
        assert rig.preset_name == "3-Point"

    def test_cycle_preset(self):
        rig = LightRig()
        name = rig.cycle_preset()
        assert name == "Rim Heavy"

    def test_cycle_wraps(self):
        rig = LightRig()
        names = []
        for _ in range(5):
            names.append(rig.cycle_preset())
        # Should wrap back to "Rim Heavy" after cycling through all 4
        assert names[3] == "3-Point"  # back to start after 4 cycles

    def test_set_preset(self):
        rig = LightRig()
        rig.set_preset("Flat")
        assert rig.preset_name == "Flat"

    def test_set_preset_invalid(self):
        rig = LightRig()
        with pytest.raises(ValueError):
            rig.set_preset("NonExistent")

    def test_lights_property_returns_copy(self):
        rig = LightRig()
        lights = rig.lights
        lights.clear()
        assert len(rig.lights) > 0


# ---------------------------------------------------------------------------
# get_uniform_data
# ---------------------------------------------------------------------------

class TestGetUniformData:
    def test_structure(self):
        rig = LightRig()
        data = rig.get_uniform_data()
        assert "uLightCount" in data
        assert "uLightDirs" in data
        assert "uLightColors" in data

    def test_light_count_matches_dirs(self):
        rig = LightRig()
        data = rig.get_uniform_data()
        count = data["uLightCount"]
        assert len(data["uLightDirs"]) == count * 3
        assert len(data["uLightColors"]) == count * 3

    def test_max_lights_respected(self):
        rig = LightRig()
        rig.set_preset("Flat")  # 4 lights
        data = rig.get_uniform_data()
        assert data["uLightCount"] <= MAX_LIGHTS

    def test_disabled_light_excluded(self):
        rig = LightRig()
        # Disable all lights
        for light in rig._lights:
            light.enabled = False
        data = rig.get_uniform_data()
        assert data["uLightCount"] == 0
