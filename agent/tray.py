"""
tray.py — Minimal system-tray UI using pystray + Pillow.

Menu items:
  Start Recording   — green dot icon
  Stop Recording    — red dot icon
  Status            — prints current session stats
  Quit              — stops capture and exits

The tray icon is a small coloured circle generated with Pillow;
no external image asset is required.
"""

import threading
from PIL import Image, ImageDraw


# ------------------------------------------------------------------
# Icon factory
# ------------------------------------------------------------------

def _make_icon(active: bool) -> Image.Image:
    """Return a 64×64 RGBA image with a green (active) or red (idle) dot."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (34, 197, 94, 255) if active else (239, 68, 68, 255)   # green / red
    margin = 8
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    return img


# ------------------------------------------------------------------
# TrayApp
# ------------------------------------------------------------------

class TrayApp:
    """
    Runs a system-tray icon.  Callbacks are invoked in daemon threads
    so they must not block the tray event loop.
    """

    def __init__(self, on_start, on_stop, on_status, on_quit):
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_status = on_status
        self._on_quit = on_quit
        self._active = False
        self._icon = None

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _action_start(self, icon, item) -> None:
        if self._active:
            return
        self._active = True
        self._refresh_icon()
        threading.Thread(target=self._on_start, daemon=True).start()

    def _action_stop(self, icon, item) -> None:
        if not self._active:
            return
        self._active = False
        self._refresh_icon()
        threading.Thread(target=self._on_stop, daemon=True).start()

    def _action_status(self, icon, item) -> None:
        threading.Thread(target=self._on_status, daemon=True).start()

    def _action_quit(self, icon, item) -> None:
        if self._active:
            self._active = False
            self._on_stop()
        icon.stop()
        self._on_quit()

    # ------------------------------------------------------------------
    # Icon refresh
    # ------------------------------------------------------------------

    def _refresh_icon(self) -> None:
        if self._icon:
            self._icon.icon = _make_icon(self._active)

    # ------------------------------------------------------------------
    # Run (blocking — call from main thread)
    # ------------------------------------------------------------------

    def run(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("▶  Start Recording", self._action_start),
            pystray.MenuItem("■  Stop Recording",  self._action_stop),
            pystray.MenuItem("ℹ  Status",          self._action_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("✕  Quit",            self._action_quit),
        )
        self._icon = pystray.Icon(
            name="FullQA.ai",
            icon=_make_icon(False),
            title="FullQA.ai",
            menu=menu,
        )
        self._icon.run()
