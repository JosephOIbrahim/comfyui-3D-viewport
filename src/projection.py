"""Physical camera projection for CarWash-2 viewport.

Computes projection matrices from real sensor dimensions and lens focal lengths.
Supports spherical and anamorphic (2x squeeze) lenses.

This replaces the simple FOV-based perspective() function with physically
accurate projection matching real cinema cameras (ARRI, RED, Sony) and
lenses (Cooke, Atlas).
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SensorGate:
    """Camera sensor/gate dimensions."""
    width_mm: float
    height_mm: float
    name: str = ""

    @property
    def aspect_ratio(self) -> float:
        return self.width_mm / self.height_mm

    @property
    def diagonal_mm(self) -> float:
        return math.sqrt(self.width_mm**2 + self.height_mm**2)


@dataclass
class Lens:
    """Lens optical properties."""
    focal_mm: float
    squeeze_ratio: float = 1.0  # 1.0 = spherical, 2.0 = anamorphic
    name: str = ""
    t_stop_range: tuple[float, float] = (2.0, 22.0)

    @property
    def is_anamorphic(self) -> bool:
        return self.squeeze_ratio != 1.0


# ---------------------------------------------------------------------------
# Common presets for quick access
# ---------------------------------------------------------------------------

SENSOR_PRESETS = {
    "alexa35_og": SensorGate(27.99, 19.22, "ARRI Alexa 35 Open Gate"),
    "alexa35_s35": SensorGate(24.89, 14.00, "ARRI Alexa 35 S35"),
    "red_vraptor_ff": SensorGate(40.96, 21.60, "RED V-RAPTOR FF"),
    "red_vraptor_s35": SensorGate(23.10, 12.15, "RED V-RAPTOR S35"),
    "venice2_ff": SensorGate(36.20, 24.10, "Sony VENICE 2 FF"),
    "venice2_s35": SensorGate(24.40, 13.70, "Sony VENICE 2 S35"),
    # Standard reference sizes
    "s35_academy": SensorGate(21.95, 16.00, "Super 35 Academy"),
    "ff_35mm": SensorGate(36.00, 24.00, "Full Frame 35mm"),
}

LENS_PRESETS = {
    "cooke_ana_40": Lens(40.0, 2.0, "Cooke Anamorphic/i 40mm"),
    "cooke_ana_50": Lens(50.0, 2.0, "Cooke Anamorphic/i 50mm"),
    "cooke_ana_75": Lens(75.0, 2.0, "Cooke Anamorphic/i 75mm"),
    "cooke_s7i_25": Lens(25.0, 1.0, "Cooke S7/i 25mm"),
    "cooke_s7i_50": Lens(50.0, 1.0, "Cooke S7/i 50mm"),
    "cooke_s7i_100": Lens(100.0, 1.0, "Cooke S7/i 100mm"),
    "atlas_orion_40": Lens(40.0, 2.0, "Atlas Orion 40mm"),
    "atlas_orion_65": Lens(65.0, 2.0, "Atlas Orion 65mm"),
    # Simple reference
    "pinhole_50": Lens(50.0, 1.0, "50mm Pinhole (reference)"),
}


class PhysicalProjection:
    """Compute GL projection matrices from physical camera parameters.

    This is the core of the CarWash-2 camera system.  Instead of a single
    FOV parameter, projection is derived from sensor dimensions and lens
    focal length -- matching real cinema camera behavior.

    Two matrix methods are provided:

    * ``projection_matrix()`` -- the exact physical projection for the
      sensor+lens combination.  The resulting aspect ratio is dictated by
      the sensor gate (and squeeze ratio for anamorphic).  Use this when
      the viewport pixel dimensions match the sensor aspect.

    * ``fov_perspective_matrix(aspect)`` -- a standard perspective matrix
      whose vertical FOV is derived from the physical sensor+lens, but
      whose horizontal extent is controlled by the given *aspect* ratio.
      Use this for viewport rendering where the window aspect may differ
      from the sensor aspect (the typical case).
    """

    def __init__(
        self,
        sensor: SensorGate,
        lens: Lens,
        near: float = 0.1,
        far: float = 100.0,
    ):
        self.sensor = sensor
        self.lens = lens
        self.near = near
        self.far = far

    # -- derived properties -------------------------------------------------

    @property
    def fov_h_deg(self) -> float:
        """Horizontal field of view in degrees (taking FOV, post-squeeze)."""
        half_w = self.sensor.width_mm / 2.0
        if self.lens.is_anamorphic:
            # Anamorphic lens captures squeeze_ratio times wider
            half_w *= self.lens.squeeze_ratio
        return math.degrees(2.0 * math.atan(half_w / self.lens.focal_mm))

    @property
    def fov_v_deg(self) -> float:
        """Vertical field of view in degrees."""
        half_h = self.sensor.height_mm / 2.0
        return math.degrees(2.0 * math.atan(half_h / self.lens.focal_mm))

    @property
    def effective_aspect(self) -> float:
        """Effective aspect ratio after anamorphic unsqueeze."""
        base_aspect = self.sensor.width_mm / self.sensor.height_mm
        return base_aspect * self.lens.squeeze_ratio

    # -- matrix builders ----------------------------------------------------

    def projection_matrix(self) -> list[float]:
        """Compute column-major 4x4 projection matrix for OpenGL.

        Returns the exact physical projection for this sensor+lens pair.
        The matrix aspect ratio equals ``effective_aspect`` (sensor gate
        aspect multiplied by squeeze ratio for anamorphic lenses).

        Returns:
            16-element list in column-major order.
        """
        # Normalized focal lengths (sensor-space)
        fx = self.lens.focal_mm / (self.sensor.width_mm / 2.0)
        fy = self.lens.focal_mm / (self.sensor.height_mm / 2.0)

        # Anamorphic: lens captures wider FOV, divide fx by squeeze
        if self.lens.is_anamorphic:
            fx = fx / self.lens.squeeze_ratio

        near = self.near
        far = self.far
        nf = 1.0 / (near - far)

        return [
            fx,  0.0, 0.0,                    0.0,
            0.0, fy,  0.0,                    0.0,
            0.0, 0.0, (far + near) * nf,     -1.0,
            0.0, 0.0, 2.0 * far * near * nf,  0.0,
        ]

    def fov_perspective_matrix(self, aspect: float) -> list[float]:
        """Simple FOV-based perspective using physically derived vertical FOV.

        Uses the vertical FOV from the real sensor+lens, but applies it
        with an arbitrary viewport aspect ratio.  This is the recommended
        method for viewport rendering because the viewport window is rarely
        the same aspect as the camera sensor.

        Matches Sprint-1 ``perspective()`` behaviour so it can serve as a
        drop-in replacement.

        Args:
            aspect: Viewport width / height.

        Returns:
            16-element list in column-major order.
        """
        fov_v_rad = math.radians(self.fov_v_deg)
        f = 1.0 / math.tan(fov_v_rad / 2.0)
        near = self.near
        far = self.far
        nf = 1.0 / (near - far)

        return [
            f / aspect, 0.0, 0.0,                    0.0,
            0.0,        f,   0.0,                    0.0,
            0.0,        0.0, (far + near) * nf,     -1.0,
            0.0,        0.0, 2.0 * far * near * nf,  0.0,
        ]

    # -- serialization ------------------------------------------------------

    def to_load3d_camera(
        self,
        position: tuple[float, float, float],
        target: tuple[float, float, float],
        up: tuple[float, float, float] = (0.0, 1.0, 0.0),
    ) -> dict:
        """Export camera state as LOAD3D_CAMERA-compatible dict.

        Includes standard Load3D fields plus ``carwash_`` extensions for
        full physical camera metadata round-tripping.
        """
        return {
            # Standard LOAD3D_CAMERA fields
            "position": list(position),
            "target": list(target),
            "up": list(up),
            "fov": self.fov_v_deg,
            "focal_length": self.lens.focal_mm,
            # CarWash-2 extensions
            "carwash_version": "2.0",
            "carwash_sensor_body": self.sensor.name,
            "carwash_sensor_width_mm": self.sensor.width_mm,
            "carwash_sensor_height_mm": self.sensor.height_mm,
            "carwash_lens_model": self.lens.name,
            "carwash_focal_mm": self.lens.focal_mm,
            "carwash_squeeze_ratio": self.lens.squeeze_ratio,
            "carwash_fov_h_deg": self.fov_h_deg,
            "carwash_fov_v_deg": self.fov_v_deg,
            "carwash_effective_aspect": self.effective_aspect,
        }


# ---------------------------------------------------------------------------
# Database helpers -- load camera/lens combos from external JSON
# ---------------------------------------------------------------------------

def load_database(path: str | Path | None = None) -> dict:
    """Load camera/lens database from JSON file.

    Args:
        path: Path to database JSON.  Defaults to
            ``data/camera_lens_database.json`` relative to project root.

    Returns:
        Dict with ``cameras``, ``lenses``, ``presets`` keys.
    """
    if path is None:
        path = Path(__file__).parent.parent / "data" / "camera_lens_database.json"
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sensor_from_database(camera_id: str, db: dict | None = None) -> SensorGate:
    """Look up a :class:`SensorGate` from the database by camera ID."""
    if db is None:
        db = load_database()
    for cam in db["cameras"]:
        if cam["id"] == camera_id:
            return SensorGate(
                width_mm=cam["sensor_width_mm"],
                height_mm=cam["sensor_height_mm"],
                name=f"{cam['name']} {cam['gate']}",
            )
    raise KeyError(f"Camera '{camera_id}' not found in database")


def lens_from_database(lens_id: str, db: dict | None = None) -> Lens:
    """Look up a :class:`Lens` from the database by lens ID."""
    if db is None:
        db = load_database()
    for entry in db["lenses"]:
        if entry["id"] == lens_id:
            return Lens(
                focal_mm=entry["focal_mm"],
                squeeze_ratio=entry["squeeze_ratio"],
                name=entry["name"],
                t_stop_range=tuple(entry["t_stop_range"]),
            )
    raise KeyError(f"Lens '{lens_id}' not found in database")


def preset_from_database(
    preset_id: str, db: dict | None = None
) -> PhysicalProjection:
    """Load a complete camera+lens preset from the database.

    Returns a ready-to-use :class:`PhysicalProjection` instance.
    """
    if db is None:
        db = load_database()
    for p in db["presets"]:
        if p["id"] == preset_id:
            sensor = sensor_from_database(p["camera_id"], db)
            lens = lens_from_database(p["lens_id"], db)
            return PhysicalProjection(sensor, lens)
    raise KeyError(f"Preset '{preset_id}' not found in database")
