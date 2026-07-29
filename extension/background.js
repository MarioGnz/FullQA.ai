// background.js — FullQA.ai Recorder service worker.
// Batches events from content scripts and POSTs them to the local FullQA.ai
// agent. If the agent is not running/recording, events are silently dropped —
// the extension never stores page content and never contacts any other host.

const ENDPOINT = "http://127.0.0.1:8765/events";
const FLUSH_MS = 400;
const MAX_BATCH = 40;

let queue = [];
let flushTimer = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || !msg.qa) return;
  queue.push(msg.qa);
  if (queue.length >= MAX_BATCH) {
    flush();
  } else if (!flushTimer) {
    flushTimer = setTimeout(flush, FLUSH_MS);
  }
});

async function bumpCounter(n) {
  try {
    const { qaSent = 0 } = await chrome.storage.session.get("qaSent");
    const total = qaSent + n;
    await chrome.storage.session.set({ qaSent: total });
    chrome.action.setBadgeBackgroundColor({ color: "#16a34a" });
    chrome.action.setBadgeText({ text: total > 999 ? "1k+" : String(total) });
  } catch (_) { /* badge is cosmetic — never fail the pipeline */ }
}

async function flush() {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (queue.length === 0) return;
  const events = queue.splice(0, MAX_BATCH);
  try {
    const r = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
    const data = await r.json();
    if (data && data.stored > 0) bumpCounter(data.stored);
  } catch (_) {
    // Agent offline or not recording — drop the batch. Never retry-buffer:
    // holding user activity in memory longer than needed is worse.
  }
  if (queue.length > 0 && !flushTimer) {
    flushTimer = setTimeout(flush, FLUSH_MS);
  }
}
