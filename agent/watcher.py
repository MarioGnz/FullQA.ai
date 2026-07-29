"""
watcher.py — Live "smart capture" driven by a local vision model.

Instead of blindly saving a screenshot on every click/keystroke, this watcher
observes the chosen capture target continuously and only saves a frame when the
screen reaches a *new, meaningful, settled* state. It works in two cheap-to-
expensive stages so the GPU is barely touched on a static screen:

  1. Cheap gate (no model): every ~INTERVAL it grabs a 32x32 grayscale
     fingerprint of the target and compares it to the previous one. Nothing is
     done while the screen is static or still animating.
  2. Settle detection: once a change is seen it waits for the frame to stop
     changing (UI transitions/animations finish).
  3. Model decision (the expensive step, only on a settled change): a local
     Ollama vision model is asked whether this screen is a distinct step worth
     documenting and, if so, for a short label. Duplicates of the last saved
     frame are dropped before the model is ever consulted.

If the model is unreachable it degrades gracefully to "capture every settled,
non-duplicate change", which already yields far fewer, more relevant shots than
per-event capture. Saved frames are logged as ``type="auto"`` events so the
existing report pipeline picks them up.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
import os
import re
import threading
import time
import urllib.request

import context as uictx
import screens


# Tunables (seconds / normalised diffs) --------------------------------------
INTERVAL_S        = 1.2      # how often the cheap fingerprint is sampled
CHANGE_THRESHOLD  = 0.030    # diff above this = "something changed"
SETTLE_THRESHOLD  = 0.010    # diff below this = "frame is stable"
SETTLE_SAMPLES    = 2        # consecutive stable samples before we act
DUP_THRESHOLD     = 0.020    # vs last SAVED frame: below this = duplicate, skip
MODEL_MIN_GAP_S   = 2.0      # min seconds between model calls (GPU friendliness)
MODEL_IMG_WIDTH   = 768      # downscale sent to the model to keep prefill cheap


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


class SmartCaptureWatcher:
    """Background thread that saves screenshots only on meaningful changes."""

    def __init__(self, session, target: dict | None = None,
                 model: str = "qwen2.5vl:7b", use_model: bool = True,
                 base_url: str | None = None,
                 shared_dedup: "screens.FrameDedup | None" = None):
        self.session = session
        self.target = target or {"kind": "active"}
        self.model = model or "qwen2.5vl:7b"
        self.use_model = use_model
        self.base_url = (base_url
                         or os.environ.get("OLLAMA_BASE_URL")
                         or "http://localhost:11434")
        # Strip a trailing /v1 if the user reused the OpenAI-compat URL.
        self.base_url = self.base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]

        self._thread: threading.Thread | None = None
        self._running = False
        self._last_sig: list[int] | None = None
        # Last SAVED frame — shared with the event capture so clicks and the
        # watcher never write near-identical screenshots twice.
        self._dedup = shared_dedup or screens.FrameDedup(DUP_THRESHOLD)
        # Last frame the model looked at and SKIPPED (local only — must not
        # suppress click captures of that same state).
        self._last_skipped_sig: list[int] | None = None
        self._pending_change = False
        self._stable_count = 0
        self._last_model_call = 0.0
        self._saved = 0

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=INTERVAL_S * 2)

    @property
    def saved_count(self) -> int:
        return self._saved

    # -- main loop -----------------------------------------------------------
    def _loop(self) -> None:
        while self._running:
            t0 = time.monotonic()
            try:
                self._tick()
            except Exception:
                pass  # never let the watcher thread die on a transient error
            elapsed = time.monotonic() - t0
            time.sleep(max(0.05, INTERVAL_S - elapsed))

    def _tick(self) -> None:
        bbox = screens.resolve_bbox(self.target)
        sig = screens.grab_signature(bbox)
        if sig is None:
            return
        if self._last_sig is None:
            self._last_sig = sig
            return

        d = screens.signature_diff(sig, self._last_sig)
        self._last_sig = sig

        if d >= CHANGE_THRESHOLD:
            # Screen is moving — remember it and wait for it to settle.
            self._pending_change = True
            self._stable_count = 0
            return

        if d < SETTLE_THRESHOLD:
            self._stable_count += 1
        else:
            self._stable_count = 0

        if not self._pending_change or self._stable_count < SETTLE_SAMPLES:
            return

        # Settled after a change → consider capturing this frame.
        self._pending_change = False
        self._stable_count = 0

        # Skip if it's basically what was last saved (by us OR a click),
        # or a state the model already looked at and rejected.
        if self._dedup.is_dup(sig, DUP_THRESHOLD):
            return
        if (self._last_skipped_sig is not None
                and screens.signature_diff(sig, self._last_skipped_sig) < DUP_THRESHOLD):
            return

        img = screens.grab_image(bbox)
        if img is None:
            return

        capture, label = self._decide(img)
        if not capture:
            # Remember locally so we don't re-ask the model about this state —
            # but do NOT touch the shared dedup: a click on this same state
            # must still be able to capture it.
            self._last_skipped_sig = sig
            return

        self._save(img, label, sig, bbox)

    # -- model decision ------------------------------------------------------
    def _decide(self, img) -> tuple[bool, str]:
        """Ask the local model whether to capture. Falls back to heuristic."""
        if not self.use_model:
            return True, "auto"
        now = time.monotonic()
        if now - self._last_model_call < MODEL_MIN_GAP_S:
            # Too soon since the last inference — capture heuristically instead
            # of hammering the GPU.
            return True, "auto"
        self._last_model_call = now
        try:
            verdict = self._ask_model(img)
            if verdict is None:
                return True, "auto"          # model failed → heuristic capture
            return verdict
        except Exception:
            return True, "auto"

    def _ask_model(self, img) -> tuple[bool, str] | None:
        b64 = self._encode(img, MODEL_IMG_WIDTH)
        system = (
            "You decide whether a screenshot of an app under QA testing shows a "
            "distinct, meaningful UI state worth documenting as a step "
            "(a page, dialog, form, menu, or result). Ignore trivial cursor "
            "moves, hovers, and mid-animation frames."
        )
        user = (
            "Look at this screen. Reply with ONLY compact JSON, no prose:\n"
            '{"capture": true|false, "label": "<=6 word description"}\n'
            "capture=true only for a meaningful, distinct state."
        )
        payload = {
            "model": self.model,
            "stream": False,
            "keep_alive": "2m",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": [b64]},
            ],
            "options": {"temperature": 0.1, "num_predict": 64},
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        content = (resp.get("message", {}) or {}).get("content", "") or ""
        return self._parse_verdict(content)

    @staticmethod
    def _parse_verdict(text: str) -> tuple[bool, str] | None:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            # No JSON — treat a bare yes/no if present, else give up.
            low = text.lower()
            if "true" in low or "capture" in low:
                return True, "auto"
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
        cap = bool(obj.get("capture", False))
        label = str(obj.get("label", "") or "").strip() or "auto"
        label = re.sub(r"\s+", " ", label)[:60]
        return cap, label

    @staticmethod
    def _encode(img, max_w: int) -> str:
        im = img
        if im.width > max_w:
            ratio = max_w / im.width
            im = im.resize((max_w, int(im.height * ratio)))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    # -- persistence ---------------------------------------------------------
    def _save(self, img, label: str, sig: list[int], bbox: dict | None = None) -> None:
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        fname = f"{ts}_auto.png"
        out_path = str(self.session.screenshots_dir / fname)
        if not screens.save_image_png(img, out_path):
            return
        self._dedup.update(sig, img=img, bbox=bbox)
        self._last_skipped_sig = None
        self._saved += 1
        pos = screens.cursor_pos() or (0, 0)
        # Cheap window/app context (no COM) so auto events say where they were.
        ctx = uictx._window_info(uictx._foreground_hwnd())
        self.session.log_event({
            "ts": _now_iso(),
            "type": "auto",
            "x": pos[0],
            "y": pos[1],
            "button": "",
            "text": label if label != "auto" else "",
            "screenshot": fname,
            **ctx,
        })
