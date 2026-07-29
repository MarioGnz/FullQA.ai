"""
playwright_gen.py — Deterministic, professional Playwright codegen.

No AI involved: the spec is assembled from the events the agent + browser
extension captured (CSS selectors, roles, accessible names, values, URLs).
The output follows Playwright best practices so it reads like hand-written,
review-ready code:

  * `@playwright/test` with `test.describe` + a meaningful test title
  * every logical action wrapped in `test.step(...)` for readable traces
  * user-facing, auto-waiting locators preferred:
        getByRole → getByLabel → getByPlaceholder → getByText → locator(css)
  * web-first assertions (`await expect(...)`) after navigation and input
  * no hard waits / no `waitForTimeout` — Playwright auto-waits
  * coordinate-only actions (desktop apps, unnamed elements) become clearly
    marked TODO steps instead of brittle `mouse.click(x, y)` calls

Precision mirrors capture quality: web steps recorded with the browser
extension produce real locators; desktop-only steps become TODOs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from claude_gen import _clean_url, _fuse_web_events, _is_own_app_event, _ts_or_none

# Browser-internal pages that appear as navs but are never part of the flow.
_NOISE_URL_RE = re.compile(r"chrome://|edge://|about:blank|/warmup\.html", re.I)

# UIA control types / web roles → Playwright ARIA roles.
_ROLE_MAP = {
    "button": "button", "link": "link", "hyperlink": "link",
    "checkbox": "checkbox", "radio": "radio", "radiobutton": "radio",
    "textbox": "textbox", "edit": "textbox", "combobox": "combobox",
    "tab": "tab", "tabitem": "tab", "menuitem": "menuitem",
    "listitem": "listitem", "option": "option", "dataitem": "row",
}

_TYPING_KEYS = {"enter": "Enter", "tab": "Tab", "escape": "Escape"}

# Credential-shaped fields. Passwords are never captured (by design), so the
# spec reads them from env vars (qa-scripts/.env, git-ignored) at run time:
#   QA_BASE_URL · QA_USERNAME · QA_PASSWORD
_PASS_RE = re.compile(r"pass|pwd|contrase|secret|token|\bpin\b", re.I)
_USER_RE = re.compile(r"e-?mail|correo|usuario|user(name)?\b|login|account", re.I)

# Dismiss buttons of toasts/banners: they may legitimately not appear on
# replay (different timing), so their click must be best-effort, not fatal.
_DISMISS_RE = re.compile(
    r"^(cerrar|close|dismiss|aceptar|ok|got it|entendido|×|x)$", re.I)

# Login/submit controls. Clicking one right after typing credentials kicks off
# auth + a redirect; without an explicit settle wait the next step raced the
# login and clicked on the OLD page (the reported "no hace los wait" failure).
_SUBMIT_RE = re.compile(
    r"sign ?in|sign ?up|log ?in|log ?on|iniciar|entrar|acceder|ingresar|"
    r"submit|continu(e|ar)|siguiente|next|acceso|access", re.I)

# Settle wait emitted after a login submit (and other app-changing actions):
# resolves as soon as the network goes quiet, and NEVER fails the test — SPAs
# with live sockets time out on networkidle, hence the catch.
_SETTLE_WAIT = ("await page.waitForLoadState('networkidle', "
                "{ timeout: 15_000 }).catch(() => { /* SPA keeps the network busy */ });")


def _field_hint(step: dict) -> str:
    """Concatenated identifying strings of a field, for credential detection."""
    hint = " ".join(
        str(step.get(k) or "")
        for k in ("element", "label", "placeholder", "selector", "name")
    )
    # UIA verified the field is a password box — stronger than any name regex.
    if step.get("is_password"):
        hint += " password"
    return hint


def _esc(text: str) -> str:
    """Escape a string for a single-quoted TS literal (bounded length).

    Newlines are collapsed to spaces — a session name with a line break was
    emitted verbatim into test('…') and broke the whole spec at parse time.
    """
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat.replace("\\", "\\\\").replace("'", "\\'")[:120]


def _esc_re(text: str) -> str:
    """Escape a string for use inside a `/.../ ` TS regex literal.

    Whitespace runs (incl. newlines — a literal newline inside /…/ is a TS
    parse error) become `\\s+`, which also matches the normalized accessible
    name Playwright compares against.
    """
    flat = re.sub(r"[.*+?^${}()|[\]\\/]", lambda m: "\\" + m.group(0),
                  (text or "").strip())
    return re.sub(r"\s+", r"\\s+", flat)


def _role_of(step: dict) -> str | None:
    return _ROLE_MAP.get((step.get("control") or "").strip().lower())


# Roles a Playwright ``.fill()`` can actually target — a fill on anything else
# (button/link/checkbox…) can never match a real input and just times out.
_FILLABLE_ROLES = {"textbox", "searchbox", "spinbutton", "combobox"}


# Browser-chrome UI (address bar etc.) in common locales.
_ADDRESS_BAR_RE = re.compile(
    r"barra de direcciones|address and search|address bar|omnibox", re.I)
_URLISH_RE = re.compile(r"^(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?$", re.I)


def _is_browser_chrome(ev: dict) -> bool:
    """Interactions with the BROWSER UI (address bar…), not the page.

    Typing a URL into the address bar was being emitted as a page fill on a
    locator that can never exist in the DOM — an instant 30s timeout that
    killed the run. Navigation itself is already covered by goto()/nav events.
    """
    if (ev.get("selector") or "").strip():
        return False                    # the extension saw it → it's in the page
    if _ADDRESS_BAR_RE.search(ev.get("element") or ""):
        return True
    # Typing whose content is a URL/domain into a bare browser Edit control.
    if ev.get("type") == "key" and (ev.get("control") or "") == "Edit":
        val = (ev.get("value") or ev.get("text") or "").strip()
        if val and _URLISH_RE.match(val):
            return True
    # Click on an address-bar autocomplete suggestion: a browser ListItem whose
    # name embeds the target URL ("Page Title  app.example.com").
    if (ev.get("type") == "click"
            and (ev.get("control") or "") in ("ListItem", "List")):
        name = ev.get("element") or ""
        if any(_URLISH_RE.match(tok) for tok in name.split()):
            return True
    # Enter pressed with no real input focused (UIA reports the page Document):
    # that's the address-bar Enter that loaded the page. Replaying it on the
    # page body can submit an autofocused form EMPTY — a premature submit that
    # wiped the login. Page Enters arrive via the extension with the real
    # target element instead.
    if (ev.get("type") == "key"
            and (ev.get("control") or "") == "Document"
            and (ev.get("text") or "").lower().startswith("key.")):
        return True
    return False


def _is_page_title_name(step: dict, name: str) -> bool:
    """True when the captured 'element' is really the window/page title.

    When a control exposes no accessible name, UIA falls back to the document
    title, so the fused event carries e.g. element="My Product Suite® -
    Item Catalo" — a name no real control has. A locator built from it can
    never match and times out, killing the whole run at that step.
    """
    if not name or len(name) < 12:
        return False
    # Compare on a normalized form: the native (UIA) and web captures encode
    # symbols differently ("Suite®" vs "SuiteÂ®"), which silently broke the
    # startswith comparison and let title-clicks through as locators.
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    n = _norm(name)
    if not n:
        return False
    for t in (step.get("window") or "", step.get("title") or ""):
        tn = _norm(t)
        if tn and (tn.startswith(n) or n.startswith(tn)):
            return True
    return False


def _locator(step: dict, fillable: bool = False) -> str | None:
    """Best Playwright locator for a step, or None if we lack usable data.

    Prefers user-facing locators (role/name), which survive DOM refactors far
    better than CSS paths, and falls back progressively.

    ``fillable=True`` means the locator will be used for ``.fill()``. UIA (and
    fused web events) sometimes mislabel a text input's control — e.g. an email
    field captured as a "button" — which would emit a role no ``.fill()`` can
    ever match. When we have an accessible name, coerce such a role to
    ``textbox`` (the input the name actually points at) instead.
    """
    role = _role_of(step)
    name = (step.get("element") or "").strip()
    placeholder = (step.get("placeholder") or "").strip()
    label = (step.get("label") or "").strip()
    selector = (step.get("selector") or "").strip()

    if _is_page_title_name(step, name):
        name = ""          # document title, not a control name — never usable

    # If the "name" is just an id/name ATTRIBUTE echoed by the capture (it
    # appears inside the CSS selector, e.g. element='group-action' with
    # selector='[name="group-action"]'), no role locator can match it — the
    # accessible name of that control is something else (often empty). The
    # selector is the truth there.
    if name and selector and name.lower() in selector.lower():
        return f"page.locator('{_esc(selector)}')"

    if fillable and name and (not role or role not in _FILLABLE_ROLES):
        role = "textbox"

    if role and name:
        if role == "row":
            # A row's accessible name concatenates ALL its cells — the captured
            # name is just the cell the user saw, so anchoring can never match.
            # Substring + first(): rows sharing that text are interchangeable
            # for a recorded click.
            return (f"page.getByRole('row', "
                    f"{{ name: '{_esc(name)}' }}).first()")
        if len(name) < 80:
            # Whole-name matching that still tolerates decoration around the
            # text. Substring (the default) matches supersets — 'Item
            # List' also hit 'Add to Item List' (strict-mode
            # violation). exact:true broke on invisible icon-font glyphs in
            # the accessible name (link " AC DC"). The anchored regex accepts
            # non-word padding at the edges and nothing more.
            return (f"page.getByRole('{role}', "
                    f"{{ name: /^\\W*{_esc_re(name)}\\W*$/i }})")
        # Name hit the 80-char capture truncation — it's a prefix; keep the
        # default substring matching.
        return f"page.getByRole('{role}', {{ name: '{_esc(name)}' }})"
    if label:
        return f"page.getByLabel('{_esc(label)}')"
    if placeholder:
        return f"page.getByPlaceholder('{_esc(placeholder)}')"
    if selector:
        return f"page.locator('{_esc(selector)}')"
    if name:
        return f"page.getByText('{_esc(name)}', {{ exact: false }})"
    return None


def _human_target(step: dict) -> str:
    """Short human label for a step's target, for readable step titles."""
    name = (step.get("element") or "").strip()
    if name:
        return f'"{name[:50]}"'
    role = _role_of(step)
    if role:
        return f"the {role}"
    sel = (step.get("selector") or "").strip()
    return f"`{sel[:40]}`" if sel else "the element"


def _url_assertion(url: str) -> str | None:
    """A resilient URL assertion keyed on host + first path segment.

    Uses expect.poll(() => pg.url()) instead of expect(page).toHaveURL so it
    re-reads the CURRENT page on every retry — clicks that open a new tab
    reassign ``pg`` an instant after the click, and a frozen page reference
    would keep asserting against the old tab.
    """
    m = re.match(r"^https?://([^/]+)(/[^?#]*)?", url)
    if not m:
        return None
    host = m.group(1)
    path = (m.group(2) or "").rstrip("/")
    # First path segment only — deep paths / ids change between runs.
    seg = ""
    if path:
        parts = [p for p in path.split("/") if p]
        if parts:
            seg = "/" + parts[0]
    pattern = _esc_re(host + seg)
    return (f"await expect.poll(() => pg.url(), {{ timeout: 15_000 }})"
            f".toMatch(/{pattern}/);")


def generate_playwright(
    session_dir: Path,
    language: str = "es",
    name: str = "",
    project: str = "",
) -> str:
    """Build a professional Playwright spec from the session's fused events."""
    es = language == "es"
    events_file = session_dir / "events.jsonl"
    if not events_file.exists():
        return "// No events file found for this session."
    raw = [
        json.loads(line)
        for line in events_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = [e for e in _fuse_web_events(raw) if not _is_own_app_event(e)]

    steps_ts: list[str] = []          # rendered `test.step(...)` blocks
    first_url: str | None = None
    last_signature: str | None = None
    last_fill_loc: str | None = None  # locator of the previous step IF it was a fill
    last_was_nav = False              # previous emitted step was a navigation
    uses_env = False                  # spec reads QA_* env vars → note in header
    creds_pending = False             # credentials typed, submit not yet seen
    password_done = False             # a QA_PASSWORD fill has been emitted
    # A submit click captured BEFORE the password fill (UIA timestamp lag puts
    # the "Log In" echo first) is held back and emitted right after the fill —
    # otherwise the replay submits the form with an empty password.
    deferred_submit: tuple[str, list[str], float | None] | None = None

    def step(title: str, body_lines: list[str],
             fill_loc: str | None = None, is_nav: bool = False) -> None:
        """Append a test.step block, collapsing immediate duplicates.

        ``fill_loc``: locator this step fills. Consecutive fills on the SAME
        field keep only the LAST one — slow typing produces several
        partial-value bursts for one field, and a password field gets a fill
        from both its click and its typing event. Replaying every partial fill
        pastes into the field repeatedly and ends on a stale value.
        """
        nonlocal last_signature, last_fill_loc, last_was_nav
        if fill_loc is not None and fill_loc == last_fill_loc and steps_ts:
            steps_ts.pop()            # supersede the previous fill of this field
            last_signature = None
        sig = title + "".join(body_lines)
        if sig == last_signature:
            return
        last_signature = sig
        block = [f"    await test.step('{_esc(title)}', async () => {{"]
        block += [f"      {ln}" for ln in body_lines]
        block.append("    });")
        steps_ts.append("\n".join(block))
        last_fill_loc = fill_loc
        last_was_nav = is_nav

    # Starting URL: the first event carrying any url (clicks/keys carry the page
    # url too, not just nav events). Recordings that begin on an already-loaded
    # page never emit an initial `nav`, so without this the first action runs on
    # about:blank. Emit the opening goto up-front, before any action.
    for ev in events:
        u = _clean_url(ev.get("url") or "")
        if u and not _NOISE_URL_RE.search(u):
            first_url = u
            body = [f"await page.goto('{_esc(u)}');"]
            a = _url_assertion(u)
            if a:
                body.append(a)
            step(f"Open {u}", body, is_nav=True)
            break

    # A `toHaveURL` assertion only makes sense when something in the REPLAY
    # triggers the navigation (a click/Enter we emitted). Navs the user caused
    # by hand (address bar) must become page.goto(), and redirect chains right
    # after another nav are already covered — asserting them would wait forever.
    last_action_ts: float | None = None   # ts of the last emitted click/Enter
    last_nav_ts: float | None = None
    ACTION_NAV_WINDOW = 8.0                # nav within 8s of an action = its result
    REDIRECT_WINDOW = 3.0                  # nav within 3s of a nav = redirect chain

    def _flush_deferred() -> None:
        nonlocal deferred_submit, last_action_ts, creds_pending
        if deferred_submit is not None:
            title, body, dts = deferred_submit
            deferred_submit = None
            step(title, body)
            creds_pending = False      # the submit consumed the credentials
            if dts is not None:
                last_action_ts = dts

    def _password_later(i: int, ets: float | None) -> bool:
        """A password click/fill event follows within a few seconds."""
        if ets is None:
            return False
        for nxt in events[i + 1:]:
            nts = _ts_or_none(nxt)
            if nts is None:
                continue
            if nts - ets > 6.0:
                break
            if (nxt.get("type") in ("click", "key")
                    and _PASS_RE.search(_field_hint(nxt))):
                return True
        return False

    for i, ev in enumerate(events):
        etype = ev.get("type", "")
        url = _clean_url(ev.get("url") or "")
        ets = _ts_or_none(ev)

        # Address bar & co.: browser UI, not the page — never a page action.
        if etype in ("click", "key") and _is_browser_chrome(ev):
            continue

        if etype == "nav":
            # A held-back submit must run before its own navigation.
            _flush_deferred()
            if url and _NOISE_URL_RE.search(url):
                continue
            if first_url is None and url:
                first_url = url
                body = [f"await page.goto('{_esc(url)}');"]
                assertion = _url_assertion(url)
                if assertion:
                    body.append(assertion)
                step(f"Open {url}", body, is_nav=True)
            elif url:
                assertion = _url_assertion(url)
                caused_by_action = (
                    ets is not None and last_action_ts is not None
                    and 0 <= ets - last_action_ts <= ACTION_NAV_WINDOW)
                redirect_chain = (
                    ets is not None and last_nav_ts is not None
                    and 0 <= ets - last_nav_ts <= REDIRECT_WINDOW)
                if caused_by_action:
                    body = [assertion] if assertion else [
                        f"await page.waitForURL('{_esc(url)}**');"]
                    # The URL matching is not enough: the new document may
                    # still be parsing — wait for the DOM before acting on it.
                    body.append("await page.waitForLoadState('domcontentloaded')"
                                ".catch(() => {});")
                    step(f"Navigate to {url}", body, is_nav=True)
                elif redirect_chain:
                    pass          # the app navigated on its own — nothing to do
                elif url == first_url and len(steps_ts) <= 1:
                    pass          # duplicate of the opening goto — skip
                else:
                    # User navigated by hand — replay it explicitly.
                    body = [f"await page.goto('{_esc(url)}');"]
                    if assertion:
                        body.append(assertion)
                    step(f"Go to {url}", body, is_nav=True)
            if ets is not None:
                last_nav_ts = ets
            continue

        if etype == "click":
            # Clicks on the page background (UIA reports the Document control)
            # with no web selector are focus/dismiss noise, not actions — and
            # when UIA also fails to give a window title, their "name" (the
            # page title) slipped through as an un-matchable getByText locator.
            if ((ev.get("control") or "") == "Document"
                    and not (ev.get("selector") or "").strip()):
                continue
            loc = _locator(ev)
            role = _role_of(ev)
            # Password fields never produce input events (values are not
            # captured, by design) — the click on the field is the only trace.
            # Emit the fill from QA_PASSWORD so the flow actually works.
            if (loc and role not in ("button", "link", "checkbox", "radio")
                    and _PASS_RE.search(_field_hint(ev))):
                uses_env = True
                creds_pending = True
                password_done = True
                floc = _locator(ev, fillable=True) or loc   # never fill a non-input
                step(f"Fill {_human_target(ev)} (value from QA_PASSWORD)", [
                    f"await {floc}.click();",
                    f"await {floc}.fill(process.env.QA_PASSWORD ?? '');",
                ], fill_loc=floc)
                _flush_deferred()      # the submit that was waiting on this fill
            elif loc and _DISMISS_RE.match((ev.get("element") or "").strip()):
                # Toast/banner dismissals are timing-dependent: the toast the
                # user closed may never appear on replay. Try briefly, move on.
                step(f"Click {_human_target(ev)} (if present)", [
                    f"await {loc}.click({{ timeout: 3000 }})"
                    ".catch(() => { /* toast already gone */ });",
                ])
                last_action_ts = ets
            elif loc:
                ename = (ev.get("element") or "").strip()
                is_submit = bool(_SUBMIT_RE.search(ename)) or (
                    creds_pending and role in ("button", "link"))
                body = [f"await {loc}.click();"]
                if is_submit:
                    # Login/submit: hold the replay until the app settles —
                    # otherwise the next step runs against the pre-login page.
                    body.append(_SETTLE_WAIT)
                    if creds_pending and not password_done \
                            and _password_later(i, ets):
                        # Captured before the password fill — emit it after.
                        deferred_submit = (f"Click {_human_target(ev)}",
                                           body, ets)
                        creds_pending = False
                        continue
                    creds_pending = False
                step(f"Click {_human_target(ev)}", body)
                last_action_ts = ets
            else:
                where = (ev.get("window") or "")[:50]
                todo = (f"// TODO: click at ({ev.get('x')}, {ev.get('y')})"
                        + (f" — {where}" if where else "")
                        + " — add a proper locator (no web selector captured).")
                step("Manual step (no web selector)", [todo])
                # NOTE: a TODO performs nothing at runtime, so a nav that
                # followed this click must be replayed with goto — don't mark
                # it as an action.
            continue

        if etype == "key":
            text = (ev.get("text") or "").strip()
            value = (ev.get("value") or "").strip()
            # Checkbox / radio state changes arrive as value "checked" /
            # "unchecked" (from the extension). They are check()/uncheck()
            # actions — a .fill('checked') is invalid and aborts the run.
            if value in ("checked", "unchecked"):
                cloc = _locator(ev)          # keep the real checkbox/radio role
                if cloc:
                    verb = "check" if value == "checked" else "uncheck"
                    step(f"{verb.capitalize()} {_human_target(ev)}",
                         [f"await {cloc}.{verb}();"])
                    last_action_ts = ets
                continue
            # Key events become .fill()s (except bare Enter/Tab), so resolve a
            # fillable locator — never a button/link role captured by mistake.
            loc = _locator(ev, fillable=True)
            filled = value or (text if text and not text.startswith("Key.") else "")
            hint = _field_hint(ev)
            ename = (ev.get("element") or "").strip()
            role = _role_of(ev)
            # A "fill" targeting a BUTTON whose value is its own label is the
            # submit click echoed as an input event ([name="commit"] fires one
            # on form submit). Filling a button can never match anything — and
            # skipping the submit left logins half-done (password filled, form
            # never sent, then a goto wiped the session). Replay it as a click.
            if role in ("button", "link") and (
                    not filled or filled == ename or _SUBMIT_RE.search(ename)):
                cloc = _locator(ev)            # keep the real button role
                if cloc:
                    body = [f"await {cloc}.click();"]
                    if creds_pending or _SUBMIT_RE.search(ename):
                        body.append(_SETTLE_WAIT)
                        if creds_pending and not password_done \
                                and _password_later(i, ets):
                            deferred_submit = (f"Click {_human_target(ev)}",
                                               body, ets)
                            creds_pending = False
                            continue
                        creds_pending = False
                    step(f"Click {_human_target(ev)}", body)
                    last_action_ts = ets
                continue
            # Pure key presses (Enter/Tab/Escape) FIRST — an Enter pressed on
            # the password field must be press('Enter'), never yet another
            # QA_PASSWORD fill (that swallowed the submit and re-filled the
            # field after login).
            if not filled and text.lower().replace("key.", "") in _TYPING_KEYS:
                key = _TYPING_KEYS[text.lower().replace("key.", "")]
                body = [f"await page.keyboard.press('{key}');"]
                if key == "Enter" and creds_pending:
                    body.append(_SETTLE_WAIT)   # Enter submitted the login
                    creds_pending = False
                step(f"Press {key}", body)
                last_action_ts = ets    # Enter can submit → may cause a nav
                continue
            if loc and _PASS_RE.search(hint):
                # A password fill arriving right AFTER a navigation is a
                # late-flushed echo of the typing burst that submitted the
                # login — the field no longer exists on the new page and the
                # step would only time out. The real fill was already emitted.
                if last_was_nav:
                    continue
                # Never a literal secret in the spec — read from env at run time.
                uses_env = True
                creds_pending = True
                password_done = True
                step(f"Fill {_human_target(ev)} (value from QA_PASSWORD)",
                     [f"await {loc}.fill(process.env.QA_PASSWORD ?? '');"],
                     fill_loc=loc)
                _flush_deferred()      # the submit that was waiting on this fill
            elif loc and filled and _USER_RE.search(hint):
                # Test account: overridable via env, captured value as default.
                uses_env = True
                creds_pending = True
                expr = f"process.env.QA_USERNAME ?? '{_esc(filled)}'"
                step(f"Fill {_human_target(ev)} (QA_USERNAME)", [
                    f"await {loc}.fill({expr});",
                    f"await expect({loc}).toHaveValue({expr});",
                ], fill_loc=loc)
            elif loc and filled and _role_of(ev) == "combobox":
                # A <select>: the captured value is the chosen option's LABEL.
                # .fill() is invalid on selects; custom (ARIA) comboboxes fall
                # back to fill. No toHaveValue: a select's value is the option's
                # value attribute, not its label.
                step(f"Select \"{filled[:30]}\" in {_human_target(ev)}", [
                    f"await {loc}.selectOption({{ label: '{_esc(filled)}' }})",
                    f"  .catch(async () => {{ await {loc}.fill('{_esc(filled)}'); }});",
                ], fill_loc=loc)
            elif loc and filled:
                body = [f"await {loc}.fill('{_esc(filled)}');"]
                # Web-first assertion: the field now holds what we typed.
                body.append(f"await expect({loc}).toHaveValue('{_esc(filled)}');")
                step(f"Fill {_human_target(ev)} with \"{filled[:30]}\"", body,
                     fill_loc=loc)
            elif text.lower().replace("key.", "") in _TYPING_KEYS:
                key = _TYPING_KEYS[text.lower().replace("key.", "")]
                body = [f"await page.keyboard.press('{key}');"]
                if key == "Enter" and creds_pending:
                    body.append(_SETTLE_WAIT)   # Enter submitted the login
                    creds_pending = False
                step(f"Press {key}", body)
                last_action_ts = ets    # Enter can submit → may cause a nav
            elif filled:
                # A bare typing burst arriving right after a navigation is the
                # late flush of text typed BEFORE it (the password burst lands
                # here attributed to the new page's Document — typing it now
                # would paste the secret in plaintext onto the wrong page).
                if last_was_nav:
                    continue
                step(f"Type \"{filled[:30]}\"",
                     [f"await page.keyboard.type('{_esc(filled)}');"])
            continue

        if etype == "scroll":
            # Replay the user's scrolling. It is not just cosmetic: pages
            # lazy-render below-the-fold content (a table that only mounts on
            # scroll), so without it the next click waits on an element that
            # never enters the DOM. Text form: "down (18 ticks)" / "up (2 ticks)".
            m = re.match(r"(down|up)\s*\((\d+)", (ev.get("text") or "").strip())
            if m:
                ticks = min(int(m.group(2)), 60)
                dy = ticks * 120 * (1 if m.group(1) == "down" else -1)
                step(f"Scroll {m.group(1)} ({ticks} ticks)", [
                    # wheel() scrolls whatever is UNDER the cursor; park it in
                    # the content area first or the wheel hits the sidebar.
                    "await page.mouse.move(640, 400);",
                    f"await page.mouse.wheel(0, {dy});",
                ])
            continue

        # auto events don't translate into meaningful script actions.

    _flush_deferred()   # never drop a held-back submit

    # No nav events (extension not installed?) — seed goto from any event URL.
    if first_url is None:
        for ev in events:
            u = _clean_url(ev.get("url") or "")
            if u:
                first_url = u
                seed = [f"    await test.step('Open {_esc(u)}', async () => {{",
                        f"      await page.goto('{_esc(u)}');"]
                a = _url_assertion(u)
                if a:
                    seed.append(f"      {a}")
                seed.append("    });")
                steps_ts.insert(0, "\n".join(seed))
                break

    # Still no URL anywhere (session recorded without the browser extension):
    # never leave the test on about:blank — open QA_BASE_URL from the env.
    if first_url is None and steps_ts:
        uses_env = True
        todo = ("// TODO: no se capturó ninguna URL — define QA_BASE_URL en "
                "qa-scripts/.env o edita este goto."
                if es else
                "// TODO: no URL was captured — set QA_BASE_URL in "
                "qa-scripts/.env or edit this goto.")
        seed = ["    await test.step('Open base URL (QA_BASE_URL)', async () => {",
                f"      {todo}",
                "      await page.goto(process.env.QA_BASE_URL ?? 'http://localhost:3000');",
                "    });"]
        steps_ts.insert(0, "\n".join(seed))

    describe = (project or "FullQA.ai").strip() or "FullQA.ai"
    test_title = (name or "").strip() or f"recorded session {session_dir.name[:8]}"

    header = (
        "// Generado por FullQA.ai a partir de la sesión grabada.\n"
        "// Determinista: usa los selectores accesibles capturados (sin IA).\n"
        "// Revisa los pasos marcados con TODO (acciones sin selector web:\n"
        "// apps de escritorio o elementos sin nombre accesible).\n"
        if es else
        "// Generated by FullQA.ai from the recorded session.\n"
        "// Deterministic: built from the captured accessible selectors (no AI).\n"
        "// Review the steps marked TODO (actions without a web selector:\n"
        "// desktop apps or elements lacking an accessible name).\n"
    )
    if uses_env:
        header += (
            "//\n"
            "// Credenciales/URL de test: este spec lee QA_BASE_URL, QA_USERNAME y\n"
            "// QA_PASSWORD desde qa-scripts/.env (git-ignorado; lo carga el config).\n"
            "// Las contraseñas NUNCA se capturan ni se escriben en el código.\n"
            if es else
            "//\n"
            "// Test credentials/URL: this spec reads QA_BASE_URL, QA_USERNAME and\n"
            "// QA_PASSWORD from qa-scripts/.env (git-ignored; loaded by the config).\n"
            "// Passwords are NEVER captured nor written into the code.\n"
        )

    lines = [
        header,
        "import { test, expect } from '@playwright/test';",
        "",
        f"test.describe('{_esc(describe)}', () => {{",
        f"  test('{_esc(test_title)}', async ({{ page, context }}) => {{",
        "    // The user may continue in a tab a click opened (target=_blank):",
        "    // adopt the newest page so the following steps run where they did.",
        "    let pg = page;",
        "    context.on('page', (p) => { pg = p; "
        "p.once('close', () => { pg = page; }); });",
        "",
    ]
    if not steps_ts:
        lines.append("    // (no reproducible web actions were recorded in this session)"
                     if not es else
                     "    // (la sesión no contiene acciones web reproducibles)")
    else:
        # Every action targets `pg` — the tab the user is currently on. Cover
        # BOTH forms: `await page.…` AND `expect(page.…)` / `(page)` — the old
        # await-only replace left assertions pinned to the original tab.
        joined = ("\n\n".join(steps_ts)
                  .replace("await page.", "await pg.")
                  .replace("(page.", "(pg.")
                  .replace("(page)", "(pg)"))
        lines.append(joined)
    lines.append("  });")
    lines.append("});")
    return "\n".join(lines) + "\n"
