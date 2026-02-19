"""Drag-and-drop file handler for the 3D viewport.

Adds support for dropping USD, GLB, OBJ, and PLY files onto the
StormViewport widget. Provides visual feedback during the drag via a
translucent overlay drawn with QPainter (same pattern as :mod:`hud`).

Integration in StormViewport
----------------------------

::

    # In StormViewport.__init__:
    FileDropHandler.setup_drop(self)
    self._drop_overlay = FileDropOverlay()
    self._drop_file = None
    self._drag_valid = False
    self._drag_filename = ""

    # In StormViewport.dragEnterEvent:
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

    # In StormViewport.dragLeaveEvent:
    self._drop_file = None
    self._drag_valid = False
    self._drag_filename = ""
    self.update()

    # In StormViewport.dropEvent:
    if self._drop_file:
        self._reload_scene(self._drop_file)
    self._drop_file = None
    self._drag_valid = False
    self._drag_filename = ""
    self.update()

    # In StormViewport.paintGL (after HUD draw, inside QPainter block):
    if self._drag_filename:
        self._drop_overlay.draw_drag_overlay(
            painter, self._width, self._height,
            self._drag_filename, self._drag_valid,
        )
"""

from __future__ import annotations

import os
import re
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QMimeData, Qt, QRectF
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QPainter, QPen


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".usd", ".usdc", ".usda", ".glb", ".gltf", ".obj", ".ply"}
)

_FORMAT_MAP: dict[str, str] = {
    ".usd": "usd",
    ".usdc": "usd",
    ".usda": "usd",
    ".glb": "glb",
    ".gltf": "gltf",
    ".obj": "obj",
    ".ply": "ply",
}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def normalize_path(url_or_path: str) -> str:
    """Convert a Qt URL string or raw filesystem path to a clean path.

    Handles ``file:///C:/Users/...`` URLs that Qt produces on Windows
    when the OS drag-drops a file.  Also handles plain paths and
    percent-encoded characters.

    Parameters
    ----------
    url_or_path:
        Either a ``file://`` URL or a raw filesystem path.

    Returns
    -------
    str
        A normalised absolute path suitable for ``open()`` or USD stage
        loading.
    """
    text = url_or_path.strip()

    if text.startswith("file:///"):
        # On Windows Qt gives file:///C:/path -- urlparse puts "C:/path"
        # in the path component (with a leading slash: "/C:/path").
        parsed = urlparse(text)
        path = unquote(parsed.path)
        # Strip the leading "/" before a Windows drive letter (e.g. /C:/)
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
    elif text.startswith("file://"):
        # Unix-style: file:///home/... already handled above.
        # Bare file://host/path is rare but handle gracefully.
        parsed = urlparse(text)
        path = unquote(parsed.path)
    else:
        path = text

    return os.path.normpath(path)


def detect_format(path: str) -> str:
    """Return the format identifier for a file path.

    Parameters
    ----------
    path:
        Filesystem path (need not exist).

    Returns
    -------
    str
        One of ``"usd"``, ``"glb"``, ``"gltf"``, ``"obj"``, ``"ply"``,
        or ``"unknown"`` if the extension is not recognised.
    """
    _, ext = os.path.splitext(path)
    return _FORMAT_MAP.get(ext.lower(), "unknown")


# ---------------------------------------------------------------------------
# FileDropHandler
# ---------------------------------------------------------------------------

class FileDropHandler:
    """Static helper that adds drag-and-drop file loading to a QWidget.

    This is not meant to be instantiated.  All methods are ``@staticmethod``
    so they can be called from any widget without inheritance.
    """

    @staticmethod
    def setup_drop(widget) -> None:
        """Enable drop acceptance on *widget*.

        Call once during ``__init__`` of the target widget.
        """
        widget.setAcceptDrops(True)

    @staticmethod
    def validate_drop(event: QDragEnterEvent | QDropEvent) -> str | None:
        """Check whether *event* carries a file with a supported extension.

        If the event contains multiple files, only the first is considered.

        Parameters
        ----------
        event:
            A ``QDragEnterEvent`` or ``QDropEvent``.

        Returns
        -------
        str | None
            The normalised filesystem path if the file extension is
            supported, or ``None`` otherwise.
        """
        mime: QMimeData | None = event.mimeData()
        if mime is None:
            return None

        if mime.hasUrls():
            for url in mime.urls():
                raw = url.toLocalFile() or url.toString()
                path = normalize_path(raw)
                _, ext = os.path.splitext(path)
                if ext.lower() in SUPPORTED_EXTENSIONS:
                    return path
            return None

        # Some applications pass plain text paths instead of URLs.
        if mime.hasText():
            raw = mime.text().strip().splitlines()[0] if mime.text() else ""
            if raw:
                path = normalize_path(raw)
                _, ext = os.path.splitext(path)
                if ext.lower() in SUPPORTED_EXTENSIONS:
                    return path

        return None

    @staticmethod
    def extract_filename(event: QDragEnterEvent | QDropEvent) -> str | None:
        """Extract the filename from *event* regardless of validity.

        Used to show the filename in the overlay even when the format
        is unsupported.

        Returns
        -------
        str | None
            The basename of the first dragged file, or ``None`` if no
            filename could be extracted.
        """
        mime: QMimeData | None = event.mimeData()
        if mime is None:
            return None

        if mime.hasUrls():
            for url in mime.urls():
                raw = url.toLocalFile() or url.toString()
                path = normalize_path(raw)
                name = os.path.basename(path)
                if name:
                    return name
            return None

        if mime.hasText():
            raw = mime.text().strip().splitlines()[0] if mime.text() else ""
            if raw:
                return os.path.basename(normalize_path(raw))

        return None


# ---------------------------------------------------------------------------
# FileDropOverlay
# ---------------------------------------------------------------------------

class FileDropOverlay:
    """Visual feedback overlay drawn during a file drag operation.

    Uses :class:`QPainter` following the same pattern as :class:`HUD`.
    """

    def __init__(self, font_size: int = 14) -> None:
        self._font = QFont("Consolas", font_size)
        self._font_small = QFont("Consolas", font_size - 2)

    def draw_drag_overlay(
        self,
        painter: QPainter,
        width: int,
        height: int,
        filename: str,
        valid: bool,
    ) -> None:
        """Draw a semi-transparent overlay indicating drop readiness.

        Parameters
        ----------
        painter:
            An active ``QPainter`` bound to the viewport widget.
        width, height:
            Current viewport dimensions in pixels.
        filename:
            The basename of the file being dragged.
        valid:
            ``True`` if the file has a supported extension.
        """
        painter.setRenderHint(QPainter.Antialiasing)

        # Full-viewport scrim
        scrim = QColor(0, 0, 0, 100) if valid else QColor(60, 0, 0, 100)
        painter.fillRect(QRectF(0, 0, width, height), scrim)

        # Border highlight
        border_color = QColor(120, 180, 255, 180) if valid else QColor(220, 80, 80, 180)
        border_pen = QPen(border_color, 3.0)
        border_pen.setStyle(Qt.DashLine)
        painter.setPen(border_pen)
        inset = 8
        painter.drawRect(QRectF(inset, inset, width - 2 * inset, height - 2 * inset))

        # Centre text
        painter.setFont(self._font)
        if valid:
            label = "Drop to load"
            label_color = QColor(220, 220, 220)
        else:
            label = "Unsupported format"
            label_color = QColor(220, 80, 80)

        fm = painter.fontMetrics()
        label_w = fm.horizontalAdvance(label)
        label_h = fm.height()

        centre_y = height // 2

        painter.setPen(QPen(label_color))
        painter.drawText(
            (width - label_w) // 2, centre_y - label_h // 2, label
        )

        # Filename below the label
        painter.setFont(self._font_small)
        painter.setPen(QPen(QColor(170, 170, 170)))
        fm_small = painter.fontMetrics()
        name_w = fm_small.horizontalAdvance(filename)
        painter.drawText(
            (width - name_w) // 2, centre_y + label_h, filename
        )
