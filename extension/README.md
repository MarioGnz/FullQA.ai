📖 **English** · [Español](README.es.md)

# FullQA.ai Recorder — private browser extension

Captures what the operating system can't see: the **exact CSS selector**, the
**real text** of the clicked element, the **final value** of every field, and
**navigations** (SPAs included). The FullQA.ai agent merges these events with
the native ones so the documentation says exactly what happened.

It includes a **popup** (click the blue "QA" icon in the toolbar) that shows
live: whether the agent is connected, whether a recording is active, and how
many events have been sent. The icon shows a green counter while recording.

## How it works (full flow)

```
Web page (content.js)            Service worker              FullQA.ai agent
─ listens to clicks/inputs/nav →  batches them (400ms)  →   127.0.0.1:8765
─ extracts selector/text/value                                ↓ only while recording
                                                    the session's events.jsonl
                                                              ↓
                                              merged with native events (UIA)
                                                              ↓
                                                     generated documentation
```

## Security and privacy (by design)

| Layer | Guarantee |
|---|---|
| Network | The only host allowed in the manifest is `http://127.0.0.1:8765` — Chrome **blocks** any other destination. Nothing leaves your machine. |
| Agent | Listens only on `127.0.0.1` (unreachable from the network) and **only while you are recording**; with no active session, it discards everything. |
| Anti-injection | The agent rejects (403) any POST whose `Origin` is not an extension — a malicious web page cannot inject fake events into your session. |
| Sensitive data | `type=password` is never captured. Fields that look sensitive (card, CVV, token, PIN…) are redacted in the extension AND in the agent (two layers). |
| Permissions | Only requests `storage` (the popup counter). No `tabs`, no `history`, no `cookies`, no background `<all_urls>` read access. |
| Distribution | Installed **from a folder** (unpacked). It never goes through the Web Store; nobody else can update or see it. |
| Storage | The extension stores nothing in the browser (only the counter, which is cleared when it closes). Events live solely in your `qa-sessions/`. |

## Installation (once, ~1 minute)

1. Open `chrome://extensions` (or `edge://extensions`).
2. Enable **Developer mode** (toggle in the top right).
3. Click **Load unpacked** and choose this folder (`FullQA.ai/extension`).
4. (Optional) Pin the "QA" icon to the toolbar: puzzle 🧩 → pin.

> Chrome may warn about "extension in developer mode" on restart — that's the
> normal behaviour for any unpublished private extension.

## Usage

Nothing special: click **Start Recording** in FullQA.ai and browse as usual.
The popup turns **green "Recording session"** and the counter goes up with every
action. When you stop recording, the events are already merged into the session.

## Verify it works

- Popup: green = recording · amber = agent connected but not recording · red = FullQA.ai closed.
- Or open `http://127.0.0.1:8765/ping` → `{"ok": true, "recording": true}`.

## Uninstall

`chrome://extensions` → Remove. (With no active recording it sends nothing anyway.)
