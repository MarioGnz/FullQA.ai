"""
screens.py — Capture-target resolution (monitors + windows) and frame helpers.

This module centralises everything about *where* to capture so both the
event-driven capture (capture.py) and the live smart watcher (watcher.py)
agree on the target.

A "target" is a small dict the UI builds and hands back to the capture layer:

    {"kind": "active"}                         # monitor under the cursor (auto)
    {"kind": "all"}                            # whole virtual desktop
    {"kind": "monitor", "index": 2}            # a specific mss monitor index
    {"kind": "window", "hwnd": 12345,
     "title": "Chrome"}                        # a specific top-level window

``resolve_bbox(target)`` turns any of those into an mss-style region
``{"left", "top", "width", "height"}`` that is re-evaluated *every* capture,
so "active monitor" follows the cursor and "window" follows the window as it
moves. Window enumeration is Windows-only (via ctypes); on other platforms the
window list is empty and everything falls back to monitors.
"""

from __future__ import annotations

import sys
import threading

from mss import mss as _MssClass

_IS_WIN = sys.platform.startswith("win")


# ──────────────────────────────────────────────────────────────────────────
# Monitors (cross-platform via mss)
# ──────────────────────────────────────────────────────────────────────────

def _virtual_bbox() -> dict:
    """The full virtual desktop spanning every monitor (mss monitors[0])."""
    with _MssClass() as sct:
        m = sct.monitors[0]
    return {"left": m["left"], "top": m["top"],
            "width": m["width"], "height": m["height"]}


def list_monitors() -> list[dict]:
    """Return one entry per physical monitor (mss index >= 1)."""
    out: list[dict] = []
    with _MssClass() as sct:
        mons = sct.monitors
    for i, m in enumerate(mons):
        if i == 0:
            continue  # index 0 is the combined virtual screen
        out.append({
            "index": i,
            "primary": bool(m.get("is_primary")),
            "left": m["left"], "top": m["top"],
            "width": m["width"], "height": m["height"],
        })
    return out


def _bbox_of_monitor(index: int) -> dict:
    with _MssClass() as sct:
        mons = sct.monitors
    if 0 <= index < len(mons):
        m = mons[index]
        return {"left": m["left"], "top": m["top"],
                "width": m["width"], "height": m["height"]}
    return _virtual_bbox()


# ──────────────────────────────────────────────────────────────────────────
# Cursor / active monitor
# ──────────────────────────────────────────────────────────────────────────

def cursor_pos() -> tuple[int, int] | None:
    """Current absolute cursor position, or None if unavailable."""
    if _IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return int(pt.x), int(pt.y)
        except Exception:
            return None
    return None


def monitor_at(x: int, y: int) -> dict:
    """Return the bbox of the monitor that contains point (x, y)."""
    for m in list_monitors():
        if (m["left"] <= x < m["left"] + m["width"]
                and m["top"] <= y < m["top"] + m["height"]):
            return {"left": m["left"], "top": m["top"],
                    "width": m["width"], "height": m["height"]}
    # Fall back to the primary monitor, then the virtual desktop.
    for m in list_monitors():
        if m["primary"]:
            return {"left": m["left"], "top": m["top"],
                    "width": m["width"], "height": m["height"]}
    return _virtual_bbox()


def _active_bbox(hint: tuple[int, int] | None = None) -> dict:
    """Monitor under the cursor (or under ``hint`` if the cursor is unknown)."""
    pos = cursor_pos() or hint
    if pos is None:
        return _virtual_bbox()
    return monitor_at(pos[0], pos[1])


# ──────────────────────────────────────────────────────────────────────────
# Windows (Windows-only, via ctypes — no extra dependency)
# ──────────────────────────────────────────────────────────────────────────

def list_windows() -> list[dict]:
    """Return visible, titled, top-level windows: {hwnd, title, bbox...}.

    Empty on non-Windows platforms.
    """
    if not _IS_WIN:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    out: list[dict] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _is_cloaked(hwnd) -> bool:
        # Skip cloaked windows (e.g. background UWP apps) when DWM is available.
        try:
            DWMWA_CLOAKED = 14
            val = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd), DWMWA_CLOAKED,
                ctypes.byref(val), ctypes.sizeof(val))
            return val.value != 0
        except Exception:
            return False

    def _cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title:
                return True
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w < 200 or h < 120:           # ignore tiny/utility windows
                return True
            if _is_cloaked(hwnd):
                return True
            out.append({
                "hwnd": int(hwnd),
                "title": title,
                "left": rect.left, "top": rect.top, "width": w, "height": h,
            })
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        return []
    return out


def _window_bbox(hwnd: int) -> dict | None:
    """Live screen rectangle of a window (follows it as it moves/resizes)."""
    if not _IS_WIN or not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd),
                                                  ctypes.byref(rect)):
            return None
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        return {"left": rect.left, "top": rect.top, "width": w, "height": h}
    except Exception:
        return None


def foreground_window() -> dict | None:
    """The currently focused top-level window, if any (Windows-only)."""
    if not _IS_WIN:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        bbox = _window_bbox(int(hwnd))
        if bbox is None:
            return None
        bbox["hwnd"] = int(hwnd)
        bbox["title"] = buf.value.strip()
        return bbox
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────
# Target resolution
# ──────────────────────────────────────────────────────────────────────────

def _clamp_to_virtual(bbox: dict) -> dict:
    """Clamp a region to the virtual desktop so mss never grabs out of bounds."""
    v = _virtual_bbox()
    left = max(v["left"], bbox["left"])
    top = max(v["top"], bbox["top"])
    right = min(v["left"] + v["width"], bbox["left"] + bbox["width"])
    bottom = min(v["top"] + v["height"], bbox["top"] + bbox["height"])
    w, h = max(1, right - left), max(1, bottom - top)
    return {"left": left, "top": top, "width": w, "height": h}


def resolve_bbox(target: dict | None,
                 hint: tuple[int, int] | None = None) -> dict:
    """Resolve a UI target into a concrete mss region, re-evaluated each call."""
    target = target or {"kind": "active"}
    kind = target.get("kind", "active")

    if kind == "all":
        return _virtual_bbox()
    if kind == "monitor":
        return _bbox_of_monitor(int(target.get("index", 1)))
    if kind == "window":
        bbox = _window_bbox(int(target.get("hwnd", 0)))
        if bbox:
            return _clamp_to_virtual(bbox)
        # Window gone — fall back to the active monitor.
        return _active_bbox(hint)
    # default: "active"
    return _active_bbox(hint)


def describe_target(target: dict | None) -> str:
    target = target or {"kind": "active"}
    kind = target.get("kind", "active")
    if kind == "all":
        return "all-monitors"
    if kind == "monitor":
        return f"monitor-{target.get('index')}"
    if kind == "window":
        return f"window:{target.get('title', '')[:40]}"
    return "active-monitor"


# ──────────────────────────────────────────────────────────────────────────
# Grabbing + cheap change detection
# ──────────────────────────────────────────────────────────────────────────

def grab_png(bbox: dict, out_path: str) -> bool:
    """Grab ``bbox`` and write a PNG to ``out_path``. Returns success."""
    try:
        import mss.tools
        with _MssClass() as sct:
            shot = sct.grab(bbox)
            mss.tools.to_png(shot.rgb, shot.size, output=out_path)
        return True
    except Exception:
        return False


def grab_image(bbox: dict):
    """Grab ``bbox`` once and return a PIL RGB Image (or None on failure).

    Grabbing a single frame and deriving both the saved PNG and the dedup
    signature from it avoids capturing the screen twice per event.
    """
    try:
        from PIL import Image
        with _MssClass() as sct:
            shot = sct.grab(bbox)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception:
        return None


def image_signature(img, size: int = 32) -> list[int] | None:
    """Tiny grayscale fingerprint of an already-grabbed PIL image."""
    try:
        from PIL import Image
        return list(img.convert("L").resize((size, size), Image.BILINEAR).getdata())
    except Exception:
        return None


def save_image_png(img, out_path: str) -> bool:
    """Save a PIL image to PNG; returns success."""
    try:
        img.save(out_path, format="PNG")
        return True
    except Exception:
        return False


def grab_signature(bbox: dict, size: int = 32) -> list[int] | None:
    """Return a tiny grayscale fingerprint of ``bbox`` for cheap diffing.

    Downscales the region to ``size``x``size`` grayscale and returns the pixel
    values as a flat list. Comparing two signatures with ``signature_diff``
    gives a 0..1 measure of how much the screen changed — far cheaper than
    decoding/saving a full screenshot or calling a model.
    """
    try:
        from PIL import Image
        with _MssClass() as sct:
            shot = sct.grab(bbox)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        img = img.convert("L").resize((size, size), Image.BILINEAR)
        return list(img.getdata())
    except Exception:
        return None


def signature_diff(a: list[int] | None, b: list[int] | None) -> float:
    """Mean absolute difference of two signatures, normalised to 0..1."""
    if not a or not b or len(a) != len(b):
        return 1.0
    total = sum(abs(x - y) for x, y in zip(a, b))
    return total / (len(a) * 255.0)


class FrameDedup:
    """Thread-safe fingerprint of the LAST SAVED frame.

    Shared between capture sources (event capture + smart watcher) so that,
    whoever saves a screenshot first, the other one skips the near-identical
    frame instead of writing a duplicate file.

    Besides the global 32×32 fingerprint it keeps a small grayscale thumbnail
    of the last saved frame, enabling ``region_changed``: a checkbox toggle
    changes ~20 px on a 2560-px screen — invisible to the global fingerprint —
    but perfectly visible when comparing only the area around the click.
    """

    _THUMB_SCALE = 4          # thumbnail = frame / 4

    def __init__(self, threshold: float = 0.012):
        self.threshold = threshold
        self._lock = threading.Lock()
        self._sig: list[int] | None = None
        self._thumb = None            # PIL "L" image, 1/4 scale
        self._bbox: dict | None = None

    def is_dup(self, sig: list[int] | None, threshold: float | None = None) -> bool:
        if sig is None:
            return False
        thr = self.threshold if threshold is None else threshold
        with self._lock:
            return self._sig is not None and signature_diff(sig, self._sig) < thr

    def update(self, sig: list[int] | None, img=None, bbox: dict | None = None) -> None:
        if sig is None:
            return
        thumb = None
        if img is not None:
            try:
                w = max(1, img.width // self._THUMB_SCALE)
                h = max(1, img.height // self._THUMB_SCALE)
                thumb = img.convert("L").resize((w, h))
            except Exception:
                thumb = None
        with self._lock:
            self._sig = sig
            if thumb is not None:
                self._thumb = thumb
                self._bbox = dict(bbox) if bbox else None

    def region_changed(self, img, bbox: dict, point: tuple[int, int],
                       box_px: int = 420, threshold: float = 0.02) -> bool:
        """Did the area around ``point`` (screen coords) change vs the last
        saved frame? Only comparable when both frames cover the same bbox."""
        with self._lock:
            thumb, prev_bbox = self._thumb, self._bbox
        if thumb is None or prev_bbox is None:
            return False
        if (bbox.get("left"), bbox.get("top"), bbox.get("width"), bbox.get("height")) != \
           (prev_bbox.get("left"), prev_bbox.get("top"), prev_bbox.get("width"), prev_bbox.get("height")):
            return False
        try:
            s = self._THUMB_SCALE
            cur = img.convert("L").resize((thumb.width, thumb.height))
            # Map the screen point into thumbnail coordinates.
            px = (point[0] - bbox["left"]) // s
            py = (point[1] - bbox["top"]) // s
            half = max(8, box_px // (2 * s))
            l = max(0, px - half); t = max(0, py - half)
            r = min(thumb.width, px + half); b = min(thumb.height, py + half)
            if r - l < 4 or b - t < 4:
                return False
            a = list(thumb.crop((l, t, r, b)).getdata())
            c = list(cur.crop((l, t, r, b)).getdata())
            return signature_diff(a, c) > threshold
        except Exception:
            return False
