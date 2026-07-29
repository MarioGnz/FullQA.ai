"""
claude_gen.py — Claude AI documentation generator.

Takes a session directory on the shared volume, groups events into logical
steps, and calls the Anthropic API to produce a structured Markdown report.

Supported sections (any combination):
  "summary"            — short prose overview: what was tested + outcome
  "steps_to_reproduce" — clean numbered list of imperative repro steps
  "test_cases"         — Gherkin-style test case table
  "test_plan"          — Step/Action/Expected/Status table
  "bug_report"         — summary / severity / repro / expected vs actual
  "jira"               — Jira-ready ticket (uses title + description for context)

Screenshots are embedded as base64 data URIs so the report is self-contained.
The Claude API call is the ONLY outbound network request made by this container.
"""

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
# Cap images sent to local/Groq models. Each image is expensive to prefill —
# especially on CPU-only Ollama — so keep this modest for local inference.
MAX_IMAGES_LOCAL = int(os.environ.get("MAX_IMAGES_LOCAL", "5"))
# Seconds to wait for local inference. CPU-only generation of a vision model
# is slow, so this is generous; override with OLLAMA_TIMEOUT if needed.
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "900"))
# How long Ollama keeps the model (and its KV/prefix cache) resident after a
# request. Longer = the stable project-context prefix is reused across the
# several generations of one session without a reload. It holds VRAM while warm.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

# Prompt-caching TTL for the per-project context on Anthropic. The project
# context is identical across every section and every regeneration of a project,
# so caching it means each repeat pays ~10% instead of full price. "1h" is the
# longest standard TTL (2x write cost, but a QA session spans well over 5 min).
CACHE_TTL = os.environ.get("ANTHROPIC_CACHE_TTL", "1h")

# Tuning knobs
STEP_GAP_SECONDS   = 8.0   # seconds of inactivity → new logical step
# Hard cap on steps sent to the model (env-overridable for long sessions).
# Step TEXT is cheap (~40 tokens each; images are capped separately by
# MAX_IMAGES_LOCAL), so this can be generous — beyond it, a scored selection
# keeps whole-session coverage.
MAX_STEPS          = int(os.environ.get("MAX_STEPS", "25"))
MAX_CONSECUTIVE_SCROLLS = 1  # keep at most 1 screenshot per scroll burst
# Max characters of spoken narration (transcript.txt) injected into prompts.
MAX_NARRATION_CHARS = int(os.environ.get("MAX_NARRATION_CHARS", "2000"))


# ------------------------------------------------------------------
# Event grouping — smarter deduplication
# ------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)


def _ts_or_none(ev: dict) -> float | None:
    try:
        return _parse_iso(ev["ts"]).timestamp()
    except Exception:
        return None


def _fuse_web_events(events: list[dict]) -> list[dict]:
    """Merge browser-extension events (exact DOM data) with native events.

    The extension reports ``web_click`` / ``web_input`` / ``web_nav`` with the
    real selector, element text, final field value and page URL. A user click
    produces BOTH a native UIA event and a web event — fuse them (time
    correlation) so each action is documented once, with the richest data.
    """
    web = [e for e in events if str(e.get("type", "")).startswith("web_")]
    if not web:
        return events
    native = [e for e in events if not str(e.get("type", "")).startswith("web_")]

    import re as _re

    def _norm_name(s: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    def _names_compat(a: str, b: str) -> bool:
        """Field-name compatibility: only block fusion when BOTH sides carry a
        name and those names are unrelated (different fields)."""
        na, nb = _norm_name(a), _norm_name(b)
        if not na or not nb:
            return True
        return na == nb or na in nb or nb in na

    def _nearest(cands: list[dict], ts: float, max_dt: float,
                 web_ev: dict | None = None) -> dict | None:
        best, best_dt = None, max_dt
        for ev in cands:
            evt = _ts_or_none(ev)
            if evt is None:
                continue
            if web_ev is not None:
                # Time proximity is not enough: an email field's blur-time
                # web_input lands right when the user clicks into the password
                # field, and fused onto the password burst it renamed it to
                # "Email Address" → codegen filled the EMAIL with QA_PASSWORD.
                if not _names_compat(ev.get("element") or "",
                                     web_ev.get("element") or ""):
                    continue
                # A plaintext value can never belong to a password field
                # (the extension refuses to read those).
                if ev.get("is_password") and (web_ev.get("value") or "").strip():
                    continue
            dt = abs(evt - ts)
            if dt <= best_dt:
                best, best_dt = ev, dt
        return best

    def _enrich(target: dict, w: dict) -> None:
        # Web data wins where it is richer; never erase native info.
        # When the extension captured the actual clicked node (it has a
        # selector), ITS accessible name is the truth even if shorter — UIA
        # sometimes names a nearby/ancestor control instead (e.g. "Received
        # Requests" for a click that really hit "Logout").
        if w.get("element") and (
                w.get("selector")
                or len(w["element"]) >= len(target.get("element") or "")):
            target["element"] = w["element"]
        # control/value describe the DOM element itself — the extension reads
        # them from the real node, so they beat UIA's guess (which mislabeled
        # an email field as "Button" and snapshots values mid-typing).
        for key in ("control", "value"):
            if w.get(key):
                target[key] = w[key]
        for key in ("url", "selector"):
            if w.get(key) and not target.get(key):
                target[key] = w[key]

    clicks = [e for e in native if e.get("type") == "click"]
    keys   = [e for e in native if e.get("type") == "key"]
    fused: list[dict] = list(native)

    for w in web:
        wts = _ts_or_none(w)
        wtype = w.get("type")
        if wtype == "web_nav":
            fused.append({**w, "type": "nav"})
            continue
        if wtype == "web_enter":
            # Keyboard submit — keep it as an explicit Enter key event so the
            # generated flow actually submits after filling the fields.
            fused.append({**w, "type": "key", "text": "Key.Enter"})
            continue
        if wts is None:
            continue
        if wtype == "web_click":
            match = _nearest(clicks, wts, 1.2, web_ev=w)
            if match is not None:
                _enrich(match, w)
            else:
                fused.append({**w, "type": "click"})   # UIA missed this click
        elif wtype == "web_input":
            match = _nearest(keys, wts, 2.5, web_ev=w)
            if match is None and _norm_name(w.get("element") or ""):
                # Blur-time report of a field typed a while ago (blur fires
                # when LEAVING the field): attach the definitive final value
                # to that field's own typing burst, wherever in time it is.
                same = [k for k in keys
                        if _norm_name(k.get("element") or "")
                        and _names_compat(k.get("element") or "",
                                          w.get("element") or "")]
                match = _nearest(same, wts, 120.0, web_ev=w)
            if match is not None:
                _enrich(match, w)
            else:
                fused.append({**w, "type": "key",
                              "text": w.get("value", "") or w.get("text", "")})

    fused.sort(key=lambda e: e.get("ts", ""))

    # Collapse consecutive navs to the same PAGE (ignoring the query string —
    # filter/search reloads spam navs for what is visually the same screen).
    out: list[dict] = []
    last_nav_url = None
    for ev in fused:
        if ev.get("type") == "nav":
            page = _clean_url(ev.get("url") or "")
            if page and page == last_nav_url:
                continue
            last_nav_url = page
        out.append(ev)
    return out


_OWN_APP_PREFIXES = ("FullQA.ai", "FullQA")   # product was renamed FullQA.ai


def _is_own_app_event(ev: dict) -> bool:
    """True for interactions with FullQA.ai/FullQA itself (recorder noise): the
    desktop window OR the browser extension's own UI ("FullQA.ai Recorder…")."""
    if (ev.get("window") or "").strip().startswith(_OWN_APP_PREFIXES):
        return True
    element = (ev.get("element") or "").strip()
    if element.startswith(_OWN_APP_PREFIXES):
        return True
    # The extension popup's own start/stop buttons ("■ Stop recording",
    # "● Iniciar grabación") — always the last captured click of a session.
    low = element.lower()
    return element[:1] in ("■", "●") and (
        "recording" in low or "grabaci" in low)


def _clean_url(url: str, max_len: int = 90) -> str:
    """URL for humans: no query string / fragment, bounded length."""
    u = (url or "").split("?")[0].split("#")[0].rstrip("/")
    return u[:max_len] if u else ""


_BROWSER_APPS = {"browser", "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"}


def _step_score(step: dict) -> int:
    """Importance of a step when the session exceeds MAX_STEPS."""
    etype = step.get("type", "")
    score = {"nav": 5, "click": 4, "key": 3, "auto": 2, "scroll": 1}.get(etype, 0)
    if step.get("element"):
        score += 3
    if step.get("screenshot"):
        score += 1
    if etype == "auto" and step.get("text"):
        score += 1
    return score


def _select_steps(steps: list[dict], max_steps: int) -> list[dict]:
    """Pick ``max_steps`` covering the WHOLE session, not just its start.

    The first and last steps are always kept (setup and outcome); the interior
    is split into equal time buckets and the highest-scoring step of each
    bucket wins. This replaces the old ``steps[:MAX_STEPS]`` truncation that
    silently dropped the end of long sessions — usually the part that matters.
    """
    n = len(steps)
    if n <= max_steps or max_steps < 3:
        return steps[:max_steps] if n > max_steps else steps
    keep = {0, n - 1}
    slots = max_steps - 2
    for b in range(slots):
        lo = 1 + (n - 2) * b // slots
        hi = 1 + (n - 2) * (b + 1) // slots
        if lo >= hi:
            continue
        best = max(range(lo, hi), key=lambda i: _step_score(steps[i]))
        keep.add(best)
    return [steps[i] for i in sorted(keep)]


def group_events_into_steps(events: list[dict]) -> list[dict]:
    """
    Collapse the raw event stream into meaningful logical steps.

    Rules:
    - A CLICK or NAVIGATION always ends the current group (interaction boundary).
    - A gap > STEP_GAP_SECONDS between consecutive events starts a new group.
    - Consecutive scroll events are collapsed: only the first in a burst is kept.
    - Pure key events with no screenshot and no text are dropped entirely.
    - Interactions with FullQA.ai's own window are dropped (recorder noise).
    - Each group is represented by the last event that has a screenshot
      (falls back to the last event overall).
    - If there are more steps than MAX_STEPS, a scored selection keeps
      coverage of the WHOLE session (never just the first N).
    """
    if not events:
        return []

    # ── 1. Pre-filter: drop meaningless events ─────────────────────
    filtered: list[dict] = []
    last_scroll_ts: float | None = None

    for ev in events:
        etype = ev.get("type", "")

        # Drop clicks on the recorder itself ("Detener Grabación", etc.)
        if _is_own_app_event(ev):
            continue

        # Drop key events with no useful text and no screenshot
        if etype == "key" and not ev.get("text", "").strip() and not ev.get("screenshot"):
            continue

        # Collapse scroll bursts — keep only one per burst window
        if etype == "scroll":
            try:
                ts_s = _parse_iso(ev["ts"]).timestamp()
            except Exception:
                ts_s = None
            if ts_s is not None and last_scroll_ts is not None:
                if ts_s - last_scroll_ts < STEP_GAP_SECONDS:
                    continue   # skip: too close to previous scroll
            last_scroll_ts = ts_s
        else:
            last_scroll_ts = None   # reset burst counter on non-scroll

        filtered.append(ev)

    if not filtered:
        return []

    # ── 2. Group by clicks + time gaps ────────────────────────────
    steps: list[dict] = []
    group: list[dict] = []

    for idx, event in enumerate(filtered):
        group.append(event)

        is_last     = idx == len(filtered) - 1
        is_boundary = event.get("type") in ("click", "nav")

        time_gap = False
        if not is_last:
            try:
                gap = (
                    _parse_iso(filtered[idx + 1]["ts"]) - _parse_iso(event["ts"])
                ).total_seconds()
                time_gap = gap > STEP_GAP_SECONDS
            except Exception:
                pass

        if is_boundary or time_gap or is_last:
            # Navigations are their own step even without a screenshot.
            if event.get("type") == "nav":
                rep = event
            else:
                rep = next(
                    (e for e in reversed(group) if e.get("screenshot")),
                    group[-1],
                )
            steps.append(rep)
            group = []

    # ── 3. Deduplicate consecutive steps with the same screenshot ──
    deduped: list[dict] = []
    seen_shots: set[str] = set()
    for step in steps:
        shot = step.get("screenshot", "")
        if shot and shot in seen_shots:
            continue
        if shot:
            seen_shots.add(shot)
        deduped.append(step)

    # ── 4. Collapse consecutive steps that describe the same interaction
    # (e.g. three same-named checkboxes) into one step annotated (×N).
    collapsed: list[dict] = []
    for step in deduped:
        prev = collapsed[-1] if collapsed else None
        same = (
            prev is not None
            and prev.get("type") == step.get("type")
            and step.get("type") in ("click", "key")
            and (prev.get("element") or "") == (step.get("element") or "")
            and prev.get("element")                       # only named elements
            and (prev.get("control") or "") == (step.get("control") or "")
            and _clean_url(prev.get("url") or "") == _clean_url(step.get("url") or "")
        )
        if same:
            prev["repeat"] = int(prev.get("repeat", 1)) + 1
            if not prev.get("screenshot") and step.get("screenshot"):
                prev["screenshot"] = step["screenshot"]
        else:
            collapsed.append(step)

    # ── 5. Scored selection over the WHOLE session (never truncate the tail)
    return _select_steps(collapsed, MAX_STEPS)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------
# Provider / model registry
# ------------------------------------------------------------------

# Models known to accept image inputs
_VISION_MODELS: set[str] = {
    "claude-sonnet-5",
    "claude-opus-4-8",
    "claude-haiku-4-5",
    "qwen2.5vl:7b",
    "qwen3-vl:235b",
    "llama3.2-vision:11b",
    "llava:13b",
    "llava:7b",
    "minicpm-v",
    # Groq's llama-3.2 vision previews were decommissioned; Llama 4 replaces them.
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
}

_DEFAULT_MODEL: dict[str, str] = {
    "anthropic":    "claude-sonnet-5",
    "ollama":       "qwen2.5vl:7b",
    "ollama-cloud": "qwen3-vl:235b",   # vision model hosted on Ollama Cloud
    "groq":         "meta-llama/llama-4-scout-17b-16e-instruct",
    "gemini":       "gemini-2.5-flash",
}


def _model_has_vision(model: str) -> bool:
    """Return True if the model can accept image content blocks."""
    low = model.lower()
    return (
        model in _VISION_MODELS
        or "vision" in low
        or "gemini" in low          # all current Gemini models are multimodal
        or "llama-4" in low         # Llama 4 (Scout/Maverick) is multimodal
        or low.startswith("llava")
        or ("vl" in low and "qwen" in low)
        or "minicpm-v" in low
    )


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _lang_instruction(language: str) -> str:
    if language == "es":
        return (
            "Respond entirely in Spanish. "
            "All headings, table headers, labels, and commentary must be in Spanish."
        )
    return "Respond in English."


def _image_policy(provider: str) -> tuple[int | None, int | None]:
    """(max_images, max_width) for the screenshots sent to the model.

    - anthropic: every image, downscaled to 1568px longest edge (the API
                 rejects images over 2000px per side on many-image requests).
    - gemini:    every image, downscaled JPEG (stays under the ~20 MB
                 inline-payload limit of generateContent).
    - ollama/groq: few, small images (VRAM / provider limits).
    """
    if provider == "anthropic":
        return None, 1568
    if provider == "gemini":
        return None, 1366
    if provider == "ollama-cloud":
        # Runs on Ollama's hardware, not our GPU — no VRAM cap, so send every
        # screenshot (downscaled to keep the request payload reasonable).
        return None, 1568
    return MAX_IMAGES_LOCAL, 1024


def _load_transcript(session_dir: Path) -> str:
    """Return the tester's spoken narration (transcript.txt), trimmed."""
    tp = session_dir / "transcript.txt"
    if not tp.exists():
        return ""
    try:
        text = tp.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""
    if len(text) > MAX_NARRATION_CHARS:
        text = text[:MAX_NARRATION_CHARS] + " …"
    return text


def _project_prefix(project_context: str) -> str:
    """The per-project background document, framed for the model.

    This text is IDENTICAL across every section and every regeneration of a
    project, so it is sent as a cacheable prefix (see ``_call_ai``) rather than
    inlined per request. Returns "" when the project has no context.
    """
    if not (project_context and project_context.strip()):
        return ""
    return (
        "Project background (maintained by the QA team — treat as authoritative "
        "context for how this product works and what to expect):\n"
        f"\"\"\"\n{project_context.strip()[:6000]}\n\"\"\"\n"
    )


def _context_block(title: str, description: str, session_dir: Path) -> str:
    """Per-session prompt context: title, description, spoken narration.

    Project background is handled separately as a cacheable prefix — see
    ``_project_prefix`` — so it is intentionally NOT included here.
    """
    ctx = ""
    if title:
        ctx += f"Testing title: {title}\n"
    if description:
        ctx += f"Context: {description}\n"
    narration = _load_transcript(session_dir)
    if narration:
        ctx += (
            "Tester's spoken narration during the session (transcribed, may "
            f"contain recognition errors):\n\"\"\"\n{narration}\n\"\"\"\n"
        )
    return ctx


def _describe_step(step: dict, prev_ctx: dict | None = None) -> str:
    """Human/model-readable one-liner for an event.

    ``prev_ctx`` (mutable, shared across a sequence) enables DELTA rendering:
    page/window/app are mentioned only when they CHANGE — repeating them on
    all 25 steps buried the signal in noise. Browser apps are implied by the
    URL and never named.
    """
    etype = (step.get("type") or "?").lower()
    element = (step.get("element") or "").strip()
    control = (step.get("control") or "").strip()
    text    = (step.get("text") or "").strip()
    path    = (step.get("path") or "").strip()
    x, y    = step.get("x", 0), step.get("y", 0)
    win     = (step.get("window") or "").strip()
    app     = (step.get("app") or "").strip().lower()
    url     = _clean_url(step.get("url") or "")
    repeat  = int(step.get("repeat", 1))

    located = f'{control or "element"} "{element}"'
    # The ancestor path only earns its place when it adds new information.
    if path and path != element and path not in win and element not in path:
        located += f' (in {path[:60]})'

    if etype == "click":
        kind = "right-click" if "right" in str(step.get("button", "")).lower() else "click"
        desc = f"{kind} on {located}" if element else f"{kind} at ({x}, {y})"
    elif etype == "key":
        field = f" in {located}" if element else ""
        desc = f'typed "{text}"{field}' if text else f"keyboard input{field}"
        value = (step.get("value") or "").strip()
        if value and value != text:
            desc += f' → field content: "{value}"'
    elif etype == "scroll":
        desc = f"scrolled {text}" if text else "scrolled"
    elif etype == "auto":
        desc = f"screen state: {text}" if text else "screen changed"
    elif etype == "nav":
        title = win[:50]
        desc = f"navigated to {url or title}" + (
            f' ("{title}")' if title and url and title not in url else "")
    else:
        desc = text or f"({x}, {y})"

    if repeat > 1:
        desc += f"  (×{repeat})"

    # ── delta context: only what CHANGED since the previous step ──
    extras = []
    if prev_ctx is None:
        prev_ctx = {}
    if etype != "nav":
        if url and url != prev_ctx.get("url"):
            extras.append(f"page: {url}")
        elif not url and win and win != prev_ctx.get("window"):
            extras.append(f'window: "{win[:60]}"')
    if app and app not in _BROWSER_APPS and app != prev_ctx.get("app"):
        extras.append(f"app: {app}")
    if url:
        prev_ctx["url"] = url
    if win:
        prev_ctx["window"] = win
    if app:
        prev_ctx["app"] = app
    return desc + (f"  [{' | '.join(extras)}]" if extras else "")


# Grounding rules appended to every generation prompt — attacks the failure
# mode of models "assuming" outcomes that never happened.
_GROUNDING = (
    "Grounding rules (CRITICAL):\n"
    "- Describe ONLY what the provided steps and screenshots actually show.\n"
    "- NEVER invent outcomes, data, page names, or steps that are not in the list.\n"
    "- If an outcome cannot be verified from the evidence, write [UNCLEAR] "
    "instead of assuming success.\n"
)


def _pick_image_steps(steps: list[dict], session_dir: Path,
                      max_images: int | None) -> set[int]:
    """Indices of the steps whose screenshot is sent to the model.

    When capped, spread the budget across the WHOLE session (evenly spaced
    among steps that have an image) instead of burning it on the first N —
    otherwise the model literally never sees the end of the flow.
    """
    with_shot = [
        i for i, s in enumerate(steps)
        if s.get("screenshot") and (session_dir / "screenshots" / s["screenshot"]).exists()
    ]
    if max_images is None or len(with_shot) <= max_images:
        return set(with_shot)
    if max_images <= 0:
        return set()
    picked = {with_shot[0], with_shot[-1]}
    slots = max_images - len(picked)
    n = len(with_shot)
    for b in range(max(0, slots)):
        idx = with_shot[1 + (n - 2) * (b + 1) // (slots + 1)]
        picked.add(idx)
    return set(list(sorted(picked))[:max_images])


def _build_steps_content(
    steps: list[dict],
    session_dir: Path,
    include_images: bool = True,
    max_images: int | None = None,
    max_width: int | None = None,
) -> list[dict]:
    """Return the ordered list of image + text content blocks for the steps.

    ``max_width`` downscales the images sent to the model. Local models have
    limited VRAM, so feeding full-resolution screenshots inflates the context
    past the GPU budget and forces slow CPU inference — keep it modest there.
    """
    content: list[dict] = []
    image_steps = _pick_image_steps(steps, session_dir, max_images) \
        if include_images else set()
    prev_ctx: dict = {}
    for i, step in enumerate(steps, start=1):
        shot = step.get("screenshot", "")
        if shot and (i - 1) in image_steps:
            img_path = session_dir / "screenshots" / shot
            if max_width is not None:
                b64, media = _encode_image_for_report(img_path, max_w=max_width)
            else:
                b64 = base64.standard_b64encode(img_path.read_bytes()).decode("ascii")
                media = "image/png"
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": b64},
            })
        content.append({
            "type": "text",
            "text": f"Step {i} [{step.get('type','?').upper()}]: "
                    f"{_describe_step(step, prev_ctx)}",
        })
    return content


def _to_openai_content(content: list[dict]) -> list[dict]:
    """Convert Anthropic-style content blocks to OpenAI chat format."""
    result: list[dict] = []
    for block in content:
        if block["type"] == "text":
            result.append({"type": "text", "text": block["text"]})
        elif block["type"] == "image":
            src = block["source"]
            if src["type"] == "base64":
                url = f"data:{src['media_type']};base64,{src['data']}"
                result.append({"type": "image_url", "image_url": {"url": url}})
    return result


def _clean_output(text: str) -> str:
    """
    Strip chat-template artifacts and any preamble before the first
    Markdown heading, table row, or list item.
    """
    import re as _re
    # Remove special tokens like <|im_start|>, <|im_end|>, <|endoftext|>
    text = _re.sub(r"<\|[^|>]+\|>", "", text).strip()
    # Drop any lines before the first Markdown structural element
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(("#", "|", "-", "*", "1.", "2.", "3.")):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def _sanitize_markdown(text: str) -> str:
    """Repair repetition-loop damage in model output, deterministically.

    Local models sometimes degenerate into re-emitting the section heading and
    the table header before every row ("69 tables of one row each"). This pass:
      - drops repeated identical headings (keeps the first),
      - merges tables that repeat the same header row into ONE table,
      - drops rows whose content (ignoring the first column, usually a step
        number) duplicates a row already in the same table.
    Legit output without loops passes through unchanged.
    """
    import re as _re

    def _is_sep(l: str) -> bool:
        return bool(_re.match(r"^\s*\|[\s:\-|]+\|\s*$", l))

    def _is_row(l: str) -> bool:
        s = l.strip()
        return s.startswith("|") and s.count("|") >= 2 and not _is_sep(l)

    def _norm(l: str) -> str:
        return _re.sub(r"\s+", " ", l.strip().lower())

    def _row_key(l: str) -> str:
        # Row identity ignoring the first cell (step/case number).
        cells = [c.strip().lower() for c in l.strip().strip("|").split("|")]
        return "|".join(cells[1:]) if len(cells) > 1 else cells[0]

    lines = [l.rstrip() for l in text.splitlines()]
    out: list[str] = []
    seen_headings: set[str] = set()
    cur_header: str | None = None      # normalized header of the open table
    cur_rows: set[str] = set()         # row keys already emitted in that table

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Headings: keep the first occurrence, drop loop repeats.
        if stripped.startswith("#"):
            key = _norm(line)
            if key in seen_headings:
                i += 1
                continue               # duplicated heading — drop, keep table open
            seen_headings.add(key)
            cur_header, cur_rows = None, set()
            out.append(line)
            i += 1
            continue

        # Table header (row followed by a separator line).
        if _is_row(line) and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            if cur_header is not None and _norm(line) == cur_header:
                i += 2                 # same table re-opened — merge, skip header
                continue
            cur_header, cur_rows = _norm(line), set()
            out.append(line)
            out.append(lines[i + 1])
            i += 2
            continue

        # Data row.
        if _is_row(line):
            key = _row_key(line)
            # Drop exact duplicates AND truncated duplicates (a loop cut off
            # mid-row leaves a row whose content is a prefix of a real one).
            dup = cur_header is not None and (
                key in cur_rows
                or (len(key) > 20 and any(k.startswith(key) for k in cur_rows))
            )
            if dup:
                i += 1
                continue
            cur_rows.add(key)
            out.append(line)
            i += 1
            continue

        # Blank lines: skip them when they only separate fragments of the
        # SAME table (loop artifacts); otherwise they close the table.
        if stripped == "":
            j = i
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            nxt = lines[j] if j < len(lines) else ""
            nxt2 = lines[j + 1] if j + 1 < len(lines) else ""
            if cur_header is not None:
                if _is_row(nxt) and _is_sep(nxt2) and _norm(nxt) == cur_header:
                    i = j              # blanks before a repeated header — drop
                    continue
                if nxt.strip().startswith("#") and _norm(nxt) in seen_headings:
                    i = j              # blanks before a repeated heading — drop
                    continue
                if _is_row(nxt) and not _is_sep(nxt2):
                    i = j              # blanks splitting rows of one table — drop
                    continue
            cur_header, cur_rows = None, set()
            out.append("")
            i = j
            continue

        # Any other content closes the current table.
        cur_header, cur_rows = None, set()
        out.append(line)
        i += 1

    return "\n".join(out).strip()


# Context window for local generation. 8192 easily covers our prompt + a few
# downscaled screenshots while keeping the KV-cache small enough to fit most
# consumer GPUs (the default 16384 overflows 12 GB cards onto the CPU).
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))


def _call_ollama_native(model: str, content: list[dict],
                        cache_prefix: str = "", cloud: bool = False) -> str:
    """Call Ollama's native /api/chat endpoint (local host OR Ollama Cloud).

    Unlike the OpenAI-compatibility layer, the native API honours
    ``options.num_ctx`` and ``keep_alive``, which lets us cap the context so
    the model fits in VRAM instead of spilling onto the CPU.

    ``cache_prefix`` (per-project background) leads the system message so the
    model's KV/prefix cache is reused across the session's generations while it
    stays resident (``OLLAMA_KEEP_ALIVE``). Local inference has no token cost —
    this saves prefill time, not money.

    ``cloud=True`` targets Ollama Cloud (``OLLAMA_CLOUD_BASE_URL``, default
    https://ollama.com) with ``Authorization: Bearer $OLLAMA_API_KEY``. The wire
    format is identical, but the request runs on Ollama's hardware — so VRAM
    caps (``num_ctx``) and residency (``keep_alive``) don't apply, and the data
    DOES leave the machine. That's a deliberate, opt-in provider choice.
    """
    import httpx as _httpx

    headers: dict[str, str] = {}
    if cloud:
        base_url = os.environ.get("OLLAMA_CLOUD_BASE_URL", "https://ollama.com")
        api_key = os.environ.get("OLLAMA_API_KEY", "")
        if not api_key:
            raise ValueError("OLLAMA_API_KEY environment variable is not set "
                             "(required for the Ollama Cloud provider).")
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        base_url = os.environ.get("OLLAMA_BASE_URL",
                                  "http://host.docker.internal:11434/v1")
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    chat_url = f"{root}/api/chat"

    # First text block → system message; the rest → a single user turn that
    # carries the joined text plus every image as native base64 strings.
    system_text: str | None = None
    blocks = list(content)
    if blocks and blocks[0].get("type") == "text":
        system_text = blocks.pop(0)["text"]
    if cache_prefix:
        system_text = (cache_prefix + "\n\n" + system_text) if system_text else cache_prefix

    user_text_parts: list[str] = []
    images: list[str] = []
    for block in blocks:
        if block.get("type") == "text":
            user_text_parts.append(block["text"])
        elif block.get("type") == "image":
            src = block.get("source", {})
            if src.get("type") == "base64" and src.get("data"):
                images.append(src["data"])

    messages: list[dict] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    user_msg: dict = {"role": "user", "content": "\n".join(user_text_parts)}
    if images:
        user_msg["images"] = images
    messages.append(user_msg)

    options: dict = {
        "temperature": 0.2,
        "num_predict": MAX_TOKENS,
        # Models are prone to repetition loops on tabular output (re-emitting the
        # heading + header per row); penalise repeats.
        "repeat_penalty": 1.15,
    }
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    if not cloud:
        # VRAM caps and residency only make sense for local inference.
        payload["keep_alive"] = OLLAMA_KEEP_ALIVE
        options["num_ctx"] = OLLAMA_NUM_CTX

    where = "Ollama Cloud" if cloud else f"Ollama ({root})"
    try:
        with _httpx.Client(timeout=_httpx.Timeout(OLLAMA_TIMEOUT, connect=10.0)) as client:
            resp = client.post(chat_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except _httpx.ConnectError as exc:
        raise RuntimeError(
            f"No se pudo conectar con {where}. Verifica que Ollama esté "
            "abierto (icono en la bandeja o 'ollama serve') y vuelve a "
            f"intentarlo. [{exc}]") from exc
    except _httpx.TimeoutException as exc:
        raise RuntimeError(
            f"{where} no respondió en {OLLAMA_TIMEOUT}s con el modelo "
            f"'{model}'. Prueba un modelo más pequeño o sube OLLAMA_TIMEOUT. "
            f"[{exc.__class__.__name__}]") from exc
    except _httpx.HTTPStatusError as exc:
        try:
            detail = (exc.response.json() or {}).get("error", "")
        except Exception:
            detail = exc.response.text[:300]
        low_d = (detail or "").lower()
        if "not found" in low_d or exc.response.status_code == 404:
            raise RuntimeError(
                f"El modelo '{model}' no está instalado en {where}. "
                f"Instálalo con:  ollama pull {model}") from exc
        if "memory" in low_d or "unable to allocate" in low_d:
            raise RuntimeError(
                f"El modelo '{model}' no cabe en la memoria disponible. "
                "Prueba una variante más pequeña (p. ej. 7b) o baja "
                f"OLLAMA_NUM_CTX. Detalle: {detail}") from exc
        if exc.response.status_code in (401, 403):
            raise RuntimeError(
                f"{where} rechazó la autenticación (revisa OLLAMA_API_KEY). "
                f"Detalle: {detail}") from exc
        raise RuntimeError(f"{where} devolvió un error con el modelo "
                           f"'{model}': {detail or exc}") from exc
    raw = (data.get("message", {}) or {}).get("content", "") or ""
    if not raw.strip():
        raise RuntimeError(
            f"El modelo '{model}' devolvió una respuesta vacía. Suele indicar "
            "que el modelo no soporta este tipo de entrada (¿imágenes en un "
            "modelo solo-texto?) — prueba un modelo con visión (p. ej. "
            "qwen2.5vl:7b).")
    return _clean_output(raw)


def _call_gemini(model: str, content: list[dict], cache_prefix: str = "") -> str:
    """Call the Google Gemini API (REST v1beta, key auth) with httpx.

    The first text block becomes the systemInstruction; the rest is a single
    user turn with text + inline_data image parts. Images arrive here already
    downscaled/JPEG-encoded so the request stays under Gemini's ~20 MB inline
    payload limit.

    ``cache_prefix`` (per-project background) leads the systemInstruction; on
    Gemini 2.5 models identical prefixes are cached implicitly, so repeated
    generations for a project are discounted automatically.
    """
    import httpx as _httpx

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    system_text: str | None = None
    blocks = list(content)
    if blocks and blocks[0].get("type") == "text":
        system_text = blocks.pop(0)["text"]
    if cache_prefix:
        system_text = (cache_prefix + "\n\n" + system_text) if system_text else cache_prefix

    parts: list[dict] = []
    for block in blocks:
        if block.get("type") == "text":
            parts.append({"text": block["text"]})
        elif block.get("type") == "image":
            src = block.get("source", {})
            if src.get("type") == "base64" and src.get("data"):
                parts.append({"inline_data": {
                    "mime_type": src.get("media_type", "image/jpeg"),
                    "data": src["data"],
                }})

    payload: dict = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": MAX_TOKENS,
            "temperature": 0.2,
        },
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    with _httpx.Client(timeout=_httpx.Timeout(180.0, connect=10.0)) as client:
        resp = client.post(
            url, json=payload,
            headers={"x-goog-api-key": api_key,
                     "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        block = (data.get("promptFeedback", {}) or {}).get("blockReason", "")
        raise RuntimeError(f"Gemini returned no candidates ({block or 'unknown reason'}).")
    out_parts = (candidates[0].get("content", {}) or {}).get("parts", []) or []
    raw = "".join(p.get("text", "") for p in out_parts)
    if not raw.strip():
        raise RuntimeError(
            f"Gemini returned empty text (finishReason="
            f"{candidates[0].get('finishReason', '?')})."
        )
    return _clean_output(raw)


def _call_ai(provider: str, model: str, content: list[dict],
             cache_prefix: str = "") -> str:
    """Route the generation call to the correct AI provider.

    ``cache_prefix`` is stable-per-project background (see ``_project_prefix``).
    It is placed at the front of the prompt as a cacheable prefix so repeated
    generations for the same project don't re-pay for it every time:
      * Anthropic  → a ``system`` block with ``cache_control`` (TTL ``CACHE_TTL``);
                     reads cost ~10% of the input price.
      * Ollama     → front of the system message; the model's KV/prefix cache is
                     reused while it stays resident (``OLLAMA_KEEP_ALIVE``).
      * Gemini     → front of ``systemInstruction``; 2.5 models cache implicitly.
      * Groq       → front of the system message (no caching there, but harmless).

    Every provider's output goes through ``_sanitize_markdown`` — local models
    especially can degenerate into repetition loops (heading + table header
    re-emitted per row), and the sanitizer repairs that deterministically.
    """
    resolved_model = model or _DEFAULT_MODEL.get(provider, "")

    if provider == "anthropic":
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        def _create(system, msgs):
            kw = dict(
                model=resolved_model,
                max_tokens=MAX_TOKENS,
                # Sonnet 5 / current models run adaptive thinking by default;
                # disable it so the full max_tokens budget goes to the answer and
                # the first content block is text (not a thinking block).
                thinking={"type": "disabled"},
                messages=msgs,
            )
            if system is not None:
                kw["system"] = system
            return client.messages.create(**kw)

        system = None
        if cache_prefix:
            # Cache the project context so every later section / regeneration
            # reads it at ~10% price instead of re-sending it in full.
            system = [{
                "type": "text",
                "text": cache_prefix,
                "cache_control": {"type": "ephemeral", "ttl": CACHE_TTL},
            }]
        try:
            resp = _create(system, [{"role": "user", "content": content}])
        except anthropic.BadRequestError:
            # Caching/extended-TTL not accepted for this config — never let that
            # break generation: inline the context into the user turn instead.
            merged = ([{"type": "text", "text": cache_prefix}] + content
                      if cache_prefix else content)
            resp = _create(None, [{"role": "user", "content": merged}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return _sanitize_markdown(text)

    # ── Ollama: use the NATIVE API so we can control num_ctx / keep_alive ──
    if provider == "ollama":
        return _sanitize_markdown(
            _call_ollama_native(resolved_model, content, cache_prefix))

    # ── Ollama Cloud: same native API, but on Ollama's hardware (bearer auth).
    # Data leaves the machine — this is the deliberate cloud provider choice.
    if provider == "ollama-cloud":
        return _sanitize_markdown(
            _call_ollama_native(resolved_model, content, cache_prefix, cloud=True))

    # ── Google Gemini (REST, key auth) ──────────────────────────────
    if provider == "gemini":
        return _sanitize_markdown(
            _call_gemini(resolved_model, content, cache_prefix))

    # ── OpenAI-compatible providers (Groq) ──────────────────────────
    import openai as _openai
    import httpx as _httpx

    if provider == "groq":
        base_url = "https://api.groq.com/openai/v1"
        api_key  = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set.")
        timeout  = _httpx.Timeout(120.0, connect=10.0)
    else:
        raise ValueError(f"Unknown provider: {provider!r}")

    # Split the first text block (instructions) into a system message so the
    # model clearly separates its role from the session data being analysed.
    # The project context (cache_prefix) leads the system so its stable prefix
    # can be reused by any provider that caches identical prefixes.
    system_text: str | None = None
    remaining = list(content)
    if remaining and remaining[0].get("type") == "text":
        system_text = remaining.pop(0)["text"]
    if cache_prefix:
        system_text = (cache_prefix + "\n\n" + system_text) if system_text else cache_prefix

    messages: list[dict] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": _to_openai_content(remaining)})

    client_oai = _openai.OpenAI(
        base_url=base_url,
        api_key=api_key,
        http_client=_httpx.Client(timeout=timeout),
    )
    resp_oai = client_oai.chat.completions.create(
        model=resolved_model,
        messages=messages,
        max_tokens=MAX_TOKENS,
    )
    raw = resp_oai.choices[0].message.content or ""
    return _sanitize_markdown(_clean_output(raw))


def _attach_nearest_screenshots(steps: list[dict], events: list[dict],
                                max_gap_s: float = 12.0) -> None:
    """Give screenshot-less steps the nearest-in-time capture.

    With smart capture the watcher saves the imagery as separate ``auto``
    events, so click-anchored steps can end up without a screenshot of their
    own. Each capture is lent to at most one step to keep the report light.
    """
    shot_events = []
    for ev in events:
        if not ev.get("screenshot"):
            continue
        try:
            shot_events.append((_parse_iso(ev["ts"]).timestamp(), ev["screenshot"]))
        except Exception:
            pass
    if not shot_events:
        return
    used = {s.get("screenshot") for s in steps if s.get("screenshot")}
    for step in steps:
        if step.get("screenshot"):
            continue
        try:
            ts = _parse_iso(step["ts"]).timestamp()
        except Exception:
            continue
        best = min(
            ((abs(t - ts), fname) for t, fname in shot_events if fname not in used),
            default=None,
        )
        if best and best[0] <= max_gap_s:
            step["screenshot"] = best[1]
            used.add(best[1])


def _load_steps(session_dir: Path) -> tuple[list[dict], str]:
    """Load and group events. Returns (steps, error_markdown)."""
    events_file = session_dir / "events.jsonl"
    if not events_file.exists():
        return [], "# Error\n\nNo events file found for this session."
    raw = [
        json.loads(line)
        for line in events_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not raw:
        return [], "# Error\n\nThe events log is empty."
    raw = _fuse_web_events(raw)
    steps = group_events_into_steps(raw)
    _attach_nearest_screenshots(steps, raw)
    return steps, ""


# ------------------------------------------------------------------
# Deterministic visual walkthrough (built in code, not by the model)
# ------------------------------------------------------------------

# Control-type names (from Windows UIA) → human words for the walkthrough.
_CONTROL_ES = {
    "Button": "botón", "Edit": "campo", "Hyperlink": "enlace",
    "MenuItem": "menú", "ListItem": "elemento", "TabItem": "pestaña",
    "CheckBox": "casilla", "RadioButton": "opción", "ComboBox": "desplegable",
    "Text": "texto", "Image": "imagen", "TreeItem": "elemento",
}
_CONTROL_EN = {
    "Button": "button", "Edit": "field", "Hyperlink": "link",
    "MenuItem": "menu item", "ListItem": "item", "TabItem": "tab",
    "CheckBox": "checkbox", "RadioButton": "radio button", "ComboBox": "dropdown",
    "Text": "text", "Image": "image", "TreeItem": "item",
}


def _humanize_action(step: dict, language: str) -> str:
    """Return a short, human-readable label for a step.

    Prefers the captured UI element ("Clic en botón «Iniciar sesión»") and
    only falls back to coordinates when no element name is available.
    """
    etype = step.get("type", "")
    text = (step.get("text") or "").strip()
    element = (step.get("element") or "").strip()
    control = (step.get("control") or "").strip()
    window = (step.get("window") or "").strip()
    x, y = step.get("x", 0), step.get("y", 0)
    es = language == "es"
    role = (_CONTROL_ES if es else _CONTROL_EN).get(
        control, control.lower() if control else "")
    repeat = int(step.get("repeat", 1))
    suffix = f" (×{repeat})" if repeat > 1 else ""

    if etype == "click":
        btn = step.get("button", "")
        right = "right" in btn.lower()
        if element:
            what = f"{role} «{element}»" if role else f"«{element}»"
            return (((f"Clic derecho en {what}" if right else f"Clic en {what}") if es
                     else (f"Right-click on {what}" if right else f"Click on {what}"))
                    + suffix)
        where = f" — {window[:40]}" if window else ""
        side = ("derecho" if right else "izquierdo")
        return ((f"Clic {side} en ({x}, {y}){where}" if es
                 else f"{'Right' if right else 'Left'} click at ({x}, {y}){where}")
                + suffix)
    if etype == "scroll":
        return (f"Scroll — {text}" if text else "Scroll")
    if etype == "key":
        field = ""
        if element:
            field = (f" en {role or 'campo'} «{element}»" if es
                     else f" in {role or 'field'} \"{element}\"")
        if text:
            return (f"Escribió «{text}»{field}" if es else f"Typed \"{text}\"{field}")
        return (f"Entrada de teclado{field}" if es else f"Keyboard input{field}")
    if etype == "auto":
        return (text or ("Cambio de pantalla" if es else "Screen changed"))
    if etype == "nav":
        page = (step.get("url") or "").strip() or window
        return (f"Navega a {page[:70]}" if es else f"Navigate to {page[:70]}")
    return text or f"({x}, {y})"


def _encode_image_for_report(img_path: Path, max_w: int = 1366) -> tuple[str, str]:
    """Return (base64, media_type) for embedding in the report.

    Downscales wide screenshots and re-encodes as JPEG to keep reports light
    (full-res PNGs balloon a 9-step report to ~20 MB). Falls back to the raw
    PNG bytes when Pillow is not available.
    """
    try:
        import io
        from PIL import Image

        with Image.open(img_path) as im:
            im = im.convert("RGB")
            # Cap the LONGEST edge (not just width): providers reject images whose
            # width OR height exceeds their per-image limit, so a tall portrait
            # capture must be scaled down too.
            longest = max(im.width, im.height)
            if longest > max_w:
                ratio = max_w / longest
                im = im.resize(
                    (max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                    Image.LANCZOS,
                )
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82, optimize=True)
            return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
    except Exception:
        b64 = base64.standard_b64encode(img_path.read_bytes()).decode("ascii")
        return b64, "image/png"


def build_visual_walkthrough(
    steps: list[dict],
    session_dir: Path,
    language: str = "en",
) -> str:
    """Build a self-contained Markdown walkthrough with one embedded
    screenshot per step. Deterministic — works for every provider because
    the images are placed by code, not produced by the model."""
    es = language == "es"
    heading = "## Recorrido visual paso a paso" if es else "## Visual walkthrough"
    no_img = "_(sin captura para este paso)_" if es else "_(no screenshot for this step)_"

    # Which steps actually have an embeddable image (for cross-references).
    has_img = [
        bool(s.get("screenshot"))
        and (session_dir / "screenshots" / s["screenshot"]).exists()
        for s in steps
    ]

    def _nearest_img_step(i: int) -> int | None:
        best = None
        for j, ok in enumerate(has_img):
            if ok and (best is None or abs(j - i) < abs(best - i)):
                best = j
        return best

    lines = [heading, ""]
    for idx, step in enumerate(steps):
        step_no = idx + 1
        action = _humanize_action(step, language)
        lines.append(f"### {'Paso' if es else 'Step'} {step_no} — {action}")
        lines.append("")
        if has_img[idx]:
            b64, media = _encode_image_for_report(
                session_dir / "screenshots" / step["screenshot"])
            lines.append(
                f"![{'Paso' if es else 'Step'} {step_no}]"
                f"(data:{media};base64,{b64})"
            )
        else:
            # Point the reader to the closest real capture instead of a
            # dead-end "(no screenshot)".
            near = _nearest_img_step(idx)
            if near is not None:
                lines.append(
                    f"_({'la interfaz se aprecia en la captura del Paso' if es else 'see the screenshot of Step'} {near + 1})_"
                )
            else:
                lines.append(no_img)
        lines.append("")
    return "\n".join(lines).strip()


def _report_header(
    session_dir: Path,
    title: str,
    description: str,
    language: str,
) -> str:
    """Build a small metadata header for the top of the report."""
    es = language == "es"
    manifest = {}
    mpath = session_dir / "manifest.json"
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    h1 = title.strip() or ("Reporte de QA" if es else "QA Report")
    lines = [f"# {h1}", ""]
    if description.strip():
        lines += [f"> {description.strip()}", ""]
    meta = []
    started = manifest.get("started_at", "")
    if started:
        meta.append((("Fecha" if es else "Date"), started.replace("T", " ").rstrip("Z")[:19]))
    if manifest.get("event_count") is not None:
        meta.append((("Eventos" if es else "Events"), str(manifest.get("event_count"))))
    if manifest.get("screenshot_count") is not None:
        meta.append((("Capturas" if es else "Screenshots"), str(manifest.get("screenshot_count"))))
    if meta:
        lines.append("| " + " | ".join(k for k, _ in meta) + " |")
        lines.append("|" + "|".join("---" for _ in meta) + "|")
        lines.append("| " + " | ".join(v for _, v in meta) + " |")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Individual section generators
# ------------------------------------------------------------------

def generate_test_cases(
    session_dir: Path,
    language: str = "en",
    title: str = "",
    description: str = "",
    provider: str = "anthropic",
    model: str = "",
    project_context: str = "",
) -> str:
    steps, err = _load_steps(session_dir)
    if err:
        return err
    lang = _lang_instruction(language)
    prefix = _project_prefix(project_context)
    ctx = _context_block(title, description, session_dir)
    vision = _model_has_vision(model or _DEFAULT_MODEL.get(provider, ""))
    max_img, max_w = _image_policy(provider)
    heading = "## Casos de prueba" if language == "es" else "## Test Cases"
    content = [{
        "type": "text",
        "text": (
            f"You are a senior QA engineer. {lang}\n"
            f"{ctx}\n"
            f"Below are the key steps of a recorded QA session (screenshots + actions). "
            f"The session has EXACTLY {len(steps)} steps — never invent steps beyond them.\n"
            "Steps may name the exact UI element interacted with (button, field, link…) "
            "and the window/app — use those names verbatim in your test cases instead "
            "of coordinates.\n"
            f"Start your response with the heading line: {heading} (write it ONCE).\n"
            "Then output ONLY ONE Markdown table — a single header row, then data rows. "
            "Never repeat the heading or the table header. No other prose, no code blocks.\n"
            "Columns: **#** | **Given** | **When** | **Then**\n\n"
            "Rules:\n"
            "- One row per meaningful user action. Merge trivial or duplicate steps, "
            f"but produce at least {max(4, len(steps) // 3)} rows — never collapse "
            "the whole session into one row.\n"
            "- Given: precondition/starting state.\n"
            "- When: the exact action performed (name the real control, e.g. "
            "'clicks the \"Iniciar sesión\" button').\n"
            "- Then: the expected observable result.\n"
            "- Never invent element names; if a step lacks one, describe the visible target.\n"
            "- Do NOT embed images; the report already includes the screenshots separately.\n"
            "- Be concise. No commentary outside the heading and table.\n\n"
            f"{_GROUNDING}"
        ),
    }]
    content.extend(_build_steps_content(
        steps, session_dir, include_images=vision, max_images=max_img,
        max_width=max_w,
    ))
    return _call_ai(provider, model, content, cache_prefix=prefix)


def _parse_expected_lines(raw: str, n: int) -> dict[int, tuple[str, str]]:
    """Parse `N. <expected> | <PASS|UNCLEAR>` lines from the model output.

    Tolerant to the decoration small models add: backticks, bold markers,
    "Paso N:"/"Step N:" prefixes, or table-row formatting (`| 1 | ... |`).
    """
    import re as _re
    out: dict[int, tuple[str, str]] = {}
    for line in raw.splitlines():
        s = line.strip().strip("`").strip()
        s = _re.sub(r"^\|", "", s).strip()            # table-row form
        s = _re.sub(r"^\*+\s*", "", s)                # leading bold markers
        s = _re.sub(r"^(?:paso|step)\s+", "", s, flags=_re.IGNORECASE)
        m = _re.match(r"^(\d+)\s*[.)\-:|]\s*(.+)$", s)
        if not m:
            continue
        idx = int(m.group(1))
        if not (1 <= idx <= n) or idx in out:
            continue
        body = m.group(2).strip()
        status = "[UNCLEAR]"
        if "|" in body:
            # Split off the status cell; keep the longest text cell as body.
            cells = [c.strip() for c in body.split("|")]
            st_cells = [c for c in cells if _re.fullmatch(
                r"\[?\s*(pass|unclear)\s*\]?", c, _re.IGNORECASE)]
            if any("pass" in c.lower() for c in st_cells):
                status = "[PASS]"
            text_cells = [c for c in cells if c and c not in st_cells]
            body = max(text_cells, key=len) if text_cells else ""
        body = body.strip().strip("*").strip("`").replace("|", "/").strip()
        if body:
            out[idx] = (body[:200], status)
    if len(out) < max(1, n // 2):
        # Fallback: models sometimes echo the placeholder ("N. …") or skip
        # numbering entirely. Assign result-looking lines sequentially.
        seq: dict[int, tuple[str, str]] = {}
        idx = 0
        for line in raw.splitlines():
            s = line.strip().strip("`").strip()
            m = _re.match(
                r"^(?:\|?\s*)?(?:[nN\d]+\s*[.)\-:|]\s*)?(.+?)\|\s*\[?\s*(pass|unclear)\s*\]?\s*\|?\s*$",
                s, _re.IGNORECASE)
            if not m:
                continue
            idx += 1
            if idx > n:
                break
            body = m.group(1).strip().strip("*").strip("`").replace("|", "/").strip()
            status = "[PASS]" if m.group(2).lower() == "pass" else "[UNCLEAR]"
            if body:
                seq[idx] = (body[:200], status)
        if len(seq) > len(out):
            out = seq
    if not out and raw.strip():
        # Surface the shape of unparseable output in the container logs.
        print(f"[claude_gen] expected-lines parse miss; raw head: {raw[:300]!r}",
              flush=True)
    return out


def generate_test_plan(
    session_dir: Path,
    language: str = "en",
    title: str = "",
    description: str = "",
    provider: str = "anthropic",
    model: str = "",
    project_context: str = "",
) -> str:
    """Test plan with a DETERMINISTIC skeleton.

    The Action column is built in code from the recorded events (real element
    names — cannot be hallucinated, steps cannot be dropped or collapsed). The
    model only fills what it is genuinely good at: the expected observable
    result per step, and whether the evidence proves it. Small local models
    used to collapse the whole session into one invented row; this makes that
    structurally impossible.
    """
    steps, err = _load_steps(session_dir)
    if err:
        return err
    lang = _lang_instruction(language)
    prefix = _project_prefix(project_context)
    ctx = _context_block(title, description, session_dir)
    vision = _model_has_vision(model or _DEFAULT_MODEL.get(provider, ""))
    max_img, max_w = _image_policy(provider)
    es = language == "es"
    heading = "## Plan de pruebas" if es else "## Test Plan"

    content = [{
        "type": "text",
        "text": (
            f"You are a senior QA engineer. {lang}\n"
            f"{ctx}\n"
            f"Below are the {len(steps)} steps of a recorded QA session "
            "(some include screenshots).\n"
            "For EACH numbered step, write EXACTLY one line: the step number, a "
            "period, the expected observable result, then ' | PASS' or ' | UNCLEAR'.\n"
            "Example of the required output FORMAT (do NOT copy these texts — "
            "write what each real step below should produce):\n"
            "1. <result of step 1> | PASS\n"
            "2. <result of step 2> | UNCLEAR\n"
            "Use PASS only when a screenshot or later step proves the result; "
            "otherwise UNCLEAR.\n"
            f"Output exactly {len(steps)} lines numbered 1 to {len(steps)}. "
            "No heading, no table, no extra prose.\n\n"
            f"{_GROUNDING}"
        ),
    }]
    content.extend(_build_steps_content(
        steps, session_dir, include_images=vision, max_images=max_img,
        max_width=max_w,
    ))
    try:
        expected = _parse_expected_lines(
            _call_ai(provider, model, content, cache_prefix=prefix), len(steps))
    except Exception:
        expected = {}

    fallback = ("Por verificar" if es else "To be verified")
    cols = (("Paso", "Acción", "Resultado esperado", "Estado") if es
            else ("Step", "Action", "Expected Result", "Status"))
    lines = [heading, ""]
    lines.append("| **" + "** | **".join(cols) + "** |")
    lines.append("|" + "---|" * len(cols))
    for i, step in enumerate(steps, start=1):
        action = _humanize_action(step, language).replace("|", "/")
        exp, status = expected.get(i, (fallback, "[UNCLEAR]"))
        lines.append(f"| {i} | {action} | {exp} | {status} |")
    return "\n".join(lines)


def generate_jira_ticket(
    session_dir: Path,
    language: str = "en",
    title: str = "",
    description: str = "",
    provider: str = "anthropic",
    model: str = "",
    project_context: str = "",
) -> str:
    steps, err = _load_steps(session_dir)
    if err:
        return err
    lang = _lang_instruction(language)
    prefix = _project_prefix(project_context)
    vision = _model_has_vision(model or _DEFAULT_MODEL.get(provider, ""))
    max_img, max_w = _image_policy(provider)

    title_line = f"**Title:** {title}" if title else "**Title:** (infer from session)"
    desc_line  = f"**Description:** {description}" if description else ""
    narration  = _load_transcript(session_dir)
    narr_line  = (
        f"Tester's spoken narration (transcribed):\n\"\"\"\n{narration}\n\"\"\"\n"
        if narration else ""
    )

    screenshot_instruction = "(refer to steps by number — do not embed images)"
    content = [{
        "type": "text",
        "text": (
            f"You are a senior QA engineer writing a Jira ticket. {lang}\n\n"
            f"{title_line}\n"
            f"{desc_line}\n"
            f"{narr_line}\n"
            "Below are the key steps of a recorded QA session.\n"
            "Steps may name the exact UI element and page — use those names "
            "in the reproduction steps (never coordinates).\n"
            "Write each reproduction step as a SHORT imperative action "
            "(e.g. 'Click the \"Apply\" button'). NEVER copy the bracketed "
            "technical metadata ([page: … | window: …]) into the ticket.\n"
            "Produce ONLY a Jira-ready Markdown ticket with exactly these fields:\n\n"
            "## Jira Ticket\n"
            "| Field | Value |\n"
            "|-------|-------|\n"
            "| **Title** | ... |\n"
            "| **Type** | Bug / Story / Task |\n"
            "| **Priority** | Critical / High / Medium / Low |\n"
            "| **Labels** | ... |\n\n"
            "**Description**\n"
            "(2-3 sentences summarising what was tested and what the outcome was)\n\n"
            "**Steps to Reproduce**\n"
            "1. ...\n\n"
            "**Expected Result**\n"
            "(what should happen)\n\n"
            "**Actual Result**\n"
            "(what happened instead, if a defect was found; otherwise write N/A)\n\n"
            "**Screenshots**\n"
            f"{screenshot_instruction}\n\n"
            "Be concise. Only output the ticket — no extra commentary.\n\n"
            f"{_GROUNDING}"
        ),
    }]
    content.extend(_build_steps_content(
        steps, session_dir, include_images=vision, max_images=max_img,
        max_width=max_w,
    ))
    return _call_ai(provider, model, content, cache_prefix=prefix)


# ------------------------------------------------------------------
# Additional test cases (iterative, avoids duplicating existing ones)
# ------------------------------------------------------------------

def _strip_report_images(report: str) -> str:
    """Remove embedded data-URI images so the report fits in a text prompt."""
    import re as _re
    return _re.sub(r"!\[[^\]]*\]\(data:image/[^)]*\)", "(screenshot)", report)


def generate_more_test_cases(
    session_dir: Path,
    existing_report: str,
    language: str = "en",
    count: int = 5,
    title: str = "",
    description: str = "",
    provider: str = "anthropic",
    model: str = "",
    project_context: str = "",
) -> str:
    """Generate ``count`` NEW test cases that extend (not repeat) the report.

    Focus: edge cases, negative paths, boundary values and non-functional
    checks the recorded happy path did not cover. Returns a Markdown section.
    """
    steps, err = _load_steps(session_dir)
    if err:
        return err
    lang = _lang_instruction(language)
    prefix = _project_prefix(project_context)
    ctx = _context_block(title, description, session_dir)
    vision = _model_has_vision(model or _DEFAULT_MODEL.get(provider, ""))
    max_img, max_w = _image_policy(provider)
    # Existing cases as text only — images would blow up the prompt.
    prior = _strip_report_images(existing_report)
    if len(prior) > 12000:
        prior = prior[:12000] + " …"
    heading = ("## Casos de prueba adicionales" if language == "es"
               else "## Additional Test Cases")
    content = [{
        "type": "text",
        "text": (
            f"You are a senior QA engineer expanding an existing test suite. {lang}\n"
            f"{ctx}\n"
            "Here is the CURRENT report generated for this session:\n"
            f"\"\"\"\n{prior}\n\"\"\"\n\n"
            f"Write exactly {count} NEW test cases that are NOT already covered above.\n"
            "Prioritise: negative paths, edge cases, boundary values, input validation, "
            "error handling, permissions, and usability/accessibility checks relevant "
            "to the screens shown.\n"
            f"Start your response with the heading line: {heading}\n"
            "Then output ONLY a Markdown table — no other prose, no code blocks.\n"
            "Columns: **#** | **Given** | **When** | **Then**\n"
            "Number rows continuing after the existing cases. Never repeat or trivially "
            "rephrase an existing case.\n\n"
            f"{_GROUNDING}"
        ),
    }]
    content.extend(_build_steps_content(
        steps, session_dir, include_images=vision, max_images=max_img,
        max_width=max_w,
    ))
    return _call_ai(provider, model, content, cache_prefix=prefix)


# ------------------------------------------------------------------
# Free-form prose/list sections (summary, steps-to-reproduce, bug report)
# ------------------------------------------------------------------

def _generate_freeform(
    session_dir: Path,
    heading: str,
    instructions: str,
    language: str = "en",
    title: str = "",
    description: str = "",
    provider: str = "anthropic",
    model: str = "",
    project_context: str = "",
) -> str:
    """Shared scaffold for prose/list sections: standard QA context + steps +
    grounding, with a per-section heading and body instruction."""
    steps, err = _load_steps(session_dir)
    if err:
        return err
    lang = _lang_instruction(language)
    prefix = _project_prefix(project_context)
    ctx = _context_block(title, description, session_dir)
    vision = _model_has_vision(model or _DEFAULT_MODEL.get(provider, ""))
    max_img, max_w = _image_policy(provider)
    content = [{
        "type": "text",
        "text": (
            f"You are a senior QA engineer. {lang}\n"
            f"{ctx}\n"
            f"Below are the {len(steps)} steps of a recorded QA session "
            "(some include screenshots). Steps may name the exact UI element and "
            "page — use those names verbatim, never coordinates. Never copy the "
            "bracketed technical metadata ([page: … | window: …]) into your output.\n"
            f"Start your response with the heading line: {heading} (write it ONCE).\n"
            f"{instructions}\n\n"
            f"{_GROUNDING}"
        ),
    }]
    content.extend(_build_steps_content(
        steps, session_dir, include_images=vision, max_images=max_img,
        max_width=max_w,
    ))
    return _call_ai(provider, model, content, cache_prefix=prefix)


def generate_summary(session_dir: Path, language: str = "en", title: str = "",
                     description: str = "", provider: str = "anthropic",
                     model: str = "", project_context: str = "") -> str:
    """Short prose overview: what was tested, the flow, and the outcome."""
    es = language == "es"
    heading = "## Resumen" if es else "## Summary"
    instructions = (
        "Write 2–4 sentences of plain prose (no lists, no table) explaining what "
        "was tested, the flow the user went through, and the final outcome. "
        "If the outcome cannot be verified from the evidence, say so explicitly."
    )
    return _generate_freeform(session_dir, heading, instructions, language,
                              title, description, provider, model, project_context)


def generate_steps_to_reproduce(session_dir: Path, language: str = "en",
                                title: str = "", description: str = "",
                                provider: str = "anthropic", model: str = "",
                                project_context: str = "") -> str:
    """A clean numbered list of imperative reproduction steps."""
    es = language == "es"
    heading = "## Pasos para reproducir" if es else "## Steps to Reproduce"
    instructions = (
        "Output ONLY a numbered list of short imperative reproduction steps "
        "(e.g. '1. Click the \"Login\" button', '2. Enter the email address'). "
        "One line per meaningful user action; merge trivial or duplicate steps. "
        "No table, no headings other than the one above, no extra prose."
    )
    return _generate_freeform(session_dir, heading, instructions, language,
                              title, description, provider, model, project_context)


def generate_bug_report(session_dir: Path, language: str = "en", title: str = "",
                        description: str = "", provider: str = "anthropic",
                        model: str = "", project_context: str = "") -> str:
    """A concise bug report: summary, severity, repro steps, expected vs actual."""
    es = language == "es"
    heading = "## Reporte de bug" if es else "## Bug Report"
    if es:
        instructions = (
            "Produce SOLO un reporte de bug en Markdown con exactamente estas "
            "secciones (usa **negrita** en las etiquetas):\n"
            "**Resumen**: 1–2 frases del problema.\n"
            "**Severidad**: Crítica / Alta / Media / Baja.\n"
            "**Pasos para reproducir**: lista numerada de acciones imperativas.\n"
            "**Resultado esperado**: lo que debería ocurrir.\n"
            "**Resultado actual**: lo que ocurrió (si no se detectó defecto, escribe N/A).\n"
            "Sin comentarios fuera de esas secciones."
        )
    else:
        instructions = (
            "Produce ONLY a Markdown bug report with exactly these sections "
            "(bold the labels):\n"
            "**Summary**: 1–2 sentences describing the problem.\n"
            "**Severity**: Critical / High / Medium / Low.\n"
            "**Steps to Reproduce**: a numbered list of imperative actions.\n"
            "**Expected Result**: what should happen.\n"
            "**Actual Result**: what happened (if no defect was found, write N/A).\n"
            "No commentary outside those sections."
        )
    return _generate_freeform(session_dir, heading, instructions, language,
                              title, description, provider, model, project_context)


def generate_exploratory(session_dir: Path, language: str = "en", title: str = "",
                         description: str = "", provider: str = "anthropic",
                         model: str = "", project_context: str = "") -> str:
    """Exploratory-testing analysis of the session — written to double as
    reusable project knowledge (areas, behaviour, risks, coverage gaps)."""
    es = language == "es"
    heading = "## Testing exploratorio" if es else "## Exploratory Testing"
    if es:
        instructions = (
            "Actúa como un tester exploratorio senior analizando esta sesión. "
            "Produce notas en Markdown, útiles como CONOCIMIENTO REUTILIZABLE del "
            "proyecto, con exactamente estas subsecciones (usa ### en cada una):\n"
            "### Charter\nQué área/funcionalidad se exploró y con qué objetivo.\n"
            "### Áreas y funcionalidades observadas\nViñetas de las pantallas, "
            "flujos y elementos vistos, y cómo se comportan.\n"
            "### Observaciones\nComportamientos notables, estados, validaciones, "
            "mensajes — solo lo que la evidencia muestra.\n"
            "### Riesgos y posibles problemas\nZonas frágiles o dudosas (marca con "
            "[UNCLEAR] lo no verificable).\n"
            "### Cobertura y siguientes pruebas sugeridas\nQué faltó probar y qué "
            "casos valdría la pena explorar después.\n"
            "Sé concreto y conciso; no inventes nada fuera de la evidencia."
        )
    else:
        instructions = (
            "Act as a senior exploratory tester analysing this session. Produce "
            "Markdown notes useful as REUSABLE PROJECT KNOWLEDGE, with exactly "
            "these subsections (use ### for each):\n"
            "### Charter\nWhich area/feature was explored and the goal.\n"
            "### Areas & features observed\nBullets of the screens, flows and "
            "elements seen, and how they behave.\n"
            "### Observations\nNotable behaviours, states, validations, messages — "
            "only what the evidence shows.\n"
            "### Risks & potential issues\nFragile or questionable areas (mark "
            "unverifiable ones with [UNCLEAR]).\n"
            "### Coverage & suggested next tests\nWhat was not covered and which "
            "cases are worth exploring next.\n"
            "Be concrete and concise; never invent anything beyond the evidence."
        )
    return _generate_freeform(session_dir, heading, instructions, language,
                              title, description, provider, model, project_context)


# ------------------------------------------------------------------
# Combined entry point (called by main.py)
# ------------------------------------------------------------------

# Ordered so the report reads top-down: overview → repro → cases → plan → defects.
_SECTION_GENERATORS = {
    "summary":            generate_summary,
    "steps_to_reproduce": generate_steps_to_reproduce,
    "exploratory":        generate_exploratory,
    "test_cases":         generate_test_cases,
    "test_plan":          generate_test_plan,
    "bug_report":         generate_bug_report,
    "jira":               generate_jira_ticket,
}
_SECTION_ORDER = list(_SECTION_GENERATORS.keys())
VALID_SECTIONS = set(_SECTION_GENERATORS.keys())


def generate_qa_docs(
    session_dir: Path,
    language: str = "en",
    title: str = "",
    description: str = "",
    sections: list[str] | None = None,
    provider: str = "anthropic",
    model: str = "",
    project_context: str = "",
) -> str:
    """
    Generate one or more report sections and concatenate them.

    sections: list of "test_cases", "test_plan", "jira".
              Defaults to all three if None or empty.
    provider: "anthropic" | "ollama" | "groq"
    model:    specific model name; empty string = use provider default
    """
    if not sections:
        sections = ["summary", "steps_to_reproduce", "test_cases"]

    parts: list[str] = []

    # Metadata header (deterministic)
    header = _report_header(session_dir, title, description, language)
    if header:
        parts.append(header)

    kwargs = dict(
        session_dir=session_dir,
        language=language,
        title=title,
        description=description,
        provider=provider,
        model=model,
        project_context=project_context,   # optional; "" when the project has none
    )

    # Generate the requested sections in a stable, readable order. One flaky
    # section (local models drop mid-run) must not throw away the minutes of
    # work already done on the previous ones — record the error inline and
    # keep going. Only when EVERY section failed is the whole run an error.
    requested = set(sections)
    errors: list[str] = []
    attempted = 0
    for key in _SECTION_ORDER:
        if key in requested:
            attempted += 1
            try:
                parts.append(_SECTION_GENERATORS[key](**kwargs))
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                es = language == "es"
                parts.append(
                    (f"## {key}\n\n> ⚠ Esta sección no se pudo generar: {exc}")
                    if es else
                    (f"## {key}\n\n> ⚠ This section could not be generated: {exc}")
                )
    if attempted and len(errors) == attempted:
        raise RuntimeError(errors[0])

    # Deterministic visual walkthrough with one screenshot per step — appended
    # last so the AI-written analysis comes first, the evidence after.
    steps, err = _load_steps(session_dir)
    if not err and steps:
        parts.append(build_visual_walkthrough(steps, session_dir, language))

    return "\n\n---\n\n".join(parts)
