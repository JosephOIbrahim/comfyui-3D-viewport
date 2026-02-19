"""Tests for src/config.py -- constants and env var overrides."""

import importlib

import pytest


class TestConfigDefaults:
    def test_window_defaults(self):
        import config
        assert config.WINDOW_WIDTH == 800
        assert config.WINDOW_HEIGHT == 600

    def test_camera_defaults(self):
        import config
        assert config.CAMERA_DEFAULT_FOV == 45.0
        assert config.CAMERA_NEAR == 0.1
        assert config.CAMERA_FAR == 100.0
        assert config.CAMERA_DEFAULT_DISTANCE == 5.0

    def test_msaa_default(self):
        import config
        assert config.MSAA_SAMPLES == 0

    def test_supported_extensions(self):
        import config
        assert ".usd" in config.SUPPORTED_USD_EXTENSIONS
        assert ".glb" in config.SUPPORTED_MESH_EXTENSIONS
        assert config.ALL_SUPPORTED_EXTENSIONS == (
            config.SUPPORTED_USD_EXTENSIONS | config.SUPPORTED_MESH_EXTENSIONS
        )

    def test_data_dir_exists(self):
        import config
        assert config.DATA_DIR.name == "data"

    def test_lighting_constants(self):
        import config
        assert config.MAX_LIGHTS == 4
        assert config.MAX_EFFECTIVE_INTENSITY == 64.0

    def test_animation_constants(self):
        import config
        assert config.ANIMATION_FPS == 24.0
        assert config.TURNTABLE_SPEED == 36.0

    def test_comfyui_default_url(self):
        import config
        assert config.COMFYUI_URL == "http://127.0.0.1:8188"


class TestConfigEnvOverrides:
    def test_window_width_override(self, monkeypatch):
        monkeypatch.setenv("VIEWPORT_WIDTH", "1920")
        import config
        importlib.reload(config)
        assert config.WINDOW_WIDTH == 1920

    def test_msaa_override(self, monkeypatch):
        monkeypatch.setenv("MSAA_SAMPLES", "4")
        import config
        importlib.reload(config)
        assert config.MSAA_SAMPLES == 4
