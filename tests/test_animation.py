"""Tests for src/animation.py -- lerp, turntable, keyframes."""

import math
from types import SimpleNamespace

import pytest

from animation import (
    _lerp,
    _lerp_angle,
    _lerp_tuple,
    CameraKeyframe,
    AnimationMode,
    CameraAnimator,
)


# ---------------------------------------------------------------------------
# Helper: fake camera
# ---------------------------------------------------------------------------

def _make_camera(**kwargs):
    defaults = dict(
        azimuth=0.0, elevation=20.0, distance=5.0,
        target=[0.0, 0.0, 0.0],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _lerp
# ---------------------------------------------------------------------------

class TestLerp:
    def test_t_zero(self):
        assert _lerp(0.0, 10.0, 0.0) == 0.0

    def test_t_one(self):
        assert _lerp(0.0, 10.0, 1.0) == 10.0

    def test_t_half(self):
        assert _lerp(0.0, 10.0, 0.5) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# _lerp_angle
# ---------------------------------------------------------------------------

class TestLerpAngle:
    def test_no_wrapping(self):
        assert _lerp_angle(0.0, 90.0, 0.5) == pytest.approx(45.0)

    def test_shortest_arc_positive_wrap(self):
        # 350 -> 10 should go +20 degrees (not -340)
        result = _lerp_angle(350.0, 10.0, 0.5)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_shortest_arc_negative_wrap(self):
        # 10 -> 350 should go -20 degrees
        result = _lerp_angle(10.0, 350.0, 0.5)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_t_zero(self):
        result = _lerp_angle(45.0, 90.0, 0.0)
        assert result == pytest.approx(45.0)

    def test_t_one(self):
        result = _lerp_angle(45.0, 90.0, 1.0)
        assert result == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# _lerp_tuple
# ---------------------------------------------------------------------------

class TestLerpTuple:
    def test_basic(self):
        result = _lerp_tuple((0, 0, 0), (10, 20, 30), 0.5)
        assert result == pytest.approx((5, 10, 15))


# ---------------------------------------------------------------------------
# CameraKeyframe
# ---------------------------------------------------------------------------

class TestCameraKeyframe:
    def test_ordering(self):
        k1 = CameraKeyframe(frame=1)
        k2 = CameraKeyframe(frame=10)
        assert k1 < k2

    def test_frozen(self):
        k = CameraKeyframe(frame=1)
        with pytest.raises(AttributeError):
            k.frame = 2


# ---------------------------------------------------------------------------
# CameraAnimator
# ---------------------------------------------------------------------------

class TestCameraAnimator:
    def test_initial_state(self):
        anim = CameraAnimator()
        assert anim.mode == AnimationMode.NONE
        assert not anim.is_playing
        assert anim.mode_name == "None"

    def test_start_turntable(self):
        anim = CameraAnimator()
        anim.start_turntable(speed=36.0)
        assert anim.mode == AnimationMode.TURNTABLE
        assert anim.is_playing
        assert anim.frame_range == (0, 360)

    def test_stop(self):
        anim = CameraAnimator()
        anim.start_turntable()
        anim.stop()
        assert anim.mode == AnimationMode.NONE
        assert not anim.is_playing

    def test_turntable_update(self):
        anim = CameraAnimator()
        cam = _make_camera(azimuth=0.0)
        anim.start_turntable(speed=360.0)
        anim.update(cam, dt=0.5)
        assert cam.azimuth == pytest.approx(180.0, rel=1e-4)

    def test_add_keyframe(self):
        anim = CameraAnimator()
        cam = _make_camera()
        anim.add_keyframe(0, cam)
        assert anim.keyframe_count == 1
        assert anim.mode == AnimationMode.KEYFRAME

    def test_remove_keyframe(self):
        anim = CameraAnimator()
        cam = _make_camera()
        anim.add_keyframe(0, cam)
        anim.remove_keyframe(0)
        assert anim.keyframe_count == 0

    def test_clear_keyframes(self):
        anim = CameraAnimator()
        cam = _make_camera()
        anim.add_keyframe(0, cam)
        anim.add_keyframe(10, cam)
        anim.clear_keyframes()
        assert anim.keyframe_count == 0
        assert anim.mode == AnimationMode.NONE

    def test_keyframe_interpolation(self):
        anim = CameraAnimator()
        cam1 = _make_camera(azimuth=0.0, elevation=0.0, distance=2.0)
        cam2 = _make_camera(azimuth=90.0, elevation=30.0, distance=10.0)
        anim.add_keyframe(0, cam1)
        anim.add_keyframe(10, cam2)

        # Scrub to frame 5 (midpoint)
        target_cam = _make_camera()
        anim.set_frame(5, target_cam)
        assert target_cam.azimuth == pytest.approx(45.0, abs=1.0)
        assert target_cam.elevation == pytest.approx(15.0, abs=1.0)
        assert target_cam.distance == pytest.approx(6.0, abs=1.0)

    def test_get_turntable_frames(self):
        anim = CameraAnimator()
        frames = anim.get_turntable_frames(num_frames=4)
        assert len(frames) == 4
        assert "position" in frames[0]
        assert "target" in frames[0]

    def test_play_without_keyframes_is_noop(self):
        anim = CameraAnimator()
        anim.play()
        assert not anim.is_playing

    def test_pause(self):
        anim = CameraAnimator()
        anim.start_turntable()
        anim.pause()
        assert not anim.is_playing
