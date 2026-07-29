// content.js — FullQA.ai Recorder (local-only).
// Captures DOM-level actions and relays them to the background worker, which
// POSTs them to the FullQA.ai agent at 127.0.0.1. Nothing leaves the machine.
//
// Captured:
//   click  → element role, accessible name, CSS selector, page URL/title
//   input  → final value of the field on change/blur/Enter (NEVER passwords)
//   nav    → full-page and SPA navigations (URL polling + popstate/hashchange)

(() => {
  "use strict";

  const send = (ev) => {
    try {
      chrome.runtime.sendMessage({ qa: { ...ev, t: Date.now() } });
    } catch (_) { /* extension reloaded / context gone — ignore */ }
  };

  // ── helpers ──────────────────────────────────────────────────────────────
  const ROLE_BY_TAG = {
    a: "link", button: "button", select: "combobox", textarea: "textbox",
    summary: "button", option: "option", label: "label", img: "image",
  };

  function roleOf(el) {
    const aria = el.getAttribute && el.getAttribute("role");
    if (aria) return aria;
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    if (tag === "input") {
      const t = (el.type || "text").toLowerCase();
      if (["button", "submit", "reset", "image"].includes(t)) return "button";
      if (["checkbox", "radio"].includes(t)) return t;
      return "textbox";
    }
    return ROLE_BY_TAG[tag] || tag;
  }

  function isSensitive(el) {
    if (!el) return false;
    if ((el.type || "").toLowerCase() === "password") return true;
    const hint = [el.name, el.id, el.autocomplete, el.placeholder,
                  el.getAttribute && el.getAttribute("aria-label")]
      .filter(Boolean).join(" ");
    return /pass|pwd|contrase|cvv|card.?number|secret|token|ssn|pin/i.test(hint);
  }

  function nameOf(el) {
    const pick = (s) => (s || "").trim().replace(/\s+/g, " ").slice(0, 80);
    const aria = el.getAttribute && el.getAttribute("aria-label");
    if (aria) return pick(aria);
    if (el.labels && el.labels.length) return pick(el.labels[0].innerText);
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    if (tag === "input") {
      const t = (el.type || "").toLowerCase();
      if (["button", "submit", "reset"].includes(t)) return pick(el.value);
      return pick(el.placeholder || el.name || el.id);
    }
    if (tag === "img") return pick(el.alt);
    if (tag === "select") return pick(el.name || el.id);
    return pick(el.innerText || el.title || el.value);
  }

  function cssPath(el) {
    // Prefer stable handles; fall back to a short nth-of-type path.
    if (el.id && !/^\d|^(ember|react|:r)/.test(el.id)) return `#${CSS.escape(el.id)}`;
    for (const attr of ["data-testid", "data-test", "data-cy", "data-qa", "name"]) {
      const v = el.getAttribute && el.getAttribute(attr);
      if (v) return `[${attr}="${v.slice(0, 60)}"]`;
    }
    const parts = [];
    let node = el;
    for (let depth = 0; node && node.nodeType === 1 && depth < 4; depth++) {
      let part = node.tagName.toLowerCase();
      if (node.id && !/^\d/.test(node.id)) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        break;
      }
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children)
          .filter((c) => c.tagName === node.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(" > ").slice(0, 200);
  }

  function pageInfo() {
    return { url: location.href.slice(0, 300), title: (document.title || "").slice(0, 120) };
  }

  // ── clicks ───────────────────────────────────────────────────────────────
  const CLICKABLE = "a,button,input,select,textarea,summary,[role],[onclick],[tabindex]";

  document.addEventListener("pointerdown", (e) => {
    const raw = e.target;
    if (!(raw instanceof Element)) return;
    const el = raw.closest(CLICKABLE) || raw;
    send({
      kind: "click",
      name: nameOf(el),
      role: roleOf(el),
      selector: cssPath(el),
      ...pageInfo(),
    });
  }, { capture: true, passive: true });

  // ── inputs (final value on change/blur/Enter; passwords NEVER) ──────────
  const lastSent = new WeakMap();

  function reportInput(el) {
    if (!(el instanceof Element)) return;
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    if (!["input", "textarea", "select"].includes(tag)) return;
    // Button-like inputs (submit/reset/button/image) are click targets, not
    // text fields. Real clicks on them are already captured by pointerdown;
    // a change/blur event here is NOT a user click (reporting one produced
    // phantom "Log In" clicks mid-form), and their "value" is just the button
    // label — skip them entirely.
    const itype = (el.type || "").toLowerCase();
    if (tag === "input" && ["submit", "button", "reset", "image"].includes(itype)) return;
    if (isSensitive(el)) return;                       // never capture
    let value = "";
    if (tag === "select") {
      const opt = el.selectedOptions && el.selectedOptions[0];
      value = opt ? opt.text : el.value;
    } else if (el.type === "checkbox" || el.type === "radio") {
      value = el.checked ? "checked" : "unchecked";
    } else {
      value = el.value || "";
    }
    value = String(value).slice(0, 200);
    if (lastSent.get(el) === value) return;            // no change since last report
    lastSent.set(el, value);
    send({
      kind: "input",
      name: nameOf(el),
      role: roleOf(el),
      selector: cssPath(el),
      value,
      ...pageInfo(),
    });
  }

  document.addEventListener("change", (e) => reportInput(e.target), { capture: true, passive: true });
  document.addEventListener("blur", (e) => reportInput(e.target), { capture: true, passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    reportInput(e.target);   // final value of the field being submitted
    // Record the Enter itself — it's how forms are submitted from the
    // keyboard. Without it the generated flow fills the login and never
    // actually submits it.
    const el = (e.target instanceof Element) ? e.target : document.body;
    send({ kind: "enter", name: nameOf(el), role: roleOf(el),
           selector: cssPath(el), ...pageInfo() });
  }, { capture: true, passive: true });

  // ── navigation (initial + SPA) ───────────────────────────────────────────
  let lastUrl = "";

  function reportNavIfChanged() {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    send({ kind: "nav", ...pageInfo() });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", reportNavIfChanged, { once: true });
  } else {
    reportNavIfChanged();
  }
  window.addEventListener("popstate", reportNavIfChanged);
  window.addEventListener("hashchange", reportNavIfChanged);
  setInterval(reportNavIfChanged, 700);                // catches pushState SPAs
})();
