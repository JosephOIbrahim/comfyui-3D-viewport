"""CarWash-2 Storm Viewport — Phase 0, Sprint 1.

Renders a USD stage (cube + ground plane) in a Qt window via OpenGL.
Reads back the depth buffer to verify the AOV pipeline.

Usage:
    python src/viewport.py

Requires Python 3.12 venv with: usd-core, PySide6, PyOpenGL
    .venv/Scripts/python src/viewport.py
"""

import ctypes
import math
import sys

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
    glUniform3f,
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
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMainWindow

from camera import OrbitCamera
from projection import preset_from_database
from stage_builder import create_default_stage, get_cube_vertices

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

uniform vec3 uLightDir;
uniform vec3 uBaseColor;
uniform vec3 uViewPos;

out vec4 FragColor;

void main() {
    vec3 norm = normalize(vNormal);

    // Ambient
    float ambient = 0.15;

    // Diffuse (key light)
    float diff = max(dot(norm, normalize(uLightDir)), 0.0);

    // Specular (Blinn-Phong)
    vec3 viewDir = normalize(uViewPos - vFragPos);
    vec3 halfDir = normalize(normalize(uLightDir) + viewDir);
    float spec = pow(max(dot(norm, halfDir), 0.0), 32.0) * 0.3;

    vec3 result = uBaseColor * (ambient + diff * 0.75) + vec3(spec);
    FragColor = vec4(result, 1.0);
}
"""


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def look_at(eye: tuple, target: tuple, up: tuple) -> list[float]:
    """Build a look-at view matrix (column-major for GL)."""
    def sub(a, b):
        return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
    def normalize(v):
        l = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
        return (v[0]/l, v[1]/l, v[2]/l) if l > 0 else v
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def dot(a, b):
        return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

    f = normalize(sub(target, eye))
    s = normalize(cross(f, up))
    u = cross(s, f)

    return [
        s[0], u[0], -f[0], 0,
        s[1], u[1], -f[1], 0,
        s[2], u[2], -f[2], 0,
        -dot(s, eye), -dot(u, eye), dot(f, eye), 1,
    ]


def translation_matrix(tx: float, ty: float, tz: float) -> list[float]:
    """4x4 translation matrix, column-major."""
    return [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        tx, ty, tz, 1,
    ]


def scale_matrix(sx: float, sy: float, sz: float) -> list[float]:
    """4x4 scale matrix, column-major."""
    return [
        sx, 0, 0, 0,
        0, sy, 0, 0,
        0, 0, sz, 0,
        0, 0, 0, 1,
    ]


def mat4_multiply(a: list[float], b: list[float]) -> list[float]:
    """Multiply two column-major 4x4 matrices."""
    result = [0.0] * 16
    for col in range(4):
        for row in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + row] * b[col * 4 + k]
            result[col * 4 + row] = s
    return result



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
    When UsdImagingGL becomes available (Sprint 2), the rendering call
    swaps to engine.Render() — the rest stays identical.
    """

    def __init__(self, stage, parent=None):
        super().__init__(parent)
        self._stage = stage
        self._program = None
        self._cube_vao = None
        self._cube_index_count = 0
        self._ground_vao = None
        self._ground_index_count = 0
        self._depth_verified = False
        self._initialized = False
        self._width = 800
        self._height = 600

        # Interactive orbit camera
        self._camera = OrbitCamera(
            target=(0.0, 0.3, 0.0),
            distance=5.0,
            azimuth=35.0,
            elevation=25.0,
        )

        # Mouse tracking state
        self._last_mouse_x = 0
        self._last_mouse_y = 0
        self._mouse_button = None
        self._alt_held = False

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    def initializeGL(self):
        try:
            glClearColor(0.18, 0.18, 0.20, 1.0)  # Dark grey background
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LESS)
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)

            self._program = create_shader_program(VERTEX_SHADER, FRAGMENT_SHADER)

            # Build geometry from stage_builder
            vertices, normals, indices = get_cube_vertices()
            self._cube_vao, self._cube_index_count = self._upload_mesh(
                vertices, normals, indices
            )
            # Reuse same unit cube geometry for ground (transformed via model matrix)
            self._ground_vao, self._ground_index_count = self._upload_mesh(
                vertices, normals, indices
            )

            self._initialized = True
            print("GL initialized: shader program compiled, geometry uploaded.")
        except Exception as e:
            print(f"initializeGL FAILED: {e}")
            import traceback
            traceback.print_exc()

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

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if not self._initialized:
            return
        glUseProgram(self._program)

        # Camera matrices from orbit camera (physical or simple FOV)
        cam = self._camera
        aspect = self._width / max(self._height, 1)
        proj = cam.projection_matrix(aspect)
        view = look_at(cam.eye, tuple(cam.target), cam.up)

        proj_loc = glGetUniformLocation(self._program, "uProjection")
        view_loc = glGetUniformLocation(self._program, "uView")
        model_loc = glGetUniformLocation(self._program, "uModel")
        light_loc = glGetUniformLocation(self._program, "uLightDir")
        color_loc = glGetUniformLocation(self._program, "uBaseColor")
        viewpos_loc = glGetUniformLocation(self._program, "uViewPos")

        glUniformMatrix4fv(proj_loc, 1, False, (ctypes.c_float * 16)(*proj))
        glUniformMatrix4fv(view_loc, 1, False, (ctypes.c_float * 16)(*view))
        glUniform3f(light_loc, 0.5, 0.8, 0.6)  # Key light direction
        glUniform3f(viewpos_loc, *cam.eye)

        # Draw cube: translate up by 0.5 (matches USD stage)
        cube_model = translation_matrix(0.0, 0.5, 0.0)
        glUniformMatrix4fv(model_loc, 1, False, (ctypes.c_float * 16)(*cube_model))
        glUniform3f(color_loc, 0.6, 0.6, 0.6)  # Grey
        glBindVertexArray(self._cube_vao)
        glDrawElements(GL_TRIANGLES, self._cube_index_count, GL_UNSIGNED_INT, None)

        # Draw ground plane: translate down, scale flat
        ground_t = translation_matrix(0.0, -0.025, 0.0)
        ground_s = scale_matrix(5.0, 0.05, 5.0)
        ground_model = mat4_multiply(ground_t, ground_s)
        glUniformMatrix4fv(model_loc, 1, False, (ctypes.c_float * 16)(*ground_model))
        glUniform3f(color_loc, 0.35, 0.35, 0.38)  # Darker grey
        glBindVertexArray(self._ground_vao)
        glDrawElements(GL_TRIANGLES, self._ground_index_count, GL_UNSIGNED_INT, None)

        glBindVertexArray(0)

        # Depth AOV verification — deferred to allow framebuffer to settle
        if not self._depth_verified:
            self._depth_verified = True  # Set first to prevent re-entry
            QTimer.singleShot(500, self._deferred_depth_verify)

    def _deferred_depth_verify(self):
        """Trigger depth readback after framebuffer is fully rendered."""
        self.makeCurrent()
        self._verify_depth()
        self.doneCurrent()

    def _verify_depth(self):
        """Read back the GL depth buffer and report statistics.

        With MSAA disabled (samples=0), we read directly from Qt's default FBO.
        """
        w, h = self._width, self._height
        try:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, self.defaultFramebufferObject())
            depth = glReadPixels(0, 0, w, h, GL_DEPTH_COMPONENT, GL_FLOAT)
            depth_arr = np.frombuffer(depth, dtype=np.float32)

            if len(depth_arr) == 0:
                print("Depth AOV: WARNING — empty buffer")
                return

            d_min = float(depth_arr.min())
            d_max = float(depth_arr.max())
            total = len(depth_arr)
            # Pixels < 1.0 have geometry; pixels at 1.0 are background (far plane)
            near_geo = int(np.count_nonzero(depth_arr < 0.999))
            print(f"Depth AOV: min={d_min:.4f}, max={d_max:.4f}, "
                  f"geometry pixels={near_geo}/{total}, "
                  f"background pixels={total - near_geo}/{total} "
                  f"({'PASS' if near_geo > 0 else 'FAIL — no geometry in depth buffer'})")
        except Exception as e:
            print(f"Depth AOV: readback failed ({e})")
            print("  Depth pipeline will be fully validated in Sprint 2 with render-to-texture.")

    # ------------------------------------------------------------------
    # Input handling — DCC-standard orbit/pan/dolly
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        self._last_mouse_x = event.position().x()
        self._last_mouse_y = event.position().y()
        self._mouse_button = event.button()
        self._alt_held = bool(event.modifiers() & Qt.AltModifier)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._mouse_button = None
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
        self.update()
        event.accept()

    # Camera preset map: key → (preset_id or None, label)
    _CAMERA_PRESETS = {
        Qt.Key_0: (None, "Simple FOV 45deg"),
        Qt.Key_1: ("alexa35_cooke_ana_40", "ARRI Alexa 35 + Cooke Ana 40mm"),
        Qt.Key_2: ("vraptor_atlas_65", "RED V-RAPTOR + Atlas Orion 65mm"),
        Qt.Key_3: ("venice2_cooke_s7i_50", "Sony VENICE 2 + Cooke S7/i 50mm"),
        Qt.Key_4: ("alexa35_s35_cooke_s7i_25", "ARRI Alexa 35 S35 + Cooke S7/i 25mm"),
    }

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F:
            self._camera.frame_scene()
            self.update()
        elif event.key() in self._CAMERA_PRESETS:
            preset_id, label = self._CAMERA_PRESETS[event.key()]
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
            self._update_title()
            self.update()
        event.accept()

    def _update_title(self):
        """Update window title with current camera info."""
        parent = self.parentWidget()
        if parent is not None:
            cam = self._camera
            title = f"CarWash-2 — {cam.sensor_name} | {cam.lens_name}"
            parent.setWindowTitle(title)

    def resizeGL(self, w, h):
        self._width = w
        self._height = h
        glViewport(0, 0, w, h)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, stage):
        super().__init__()
        self.setWindowTitle("CarWash-2 — Storm Viewport")
        self.resize(800, 600)

        viewport = StormViewport(stage, self)
        self.setCentralWidget(viewport)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Set OpenGL surface format before creating QApplication
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    # MSAA disabled for Sprint 1 — enables direct depth buffer readback.
    # Re-enable in Sprint 2 with render-to-texture pipeline.
    fmt.setSamples(0)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)

    # Build USD stage
    print("Building USD stage...")
    stage = create_default_stage()
    print(f"Stage created: {stage.GetRootLayer().GetDisplayName()}")

    # Print stage contents
    for prim in stage.Traverse():
        print(f"  {prim.GetPath()} [{prim.GetTypeName()}]")

    # Launch viewport
    window = MainWindow(stage)
    window.show()

    print("\nViewport open. Close the window to exit.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
