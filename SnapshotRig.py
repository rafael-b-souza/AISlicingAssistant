# Copyright (c) 2026 Rafael
# Multi-angle model snapshots for the AI assistant, extending Cura's own
# cura/Snapshot.py machinery (already used for embedded-thumbnail generation)
# instead of reimplementing the camera/render-pass plumbing.
#
# Snapshot.isometricSnapshot itself is left untouched -- Cura's own thumbnail
# generation must keep using its single hardcoded default view. Everything
# here is a parallel, generalized copy of its approach.

import base64
import os
from typing import List, Optional

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage, QPainter, QColor

from UM.Application import Application
from UM.Logger import Logger
from UM.Math.Matrix import Matrix
from UM.Math.Vector import Vector
from UM.Scene.Camera import Camera
from UM.Scene.SceneNode import SceneNode
from UM.Qt.QtRenderer import QtRenderer

from cura.PreviewPass import PreviewPass
from cura.Snapshot import Snapshot

MAX_RENDER_DISTANCE = Snapshot.MAX_RENDER_DISTANCE

# The 4 sign permutations of the diagonal direction Cura's own
# Snapshot.isometricSnapshot already uses as its single default view --
# gives one shot per "corner" of the model.
_CORNER_DIRECTIONS = [
    Vector(-1, -1, -1).normalized(),
    Vector(1, -1, -1).normalized(),
    Vector(1, -1, 1).normalized(),
    Vector(-1, -1, 1).normalized(),
]

_TOP_DIRECTION = Vector(0, -1, 0).normalized()

_ANGLE_NAMES = ["corner1", "corner2", "corner3", "corner4", "top"]


def _directional_snapshot(width: int, height: int, view_dir: Vector, node: Optional[SceneNode]) -> Optional[QImage]:
    """Same approach as Snapshot.isometricSnapshot, generalized to an
    arbitrary view direction."""
    if node is None:
        node = Application.getInstance().getController().getScene().getRoot()

    bounds = Snapshot.nodeBounds(node)
    if bounds is None:
        Logger.log("w", "[AISlicingAssistant] Nothing on the build plate to render")
        return None

    camera = Camera("ai_snapshot")

    # The cross-product tangent basis degenerates when view_dir is parallel
    # to Unit_Y (straight down/up) -- use a different up hint in that case.
    up_hint = Vector.Unit_Y
    if abs(float(view_dir.dot(Vector.Unit_Y))) > 0.999:
        up_hint = Vector.Unit_Z

    tangent_space_x_direction = view_dir.cross(up_hint).normalized()
    tangent_space_y_direction = tangent_space_x_direction.cross(view_dir).normalized()

    x_points = [p.dot(tangent_space_x_direction) for p in bounds.points]
    y_points = [p.dot(tangent_space_y_direction) for p in bounds.points]
    min_x, max_x = min(x_points), max(x_points)
    min_y, max_y = min(y_points), max(y_points)
    camera_width = max_x - min_x
    camera_height = max_y - min_y

    if camera_width == 0 or camera_height == 0:
        Logger.log("w", "[AISlicingAssistant] Degenerate bounds for snapshot")
        return None

    # increase either width or height to match the aspect ratio of the image
    if camera_width / camera_height > width / height:
        camera_height = camera_width * height / width
    else:
        camera_width = camera_height * width / height

    ortho_matrix = Matrix()
    ortho_matrix.setOrtho(
        -camera_width / 2, camera_width / 2,
        -camera_height / 2, camera_height / 2,
        -MAX_RENDER_DISTANCE, MAX_RENDER_DISTANCE,
    )
    camera.setPerspective(False)
    camera.setProjectionMatrix(ortho_matrix)
    camera.setPosition(bounds.center)
    camera.lookAt(bounds.center + view_dir)

    renderer = QtRenderer()
    render_pass = PreviewPass(width, height, root=node)
    renderer.setViewportSize(width, height)
    renderer.setWindowSize(width, height)
    render_pass.setCamera(camera)
    renderer.addRenderPass(render_pass)
    renderer.beginRendering()
    renderer.render()

    return render_pass.getOutput()


def _composite_on_background(image: QImage, background_color: QColor = QColor(210, 210, 210)) -> QImage:
    """PreviewPass renders with a transparent background. JPEG has no alpha
    channel, and an undefined/black fill outside the model silhouette would
    confuse a vision model about scale and context -- composite onto a flat
    neutral background first."""
    result = QImage(image.size(), QImage.Format.Format_RGB32)
    result.fill(background_color)
    painter = QPainter(result)
    painter.drawImage(0, 0, image)
    painter.end()
    return result


def _image_to_jpeg_base64(image: QImage, quality: int = 85) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG", quality)
    data = bytes(buffer.data())
    buffer.close()
    return base64.b64encode(data).decode("ascii")


def capture_multi_angle(width: int = 512, height: int = 512, node: Optional[SceneNode] = None) -> List[str]:
    """Capture 4 corner views + 1 top-down view of the loaded model. Returns
    base64-encoded JPEG strings, ready to drop into an OpenAI-compatible
    image_url content block ("data:image/jpeg;base64," + this).

    Must be called on the Qt/render thread -- same constraint as Cura's own
    CuraEngineBackend._createSnapshot.
    """
    directions = _CORNER_DIRECTIONS + [_TOP_DIRECTION]
    encoded_images = []
    for direction in directions:
        image = _directional_snapshot(width, height, direction, node)
        if image is None:
            continue
        encoded_images.append(_image_to_jpeg_base64(_composite_on_background(image)))
    return encoded_images


def save_debug_images(directory: str, width: int = 512, height: int = 512, node: Optional[SceneNode] = None) -> List[str]:
    """Debug helper: save the 5 angles as files instead of encoding/sending
    them, so framing can be checked without spending a real API call."""
    directions = _CORNER_DIRECTIONS + [_TOP_DIRECTION]
    saved_paths = []
    for name, direction in zip(_ANGLE_NAMES, directions):
        image = _directional_snapshot(width, height, direction, node)
        if image is None:
            continue
        path = os.path.join(directory, f"snapshot_{name}.jpg")
        _composite_on_background(image).save(path, "JPEG", 85)
        saved_paths.append(path)
    return saved_paths
