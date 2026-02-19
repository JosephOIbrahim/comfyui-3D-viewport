"""USD file loader for the 3D viewport.

Loads arbitrary USD files (.usd, .usdc, .usda) and extracts renderable
mesh geometry for OpenGL upload. Returns data in the same format as
stage_builder.get_cube_vertices() so the existing GL pipeline can consume it.
"""

import math
from dataclasses import dataclass, field

from pxr import Gf, Usd, UsdGeom


@dataclass
class MeshData:
    """Extracted mesh geometry ready for GL upload."""

    name: str                          # prim path
    vertices: list = field(default_factory=list)   # list of (x, y, z) tuples
    normals: list = field(default_factory=list)     # list of (nx, ny, nz) tuples
    indices: list = field(default_factory=list)     # flat list of triangle vertex indices
    transform: list = field(default_factory=list)   # 16-float column-major 4x4 matrix


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_usd_file(file_path: str) -> Usd.Stage:
    """Open a USD file and return the stage.

    Args:
        file_path: Path to a .usd, .usdc, or .usda file.

    Returns:
        The opened Usd.Stage.

    Raises:
        RuntimeError: If the file cannot be opened.
    """
    stage = Usd.Stage.Open(file_path)
    if stage is None:
        raise RuntimeError(f"Failed to open USD file: {file_path}")
    return stage


def extract_meshes(stage: Usd.Stage) -> list[MeshData]:
    """Traverse a USD stage and extract all UsdGeom.Mesh prims.

    Implicit geometries (Cube, Sphere, Cylinder, etc.) are skipped with a
    warning -- mesh conversion for those will be added in a later sprint.

    Args:
        stage: An opened Usd.Stage.

    Returns:
        List of MeshData objects, one per valid mesh prim found.
    """
    meshes: list[MeshData] = []
    xform_cache = UsdGeom.XformCache()

    for prim in stage.Traverse():
        # Skip implicit geometry with a warning
        if (
            prim.IsA(UsdGeom.Cube)
            or prim.IsA(UsdGeom.Sphere)
            or prim.IsA(UsdGeom.Cylinder)
            or prim.IsA(UsdGeom.Capsule)
            or prim.IsA(UsdGeom.Cone)
        ):
            print(
                f"  Skipping implicit geometry: {prim.GetPath()} "
                f"(Mesh conversion not yet supported)"
            )
            continue

        if not prim.IsA(UsdGeom.Mesh):
            continue

        mesh_data = _extract_single_mesh(prim, xform_cache)
        if mesh_data is not None:
            meshes.append(mesh_data)

    return meshes


def compute_scene_bounds(
    meshes: list[MeshData],
) -> tuple[tuple, tuple]:
    """Compute the world-space axis-aligned bounding box across all meshes.

    Vertices are transformed by each mesh's world transform before the
    comparison so the bounds are in world space.

    Args:
        meshes: List of MeshData objects.

    Returns:
        ((min_x, min_y, min_z), (max_x, max_y, max_z)).
        Falls back to ((-1, -1, -1), (1, 1, 1)) when *meshes* is empty.
    """
    if not meshes:
        return ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))

    all_min = [float("inf")] * 3
    all_max = [float("-inf")] * 3

    for mesh in meshes:
        m = mesh.transform
        for v in mesh.vertices:
            # Apply column-major 4x4 transform to the vertex
            wx = m[0] * v[0] + m[4] * v[1] + m[8] * v[2] + m[12]
            wy = m[1] * v[0] + m[5] * v[1] + m[9] * v[2] + m[13]
            wz = m[2] * v[0] + m[6] * v[1] + m[10] * v[2] + m[14]
            for i, c in enumerate((wx, wy, wz)):
                if c < all_min[i]:
                    all_min[i] = c
                if c > all_max[i]:
                    all_max[i] = c

    # Guard against a stage with meshes but no vertices
    if all_min[0] == float("inf"):
        return ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))

    return (tuple(all_min), tuple(all_max))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_single_mesh(
    prim: Usd.Prim,
    xform_cache: UsdGeom.XformCache,
) -> MeshData | None:
    """Extract geometry from a single UsdGeom.Mesh prim.

    Returns None if the prim has no usable geometry.
    """
    mesh = UsdGeom.Mesh(prim)

    # -- Points -----------------------------------------------------------
    points = mesh.GetPointsAttr().Get()
    if points is None or len(points) == 0:
        return None

    vertices = [(float(p[0]), float(p[1]), float(p[2])) for p in points]

    # -- Topology ---------------------------------------------------------
    face_counts = mesh.GetFaceVertexCountsAttr().Get()
    face_indices = mesh.GetFaceVertexIndicesAttr().Get()
    if face_counts is None or face_indices is None:
        return None

    triangles = _triangulate(face_counts, face_indices)
    if not triangles:
        return None

    # -- Normals ----------------------------------------------------------
    normals_attr = mesh.GetNormalsAttr()
    authored_normals = normals_attr.Get() if normals_attr else None

    if authored_normals is not None and len(authored_normals) > 0:
        normals = _resolve_authored_normals(
            authored_normals,
            mesh.GetNormalsInterpolation(),
            vertices,
            face_counts,
            face_indices,
        )
    else:
        normals = _compute_vertex_normals(vertices, triangles)

    # -- Transform --------------------------------------------------------
    world_xform = xform_cache.GetLocalToWorldTransform(prim)
    transform = _gf_matrix_to_list(world_xform)

    return MeshData(
        name=str(prim.GetPath()),
        vertices=vertices,
        normals=normals,
        indices=triangles,
        transform=transform,
    )


def _triangulate(
    face_counts: list | object,
    face_indices: list | object,
) -> list[int]:
    """Convert n-gon faces to triangles using fan triangulation.

    Degenerate faces (fewer than 3 vertices) are silently skipped.
    """
    triangles: list[int] = []
    idx = 0
    for count in face_counts:
        count = int(count)
        if count < 3:
            idx += count
            continue
        v0 = int(face_indices[idx])
        for i in range(1, count - 1):
            v1 = int(face_indices[idx + i])
            v2 = int(face_indices[idx + i + 1])
            triangles.extend((v0, v1, v2))
        idx += count
    return triangles


def _resolve_authored_normals(
    authored_normals,
    interpolation: str,
    vertices: list[tuple],
    face_counts,
    face_indices,
) -> list[tuple]:
    """Map authored normals to per-vertex normals regardless of interpolation.

    USD normals can be:
    - ``vertex``  : one normal per point (len == len(points))
    - ``faceVarying`` : one normal per face-vertex (len == len(faceVertexIndices))
    - ``uniform``  : one normal per face (len == len(faceVertexCounts))

    For faceVarying and uniform we average contributions per vertex to produce
    a per-vertex list that matches len(vertices).
    """
    num_verts = len(vertices)

    if interpolation == "vertex" and len(authored_normals) == num_verts:
        return [
            (float(n[0]), float(n[1]), float(n[2])) for n in authored_normals
        ]

    if interpolation == "faceVarying" and len(authored_normals) == len(face_indices):
        accum = [[0.0, 0.0, 0.0] for _ in range(num_verts)]
        counts = [0] * num_verts
        for fv_idx, vi in enumerate(face_indices):
            vi = int(vi)
            n = authored_normals[fv_idx]
            accum[vi][0] += float(n[0])
            accum[vi][1] += float(n[1])
            accum[vi][2] += float(n[2])
            counts[vi] += 1
        result: list[tuple] = []
        for i in range(num_verts):
            c = counts[i] if counts[i] > 0 else 1
            result.append(_normalize(accum[i][0] / c, accum[i][1] / c, accum[i][2] / c))
        return result

    if interpolation == "uniform" and len(authored_normals) == len(face_counts):
        accum = [[0.0, 0.0, 0.0] for _ in range(num_verts)]
        counts = [0] * num_verts
        idx = 0
        for face_i, count in enumerate(face_counts):
            count = int(count)
            n = authored_normals[face_i]
            nx, ny, nz = float(n[0]), float(n[1]), float(n[2])
            for j in range(count):
                vi = int(face_indices[idx + j])
                accum[vi][0] += nx
                accum[vi][1] += ny
                accum[vi][2] += nz
                counts[vi] += 1
            idx += count
        result = []
        for i in range(num_verts):
            c = counts[i] if counts[i] > 0 else 1
            result.append(_normalize(accum[i][0] / c, accum[i][1] / c, accum[i][2] / c))
        return result

    # Fallback: unrecognised interpolation or mismatched length --
    # recompute from geometry.
    return _compute_vertex_normals(vertices, _triangulate(face_counts, face_indices))


def _compute_vertex_normals(
    vertices: list[tuple],
    triangles: list[int],
) -> list[tuple]:
    """Compute smooth per-vertex normals by accumulating face normals.

    Each triangle's (un-normalised) face normal is added to all three of its
    vertices.  The accumulated vectors are normalised at the end, producing
    area-weighted smooth normals.  Degenerate triangles contribute zero and
    are harmless.
    """
    accum = [[0.0, 0.0, 0.0] for _ in range(len(vertices))]

    for i in range(0, len(triangles), 3):
        i0, i1, i2 = triangles[i], triangles[i + 1], triangles[i + 2]
        p0 = vertices[i0]
        p1 = vertices[i1]
        p2 = vertices[i2]

        # Edge vectors
        e1x = p1[0] - p0[0]
        e1y = p1[1] - p0[1]
        e1z = p1[2] - p0[2]
        e2x = p2[0] - p0[0]
        e2y = p2[1] - p0[1]
        e2z = p2[2] - p0[2]

        # Cross product (un-normalised face normal)
        nx = e1y * e2z - e1z * e2y
        ny = e1z * e2x - e1x * e2z
        nz = e1x * e2y - e1y * e2x

        for vi in (i0, i1, i2):
            accum[vi][0] += nx
            accum[vi][1] += ny
            accum[vi][2] += nz

    return [_normalize(a[0], a[1], a[2]) for a in accum]


def _normalize(x: float, y: float, z: float) -> tuple:
    """Return a unit-length (x, y, z) tuple; falls back to (0, 1, 0)."""
    length = math.sqrt(x * x + y * y + z * z)
    if length > 1e-10:
        return (x / length, y / length, z / length)
    return (0.0, 1.0, 0.0)


def _gf_matrix_to_list(m: Gf.Matrix4d) -> list[float]:
    """Convert a USD GfMatrix4d to a column-major 16-float list for OpenGL.

    USD stores matrices in row-major order.  OpenGL (and by convention most
    GL math libraries) expect column-major, so we transpose during
    extraction.
    """
    result: list[float] = []
    for col in range(4):
        for row in range(4):
            result.append(float(m[row][col]))
    return result
