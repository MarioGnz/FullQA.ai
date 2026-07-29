"""
weblistener.py — Local HTTP endpoint that receives browser-extension events.

The FullQA.ai browser extension (see extension/) captures DOM-level detail the
OS cannot see: exact CSS selector, the element's real text, the final value of
inputs, form submits, and SPA navigations. It POSTs those events here.

Privacy / security model:
  - Binds to 127.0.0.1 ONLY — never reachable from the network.
  - Runs ONLY while a recording session is active; events received while no
    session is attached are acknowledged and discarded.
  - Data is appended to the same local events.jsonl as native events. Nothing
    leaves the machine.
  - The extension never captures password fields (enforced in content.js) and
    the listener additionally redacts obviously sensitive field values.

Wire format (JSON body of POST /events):
    {"events": [{"kind": "click|input|nav", "t": <epoch_ms>,
                 "name": "...", "role": "...", "selector": "...",
                 "value": "...", "url": "...", "title": "..."}]}

Origin policy: browsers ALWAYS attach an ``Origin`` header to cross-origin
POSTs, so a malicious web page firing no-cors requests at 127.0.0.1:8765
arrives with its own https:// origin — rejected. Requests from the extension
arrive as chrome-extension:// (accepted); local tools like curl send no
Origin at all (accepted, they already run with user privileges anyway).
"""

from __future__ import annotations

import datetime
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8765
MAX_BODY = 512 * 1024          # sanity cap per request
_SENSITIVE = re.compile(r"pass|pwd|contrase|cvv|card|secret|token|ssn|pin",
                        re.IGNORECASE)


def _iso_from_epoch_ms(ms) -> str:
    try:
        dt = datetime.datetime.utcfromtimestamp(float(ms) / 1000.0)
        return dt.isoformat() + "Z"
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


class WebEventListener:
    """Threaded localhost server feeding extension events into the session.

    Also exposes POST /control so the browser extension can START and STOP a
    recording remotely: ``on_start(options)`` / ``on_stop()`` callbacks are
    invoked from the server thread — the UI must marshal them onto its own
    thread (Qt signals do this automatically via queued connections).
    """

    def __init__(self, port: int = DEFAULT_PORT,
                 on_start=None, on_stop=None):
        self.port = port
        self.on_start = on_start
        self.on_stop = on_stop
        self._session = None
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.received = 0

    # -- session attachment -------------------------------------------------
    def attach(self, session) -> None:
        with self._lock:
            self._session = session

    def detach(self) -> None:
        with self._lock:
            self._session = None

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> bool:
        if self._server is not None:
            return True
        listener = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):            # silence stdout spam
                pass

            def _reply(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):                        # extension health check
                if self.path == "/ping":
                    with listener._lock:
                        rec = listener._session is not None
                    self._reply(200, {"ok": True, "recording": rec})
                else:
                    self._reply(404, {"ok": False})

            def _origin_ok(self) -> bool:
                origin = (self.headers.get("Origin") or "").strip().lower()
                if not origin:
                    return True     # curl / local tooling — no Origin header
                return origin.startswith(("chrome-extension://",
                                          "moz-extension://",
                                          "safari-web-extension://"))

            def do_POST(self):
                if not self._origin_ok():
                    # A web page (not the extension) tried to talk to us.
                    self._reply(403, {"ok": False, "error": "origin rejected"})
                    return
                try:
                    n = min(int(self.headers.get("Content-Length", 0)), MAX_BODY)
                    data = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    self._reply(400, {"ok": False})
                    return

                if self.path == "/events":
                    events = data.get("events", [])
                    if not isinstance(events, list):
                        events = []
                    stored = listener._ingest(events)
                    self._reply(200, {"ok": True, "stored": stored})
                    return

                if self.path == "/control":
                    action = str(data.get("action", ""))
                    with listener._lock:
                        recording = listener._session is not None
                    if action == "start":
                        if recording:
                            self._reply(409, {"ok": False, "error": "already recording"})
                            return
                        if listener.on_start is None:
                            self._reply(501, {"ok": False, "error": "no handler"})
                            return
                        opts = data.get("options") or {}
                        try:
                            listener.on_start(opts if isinstance(opts, dict) else {})
                        except Exception:
                            pass
                        self._reply(200, {"ok": True, "starting": True})
                        return
                    if action == "stop":
                        if not recording:
                            self._reply(409, {"ok": False, "error": "not recording"})
                            return
                        if listener.on_stop is not None:
                            try:
                                listener.on_stop()
                            except Exception:
                                pass
                        self._reply(200, {"ok": True, "stopping": True})
                        return
                    self._reply(400, {"ok": False, "error": "unknown action"})
                    return

                self._reply(404, {"ok": False})

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        except OSError:
            self._server = None
            return False                # port busy — extension capture disabled
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self.detach()
        srv, self._server = self._server, None
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass

    # -- ingestion -----------------------------------------------------------
    def _ingest(self, events: list) -> int:
        with self._lock:
            session = self._session
        if session is None:
            return 0                    # not recording — acknowledge & drop
        stored = 0
        for ev in events[:200]:
            if not isinstance(ev, dict):
                continue
            kind = str(ev.get("kind", ""))
            if kind not in ("click", "input", "nav", "enter"):
                continue
            value = str(ev.get("value", ""))[:200]
            name = str(ev.get("name", ""))[:120]
            selector = str(ev.get("selector", ""))[:200]
            if value and _SENSITIVE.search(name + " " + selector):
                value = "[redacted]"
            record = {
                "ts": _iso_from_epoch_ms(ev.get("t")),
                "type": f"web_{kind}",
                "x": 0, "y": 0, "button": "",
                "text": str(ev.get("text", ""))[:120],
                "screenshot": "",
                "element": name,
                "control": str(ev.get("role", ""))[:40],
                "selector": selector,
                "value": value,
                "url": str(ev.get("url", ""))[:300],
                "window": str(ev.get("title", ""))[:120],
                "app": "browser",
            }
            try:
                session.log_event(record)
                stored += 1
            except Exception:
                pass
        self.received += stored
        return stored
