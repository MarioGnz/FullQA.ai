"""
capture.py — Cross-platform screen event capture and screenshot logic.

Uses pynput to listen for mouse clicks, scrolls, and key presses.
Screenshots are grabbed from the *chosen capture target* (see screens.py):
the active monitor by default, or a specific monitor / window / the whole
virtual desktop — fixing the old bug where the wrong monitor was captured.

Screenshot policy (event-driven mode):
  - Mouse CLICK → capture the target, but SKIP the write if the frame is
    essentially identical to the last saved one (deduplication).
  - Key presses → DEBOUNCED like scrolls: one screenshot once typing settles,
    instead of one per keystroke. This is the main fix for "too many captures".
  - Scrolls → DEBOUNCED: one screenshot once the wheel settles.

When the live smart watcher (watcher.py) is handling screenshots, this class is
constructed with ``capture_screenshots=False`` so it only records the event
stream (clicks/keys for textual context) and leaves the imagery to the model.
"""

import datetime
import threading
import time

from pynput import mouse, keyboard

import context as uictx
import screens


# Idle time after the last scroll tick before we capture the settled view.
SCROLL_SETTLE_MS = 500
# Idle time after the last keystroke before we capture the settled view.
TYPING_SETTLE_MS = 800
# Two frames whose 0..1 fingerprint difference is below this are treated as the
# same screen — no point saving another near-identical screenshot.
DEDUP_DIFF = 0.012


class EventCapture:
    """Attaches pynput listeners to the OS and writes to the session."""

    def __init__(self, session, target: dict | None = None,
                 capture_screenshots: bool = True, dedup: bool = True,
                 shared_dedup: "screens.FrameDedup | None" = None,
                 scroll_settle_ms: int = SCROLL_SETTLE_MS,
                 typing_settle_ms: int = TYPING_SETTLE_MS):
        self.session = session
        self.target = target or {"kind": "active"}
        self.capture_screenshots = capture_screenshots
        self.dedup = dedup
        self.scroll_settle_ms = scroll_settle_ms
        self.typing_settle_ms = typing_settle_ms

        self._running = False

        # Fingerprint of the last saved frame. When the smart watcher runs
        # alongside, the SAME FrameDedup is shared so click captures and
        # watcher captures never save near-identical frames twice.
        self._dedup = shared_dedup or screens.FrameDedup(DEDUP_DIFF)

        # Scroll debounce state
        self._scroll_lock = threading.Lock()
        self._scroll_timer: threading.Timer | None = None
        self._scroll_ticks = 0
        self._scroll_net_dy = 0
        self._scroll_pos = (0, 0)

        # Typing debounce state
        self._type_lock = threading.Lock()
        self._type_timer: threading.Timer | None = None
        self._type_chars: list[str] = []
        self._type_pos = (0, 0)

        self._mouse_listener: mouse.Listener | None = None
        self._keyboard_listener: keyboard.Listener | None = None

    # ------------------------------------------------------------------
    # Screenshot helper (target-aware + deduplicated)
    # ------------------------------------------------------------------

    def _capture_screenshot(self, label: str, hint: tuple[int, int] | None = None) -> str:
        """Grab the current target once; save unless it duplicates the last one.

        Returns the filename written, or "" when nothing was saved (capture
        disabled, grab failed, or the frame was a near-duplicate).
        """
        if not self.capture_screenshots:
            return ""
        bbox = screens.resolve_bbox(self.target, hint)
        img = screens.grab_image(bbox)
        if img is None:
            return ""

        if self.dedup:
            sig = screens.image_signature(img)
            if self._dedup.is_dup(sig, DEDUP_DIFF):
                # Globally identical — but a small control (checkbox, toggle)
                # may have changed right where the user clicked. Check the
                # click region before discarding.
                if hint is None or not self._dedup.region_changed(img, bbox, hint):
                    return ""
        else:
            sig = None

        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        fname = f"{ts}_{label}.png"
        out_path = str(self.session.screenshots_dir / fname)
        if not screens.save_image_png(img, out_path):
            return ""
        self._dedup.update(sig, img=img, bbox=bbox)
        return fname

    @staticmethod
    def _now_iso() -> str:
        return datetime.datetime.utcnow().isoformat() + "Z"

    # ------------------------------------------------------------------
    # pynput callbacks
    # ------------------------------------------------------------------

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not pressed or not self._running:
            return
        # A click ends any in-flight scroll/typing burst — flush them first so
        # the screenshots stay in chronological order.
        self._flush_scroll(reason="click")
        self._flush_typing(reason="click")
        # Resolve WHAT was clicked (element/window/app) BEFORE the UI reacts
        # to the click — this is what turns "click (412, 633)" into
        # "click on button «Iniciar sesión»" in the generated docs.
        ctx = uictx.event_context(x, y)
        fname = self._capture_screenshot("click", hint=(x, y))
        self.session.log_event({
            "ts": self._now_iso(),
            "type": "click",
            "x": x,
            "y": y,
            "button": str(button),
            "text": "",
            "screenshot": fname,
            **ctx,
        })

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self._running:
            return
        with self._scroll_lock:
            self._scroll_ticks += 1
            self._scroll_net_dy += int(dy)
            self._scroll_pos = (x, y)
            if self._scroll_timer is not None:
                self._scroll_timer.cancel()
            self._scroll_timer = threading.Timer(
                self.scroll_settle_ms / 1000.0, self._flush_scroll
            )
            self._scroll_timer.daemon = True
            self._scroll_timer.start()

    def _flush_scroll(self, reason: str = "settled") -> None:
        with self._scroll_lock:
            if self._scroll_timer is not None:
                self._scroll_timer.cancel()
                self._scroll_timer = None
            ticks = self._scroll_ticks
            net_dy = self._scroll_net_dy
            x, y = self._scroll_pos
            self._scroll_ticks = 0
            self._scroll_net_dy = 0

        if ticks <= 0:
            return

        fname = self._capture_screenshot("scroll", hint=(x, y))
        direction = "up" if net_dy > 0 else "down" if net_dy < 0 else "flat"
        self.session.log_event({
            "ts": self._now_iso(),
            "type": "scroll",
            "x": x,
            "y": y,
            "button": "",
            "text": f"{direction} ({ticks} ticks)",
            "screenshot": fname,
        })

    def _on_key_press(self, key) -> None:
        if not self._running:
            return
        try:
            text = key.char or ""
        except AttributeError:
            text = str(key)

        # Debounce typing: accumulate keystrokes and capture one screenshot
        # once the user pauses, instead of one per key.
        with self._type_lock:
            if not self._type_chars:
                # Context of the field that RECEIVES the burst — captured when
                # typing STARTS. At flush time focus may already be elsewhere
                # (Enter submits → page navigates), which mis-attributed the
                # text to the new page's title and let a password typed into a
                # field UIA could no longer see land in events.jsonl.
                self._type_ctx = uictx.focused_context()
                # Timestamp the burst at its START too: flushing happens up to
                # ~1s later, which sorted the typed text AFTER the Enter/nav it
                # caused and broke the replay order (fill after submit).
                self._type_start_iso = self._now_iso()
            self._type_chars.append(text)
            self._type_pos = screens.cursor_pos() or self._type_pos
            if self._type_timer is not None:
                self._type_timer.cancel()
            self._type_timer = threading.Timer(
                self.typing_settle_ms / 1000.0, self._flush_typing
            )
            self._type_timer.daemon = True
            self._type_timer.start()

    def _flush_typing(self, reason: str = "settled") -> None:
        with self._type_lock:
            if self._type_timer is not None:
                self._type_timer.cancel()
                self._type_timer = None
            chars = list(self._type_chars)
            x, y = self._type_pos
            self._type_chars = []
            ctx = getattr(self, "_type_ctx", None) or {}
            self._type_ctx = None
            start_iso = getattr(self, "_type_start_iso", None)
            self._type_start_iso = None

        if not chars:
            return

        text = "".join(c for c in chars if len(c) == 1)
        if not text:
            # Only special keys (Enter, Tab, arrows…) — summarise the last one.
            text = chars[-1]
        if ctx.get("is_password"):
            # NEVER store keystrokes typed into a password field — they would
            # land in events.jsonl and leak into reports / generated specs.
            text = ""
        fname = self._capture_screenshot("key", hint=(x, y))
        self.session.log_event({
            "ts": start_iso or self._now_iso(),
            "type": "key",
            "x": x,
            "y": y,
            "button": "",
            "text": text,
            "screenshot": fname,
            **ctx,
        })

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> None:
        self._running = False
        # Flush any pending bursts so the final state is recorded.
        self._flush_scroll(reason="stop")
        self._flush_typing(reason="stop")
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
