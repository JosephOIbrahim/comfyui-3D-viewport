"""AOV Export — Read FBO textures and send them to ComfyUI as PNG images.

Reads depth and normal AOV framebuffer data from ``AOVRenderer``, encodes
them as PNG bytes (no Pillow dependency), and pushes them through the
``ComfyBridge`` with per-AOV throttling to avoid flooding the network.

Usage::

    from aov_renderer import AOVRenderer
    from comfy_bridge import ComfyBridge
    from aov_export import AOVExporter

    bridge = ComfyBridge()
    bridge.connect()

    aov = AOVRenderer()
    aov.setup(1024, 768)

    exporter = AOVExporter(bridge, export_interval=0.5)

    # After rendering a frame:
    aov.render_depth(draw_fn, near=0.1, far=100.0)
    aov.render_normals(draw_fn)

    results = exporter.export_all(aov)
    # {"depth": True, "normal": True}

The module makes OpenGL calls (``glBindFramebuffer``, ``glReadPixels``) and
must be called from a thread with an active GL context.
"""

from __future__ import annotations

import logging
import time

from png_io import encode_png

from OpenGL.GL import (
    GL_FLOAT,
    GL_FRAMEBUFFER,
    GL_FRAMEBUFFER_BINDING,
    GL_READ_FRAMEBUFFER,
    GL_RGB,
    GL_RGBA,
    GL_UNSIGNED_BYTE,
    glBindFramebuffer,
    glGetIntegerv,
    glReadPixels,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Minimal PNG encoder (struct + zlib, no Pillow)
# ---------------------------------------------------------------------------

def _encode_png(pixels: bytes, width: int, height: int, channels: int) -> bytes:
    """Encode raw pixel data as an in-memory PNG. Thin wrapper over
    :func:`png_io.encode_png`; ``aov_export`` keeps top-to-bottom input
    convention (no flip)."""
    return encode_png(pixels, width, height, channels)


# ---------------------------------------------------------------------------
# FBO pixel readback
# ---------------------------------------------------------------------------

def _read_fbo_pixels(
    fbo_id: int,
    width: int,
    height: int,
    format: str,  # noqa: A002 — shadowing builtin is intentional for API clarity
) -> bytes:
    """Bind an FBO, read its pixels with ``glReadPixels``, and restore the
    previous FBO binding.

    Parameters
    ----------
    fbo_id : int
        OpenGL framebuffer object name to read from.
    width, height : int
        Dimensions of the framebuffer in pixels.
    format : str
        ``"depth"`` — reads ``GL_RGBA`` as ``GL_UNSIGNED_BYTE`` from the
        color attachment (the AOVRenderer writes linearized depth into
        the color attachment, not the hardware depth buffer).
        ``"color"`` — reads ``GL_RGB`` as ``GL_UNSIGNED_BYTE``.

    Returns
    -------
    bytes
        Raw pixel data in **bottom-to-top** row order (OpenGL convention).
        For ``"depth"``: ``width * height * 4`` bytes (RGBA).
        For ``"color"``: ``width * height * 3`` bytes (RGB).

    Raises
    ------
    ValueError
        If *format* is not ``"depth"`` or ``"color"``.
    """
    if format not in ("depth", "color"):
        raise ValueError(f"Unknown pixel format: {format!r}. Use 'depth' or 'color'.")

    # Save and restore the current read-framebuffer binding.
    prev_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo_id)
    try:
        if format == "depth":
            # The depth shader writes linearized depth to the RGBA color
            # attachment, so we read RGBA unsigned bytes.
            data = glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE)
        else:
            data = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
    finally:
        glBindFramebuffer(GL_READ_FRAMEBUFFER, prev_fbo)

    return bytes(data)


# ---------------------------------------------------------------------------
# AOVExporter
# ---------------------------------------------------------------------------

class AOVExporter:
    """Reads AOV framebuffer textures and sends them to ComfyUI as PNG.

    Throttles exports per AOV type so the bridge is not flooded with
    redundant frames.

    Parameters
    ----------
    bridge : ComfyBridge
        An active (or activatable) ComfyUI bridge instance.
    export_interval : float
        Minimum seconds between consecutive exports of the **same** AOV
        type.  Defaults to 0.5 s.
    """

    def __init__(self, bridge, export_interval: float = 0.5) -> None:
        self._bridge = bridge
        self._export_interval = export_interval
        self._enabled = True

        # Per-AOV last-export timestamps for independent throttling.
        self._last_export_time: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Toggle AOV export on or off."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    @property
    def export_interval(self) -> float:
        """Minimum seconds between exports of the same AOV type."""
        return self._export_interval

    @export_interval.setter
    def export_interval(self, value: float) -> None:
        self._export_interval = max(0.0, float(value))

    # ------------------------------------------------------------------
    # Export methods
    # ------------------------------------------------------------------

    def export_depth(self, aov_renderer) -> bool:
        """Read the depth FBO and send it to ComfyUI as a grayscale PNG.

        The depth texture is stored in the AOVRenderer's color attachment
        as linearized depth (near=white, far=black) in the R channel.
        This method reads the RGBA color attachment, extracts the R
        channel, and encodes it as an 8-bit grayscale PNG.

        Parameters
        ----------
        aov_renderer : AOVRenderer
            Must have been set up and had ``render_depth()`` called so
            the FBO contains valid depth data.

        Returns
        -------
        bool
            True if the PNG was sent to the bridge.  False if export is
            disabled, throttled, or the bridge is not connected.
        """
        if not self._can_export("depth", aov_renderer):
            return False

        # Read RGBA pixels from the depth FBO (bottom-to-top).
        raw_rgba = _read_fbo_pixels(
            aov_renderer._fbo,
            aov_renderer.width,
            aov_renderer.height,
            "depth",
        )

        w, h = aov_renderer.width, aov_renderer.height

        # Extract R channel and flip Y to image (top-to-bottom) order.
        grayscale = self._rgba_to_grayscale_flipped(raw_rgba, w, h)

        png_bytes = _encode_png(grayscale, w, h, channels=1)
        ok = self._bridge.send_aov("depth", png_bytes)

        if ok:
            self._last_export_time["depth"] = time.monotonic()
            logger.debug("AOV export: depth (%dx%d) sent", w, h)

        return ok

    def export_normal(self, aov_renderer) -> bool:
        """Read the normal FBO and send it to ComfyUI as an RGB PNG.

        The normal texture is stored in the AOVRenderer's color
        attachment as world-space normals mapped to [0, 1] RGB.

        Parameters
        ----------
        aov_renderer : AOVRenderer
            Must have been set up and had ``render_normals()`` called so
            the FBO contains valid normal data.

        Returns
        -------
        bool
            True if the PNG was sent to the bridge.  False if export is
            disabled, throttled, or the bridge is not connected.
        """
        if not self._can_export("normal", aov_renderer):
            return False

        # Read RGB pixels from the normal FBO (bottom-to-top).
        raw_rgb = _read_fbo_pixels(
            aov_renderer._fbo,
            aov_renderer.width,
            aov_renderer.height,
            "color",
        )

        w, h = aov_renderer.width, aov_renderer.height

        # Flip Y to image (top-to-bottom) order.
        flipped = self._flip_rows(raw_rgb, w, h, channels=3)

        png_bytes = _encode_png(flipped, w, h, channels=3)
        ok = self._bridge.send_aov("normal", png_bytes)

        if ok:
            self._last_export_time["normal"] = time.monotonic()
            logger.debug("AOV export: normal (%dx%d) sent", w, h)

        return ok

    def export_all(self, aov_renderer) -> dict[str, bool]:
        """Export both depth and normal AOVs.

        Parameters
        ----------
        aov_renderer : AOVRenderer
            Must have valid depth and normal data in its FBO.

        Returns
        -------
        dict[str, bool]
            Mapping of AOV name to whether it was successfully sent.
        """
        return {
            "depth": self.export_depth(aov_renderer),
            "normal": self.export_normal(aov_renderer),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _can_export(self, aov_type: str, aov_renderer) -> bool:
        """Check whether an export should proceed (enabled, not throttled,
        renderer ready, bridge alive)."""
        if not self._enabled:
            return False

        if not aov_renderer.is_ready:
            logger.debug("AOV export: renderer not ready, skipping %s", aov_type)
            return False

        if not self._bridge.is_connected:
            logger.debug("AOV export: bridge not connected, skipping %s", aov_type)
            return False

        # Per-AOV throttle check.
        now = time.monotonic()
        last = self._last_export_time.get(aov_type, 0.0)
        if (now - last) < self._export_interval:
            return False

        return True

    @staticmethod
    def _rgba_to_grayscale_flipped(
        raw_rgba: bytes, width: int, height: int
    ) -> bytes:
        """Extract the R channel from RGBA data and flip Y.

        Parameters
        ----------
        raw_rgba : bytes
            RGBA pixel data, ``width * height * 4`` bytes, bottom-to-top.
        width, height : int
            Image dimensions.

        Returns
        -------
        bytes
            Grayscale pixel data, ``width * height`` bytes, top-to-bottom.
        """
        row_stride = width * 4
        out = bytearray(width * height)
        for y in range(height):
            # Source row from bottom (GL convention) -> destination from top.
            src_row = (height - 1 - y) * row_stride
            dst_row = y * width
            for x in range(width):
                out[dst_row + x] = raw_rgba[src_row + x * 4]
        return bytes(out)

    @staticmethod
    def _flip_rows(
        raw: bytes, width: int, height: int, channels: int
    ) -> bytes:
        """Flip pixel data from bottom-to-top to top-to-bottom row order.

        Parameters
        ----------
        raw : bytes
            Pixel data, ``width * height * channels`` bytes, bottom-to-top.
        width, height : int
            Image dimensions.
        channels : int
            Bytes per pixel.

        Returns
        -------
        bytes
            Same data with rows reversed (top-to-bottom).
        """
        row_size = width * channels
        rows = [raw[y * row_size : (y + 1) * row_size] for y in range(height)]
        rows.reverse()
        return b"".join(rows)
