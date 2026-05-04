"""CarWash-2 Storm Viewport -- Phase 0, Sprint 5.

Renders a USD stage in a Qt window via OpenGL with:
- Multi-light Blinn-Phong shading (up to 4 directional lights)
- Environment background (gradient / HDRI / solid)
- World grid + axis gizmo overlay
- Camera info HUD with FPS counter
- Depth + Normal AOV export (P key)
- AOV bridge export to ComfyUI (auto when bridge connected)
- LOAD3D_CAMERA JSON export (L key)
- Physical camera presets (0-4 keys)
- DCC-standard orbit/pan/dolly controls
- Wireframe / shading modes (W key)
- Drag-and-drop USD/GLB/OBJ/PLY file loading
- ComfyUI WebSocket bridge (B key)
- USD material color extraction
- Click-to-select + Tab cycle selection
- Multi-light rig with presets (G key)
- Camera turntable animation (T key)
- Environment background presets (E key)

Usage:
    python src/viewport.py                    # Default cube scene
    python src/viewport.py path/to/model.usd  # Load USD file
    python src/viewport.py path/to/model.glb  # Load GLB file

Requires Python >=3.10 venv with: usd-core, PySide6, PyOpenGL, numpy, trimesh
    .venv/Scripts/python src/viewport.py
"""

import ctypes
import json
import os
import sys
import time

if sys.version_info < (3, 10):  # PEP 604 union types used throughout
    raise RuntimeError(
        f"comfyui-3d-viewport requires Python >=3.10, got "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )

import numpy as np

from OpenGL.GL import (
    GL_BACK,
    GL_COLOR_BUFFER_BIT,
    GL_CULL_FACE,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_COMPONENT,
    GL_DEPTH_TEST,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_LESS,
    GL_TRIANGLES,
    GL_VERTEX_SHADER,
    glAttachShader,
    glBindBuffer,
    glBindVertexArray,
    glBufferData,
    glClear,
    glClearColor,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glCullFace,
    glDeleteShader,
    glDepthFunc,
    glDrawElements,
    glEnable,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenVertexArrays,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glReadPixels,
    glShaderSource,
    glUniform1f,
    glUniform1i,
    glUniform3f,
    glUniform3fv,
    glUniformMatrix4fv,
    glUseProgram,
    glVertexAttribPointer,
    glViewport,
)
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_COMPILE_STATUS,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_READ_FRAMEBUFFER,
    GL_STATIC_DRAW,
    GL_UNSIGNED_INT,
    glBindFramebuffer,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMainWindow

from animation import CameraAnimator, AnimationMode
from aov_export import AOVExporter
from aov_renderer import AOVRenderer
from bridge_server import BridgeServer
from camera import OrbitCamera
from comfy_bridge import ComfyBridge
from environment import EnvironmentMap
from file_drop import FileDropHandler, FileDropOverlay, detect_format
from grid import GridRenderer
from hud import HUD
from lighting import LightRig, MAX_LIGHTS
from math_utils import (
    look_at, mat4_multiply, scale_matrix, scale_matrix_uniform,
    translation_matrix,
)
from mesh_importers import load_mesh_file
from projection import preset_from_database
from selection import SelectionManager, get_highlight_color, get_highlight_scale
from shading import ShadingManager, ShadingMode
from stage_builder import create_default_stage, get_cube_vertices
from usd_loader import MeshData, extract_meshes, load_usd_file

# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

VERTEX_SHADER = """
#version 330 core

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProjection;

out vec3 vNormal;
out vec3 vFragPos;

void main() {
    vec4 worldPos = uModel * vec4(aPos, 1.0);
    vFragPos = worldPos.xyz;
    vNormal = mat3(transpose(inverse(uModel))) * aNormal;
    gl_Position = uProjection * uView * worldPos;
}
"""

FRAGMENT_SHADER = """
#version 330 core

in vec3 vNormal;
in vec3 vFragPos;

// Multi-light uniforms (up to 4 lights)
uniform int uLightCount;
uniform vec3 uLightDirs[4];
uniform vec3 uLightColors[4];

uniform vec3 uBaseColor;
uniform vec3 uViewPos;
uniform float uAmbientOverride;

out vec4 FragColor;

void main() {
    vec3 norm = normalize(vNormal);
    vec3 viewDir = normalize(uViewPos - vFragPos);

    // Ambient (overridable for unlit mode)
    float ambient = max(0.15, uAmbientOverride);
    bool unlit = (ambient >= 1.0);

    vec3 diffuse_accum = vec3(0.0);
    vec3 specular_accum = vec3(0.0);

    if (!unlit) {
        for (int i = 0; i < uLightCount; i++) {
            vec3 lightDir = normalize(uLightDirs[i]);

            // Diffuse
            float diff = max(dot(norm, lightDir), 0.0);
            diffuse_accum += uLightColors[i] * diff;

            // Specular (Blinn-Phong)
            vec3 halfDir = normalize(lightDir + viewDir);
            float spec = pow(max(dot(norm, halfDir), 0.0), 32.0) * 0.3;
            specular_accum += uLightColors[i] * spec;
        }
    }

    vec3 result = uBaseColor * (ambient + diffuse_accum * 0.75) + specular_accum;
    FragColor = vec4(result, 1.0);
}
"""


# ---------------------------------------------------------------------------
# GL helpers
# ---------------------------------------------------------------------------

def compile_shader(source: str, shader_type: int) -> int:
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        info = glGetShaderInfoLog(shader).decode()
        raise RuntimeError(f"Shader compile error: {info}")
    return shader


def create_shader_program(vert_src: str, frag_src: str) -> int:
    vs = compile_shader(vert_src, GL_VERTEX_SHADER)
    fs = compile_shader(frag_src, GL_FRAGMENT_SHADER)
    program = glCreateProgram()
    glAttachShader(program, vs)
    glAttachShader(program, fs)
    glLinkProgram(program)
    glDeleteShader(vs)
    glDeleteShader(fs)
    return program


# ---------------------------------------------------------------------------
# Viewport widget
# ---------------------------------------------------------------------------

class StormViewport(QOpenGLWidget):
    """OpenGL viewport rendering USD geometry.

    Currently uses direct GL (no Hydra Storm) because usd-core pip wheels
    don't include UsdImagingGL. The scene is read from the USD stage.
    """

    def __init__(self, stage, parent=None):
        super().__init__(parent)
        self._stage = stage
        self._program = None
        self._uniform_locs: dict[str, int] = {}  # cached uniform locations
        self._depth_verified = False
        self._initialized = False
        self._width = 800
        self._height = 600

        # Geometry: list of (vao, index_count, model_matrix, color)
        self._draw_list: list[tuple] = []

        # MeshData list (kept in sync with _draw_list for selection)
        self._mesh_data_list: list[MeshData] = []

        # Interactive orbit camera
        self._camera = OrbitCamera(
            target=(0.0, 0.3, 0.0),
            distance=5.0,
            azimuth=35.0,
            elevation=25.0,
        )

        # Sub-renderers
        self._grid = GridRenderer()
        self._hud = HUD()
        self._aov = AOVRenderer()
        self._shading = ShadingManager()
        self._environment = EnvironmentMap()

        # Multi-light rig
        self._light_rig = LightRig()

        # Selection
        self._selection = SelectionManager()

        # Animation
        self._animator = CameraAnimator(fps=24.0)
        self._last_frame_time = time.time()

        # ComfyUI bridge + AOV exporter
        self._bridge = ComfyBridge()
        self._aov_exporter = AOVExporter(self._bridge, export_interval=0.5)

        # Viewport bridge server (WS for ComfyUI sidebar panel)
        self._bridge_server = BridgeServer()
        self._bridge_server.set_aov_callback(self._save_aovs)

        # Drag-and-drop
        FileDropHandler.setup_drop(self)
        self._drop_overlay = FileDropOverlay()
        self._drop_file = None
        self._drag_valid = False
        self._drag_filename = ""

        # FPS tracking
        self._frame_count = 0
        self._fps_time = time.time()
        self._fps = 0.0

        # Mouse tracking state
        self._last_mouse_x = 0
        self._last_mouse_y = 0
        self._mouse_button = None
        self._alt_held = False
        self._mouse_moved = False

        # File path (USD or mesh)
        self._scene_file = None

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        # Animation timer (16ms ~ 60fps)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.setInterval(16)

    def initializeGL(self):
        try:
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LESS)
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)

            self._program = create_shader_program(VERTEX_SHADER, FRAGMENT_SHADER)

            # Cache uniform locations (avoids per-frame string lookups)
            uniform_names = [
                "uProjection", "uView", "uModel", "uBaseColor",
                "uViewPos", "uAmbientOverride", "uLightCount",
            ]
            for i in range(MAX_LIGHTS):
                uniform_names.append(f"uLightDirs[{i}]")
                uniform_names.append(f"uLightColors[{i}]")
            self._uniform_locs = {
                name: glGetUniformLocation(self._program, name)
                for name in uniform_names
            }

            # Build geometry
            if self._scene_file:
                self._load_scene_file(self._scene_file)
            else:
                self._load_default_geometry()

            # Initialize sub-renderers
            self._grid.setup()
            self._aov.setup(self._width, self._height)
            self._environment.init_gl()

            self._initialized = True
            print("GL initialized: shader program compiled, geometry uploaded.")

            # Start bridge server (non-blocking, runs in Qt event loop)
            self._bridge_server.start()
        except Exception as e:
            print(f"initializeGL FAILED: {e}")
            import traceback
            traceback.print_exc()

    def _load_default_geometry(self):
        """Load the default cube + ground plane scene."""
        vertices, normals, indices = get_cube_vertices()

        # Create MeshData for selection registration
        cube_model = translation_matrix(0.0, 0.5, 0.0)
        cube_md = MeshData(
            name="/World/Cube", vertices=vertices, normals=normals,
            indices=indices, transform=cube_model, color=(0.6, 0.6, 0.6),
        )
        cube_vao, cube_count = self._upload_mesh(vertices, normals, indices)
        self._draw_list.append((cube_vao, cube_count, cube_model, (0.6, 0.6, 0.6)))
        self._mesh_data_list.append(cube_md)
        self._selection.register(cube_md, cube_vao, cube_count)

        # Ground plane: flat scaled cube
        ground_t = translation_matrix(0.0, -0.025, 0.0)
        ground_s = scale_matrix(5.0, 0.05, 5.0)
        ground_model = mat4_multiply(ground_t, ground_s)
        ground_md = MeshData(
            name="/World/Ground", vertices=vertices, normals=normals,
            indices=indices, transform=ground_model, color=(0.35, 0.35, 0.38),
        )
        ground_vao, ground_count = self._upload_mesh(vertices, normals, indices)
        self._draw_list.append((ground_vao, ground_count, ground_model, (0.35, 0.35, 0.38)))
        self._mesh_data_list.append(ground_md)
        self._selection.register(ground_md, ground_vao, ground_count)

    def _load_usd_geometry(self, file_path: str) -> bool:
        """Load geometry from a USD file. Returns True on success."""
        try:
            stage = load_usd_file(file_path)
            meshes = extract_meshes(stage)
            if not meshes:
                print(f"  No meshes found in {file_path}")
                return False

            print(f"  Loaded {len(meshes)} mesh(es) from {file_path}")
            for mesh_data in meshes:
                vao, count = self._upload_mesh(
                    mesh_data.vertices, mesh_data.normals, mesh_data.indices
                )
                self._draw_list.append(
                    (vao, count, mesh_data.transform, mesh_data.color)
                )
                self._mesh_data_list.append(mesh_data)
                self._selection.register(mesh_data, vao, count)
            return True
        except Exception as e:
            print(f"  Failed to load USD file: {e}")
            return False

    def _load_mesh_geometry(self, file_path: str) -> bool:
        """Load geometry from a non-USD mesh file (GLB/OBJ/PLY). Returns True on success."""
        try:
            meshes = load_mesh_file(file_path)
            if not meshes:
                print(f"  No meshes found in {file_path}")
                return False

            print(f"  Loaded {len(meshes)} mesh(es) from {file_path}")
            for mesh_data in meshes:
                vao, count = self._upload_mesh(
                    mesh_data.vertices, mesh_data.normals, mesh_data.indices
                )
                self._draw_list.append(
                    (vao, count, mesh_data.transform, mesh_data.color)
                )
                self._mesh_data_list.append(mesh_data)
                self._selection.register(mesh_data, vao, count)
            return True
        except Exception as e:
            print(f"  Failed to load mesh file: {e}")
            return False

    def _load_scene_file(self, file_path: str):
        """Load a scene from any supported file format."""
        fmt = detect_format(file_path)
        if fmt == "usd":
            if not self._load_usd_geometry(file_path):
                print("  Falling back to default scene.")
                self._load_default_geometry()
        elif fmt in ("glb", "gltf", "obj", "ply"):
            if not self._load_mesh_geometry(file_path):
                print("  Falling back to default scene.")
                self._load_default_geometry()
        else:
            print(f"  Unknown format for {file_path}, falling back to default scene.")
            self._load_default_geometry()

    def _reload_scene(self, file_path: str):
        """Reload the viewport with a new file (e.g. from drag-drop)."""
        self.makeCurrent()
        self._draw_list.clear()
        self._mesh_data_list.clear()
        self._selection.clear()
        self._scene_file = file_path
        self._load_scene_file(file_path)
        self.doneCurrent()
        self._update_title()
        self.update()
        print(f"Scene reloaded: {file_path}")

    def set_scene_file(self, path: str):
        """Set file path to load on initialization."""
        self._scene_file = path

    def _upload_mesh(self, vertices, normals, indices):
        """Upload vertex/normal/index data to GPU, return (VAO, index_count)."""
        # Interleave position + normal
        data = []
        for v, n in zip(vertices, normals):
            data.extend(v)
            data.extend(n)
        data = np.array(data, dtype=np.float32)
        idx = np.array(indices, dtype=np.uint32)

        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)

        vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)

        ebo = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)

        stride = 6 * 4  # 6 floats * 4 bytes
        # Position (location 0)
        glVertexAttribPointer(0, 3, GL_FLOAT, False, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        # Normal (location 1)
        glVertexAttribPointer(1, 3, GL_FLOAT, False, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)

        glBindVertexArray(0)
        return vao, len(indices)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if not self._initialized:
            return

        # -- FPS tracking --
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._fps_time
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_time = now

        # -- Camera matrices --
        cam = self._camera
        aspect = self._width / max(self._height, 1)
        proj = cam.projection_matrix(aspect)
        view = look_at(cam.eye, tuple(cam.target), cam.up)

        # -- Environment background (draws before scene, no depth write) --
        self._environment.draw(view, proj)

        # -- Draw grid (behind scene geometry) --
        self._grid.draw(view, proj)

        # -- Draw scene geometry with shading mode --
        shading = self._shading
        unlit = shading.get_unlit_overrides()
        ambient_override = unlit.get("ambient", 0.0)

        glUseProgram(self._program)

        # Use cached uniform locations (no per-frame string lookups)
        uloc = self._uniform_locs
        proj_loc = uloc["uProjection"]
        view_loc = uloc["uView"]
        model_loc = uloc["uModel"]
        color_loc = uloc["uBaseColor"]
        viewpos_loc = uloc["uViewPos"]
        ambient_loc = uloc["uAmbientOverride"]
        light_count_loc = uloc["uLightCount"]

        glUniformMatrix4fv(proj_loc, 1, False, (ctypes.c_float * 16)(*proj))
        glUniformMatrix4fv(view_loc, 1, False, (ctypes.c_float * 16)(*view))
        glUniform3f(viewpos_loc, *cam.eye)
        glUniform1f(ambient_loc, ambient_override)

        # Multi-light uniforms from the light rig
        light_data = self._light_rig.get_uniform_data()
        light_count = light_data["uLightCount"]
        glUniform1i(light_count_loc, light_count)
        if light_count > 0:
            dirs = light_data["uLightDirs"]
            colors = light_data["uLightColors"]
            # Pad to MAX_LIGHTS * 3 floats
            dirs_padded = dirs + [0.0] * (MAX_LIGHTS * 3 - len(dirs))
            colors_padded = colors + [0.0] * (MAX_LIGHTS * 3 - len(colors))
            for i in range(light_count):
                glUniform3f(uloc[f"uLightDirs[{i}]"], dirs_padded[i*3], dirs_padded[i*3+1], dirs_padded[i*3+2])
                glUniform3f(uloc[f"uLightColors[{i}]"], colors_padded[i*3], colors_padded[i*3+1], colors_padded[i*3+2])

        # Primary draw pass
        shading.apply_pre_draw()
        self._draw_scene(model_loc, color_loc)
        shading.apply_post_draw()

        # Selection highlight (wireframe overlay on selected object)
        selected = self._selection.get_selected()
        if selected is not None:
            from OpenGL.GL import GL_LINE, GL_FILL, GL_FRONT_AND_BACK, glPolygonMode
            from OpenGL.GL import GL_POLYGON_OFFSET_LINE, glPolygonOffset, glDisable as glDisable2, glEnable as glEnable2
            hl_color = get_highlight_color()
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            glEnable2(GL_POLYGON_OFFSET_LINE)
            glPolygonOffset(-1.0, -1.0)
            glUniform1f(ambient_loc, 1.0)  # Unlit highlight
            glUniformMatrix4fv(model_loc, 1, False, (ctypes.c_float * 16)(*selected.model_matrix))
            glUniform3f(color_loc, *hl_color)
            glBindVertexArray(selected.vao)
            glDrawElements(GL_TRIANGLES, selected.index_count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
            glPolygonOffset(0.0, 0.0)
            glDisable2(GL_POLYGON_OFFSET_LINE)
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            glUniform1f(ambient_loc, ambient_override)  # Restore

        # Wireframe overlay (second pass for WIREFRAME_ON_SHADED)
        if shading.needs_second_pass:
            shading.apply_wireframe_overlay_state()
            glUniform1f(ambient_loc, 1.0)  # Unlit wireframe
            wc = shading.wireframe_color
            for vao, index_count, model, _color in self._draw_list:
                glUniformMatrix4fv(model_loc, 1, False, (ctypes.c_float * 16)(*model))
                glUniform3f(color_loc, *wc)
                glBindVertexArray(vao)
                glDrawElements(GL_TRIANGLES, index_count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
            shading.restore_wireframe_overlay_state()

        glUseProgram(0)

        # -- QPainter overlays (HUD + drag feedback) --
        painter = QPainter(self)
        if self._hud.enabled:
            camera_info = self._hud.build_camera_info(self._camera)
            camera_info["shading"] = shading.mode_name
            camera_info["bridge"] = self._bridge.status
            ws_count = self._bridge_server.client_count
            if ws_count > 0:
                camera_info["bridge"] += f" | WS:{ws_count}"
            camera_info["lights"] = self._light_rig.preset_name
            camera_info["environment"] = self._environment.mode
            selected_obj = self._selection.get_selected()
            camera_info["selection"] = selected_obj.name if selected_obj else "None"
            if self._animator.is_playing:
                camera_info["animation"] = f"{self._animator.mode_name} F{self._animator.current_frame}"
            self._hud.draw(painter, self._width, self._height, camera_info, self._fps)
        if self._drag_filename:
            self._drop_overlay.draw_drag_overlay(
                painter, self._width, self._height,
                self._drag_filename, self._drag_valid,
            )
        painter.end()

        # Depth AOV verification -- deferred to allow framebuffer to settle
        if not self._depth_verified:
            self._depth_verified = True
            QTimer.singleShot(500, self._deferred_depth_verify)

    def _draw_scene(self, model_loc, color_loc):
        """Draw all scene geometry (used by primary pass and AOV callbacks)."""
        for vao, index_count, model, color in self._draw_list:
            glUniformMatrix4fv(model_loc, 1, False, (ctypes.c_float * 16)(*model))
            glUniform3f(color_loc, *color)
            glBindVertexArray(vao)
            glDrawElements(GL_TRIANGLES, index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

    def _draw_scene_for_aov(self, program):
        """Callback for AOV renderer: draw all scene geometry with a given shader program."""
        cam = self._camera
        aspect = self._width / max(self._height, 1)
        proj = cam.projection_matrix(aspect)
        view = look_at(cam.eye, tuple(cam.target), cam.up)

        proj_loc = glGetUniformLocation(program, "uProjection")
        view_loc = glGetUniformLocation(program, "uView")
        model_loc = glGetUniformLocation(program, "uModel")

        glUniformMatrix4fv(proj_loc, 1, False, (ctypes.c_float * 16)(*proj))
        glUniformMatrix4fv(view_loc, 1, False, (ctypes.c_float * 16)(*view))

        for vao, index_count, model, _color in self._draw_list:
            glUniformMatrix4fv(model_loc, 1, False, (ctypes.c_float * 16)(*model))
            glBindVertexArray(vao)
            glDrawElements(GL_TRIANGLES, index_count, GL_UNSIGNED_INT, None)

        glBindVertexArray(0)

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _on_anim_tick(self):
        """Timer callback for animation updates."""
        now = time.time()
        dt = now - self._last_frame_time
        self._last_frame_time = now
        self._animator.update(self._camera, dt)
        self._send_camera_to_bridge()
        self.update()

    def _toggle_turntable(self):
        """Toggle turntable animation on/off."""
        if self._animator.is_playing and self._animator.mode == AnimationMode.TURNTABLE:
            self._animator.stop()
            self._anim_timer.stop()
            print("Turntable: stopped")
        else:
            self._animator.start_turntable(camera=self._camera)
            self._last_frame_time = time.time()
            self._anim_timer.start()
            print("Turntable: started (36 deg/s)")

    # ------------------------------------------------------------------
    # AOV + Camera export
    # ------------------------------------------------------------------

    def _save_aovs(self):
        """Save depth + normal AOV passes to PNG files."""
        self.makeCurrent()
        try:
            if self._aov.width != self._width or self._aov.height != self._height:
                self._aov.setup(self._width, self._height)

            near = self._camera.near
            far = self._camera.far

            self._aov.save_depth_png("depth_aov.png", self._draw_scene_for_aov, near, far)
            self._aov.save_normal_png("normal_aov.png", self._draw_scene_for_aov)

            print(f"AOVs saved: depth_aov.png, normal_aov.png ({self._width}x{self._height})")

            # Broadcast AOV paths to WS panel clients
            if self._bridge_server.is_running:
                import os
                self._bridge_server.broadcast_aov(
                    {
                        "depth": os.path.abspath("depth_aov.png"),
                        "normal": os.path.abspath("normal_aov.png"),
                    },
                    (self._width, self._height),
                )

            # Also export to bridge if connected
            if self._bridge.is_connected:
                results = self._aov_exporter.export_all(self._aov)
                if any(results.values()):
                    print(f"AOVs sent to ComfyUI: {results}")
        except Exception as e:
            print(f"AOV save failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.doneCurrent()

    def _export_camera_json(self):
        """Export camera state as LOAD3D_CAMERA JSON."""
        camera_dict = self._camera.to_load3d_camera()
        path = "camera_export.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(camera_dict, f, indent=2, sort_keys=True)
        print(f"Camera exported: {path}")
        print(f"  Sensor: {self._camera.sensor_name} | Lens: {self._camera.lens_name}")
        print(f"  Position: {camera_dict['position']}")
        print(f"  Target: {camera_dict['target']}")

    # ------------------------------------------------------------------
    # ComfyUI bridge
    # ------------------------------------------------------------------

    def _toggle_bridge(self):
        """Toggle the ComfyUI bridge connection."""
        if self._bridge.is_connected:
            self._bridge.disconnect()
            print("ComfyUI bridge: disconnected")
        else:
            print("ComfyUI bridge: connecting...")
            if self._bridge.connect():
                print(f"ComfyUI bridge: {self._bridge.status}")
            else:
                print("ComfyUI bridge: ComfyUI not reachable (will retry on next send)")

    def _send_camera_to_bridge(self):
        """Send current camera state to ComfyUI bridge and WS panel clients."""
        camera_dict = self._camera.to_load3d_camera()

        # Legacy REST bridge
        if self._bridge.is_connected:
            self._bridge.send_viewport_state(camera_dict, self._width, self._height)

        # WS bridge server (broadcasts to panel clients + writes camera_state.json)
        if self._bridge_server.is_running:
            self._bridge_server.broadcast_camera(camera_dict)

    # ------------------------------------------------------------------
    # Depth verification
    # ------------------------------------------------------------------

    def _deferred_depth_verify(self):
        """Trigger depth readback after framebuffer is fully rendered."""
        self.makeCurrent()
        self._verify_depth()
        self.doneCurrent()

    def _verify_depth(self):
        """Read back the GL depth buffer and report statistics."""
        w, h = self._width, self._height
        try:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, self.defaultFramebufferObject())
            depth = glReadPixels(0, 0, w, h, GL_DEPTH_COMPONENT, GL_FLOAT)
            depth_arr = np.frombuffer(depth, dtype=np.float32)

            if len(depth_arr) == 0:
                print("Depth AOV: WARNING -- empty buffer")
                return

            d_min = float(depth_arr.min())
            d_max = float(depth_arr.max())
            total = len(depth_arr)
            near_geo = int(np.count_nonzero(depth_arr < 0.999))
            print(f"Depth AOV: min={d_min:.4f}, max={d_max:.4f}, "
                  f"geometry pixels={near_geo}/{total}, "
                  f"background pixels={total - near_geo}/{total} "
                  f"({'PASS' if near_geo > 0 else 'FAIL -- no geometry in depth buffer'})")
        except Exception as e:
            print(f"Depth AOV: readback failed ({e})")

    # ------------------------------------------------------------------
    # Input handling -- DCC-standard orbit/pan/dolly
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        self._last_mouse_x = event.position().x()
        self._last_mouse_y = event.position().y()
        self._mouse_button = event.button()
        self._alt_held = bool(event.modifiers() & Qt.AltModifier)
        self._mouse_moved = False
        event.accept()

    def mouseReleaseEvent(self, event):
        # Click-to-select (only if mouse didn't move, no Alt, left button)
        if (
            not self._mouse_moved
            and not self._alt_held
            and event.button() == Qt.LeftButton
        ):
            cam = self._camera
            aspect = self._width / max(self._height, 1)
            proj = cam.projection_matrix(aspect)
            view = look_at(cam.eye, tuple(cam.target), cam.up)
            hit = self._selection.pick(
                event.position().x(), event.position().y(),
                self._width, self._height, view, proj,
            )
            if hit:
                self._selection.select(hit.id)
                print(f"Selected: {hit.name}")
            else:
                self._selection.select(None)
            self.update()

        self._mouse_button = None
        # Send camera to bridge after orbit/pan/dolly ends
        self._send_camera_to_bridge()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._mouse_button is None:
            return

        x = event.position().x()
        y = event.position().y()
        dx = x - self._last_mouse_x
        dy = y - self._last_mouse_y
        self._last_mouse_x = x
        self._last_mouse_y = y

        if abs(dx) > 2 or abs(dy) > 2:
            self._mouse_moved = True

        alt = self._alt_held or bool(event.modifiers() & Qt.AltModifier)

        if alt and self._mouse_button == Qt.LeftButton:
            self._camera.orbit(dx, dy)
            self.update()
        elif alt and self._mouse_button == Qt.MiddleButton:
            self._camera.pan(dx, dy)
            self.update()
        elif alt and self._mouse_button == Qt.RightButton:
            self._camera.dolly(dy * self._camera.dolly_speed)
            self.update()

        event.accept()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self._camera.dolly_scroll(steps)
        self._send_camera_to_bridge()
        self.update()
        event.accept()

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        path = FileDropHandler.validate_drop(event)
        if path:
            event.acceptProposedAction()
            self._drop_file = path
            self._drag_valid = True
            self._drag_filename = os.path.basename(path)
        else:
            event.acceptProposedAction()
            self._drag_valid = False
            self._drag_filename = FileDropHandler.extract_filename(event) or ""
        self.update()

    def dragLeaveEvent(self, event):
        self._drop_file = None
        self._drag_valid = False
        self._drag_filename = ""
        self.update()

    def dropEvent(self, event):
        if self._drop_file:
            self._reload_scene(self._drop_file)
        self._drop_file = None
        self._drag_valid = False
        self._drag_filename = ""
        self.update()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    # Camera preset map: key -> (preset_id or None, label)
    _CAMERA_PRESETS = {
        Qt.Key_0: (None, "Simple FOV 45deg"),
        Qt.Key_1: ("alexa35_cooke_ana_40", "ARRI Alexa 35 + Cooke Ana 40mm"),
        Qt.Key_2: ("vraptor_atlas_65", "RED V-RAPTOR + Atlas Orion 65mm"),
        Qt.Key_3: ("venice2_cooke_s7i_50", "Sony VENICE 2 + Cooke S7/i 50mm"),
        Qt.Key_4: ("alexa35_s35_cooke_s7i_25", "ARRI Alexa 35 S35 + Cooke S7/i 25mm"),
    }

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_F:
            self._camera.frame_scene()
            self._send_camera_to_bridge()
            self.update()
        elif key == Qt.Key_H:
            self._hud.toggle()
            self.update()
        elif key == Qt.Key_W:
            self._shading.cycle()
            print(f"Shading: {self._shading.mode_name}")
            self.update()
        elif key == Qt.Key_B:
            self._toggle_bridge()
            self.update()
        elif key == Qt.Key_G:
            name = self._light_rig.cycle_preset()
            print(f"Lighting: {name}")
            self.update()
        elif key == Qt.Key_T:
            self._toggle_turntable()
        elif key == Qt.Key_E:
            mode = self._environment.cycle_mode()
            print(f"Environment: {mode}")
            self.update()
        elif key == Qt.Key_Tab:
            self._selection.cycle_selection()
            sel = self._selection.get_selected()
            if sel:
                print(f"Selected: {sel.name}")
            self.update()
        elif key == Qt.Key_Escape:
            self._selection.select(None)
            if self._animator.is_playing:
                self._animator.stop()
                self._anim_timer.stop()
                print("Animation stopped")
            self.update()
        elif key == Qt.Key_P:
            self._save_aovs()
        elif key == Qt.Key_L:
            self._export_camera_json()
        elif key in self._CAMERA_PRESETS:
            preset_id, label = self._CAMERA_PRESETS[key]
            if preset_id is None:
                self._camera.clear_projection()
            else:
                try:
                    proj = preset_from_database(preset_id)
                    self._camera.set_projection(proj)
                except Exception as e:
                    print(f"Could not load preset: {e}")
                    return
            print(f"Camera: {label}  [{self._camera.sensor_name} | {self._camera.lens_name}]")
            self._send_camera_to_bridge()
            self._update_title()
            self.update()
        event.accept()

    def _update_title(self):
        """Update window title with current camera info."""
        parent = self.parentWidget()
        if parent is not None:
            cam = self._camera
            title = f"CarWash-2 -- {cam.sensor_name} | {cam.lens_name}"
            parent.setWindowTitle(title)

    def resizeGL(self, w, h):
        self._width = w
        self._height = h
        glViewport(0, 0, w, h)

    def cleanup_gl(self):
        """Release GL resources and stop background services."""
        # Stop animation timer
        if self._anim_timer.isActive():
            self._anim_timer.stop()

        # Stop bridge server
        if self._bridge_server.is_running:
            try:
                self._bridge_server.stop()
            except Exception:
                pass

        # Disconnect ComfyUI bridge
        if self._bridge.is_connected:
            try:
                self._bridge.disconnect()
            except Exception:
                pass

        # Cleanup sub-renderers that have cleanup methods
        self.makeCurrent()
        try:
            self._grid.cleanup()
            self._environment.cleanup()
            self._aov.cleanup()
        except Exception:
            pass
        finally:
            self.doneCurrent()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, stage, scene_file=None):
        super().__init__()
        self.setWindowTitle("CarWash-2 -- Storm Viewport")
        self.resize(800, 600)

        self._viewport = StormViewport(stage, self)
        if scene_file:
            self._viewport.set_scene_file(scene_file)
        self.setCentralWidget(self._viewport)

    def closeEvent(self, event):
        """Clean up GL resources and background services on window close."""
        self._viewport.cleanup_gl()
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Set OpenGL surface format before creating QApplication
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    # MSAA disabled -- enables direct depth buffer readback.
    fmt.setSamples(0)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)

    # Check for file argument (USD, GLB, OBJ, PLY)
    scene_file = None
    if len(sys.argv) > 1:
        scene_file = sys.argv[1]
        print(f"Loading scene file: {scene_file}")

    # Build USD stage
    print("Building USD stage...")
    stage = create_default_stage()
    print(f"Stage created: {stage.GetRootLayer().GetDisplayName()}")

    # Print stage contents
    for prim in stage.Traverse():
        print(f"  {prim.GetPath()} [{prim.GetTypeName()}]")

    # Launch viewport
    window = MainWindow(stage, scene_file=scene_file)
    window.show()

    print("\nViewport open. Close the window to exit.")
    print("Controls: Alt+LMB=Orbit  Alt+MMB=Pan  Scroll=Zoom  F=Frame")
    print("          0-4=Camera Presets  H=Toggle HUD  P=Save AOVs  L=Export Camera")
    print("          W=Cycle Shading  B=Toggle ComfyUI Bridge  G=Cycle Lights")
    print("          T=Turntable  E=Cycle Environment  Tab=Cycle Selection")
    print("          Click=Select  Esc=Deselect/Stop")
    print("          Drag-drop USD/GLB/OBJ/PLY files to load")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
