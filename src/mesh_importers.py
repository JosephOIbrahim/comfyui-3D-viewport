"""Generic mesh file importers for the 3D viewport.

Loads GLB, GLTF, OBJ, and PLY files via trimesh and returns MeshData objects
compatible with the existing USD loader pipeline. All meshes are triangulated,
given smooth normals when none are provided, and assigned an identity transform
(trimesh already applies scene transforms during loading).
"""

import os

import numpy as np
import trimesh

from math_utils import compute_vertex_normals, vec3_normalize
from usd_loader import MeshData

# Column-major 4x4 identity matrix (16 floats) for OpenGL.
_IDENTITY_MATRIX: list[float] = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]

_DEFAULT_COLOR: tuple = (0.6, 0.6, 0.6)

_SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".glb": "glb",
    ".gltf": "gltf",
    ".obj": "obj",
    ".ply": "ply",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_glb(file_path: str) -> list[MeshData]:
    """Load a GLB or GLTF file and return a list of MeshData objects.

    GLB/GLTF scenes may contain multiple meshes. Each is returned as a
    separate MeshData with triangulated faces and computed normals.

    Args:
        file_path: Path to a .glb or .gltf file.

    Returns:
        List of MeshData objects, one per mesh in the scene.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be parsed.
    """
    return _load_via_trimesh(file_path, file_type=None)


def load_obj(file_path: str) -> list[MeshData]:
    """Load an OBJ file and return a list of MeshData objects.

    Args:
        file_path: Path to a .obj file.

    Returns:
        List of MeshData objects.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be parsed.
    """
    return _load_via_trimesh(file_path, file_type="obj")


def load_ply(file_path: str) -> list[MeshData]:
    """Load a PLY file and return a list of MeshData objects.

    Args:
        file_path: Path to a .ply file.

    Returns:
        List of MeshData objects.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be parsed.
    """
    return _load_via_trimesh(file_path, file_type="ply")


def load_mesh_file(file_path: str) -> list[MeshData]:
    """Dispatcher: load any supported mesh file based on its extension.

    Supported extensions: .glb, .gltf, .obj, .ply

    Args:
        file_path: Path to a mesh file.

    Returns:
        List of MeshData objects.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the extension is unsupported or the file cannot be parsed.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Mesh file not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported mesh format '{ext}'. "
            f"Supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
        )

    # Let trimesh detect the format from the extension (works for all four).
    return _load_via_trimesh(file_path, file_type=None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_via_trimesh(
    file_path: str,
    file_type: str | None,
) -> list[MeshData]:
    """Core loader: open a file with trimesh and convert all meshes.

    Handles both single-mesh files (trimesh.Trimesh) and multi-mesh scenes
    (trimesh.Scene).
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Mesh file not found: {file_path}")

    kwargs = {}
    if file_type is not None:
        kwargs["file_type"] = file_type

    loaded = trimesh.load(file_path, force=None, **kwargs)

    meshes: list[MeshData] = []

    if isinstance(loaded, trimesh.Trimesh):
        mesh_data = _trimesh_to_meshdata(loaded, name=_mesh_name(file_path, 0))
        if mesh_data is not None:
            meshes.append(mesh_data)

    elif isinstance(loaded, trimesh.Scene):
        for idx, (geom_name, geom) in enumerate(
            sorted(loaded.geometry.items())
        ):
            if not isinstance(geom, trimesh.Trimesh):
                continue
            mesh_data = _trimesh_to_meshdata(geom, name=str(geom_name))
            if mesh_data is not None:
                meshes.append(mesh_data)

    else:
        raise ValueError(
            f"Unexpected trimesh result type: {type(loaded).__name__}"
        )

    return meshes


def _trimesh_to_meshdata(
    mesh: trimesh.Trimesh,
    name: str,
) -> MeshData | None:
    """Convert a single trimesh.Trimesh into a MeshData object.

    - Triangulates faces (trimesh does this by default on load).
    - Computes smooth vertex normals if none are present.
    - Extracts vertex colors or material diffuse color where available.
    """
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        return None

    # -- Vertices ---------------------------------------------------------
    vertices = [(float(v[0]), float(v[1]), float(v[2])) for v in mesh.vertices]

    # -- Indices (flat triangle list) -------------------------------------
    indices = mesh.faces.flatten().tolist()

    # -- Normals ----------------------------------------------------------
    try:
        # trimesh computes vertex normals on demand; this may fail on
        # degenerate geometry. Only swallow predictable parsing errors;
        # let MemoryError, KeyboardInterrupt, etc. propagate.
        raw_normals = mesh.vertex_normals
        if raw_normals is not None and len(raw_normals) == len(vertices):
            normals = [
                (float(n[0]), float(n[1]), float(n[2])) for n in raw_normals
            ]
        else:
            normals = _compute_vertex_normals(vertices, indices)
    except (ValueError, AttributeError, IndexError, TypeError):
        normals = _compute_vertex_normals(vertices, indices)

    # -- Color ------------------------------------------------------------
    color = _extract_color(mesh)

    return MeshData(
        name=name,
        vertices=vertices,
        normals=normals,
        indices=indices,
        transform=list(_IDENTITY_MATRIX),
        color=color,
    )


def _extract_color(mesh: trimesh.Trimesh) -> tuple:
    """Extract a representative RGB color from a trimesh mesh.

    Resolution order:
        1. Per-vertex colors (average of all vertex colors).
        2. Material diffuse / base color.
        3. Default grey (0.6, 0.6, 0.6).
    """
    # 1. Vertex colors
    if (
        mesh.visual is not None
        and hasattr(mesh.visual, "kind")
        and mesh.visual.kind == "vertex"
    ):
        try:
            vc = mesh.visual.vertex_colors
            if vc is not None and len(vc) > 0:
                # vertex_colors is Nx4 uint8 (RGBA). Average and normalise.
                avg = np.mean(vc[:, :3].astype(float), axis=0) / 255.0
                return (float(avg[0]), float(avg[1]), float(avg[2]))
        except (ValueError, AttributeError, IndexError, TypeError):
            pass

    # 2. Material color
    if mesh.visual is not None:
        try:
            material = None
            if hasattr(mesh.visual, "material"):
                material = mesh.visual.material

            if material is not None:
                # PBRMaterial uses baseColorFactor; SimpleMaterial uses diffuse.
                for attr in ("baseColorFactor", "diffuse", "main_color"):
                    val = getattr(material, attr, None)
                    if val is not None:
                        arr = np.asarray(val, dtype=float)
                        if arr.ndim == 0:
                            continue
                        # Normalise uint8 values to 0-1 range.
                        if arr.max() > 1.0:
                            arr = arr / 255.0
                        if len(arr) >= 3:
                            return (
                                float(np.clip(arr[0], 0.0, 1.0)),
                                float(np.clip(arr[1], 0.0, 1.0)),
                                float(np.clip(arr[2], 0.0, 1.0)),
                            )
        except (ValueError, AttributeError, IndexError, TypeError):
            pass

    return _DEFAULT_COLOR


# Normal computation imported from math_utils (compute_vertex_normals, vec3_normalize)
_compute_vertex_normals = compute_vertex_normals
_normalize = vec3_normalize


def _mesh_name(file_path: str, index: int) -> str:
    """Generate a mesh name from the file basename and index."""
    base = os.path.splitext(os.path.basename(file_path))[0]
    return f"/{base}/mesh_{index}"
