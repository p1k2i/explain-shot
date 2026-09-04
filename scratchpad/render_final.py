"""Render the current gallery to a PNG, seeded with a screenshot + a chat
that contains a system-error row, so the fixes are visible."""

import os, sys, tempfile, asyncio
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

from PIL import Image, ImageDraw
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
import qasync
loop = qasync.QEventLoop(app); asyncio.set_event_loop(loop)

from explainshot.config.settings import load_settings
from explainshot.core.database import Database
from explainshot.core.signals import AppSignals
from explainshot.capture.screenshot import ScreenshotService
from explainshot.capture.thumbnails import ThumbnailCache
from explainshot.presets.manager import PresetManager
from explainshot.ai.history import ChatHistory, MessageNode
from explainshot.ai.controller import ChatController
from explainshot.ai.provider import AIProvider
from explainshot.ui.theme import Theme, apply_theme
from explainshot.ui.gallery import GalleryWindow

settings = load_settings()
apply_theme(app, Theme.resolve(settings.ui.theme, settings.ui.accent))

db = Database()
signals = AppSignals()
scrs = ScreenshotService(db, settings.screenshot, settings.resolved_screenshot_dir(), signals)

# Seed a screenshot on disk so the panel is non-empty.
scratch = os.path.join(tempfile.mkdtemp(), "seed")
os.makedirs(scratch, exist_ok=True)
img = Image.new("RGB", (528, 168), "#0067c0")
ImageDraw.Draw(img).text((10, 60), "captured region 528x168", fill="white")
path = os.path.join(scratch, "seed_0.png")
img.save(path)
from pathlib import Path
scrs.import_existing(Path(path))

history = ChatHistory(db)
chat = ChatController(history, lambda: AIProvider(settings.ai.base_url, model=settings.ai.model))

gw = GalleryWindow(
    settings=settings, signals=signals, db=db,
    screenshots=scrs, thumbnails=ThumbnailCache(size=settings.ui.thumbnail_px),
    presets=PresetManager(db, signals), history=history, chat=chat,
)
gw.resize(1400, 860)
gw.show()

# Select the first screenshot to populate the context row + enable chat.
records = scrs.list_recent(limit=1)
if records:
    gw.screenshots_panel.select(records[0].id)
    # Simulate a completed conversation + one system error at the end
    history.append_root(records[0].id, "user", "What is this screenshot?")
    history.append_root(records[0].id, "assistant", "It's a blue rectangle with a caption.")
    gw._refresh_transcript()
    chat.add_notice(
        records[0].id, "error",
        "Connection to the model server failed: connection refused. Check your AI provider settings.",
    )
    gw.chat_panel.set_status(gw.chat_panel.STATUS_ERROR)

for _ in range(5):
    app.processEvents()
gw.grab().save("scratchpad/gallery_final.png", "PNG")
print("saved scratchpad/gallery_final.png")
