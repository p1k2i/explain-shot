"""Render the Lightshot-style CaptureOverlay to a PNG.

We fake a "desktop" pixmap (real captures use ImageGrab), pre-populate a
selection so the toolbox is visible, and add a couple of annotations."""

import os, sys, tempfile
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from explainshot.ui.overlay.capture_overlay import (
    CaptureOverlay, TOOL_RECT, TOOL_ARROW, _Op,
)


def make_desktop(width: int = 1600, height: int = 900) -> QPixmap:
    pm = QPixmap(width, height)
    pm.fill(QColor("#0f1a2b"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QColor("#f5f5f5"))
    p.setFont(QFont("Segoe UI", 44, QFont.Weight.Bold))
    p.drawText(pm.rect().adjusted(0, -80, 0, 0), Qt.AlignmentFlag.AlignCenter, "Faux desktop")
    p.setFont(QFont("Segoe UI", 14))
    p.setPen(QColor("#c0c0c0"))
    p.drawText(pm.rect().adjusted(0, 60, 0, 0), Qt.AlignmentFlag.AlignCenter,
               "The overlay dims the desktop and cuts a bright window through the selection.")
    p.end()
    return pm


desktop = make_desktop()
overlay = CaptureOverlay(desktop, accent="#0067c0")
overlay.resize(desktop.size())
overlay._geometry_origin = overlay.rect().topLeft()

# Simulate a selection covering the middle of the "desktop"
sel = QRect(320, 220, 900, 440)
overlay._selection = sel

# Pre-populate two annotations so the toolbox impact shows in the render
overlay._ops.append(
    _Op(tool=TOOL_RECT, color=QColor("#ff5252"), width=3,
        start=QPointF(420, 300), end=QPointF(680, 420))
)
overlay._ops.append(
    _Op(tool=TOOL_ARROW, color=QColor("#4dd0e1"), width=4,
        start=QPointF(760, 320), end=QPointF(1080, 500))
)

overlay._enter_editing()
overlay.show()
for _ in range(4):
    app.processEvents()
overlay.grab().save("scratchpad/overlay_lightshot.png", "PNG")
print("saved scratchpad/overlay_lightshot.png")
