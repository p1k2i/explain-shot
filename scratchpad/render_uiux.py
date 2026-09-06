"""Render the new UI/UX: grid vs list screenshots + collapsed/expanded chat."""
import os, sys, tempfile, asyncio
sys.path.insert(0, os.path.abspath("."))
# Direct assignment (NOT setdefault): APPDATA is always set on Windows, so
# setdefault would fall through to the user's REAL ExplainShot database. Force
# an isolated temp profile so this render never reads or writes real data.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="es_uiux_")

from pathlib import Path
from PIL import Image
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
from explainshot.ai.history import ChatHistory
from explainshot.ai.controller import ChatController
from explainshot.ai.provider import AIProvider
from explainshot.ui.theme import Theme, apply_theme
from explainshot.ui.gallery import GalleryWindow

settings = load_settings()
apply_theme(app, Theme.resolve(settings.ui.theme, settings.ui.accent))
db = Database(); signals = AppSignals()
scrs = ScreenshotService(db, settings.screenshot, settings.resolved_screenshot_dir(), signals)

scratch = tempfile.mkdtemp()
colors = ["#123456", "#8a5a2b", "#2b7a4b", "#6b2b7a", "#7a2b3a", "#2b5a7a", "#5a7a2b"]
recs = []
for i, c in enumerate(colors):
    p = os.path.join(scratch, f"capture_{i:02d}.png")
    Image.new("RGB", (600 + i * 20, 340 + i * 10), c).save(p)
    recs.append(scrs.import_existing(Path(p)))

history = ChatHistory(db)
chat = ChatController(history, lambda: AIProvider(settings.ai.base_url, model=settings.ai.model),
                      context_chars_limit=2000)

rec = recs[0]
long_a = "A detailed answer covering several points about the screenshot. " * 5
# Two summaries in sequence to show the matryoshka collapse.
for i in range(3):
    history.append_root(rec.id, "user", f"Question {i + 1} about this capture?")
    history.append_root(rec.id, "assistant", long_a, model="m")
history.compact_from_tip(rec.id, "First summary: the user asked three questions about "
                         "the capture's colours and dimensions; we established it is a "
                         "solid fill test image.")
for i in range(3, 6):
    history.append_root(rec.id, "user", f"Question {i + 1} about this capture?")
    history.append_root(rec.id, "assistant", long_a, model="m")
history.compact_from_tip(rec.id, "Second summary (folds in the first): across six "
                         "questions we covered the image's colours, size, and how "
                         "ExplainShot renders and stores it.")
history.append_root(rec.id, "user", "Great — one more after the summaries.")
history.append_root(rec.id, "assistant", "Absolutely, ask away.", model="m")

gw = GalleryWindow(
    settings=settings, signals=signals, db=db,
    screenshots=scrs, thumbnails=ThumbnailCache(size=settings.ui.thumbnail_px),
    presets=PresetManager(db, signals), history=history, chat=chat,
)
gw.resize(1400, 880)
gw.show()
gw.screenshots_panel.select(rec.id)


def pump(n=14):
    for _ in range(n):
        app.processEvents()


# 1) Grid view + collapsed chat (newest summary + tail, "show earlier" bar)
pump()
gw.grab().save("scratchpad/uiux_grid_collapsed.png", "PNG")
print("saved scratchpad/uiux_grid_collapsed.png")

# 2) Reveal one matryoshka layer (back to the previous summary)
gw.chat_panel._on_show_earlier()
pump()
gw.grab().save("scratchpad/uiux_chat_layer1.png", "PNG")
print("saved scratchpad/uiux_chat_layer1.png")

# 3) Reveal the earliest segment (fully expanded)
gw.chat_panel._on_show_earlier()
pump()
gw.grab().save("scratchpad/uiux_chat_expanded.png", "PNG")
print("saved scratchpad/uiux_chat_expanded.png")

# 3) List view (click the list toggle) + larger size
gw.screenshots_panel._list_btn.click()
pump()
gw.grab().save("scratchpad/uiux_list.png", "PNG")
print("saved scratchpad/uiux_list.png")

# 4) List view at size L
from explainshot.ui.gallery.screenshots_panel import _SIZE_PRESETS
gw.screenshots_panel._size_btns[_SIZE_PRESETS["L"]].click()
pump()
gw.grab().save("scratchpad/uiux_list_large.png", "PNG")
print("saved scratchpad/uiux_list_large.png")

print("done")
