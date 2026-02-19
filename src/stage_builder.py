"""USD stage factory for CarWash-2 viewport.

Creates an in-memory Usd.Stage with default geometry (cube),
lighting (dome light), and scene configuration (Y-up).
"""

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux


def create_default_stage() -> Usd.Stage:
    """Create an in-memory USD stage with a cube, ground plane, and dome light.

    Returns:
        Configured Usd.Stage ready for rendering.
    """
    stage = Usd.Stage.CreateInMemory()

    # Set Y-up (USD default, explicit for clarity)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)  # cm

    # Root xform
    world = UsdGeom.Xform.Define(stage, "/World")

    # Cube at origin, size 1.0
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.GetSizeAttr().Set(1.0)
    # Lift cube so it sits on Y=0 ground plane
    cube.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.5, 0.0))

    # Ground plane (thin cube scaled flat)
    ground = UsdGeom.Cube.Define(stage, "/World/Ground")
    ground.GetSizeAttr().Set(1.0)
    ground.AddTranslateOp().Set(Gf.Vec3d(0.0, -0.025, 0.0))
    ground.AddScaleOp().Set(Gf.Vec3f(5.0, 0.05, 5.0))

    # Dome light for ambient illumination
    dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome.GetIntensityAttr().Set(1.0)

    return stage


def get_cube_vertices() -> tuple[list, list, list]:
    """Return hardcoded unit cube geometry centered at origin.

    Returns:
        (vertices, normals, indices) for a unit cube.
        vertices: list of (x, y, z) floats
        normals: list of (nx, ny, nz) floats (per-vertex)
        indices: list of int (triangles)
    """
    # 24 vertices (4 per face, for correct normals)
    vertices = [
        # Front face (Z+)
        (-0.5, -0.5,  0.5), ( 0.5, -0.5,  0.5),
        ( 0.5,  0.5,  0.5), (-0.5,  0.5,  0.5),
        # Back face (Z-)
        ( 0.5, -0.5, -0.5), (-0.5, -0.5, -0.5),
        (-0.5,  0.5, -0.5), ( 0.5,  0.5, -0.5),
        # Top face (Y+)
        (-0.5,  0.5,  0.5), ( 0.5,  0.5,  0.5),
        ( 0.5,  0.5, -0.5), (-0.5,  0.5, -0.5),
        # Bottom face (Y-)
        (-0.5, -0.5, -0.5), ( 0.5, -0.5, -0.5),
        ( 0.5, -0.5,  0.5), (-0.5, -0.5,  0.5),
        # Right face (X+)
        ( 0.5, -0.5,  0.5), ( 0.5, -0.5, -0.5),
        ( 0.5,  0.5, -0.5), ( 0.5,  0.5,  0.5),
        # Left face (X-)
        (-0.5, -0.5, -0.5), (-0.5, -0.5,  0.5),
        (-0.5,  0.5,  0.5), (-0.5,  0.5, -0.5),
    ]

    normals = [
        # Front
        (0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1),
        # Back
        (0, 0, -1), (0, 0, -1), (0, 0, -1), (0, 0, -1),
        # Top
        (0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0),
        # Bottom
        (0, -1, 0), (0, -1, 0), (0, -1, 0), (0, -1, 0),
        # Right
        (1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0),
        # Left
        (-1, 0, 0), (-1, 0, 0), (-1, 0, 0), (-1, 0, 0),
    ]

    # Two triangles per face
    indices = []
    for face in range(6):
        base = face * 4
        indices.extend([base, base + 1, base + 2,
                        base, base + 2, base + 3])

    return vertices, normals, indices
