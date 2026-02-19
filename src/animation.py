"""Camera animation system for the 3D viewport.

Provides two animation modes:

    Turntable -- continuous auto-orbit around the target point at a
    configurable speed (degrees per second).  Useful for product
    turntables and batch ControlNet conditioning.

    Keyframe -- scrub or play through user-defined camera keyframes
    with linear interpolation (including 360-degree azimuth wrapping).

Usage::

    animator = CameraAnimator(fps=24.0)
    animator.start_turntable(speed=36.0)

    # In the render loop:
    animator.update(camera, dt)

No OpenGL or Qt calls -- the viewport drives the animation via a
QTimer and calls ``update(camera, dt)`` each frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camera import OrbitCamera


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class CameraKeyframe:
    """Snapshot of camera state at a specific frame number.

    Ordered by *frame* so a sorted list gives chronological order.
    """

    frame: int
    azimuth: float = 0.0
    elevation: float = 20.0
    distance: float = 5.0
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)


class AnimationMode(Enum):
    """Active animation behaviour."""

    NONE = auto()
    TURNTABLE = auto()
    KEYFRAME = auto()


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------

def _lerp(a: float, b: float, t: float) -> float:
    """Standard linear interpolation."""
    return a + (b - a) * t


def _lerp_angle(a: float, b: float, t: float) -> float:
    """Linearly interpolate between two angles in degrees.

    Takes the shortest arc around the 360-degree circle so that
    interpolating from 350 to 10 travels +20 degrees, not -340.
    """
    diff = (b - a) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return (a + diff * t) % 360.0


def _lerp_tuple(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    t: float,
) -> tuple[float, float, float]:
    return (
        _lerp(a[0], b[0], t),
        _lerp(a[1], b[1], t),
        _lerp(a[2], b[2], t),
    )


# ---------------------------------------------------------------------------
# CameraAnimator
# ---------------------------------------------------------------------------

class CameraAnimator:
    """Drives turntable orbits and keyframe playback on an OrbitCamera.

    Parameters
    ----------
    fps : float
        Frames-per-second used when converting between wall-clock delta
        and frame numbers during keyframe playback.
    """

    def __init__(self, fps: float = 24.0) -> None:
        self._mode: AnimationMode = AnimationMode.NONE
        self._fps: float = fps
        self._current_frame: float = 0.0
        self._playing: bool = False

        # Turntable settings
        self._turntable_speed: float = 36.0   # degrees / second
        self._turntable_elevation: float = 20.0
        self._turntable_distance: float = 5.0

        # Keyframe storage (kept sorted by frame)
        self._keyframes: list[CameraKeyframe] = []

        self._loop: bool = True
        self._start_time: float = 0.0

    # -- Properties ---------------------------------------------------------

    @property
    def mode(self) -> AnimationMode:
        """Current animation mode."""
        return self._mode

    @property
    def is_playing(self) -> bool:
        """``True`` while turntable or keyframe playback is active."""
        return self._playing

    @property
    def current_frame(self) -> int:
        """Current playback position rounded to the nearest integer frame."""
        return round(self._current_frame)

    @property
    def frame_range(self) -> tuple[int, int]:
        """``(first_frame, last_frame)`` of the active animation.

        Turntable mode returns ``(0, 360)`` (one full revolution at
        1 degree per frame).  Keyframe mode returns the range spanned
        by the first and last keyframes, or ``(0, 0)`` if empty.
        """
        if self._mode == AnimationMode.TURNTABLE:
            return (0, 360)
        if self._keyframes:
            return (self._keyframes[0].frame, self._keyframes[-1].frame)
        return (0, 0)

    @property
    def keyframe_count(self) -> int:
        return len(self._keyframes)

    @property
    def mode_name(self) -> str:
        _NAMES = {
            AnimationMode.NONE: "None",
            AnimationMode.TURNTABLE: "Turntable",
            AnimationMode.KEYFRAME: "Keyframe",
        }
        return _NAMES[self._mode]

    # -- Turntable ----------------------------------------------------------

    def start_turntable(
        self,
        speed: float = 36.0,
        elevation: float | None = None,
        distance: float | None = None,
        camera: OrbitCamera | None = None,
    ) -> None:
        """Begin continuous turntable orbit.

        If *elevation* or *distance* are ``None`` and a *camera* is
        provided, the camera's current values are used.  Otherwise the
        stored defaults apply.
        """
        self._mode = AnimationMode.TURNTABLE
        self._turntable_speed = speed
        self._playing = True
        self._current_frame = 0.0

        if elevation is not None:
            self._turntable_elevation = elevation
        elif camera is not None:
            self._turntable_elevation = camera.elevation

        if distance is not None:
            self._turntable_distance = distance
        elif camera is not None:
            self._turntable_distance = camera.distance

    def stop(self) -> None:
        """Stop any active animation and reset mode to NONE."""
        self._playing = False
        self._mode = AnimationMode.NONE

    # -- Keyframe -----------------------------------------------------------

    def add_keyframe(self, frame: int, camera: OrbitCamera) -> None:
        """Capture the camera's current state as a keyframe at *frame*.

        If a keyframe already exists at *frame* it is replaced.
        """
        kf = CameraKeyframe(
            frame=frame,
            azimuth=camera.azimuth,
            elevation=camera.elevation,
            distance=camera.distance,
            target=tuple(camera.target),
        )
        # Remove existing keyframe at same frame, then insert sorted
        self._keyframes = [k for k in self._keyframes if k.frame != frame]
        self._keyframes.append(kf)
        self._keyframes.sort()

        # Ensure mode is KEYFRAME once we have keyframes
        if self._mode == AnimationMode.NONE:
            self._mode = AnimationMode.KEYFRAME

    def remove_keyframe(self, frame: int) -> None:
        """Remove the keyframe at *frame* (no-op if none exists)."""
        self._keyframes = [k for k in self._keyframes if k.frame != frame]

    def clear_keyframes(self) -> None:
        """Remove all keyframes and stop playback."""
        self._keyframes.clear()
        if self._mode == AnimationMode.KEYFRAME:
            self._playing = False
            self._mode = AnimationMode.NONE

    def play(self) -> None:
        """Start keyframe playback from the current frame."""
        if not self._keyframes:
            return
        self._mode = AnimationMode.KEYFRAME
        self._playing = True

    def pause(self) -> None:
        """Pause playback without resetting the current frame."""
        self._playing = False

    def set_frame(self, frame: int, camera: OrbitCamera) -> None:
        """Scrub to *frame* and apply the interpolated state to *camera*."""
        self._current_frame = float(frame)
        if not self._keyframes:
            return
        kf = self._interpolate(float(frame))
        self._apply_keyframe(camera, kf)

    # -- Core update --------------------------------------------------------

    def update(self, camera: OrbitCamera, dt: float) -> None:
        """Advance the animation by *dt* seconds and apply to *camera*.

        Call this once per render frame from the viewport's timer
        callback.
        """
        if not self._playing:
            return

        if self._mode == AnimationMode.TURNTABLE:
            self._update_turntable(camera, dt)
        elif self._mode == AnimationMode.KEYFRAME:
            self._update_keyframe(camera, dt)

    # -- Turntable internals ------------------------------------------------

    def _update_turntable(self, camera: OrbitCamera, dt: float) -> None:
        camera.azimuth += self._turntable_speed * dt
        camera.elevation = self._turntable_elevation
        camera.distance = self._turntable_distance
        self._current_frame += self._turntable_speed * dt

    # -- Keyframe internals -------------------------------------------------

    def _update_keyframe(self, camera: OrbitCamera, dt: float) -> None:
        if not self._keyframes:
            return

        self._current_frame += self._fps * dt

        first = self._keyframes[0].frame
        last = self._keyframes[-1].frame
        span = last - first

        if span <= 0:
            # Single keyframe -- just hold it
            self._apply_keyframe(camera, self._keyframes[0])
            return

        if self._current_frame > last:
            if self._loop:
                # Wrap around to first frame
                self._current_frame = first + (
                    (self._current_frame - first) % (span + 1)
                )
            else:
                self._current_frame = float(last)
                self._playing = False

        kf = self._interpolate(self._current_frame)
        self._apply_keyframe(camera, kf)

    def _interpolate(self, frame: float) -> CameraKeyframe:
        """Linearly interpolate between the two keyframes surrounding *frame*.

        Azimuth uses shortest-arc wrapping.  At the boundaries the
        first/last keyframe is clamped (unless looping wraps the
        frame beforehand).
        """
        if not self._keyframes:
            return CameraKeyframe(frame=round(frame))

        # Before first keyframe -- clamp
        if frame <= self._keyframes[0].frame:
            k = self._keyframes[0]
            return CameraKeyframe(
                frame=round(frame),
                azimuth=k.azimuth,
                elevation=k.elevation,
                distance=k.distance,
                target=k.target,
            )

        # After last keyframe -- clamp
        if frame >= self._keyframes[-1].frame:
            k = self._keyframes[-1]
            return CameraKeyframe(
                frame=round(frame),
                azimuth=k.azimuth,
                elevation=k.elevation,
                distance=k.distance,
                target=k.target,
            )

        # Find surrounding pair
        for i in range(len(self._keyframes) - 1):
            k0 = self._keyframes[i]
            k1 = self._keyframes[i + 1]
            if k0.frame <= frame <= k1.frame:
                span = k1.frame - k0.frame
                t = (frame - k0.frame) / span if span > 0 else 0.0
                return CameraKeyframe(
                    frame=round(frame),
                    azimuth=_lerp_angle(k0.azimuth, k1.azimuth, t),
                    elevation=_lerp(k0.elevation, k1.elevation, t),
                    distance=_lerp(k0.distance, k1.distance, t),
                    target=_lerp_tuple(k0.target, k1.target, t),
                )

        # Fallback (should not be reached)
        k = self._keyframes[-1]
        return CameraKeyframe(
            frame=round(frame),
            azimuth=k.azimuth,
            elevation=k.elevation,
            distance=k.distance,
            target=k.target,
        )

    @staticmethod
    def _apply_keyframe(camera: OrbitCamera, kf: CameraKeyframe) -> None:
        """Write keyframe values onto the camera."""
        camera.azimuth = kf.azimuth
        camera.elevation = kf.elevation
        camera.distance = kf.distance
        camera.target = list(kf.target)

    # -- Export helper ------------------------------------------------------

    def get_turntable_frames(
        self,
        num_frames: int = 36,
        elevation: float = 20.0,
        distance: float = 5.0,
        target: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> list[dict]:
        """Return evenly-spaced turntable camera dicts.

        Each dict matches the format of ``OrbitCamera.to_load3d_camera()``
        (position, target, up, fov, focal_length).  Useful for batch
        ControlNet conditioning where you need N views around an object.

        Parameters
        ----------
        num_frames : int
            Number of views around the full 360-degree orbit.
        elevation : float
            Vertical angle in degrees.
        distance : float
            Orbit radius.
        target : tuple
            Orbit center ``(x, y, z)``.
        """
        step = 360.0 / num_frames
        frames: list[dict] = []

        for i in range(num_frames):
            azimuth = i * step
            az_rad = math.radians(azimuth)
            el_rad = math.radians(elevation)
            cos_el = math.cos(el_rad)

            x = target[0] + distance * cos_el * math.sin(az_rad)
            y = target[1] + distance * math.sin(el_rad)
            z = target[2] + distance * cos_el * math.cos(az_rad)

            frames.append({
                "position": [x, y, z],
                "target": list(target),
                "up": [0.0, 1.0, 0.0],
                "fov": 45.0,
                "focal_length": None,
            })

        return frames
