"""
context.py — Rich per-event context via Windows UI Automation.

Answers "WHAT did the user interact with?" so the documentation can say
"clic en botón «Iniciar sesión» (Checkout — Chrome)" instead of a bare
coordinate:

  event_context(x, y)   → element under the point (for clicks)
  focused_context()     → element with keyboard focus (for typing bursts)

Both return a dict with any of: ``element`` (accessible name), ``control``
(type, e.g. "Button"), ``window`` (top-level title), ``app`` (process exe).
Missing keys simply mean the information wasn't exposed — callers must treat
every key as optional. Everything degrades to {} on non-Windows platforms,
when the `uiautomation` package is missing, or when a lookup fails/times out;
recording NEVER breaks because context capture failed.

Window title + process come from cheap pure-ctypes Win32 calls; only the
element name/type needs UI Automation (COM), which is initialised once per
calling thread and reused (pynput listener callbacks run on a stable thread).
"""

from __future__ import annotations

import sys
import threading

_IS_WIN = sys.platform.startswith("win")

# Longest element/window strings we store per event.
_MAX_NAME = 80
_MAX_TITLE = 100

# Per-thread COM/UIA initialisation state.
_tls = threading.local()


# ──────────────────────────────────────────────────────────────────────────
# Window + process (pure ctypes — cheap, no COM)
# ──────────────────────────────────────────────────────────────────────────

def _win32():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes


def _root_hwnd_at(x: int, y: int) -> int:
    if not _IS_WIN:
        return 0
    try:
        ctypes, wintypes = _win32()
        GA_ROOT = 2
        hwnd = ctypes.windll.user32.WindowFromPoint(wintypes.POINT(x, y))
        if not hwnd:
            return 0
        return int(ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    except Exception:
        return 0


def _foreground_hwnd() -> int:
    if not _IS_WIN:
        return 0
    try:
        ctypes, _ = _win32()
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        ctypes, _ = _win32()
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value.strip()[:_MAX_TITLE]
    except Exception:
        return ""


def _process_name(hwnd: int) -> str:
    """Executable basename of the window's owning process (e.g. chrome.exe)."""
    if not hwnd:
        return ""
    try:
        ctypes, wintypes = _win32()
        pid = wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                h, 0, buf, ctypes.byref(size))
            if not ok:
                return ""
            path = buf.value
            return path.rsplit("\\", 1)[-1].lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return ""


def _window_info(hwnd: int) -> dict:
    out: dict = {}
    title = _window_title(hwnd)
    app = _process_name(hwnd)
    if title:
        out["window"] = title
    if app:
        out["app"] = app
    return out


# ──────────────────────────────────────────────────────────────────────────
# Element under point / with focus (UI Automation via `uiautomation`)
# ──────────────────────────────────────────────────────────────────────────

def _uia():
    """Import uiautomation, COM-initialising the CURRENT thread once."""
    if not _IS_WIN:
        return None
    try:
        import uiautomation as auto
    except Exception:
        return None
    if not getattr(_tls, "com_ready", False):
        try:
            # Keep the initializer object alive for the thread's lifetime so
            # COM stays initialised for every subsequent lookup.
            _tls.initializer = auto.UIAutomationInitializerInThread(debug=False)
            _tls.com_ready = True
        except Exception:
            return None
    return auto


# UIA property id: element is a password field — its value must NEVER be read.
_UIA_IS_PASSWORD = 30019
# Ancestors walked when building the element path / searching the document URL.
_MAX_ANCESTORS = 8
# Control types that never add useful info to a path.
_PATH_SKIP = {"Pane", "Group", "Custom", "DataGrid", "List", "Table"}


def _ctype(ctrl) -> str:
    try:
        return (ctrl.ControlTypeName or "").replace("Control", "").strip()
    except Exception:
        return ""


def _describe_control(ctrl) -> dict:
    """Playwright-grade element description: name, role, automation id,
    ancestor path, current value (password-safe) and page URL (browsers)."""
    out: dict = {}
    try:
        name = (ctrl.Name or "").strip()
        if name:
            out["element"] = name[:_MAX_NAME]
        ctype = _ctype(ctrl)
        if ctype:
            out["control"] = ctype

        # Stable developer-assigned id — gold for future automation codegen.
        try:
            auto_id = (ctrl.AutomationId or "").strip()
            if auto_id and not auto_id.isdigit():   # numeric ids are runtime noise
                out["auto_id"] = auto_id[:_MAX_NAME]
        except Exception:
            pass

        # Current value of inputs — the "what was actually in the field" that
        # coordinates can never tell you. NEVER read password fields.
        if ctype in ("Edit", "ComboBox", "Document"):
            try:
                is_pwd = bool(ctrl.GetPropertyValue(_UIA_IS_PASSWORD))
            except Exception:
                is_pwd = None          # can't verify → don't read the value
            if is_pwd:
                # VERIFIED password field: flag it so the capture layer drops
                # the raw keystrokes too (they'd otherwise land in events.jsonl
                # and from there in reports / generated code).
                out["is_password"] = True
            elif is_pwd is False:
                try:
                    val = (ctrl.GetValuePattern().Value or "").strip()
                    if val and ctype != "Document":
                        out["value"] = val[:120]
                except Exception:
                    pass

        # Ancestor chain + document URL in one upward walk.
        crumbs: list[str] = []
        node = ctrl
        for _ in range(_MAX_ANCESTORS):
            try:
                node = node.GetParentControl()
            except Exception:
                break
            if node is None:
                break
            nctype = _ctype(node)
            if nctype == "Window":
                break                  # window title is stored separately
            try:
                nname = (node.Name or "").strip()
            except Exception:
                nname = ""
            # Browsers expose the page URL as the Document's value.
            if nctype == "Document" and "url" not in out:
                try:
                    url = (node.GetValuePattern().Value or "").strip()
                    if url.startswith(("http://", "https://", "file://")):
                        out["url"] = url[:200]
                except Exception:
                    pass
            if nname and nctype not in _PATH_SKIP and nname != name:
                crumbs.append(nname[:40])
        if crumbs:
            # Outermost-first, e.g. "Payment methods > Credit card".
            out["path"] = " > ".join(reversed(crumbs[:3]))

        # An unnamed Edit/Button often has a useful name on its parent
        # (e.g. the field's label wraps the input).
        if "element" not in out and crumbs:
            out["element"] = crumbs[0][:_MAX_NAME]
    except Exception:
        pass
    return out


def event_context(x: int, y: int) -> dict:
    """Context for a click at (x, y): element + window + app. Never raises."""
    out: dict = {}
    try:
        out.update(_window_info(_root_hwnd_at(x, y)))
        auto = _uia()
        if auto is not None:
            ctrl = auto.ControlFromPoint(x, y)
            if ctrl is not None:
                out.update(_describe_control(ctrl))
    except Exception:
        pass
    return out


def focused_context() -> dict:
    """Context for a typing burst: focused element + foreground window."""
    out: dict = {}
    try:
        out.update(_window_info(_foreground_hwnd()))
        auto = _uia()
        if auto is not None:
            ctrl = auto.GetFocusedControl()
            if ctrl is not None:
                out.update(_describe_control(ctrl))
    except Exception:
        pass
    return out
