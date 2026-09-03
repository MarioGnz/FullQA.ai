📖 **English** · [Español](README.es.md)

# FullQA.ai

**A fully local QA session recorder that turns what you do on screen into professional QA documentation and runnable automation — powered by AI, organised by project.**

Record a QA session (clicks, keystrokes, screenshots, optional voice narration), and FullQA.ai produces clean, copy‑paste‑ready Markdown: a summary, reproduction steps, exploratory‑testing notes, test cases, a test plan, bug reports, Jira tickets — plus a **professional Playwright script you can run and watch in a real browser**. Everything is grouped by **project**, and each project can carry a **context document** that makes the AI far more accurate about *your* app.

> **Everything stays on your machine.** The only data that ever leaves is the session you explicitly send to your chosen AI provider — and with Ollama, nothing leaves at all. Zero cloud sync, zero telemetry.

---

## Table of contents

- [What's new](#whats-new)
- [How it works](#how-it-works)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [The desktop app](#the-desktop-app)
  - [My Sessions](#my-sessions)
  - [My Scripts](#my-scripts)
  - [Record](#record)
- [Project context — teaching the AI about your product](#project-context--teaching-the-ai-about-your-product)
- [Exploratory testing](#exploratory-testing)
- [Report sections](#report-sections)
- [Professional automation scripts](#professional-automation-scripts)
- [AI providers](#ai-providers)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Data formats](#data-formats)
- [API reference](#api-reference)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## What's new

Recent releases added a lot. If you used an early version, here's the short list:

- **Project-based organisation** — sessions and scripts are grouped by **project**. Name and rename sessions; pick an existing project or create a new one on the fly.
- **My Sessions / My Scripts / Record** — a three-section sidebar. My Sessions shows **thumbnails** so you recognise a run at a glance.
- **Project context** — a per-project, editable document that is fed to the AI on **every** generation, so results actually match how your product works.
- **Exploratory testing** — a dedicated analysis (charter, areas, observations, risks, coverage) that is designed to double as **reusable project knowledge**: one click appends it to the project context.
- **Structured report sections** — pick exactly what you want: Summary, Steps to reproduce, Exploratory, Test cases, Test plan, Bug report, Jira ticket.
- **Professional Playwright scripts** — clean, best‑practice TypeScript (`test.describe` / `test.step`, role/label locators, web‑first assertions) that you can **Run** from the app and watch in a real browser.
- **Up-to-date models** — defaults to current Claude models (e.g. Claude Sonnet 5), with adaptive‑thinking handling and automatic image downscaling to stay within provider limits.

---

## How it works

```
┌────────────┐   records    ┌──────────────────────┐   reads/writes   ┌──────────────────┐
│  Agent      │ ───────────▶ │  qa-sessions/            │ ◀──────────────  │  FastAPI backend │
│ (tray, host)│  clicks,     │  <date>/<uuid>/          │   (shared vol)   │  (Docker)        │
└────────────┘  keys,        │   ├ events.jsonl         │                  │  claude_gen.py   │
     ▲          screenshots, │   ├ screenshots/*.png    │                  │  playwright_gen  │
     │          audio        │   ├ manifest.json        │                  │  + SQLite        │
     │                       │   └ transcript.txt       │                  └────────┬─────────┘
     │                       └──────────────────────┘                           │ AI
┌────┴────────────────────────────────────────────────────────────────────┐    ▼
│  Desktop app (PyQt6)  —  My Sessions · My Scripts · Record                │  Anthropic / Ollama /
│  browse, name, add project context, generate docs, run automations       │  Groq / Gemini
└──────────────────────────────────────────────────────────────────────────┘
        writes generated Playwright specs ▶  qa-scripts/<project>/*.spec.ts
```

Three processes cooperate:

1. **Agent** (`agent/main.py`) — runs natively on the host from a tray icon. Captures events, screenshots, and (optionally) narrated audio into `qa-sessions/`.
2. **Backend** (`services/api`, in Docker) — groups raw events into meaningful steps, calls the AI provider, and returns Markdown. Also stores session metadata (name, project) and per‑project context in SQLite.
3. **Desktop app** (`desktop/ui.py`) — the control centre: browse/organise sessions, edit project context, generate documentation, and generate + **run** automation scripts.

---

## Features

**Capture**
- Mouse clicks, scrolls, and key presses via `pynput`; screenshots via `mss`.
- Smart scroll capture — one clean screenshot when the wheel *settles*, not one per tick.
- Optional voice narration (EN/ES) transcribed **offline** with `faster-whisper`.
- Capture target: active monitor, whole screen, a specific monitor, or a single window.
- Optional live "smart capture": a local vision model saves a screenshot only on meaningful screen changes.
- Browser extension support: web sessions capture real CSS selectors, ARIA roles, and accessible names for high‑quality scripts.

**Organise**
- **Projects**: group sessions and scripts; rename sessions; assign/create projects from a dropdown.
- **Thumbnails** in the session list for instant recognition.
- **Project context** document per project, injected into every AI generation.

**Generate**
- Choose sections: **Summary**, **Steps to reproduce**, **Exploratory testing**, **Test cases**, **Test plan**, **Bug report**, **Jira ticket**.
- **Visual walkthrough** appended to every report — one screenshot per step.
- **PDF export** (screenshots embedded).
- Multi‑provider AI: **Anthropic Claude**, **Ollama** (fully local), **Groq**, **Google Gemini**.
- "Test connection" lists the models actually installed/available for Ollama and Gemini.

**Automate**
- One click turns a session into a **professional Playwright spec** and files it under `qa-scripts/<project>/`.
- **Run** a script from **My Scripts** — it opens a real (headed, slowed‑down) browser so you can watch the whole flow.

**Robust**
- Offline‑resilient: if the backend is down, the app still lists/opens sessions straight from disk.
- Metadata is mirrored to `manifest.json` on disk, so it survives a DB reset.
- Localhost‑only backend, non‑root container, path‑traversal validation.

---

## Prerequisites

| Tool | Required for | Notes |
|------|--------------|-------|
| **Python 3.10+** | agent + desktop app | [python.org](https://www.python.org) or via `uv` |
| **Docker Desktop 4.x+** | backend | [docker.com](https://www.docker.com/products/docker-desktop/) — includes Compose v2 |
| **An AI provider** | generation | One of: Anthropic key, Groq key, Gemini key, or Ollama running locally |
| **Node.js 18+** | *running* automation scripts | Only needed if you use **My Scripts → Run** ([nodejs.org](https://nodejs.org)) |

> **Windows note:** if `python` isn't on your PATH, use `uv` to manage the venv (see step 2), or call `.\.venv\Scripts\python.exe` directly.

---

## Quick start

### 1 — Pick an AI provider (at least one)

| Provider | Cost | Where to get a key |
|----------|------|--------------------|
| **Anthropic Claude** | Paid, best quality | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| **Groq** | Free tier, fast cloud | [console.groq.com](https://console.groq.com) → API Keys |
| **Google Gemini** | Free tier | [aistudio.google.com](https://aistudio.google.com) → Get API key |
| **Ollama** | Free, fully local | [Local AI with Ollama](#local-ai-with-ollama) |

### 2 — Create the virtual environment

```powershell
cd C:\path\to\FullQA.ai

# Recommended (uv):
uv venv .venv --python 3.12
uv pip install -r requirements.txt

# Or standard Python:
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 3 — Configure environment variables

Copy `.env.example` to `.env` and fill in only the key(s) you'll use:

```
ANTHROPIC_API_KEY=sk-ant-your_key_here
GROQ_API_KEY=gsk_your_key_here
GEMINI_API_KEY=your_key_here
OLLAMA_BASE_URL=            # blank = default http://host.docker.internal:11434/v1
```

> ⚠️ **The `.env` file holds real secrets — never commit it.** Keep `.env.example` with empty/placeholder values only. After editing `.env`, **recreate the backend container** (below) so it picks up the new values — a running container does not re‑read `.env`.

### 4 — Start the Docker backend

```powershell
docker compose up -d --build
```

The API starts at `http://localhost:8000/docs`. First run needs `--build`; after that `docker compose up -d` is enough. **Any time you change `.env`, run `docker compose up -d --force-recreate`.**

### 5 — Open the desktop app

```powershell
.\.venv\Scripts\python.exe desktop\ui.py
```

The header's **API Online** pill turns green once the backend is ready.

### 6 — Start the capture agent

In a second terminal:

```powershell
.\.venv\Scripts\python.exe agent\main.py
```

A tray icon appears. Right‑click → **▶ Start Recording**.

### 7 — Record → organise → generate → automate

1. In **Record**, optionally set a **session name** and pick/type a **project**, then start recording (or start from the tray).
2. Do your QA workflow; stop when done.
3. In **My Sessions**, select the run (thumbnail + name), optionally **Rename** it, and add **Project context**.
4. In the **Overview** tab, choose sections + provider/model and click **Generate**.
5. Read the report (**Report** tab); export PDF or copy Markdown.
6. Tick **Playwright script** when generating to file a spec under **My Scripts**, then **Run** it to watch it in a browser.

---

## The desktop app

The left sidebar has four sections.

### My Sessions

- Sessions grouped by **project** (ungrouped ones fall under *No project*).
- A **thumbnail** (first screenshot) per session for quick recognition.
- **Rename** (button or double‑click): edit the session **name** and **project**. The project field is a dropdown of existing projects — type a new name to create one.
- **Project context** button (top right of the detail pane): opens the editor for the selected session's project.
- Selecting a session opens the detail pane: **Overview** (generate), **Events**, **Report**.

### Projects

A dedicated view to see and manage every project. Each project is a card showing its **session count**, **script count**, and whether it has a **context** document. From here you can:

- **Context** — edit the per‑project context the AI uses in every generation.
- **View sessions** — jump to My Sessions filtered to that project.
- **Scripts** — open the project's `qa-scripts/` folder.
- **Rename** — renames the project everywhere (reassigns its sessions, moves its context, renames its scripts folder).
- **Delete** — unassigns the project from its sessions (the sessions are **not** deleted), clears its context, and drops the empty scripts folder.
- **＋ New project** — create a project and open its context editor straight away.

### My Scripts

- Every generated Playwright spec, grouped by project folder under `qa-scripts/`.
- **▶ Run** — executes `npx playwright test --headed` for the selected spec; a real, slowed‑down browser opens so you can watch each step. Output streams into a log panel.
- **Install Playwright** — one‑time setup (`npm install -D @playwright/test` + `npx playwright install chromium`). The app also offers this automatically the first time you Run.
- **Open folder**, **Delete**, **Refresh**.

### Record

- Optional **Session name** and **Project** (dropdown of existing projects, or type a new one).
- Language, microphone, capture target, and optional smart capture.
- 3‑2‑1 countdown, then records until you stop. On stop, the name/project are saved automatically.

---

## Project context — teaching the AI about your product

Generic screenshots only tell the AI *what happened*, not *what your product is*. **Project context** fixes that.

Each project has an editable Markdown document describing what the app is, how it works, its roles, business rules, and what to expect. This text is prepended to the prompt on **every** generation for that project, so the AI produces results grounded in your reality instead of guessing.

**Edit it:** My Sessions → select a session that has a project → **Project context** → write/save. (Assign a project first via **Rename** if the session has none.)

Example:

```markdown
# Project: Customer Portal

A B2B portal for managing client accounts.
- Login is email + password; SSO is not enabled in test.
- Roles: **admin** (full access) and **user** (read-only on billing).
- "Impersonate" lets an admin act as a user — expect a yellow banner while impersonating.
- Formulations must have at least one component before they can be saved.
```

With that in place, a "Bug report" or "Test cases" generation will use the right terminology, know which behaviours are expected, and flag deviations more precisely.

---

## Exploratory testing

The **Exploratory testing** section analyses a session the way a senior exploratory tester would, and is written to be **reusable project knowledge**:

- **Charter** — what area/feature was explored and why.
- **Areas & features observed** — screens, flows, elements, and how they behave.
- **Observations** — notable behaviours, states, validations, messages (evidence‑based only).
- **Risks & potential issues** — fragile or questionable areas (`[UNCLEAR]` when unverifiable).
- **Coverage & suggested next tests** — gaps and what to explore next.

**The loop that makes the AI smarter over time:** generate the exploratory section, then in the **Report** tab click **➕ Add to context**. The notes are appended to the project context, so future generations for that project are informed by what exploration already uncovered. Run a few exploratory sessions and the project context becomes a living knowledge base.

---

## Report sections

Pick any combination in the **Overview** tab. Sections always render in a logical top‑down order.

| Section | What it produces |
|---|---|
| **Summary / Explanation** | 2–4 sentences: what was tested, the flow, the outcome |
| **Steps to reproduce** | Clean numbered list of imperative steps |
| **Exploratory testing** | Charter, areas, observations, risks, coverage (see above) |
| **Test cases** | One block per case: objective, preconditions, the acceptance criteria it verifies, and a Step / Expected Result / Actual Result / Status table. A test case groups several steps — it is not one case per action. With ticket criteria pasted in, it closes with an AC-coverage table |
| **Test plan** | Step / Action / Expected / Status table (actions built deterministically from real events) |
| **Bug report** | Summary, severity, repro steps, expected vs actual |
| **Jira ticket** | Jira‑ready ticket (title, type, priority, labels, description, repro, expected/actual) |

Every report also ends with a **visual walkthrough**: one screenshot per step.

The report is yours to finish:

- **Edit** opens the report’s Markdown for editing — correct a status, reword a case, add a note — and **Save** writes it back. Screenshots collapse to short `![alt](img://N)` markers while you edit (a report is mostly base64) and are put back on save; delete a marker to drop that screenshot.
- **+ Test cases** appends new, non‑duplicate cases to an existing report. The box next to it picks how many (1–20), and the choice is remembered.

---

## Professional automation scripts

Scripts are generated **deterministically** (no AI) from the captured events, and follow Playwright best practices so they read like review‑ready, hand‑written code:

- `@playwright/test` with a `test.describe(<project>)` block and a meaningful `test(<session name>)` title.
- Every action wrapped in `test.step(...)` for readable traces.
- **User‑facing, auto‑waiting locators**, preferred in order: `getByRole` → `getByLabel` → `getByPlaceholder` → `getByText` → `locator(css)`.
- **Web‑first assertions**: `await expect(page).toHaveURL(...)` after navigation, `await expect(field).toHaveValue(...)` after input.
- **No hard waits** — Playwright auto‑waits.
- Coordinate‑only actions (desktop apps or elements without an accessible name) become clearly marked **TODO** steps instead of brittle pixel clicks.

> Script quality mirrors capture quality: **web sessions recorded with the browser extension produce real locators**; desktop‑only steps become TODOs you can fill in.

**Test credentials & URL — never in the code.** Passwords are *never* captured (by design), so generated specs read credentials from environment variables at run time: `QA_BASE_URL`, `QA_USERNAME`, `QA_PASSWORD`. Set them in **My Scripts → 🔐 Test credentials** (writes `qa-scripts/.env`, which is git-ignored and loaded automatically by `playwright.config.ts`):

- Password fields become `fill(process.env.QA_PASSWORD ?? '')` — the secret never touches the `.spec.ts`.
- Email/username fields become `process.env.QA_USERNAME ?? '<captured value>'` — overridable per environment.
- The spec always opens the app (from the first captured URL, or `QA_BASE_URL` if none) **before** the first action, so it never sits on `about:blank`.

**Recording started already logged in? Use a saved login.** If a session was recorded *after* login, its spec has no login steps, so a fresh browser lands on the login page. Log in once and reuse the session for every spec (Playwright `storageState`):

```powershell
cd qa-scripts
npx playwright test --project=setup     # logs in with QA_* and saves .auth/state.json
```

`auth.setup.ts` (created automatically) signs in with `QA_USERNAME` / `QA_PASSWORD` against `QA_LOGIN_URL` (or `QA_BASE_URL`); adjust its locators if they don't match your login form. After that, every `*.spec.ts` starts authenticated. `.auth/` is git-ignored.

**Generate:** tick **Playwright script** when generating a report (Overview tab). The spec is filed under `qa-scripts/<project>/<name>-<id>.spec.ts` and shows up in **My Scripts**.

**Run from the app:** My Scripts → select → **▶ Run**. First time, accept the one‑time Playwright install. A headed browser opens and steps run slowed down so you can watch.

**Run from a terminal** (equivalent):

```powershell
cd qa-scripts
npm install -D @playwright/test        # first time only
npx playwright install chromium        # first time only
npx playwright test --headed <project>/<file>.spec.ts
```

`qa-scripts/playwright.config.ts` is created automatically (headed, `slowMo`, single worker, `list` reporter). The `.spec.ts` files are safe to commit; `node_modules/`, `test-results/`, and `playwright-report/` are git‑ignored.

---

## AI providers

### Local AI with Ollama

Run inference entirely on your own GPU — no API key, no internet.

```powershell
# 1. Install Ollama from https://ollama.com/download and launch it
# 2. Pull a vision-capable model
ollama pull qwen2.5vl:7b          # 7B vision model (recommended default)
ollama pull llama3.2-vision:11b   # 11B vision model
# 3. Ollama serves on http://localhost:11434 automatically
```

In the app: open a session → **Overview** → provider **Local (Ollama)** → **Test connection** (populates the model list) → **Generate**. No `ANTHROPIC_API_KEY` needed.

> **Docker note:** `docker-compose.yml` passes `host.docker.internal` so the container reaches Ollama on the host (with a Linux `host-gateway` fallback).

**Local performance & VRAM** — generation uses the native Ollama API with a capped context window to stay in VRAM:

| Variable | Default | Effect |
|----------|---------|--------|
| `OLLAMA_NUM_CTX`   | `8192` | Context window. Lower (e.g. `4096`) if it spills to CPU; raise with more VRAM. |
| `MAX_IMAGES_LOCAL` | `5`    | Screenshots sent to the model. Fewer = faster on CPU. |
| `OLLAMA_TIMEOUT`   | `900`  | Max seconds to wait for local inference. |
| `OLLAMA_KEEP_ALIVE`| `30m`  | How long Ollama keeps the model + its prefix cache resident (reused across a session's generations). Longer = faster repeats, more VRAM held. |

> **GPU note:** Ollama uses your GPU only with matching ROCm (AMD) / CUDA (NVIDIA) support. Very new GPUs need a recent Ollama build (e.g. AMD RDNA 4 / RX 9000 `gfx1201` from Ollama 0.30+). Upgrade with `winget upgrade --id Ollama.Ollama`; verify with `curl http://localhost:11434/api/ps` (`size_vram` should be > 0). Cloud providers are unaffected.

### Groq / Gemini (free cloud)

1. Get a key (Groq: <https://console.groq.com>; Gemini: <https://aistudio.google.com>).
2. Add it to `.env` (`GROQ_API_KEY=` / `GEMINI_API_KEY=`).
3. `docker compose up -d --force-recreate`.
4. In the app, select the provider and a model, then Generate. (Gemini and Ollama support **Test connection** to list live models.)

### Anthropic Claude

Add `ANTHROPIC_API_KEY` to `.env`, recreate the container, and pick **Anthropic (Claude)**. The default model is a current Claude model; images are automatically downscaled to stay within provider limits, and adaptive thinking is handled for you.

**Project context is prompt-cached to cut cost.** The per-project context is identical across every section and every regeneration, so it's sent as a **cacheable prefix** instead of re-billed each time — on Anthropic it becomes a `system` block with `cache_control` at a **1-hour TTL** (`ANTHROPIC_CACHE_TTL`), so repeated generations read it at ~10% of the input price. The same stable-prefix placement lets **Gemini 2.5** cache it implicitly and **Ollama** reuse its local KV cache; **Groq** has no caching but is unaffected. If the provider ever rejects the cache options, generation transparently falls back to sending the context inline.

---

## Architecture

- **Agent** and **desktop app** run **natively** on the host (they need screen/keyboard/mic access). They are *not* containerised.
- **Backend** runs in Docker, bound to `127.0.0.1:8000`, on an outbound‑only bridge.
- **Shared volume**: the host `qa-sessions/` is mounted into the API container so it can read events/screenshots and write session metadata back to `manifest.json`.
- **Persistence**: `qa-data` Docker volume holds `sessions.db` (SQLite: sessions + per‑project context) and generated reports.
- **Scripts** live on the host under `qa-scripts/` and are generated/run by the desktop app (Node/Playwright run host‑side so a real browser can open).

---

## Project structure

```
FullQA.ai/
├── .env.example            # Template — copy to .env, fill in your key(s)
├── .gitignore              # Excludes .env, qa-sessions/, qa-scripts/node_modules/, *.wav …
├── docker-compose.yml      # API service only; localhost-only port; qa-sessions mounted
├── requirements.txt        # Host agent + desktop UI dependencies
├── build.ps1               # PyInstaller → dist\FullQA.ai.exe
│
├── agent/                  # Host agent (native, NOT in Docker)
│   ├── main.py             # CLI entry point + tray
│   ├── session.py          # Session lifecycle → qa-sessions/YYYY-MM-DD/{uuid}/
│   ├── capture.py          # pynput events + mss screenshots
│   ├── audio.py            # sounddevice + faster-whisper transcription
│   ├── watcher.py          # optional smart (AI) capture
│   ├── weblistener.py      # local endpoint for the browser extension
│   └── tray.py             # system-tray UI
│
├── desktop/
│   └── ui.py               # PyQt6 app: My Sessions / My Scripts / Record,
│                           #   project context editor, report viewer, i18n (ES/EN)
│
├── services/
│   └── api/                # FastAPI backend (Docker)
│       └── app/
│           ├── main.py           # REST endpoints (sessions, meta, projects, playwright…)
│           ├── claude_gen.py     # Multi-provider AI + event grouping + report sections
│           ├── playwright_gen.py # Deterministic professional Playwright codegen
│           └── database.py       # SQLite: sessions + per-project context
│
├── extension/              # Optional browser extension (real web selectors)
│
├── qa-sessions/            # Auto-created, git-ignored — recorded sessions
│   └── YYYY-MM-DD/{uuid}/
│       ├── manifest.json   #   incl. name + project
│       ├── events.jsonl
│       ├── screenshots/*.png
│       ├── audio.wav       #   (if --audio)
│       └── transcript.txt  #   (if --audio)
│
└── qa-scripts/             # Auto-created — generated Playwright specs
    ├── playwright.config.ts    #   headed + slowMo scaffold
    ├── package.json
    └── <project>/*.spec.ts     #   grouped by project (node_modules/ git-ignored)
```

---

## Data formats

### `manifest.json`

```json
{
  "session_id":       "uuid",
  "started_at":       "2026-05-04T12:00:00Z",
  "ended_at":         "2026-05-04T12:05:00Z",
  "os":               "win",
  "language":         "en",
  "audio_enabled":    false,
  "event_count":      47,
  "screenshot_count": 12,
  "name":             "Login with invalid credentials",
  "project":          "Customer Portal"
}
```

### `events.jsonl` — one JSON object per line

```json
{"ts": "2026-05-04T12:00:00.123456Z", "type": "click", "x": 640, "y": 400, "selector": "#login", "control": "button", "element": "Sign in", "screenshot": "…_click.png"}
{"ts": "2026-05-04T12:00:01.000000Z", "type": "key",   "text": "user@example.com", "selector": "#email", "control": "textbox", "element": "Email"}
```

The richer the captured fields (`selector`, `control`, `element`), the better both the AI docs and the generated Playwright locators.

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness probe |
| `GET`  | `/providers/ollama/models` | Installed Ollama models + connectivity |
| `GET`  | `/providers/gemini/models` | Available Gemini models |
| `GET`  | `/sessions` | List all sessions (DB + filesystem) |
| `GET`  | `/sessions/{id}` | Session detail |
| `POST` | `/sessions/{id}/ingest` | Register a session from the shared volume |
| `POST` | `/sessions/{id}/meta` | Set session **name** + **project** |
| `POST` | `/sessions/{id}/generate` | Start async report generation (sections, provider, model) |
| `POST` | `/sessions/{id}/report/more-cases` | Append N new test cases |
| `GET`  | `/sessions/{id}/report` | Fetch the generated Markdown report |
| `PUT`  | `/sessions/{id}/report` | Overwrite the report with edited Markdown |
| `GET`  | `/sessions/{id}/events` | Parsed events |
| `GET`  | `/sessions/{id}/screenshots/{file}` | Serve a screenshot PNG |
| `GET`  | `/sessions/{id}/playwright` | Generate a professional Playwright spec |
| `DELETE` | `/sessions/{id}` | Delete a session (DB + report + files) |
| `GET`  | `/projects` | List known project names |
| `GET`  | `/projects/{name}/context` | Fetch a project's context |
| `PUT`  | `/projects/{name}/context` | Set a project's context |

Interactive docs: `http://localhost:8000/docs`

---

## Security

| Control | Implementation |
|---------|---------------|
| Ports | API bound to `127.0.0.1:8000` — never `0.0.0.0` |
| Network isolation | API container on an outbound‑only bridge; no inbound exposure |
| Secrets | API keys read from env vars only; never hardcoded. `.env` is git‑ignored; keep real keys **out** of `.env.example`. A pre‑commit hook blocks `.env` commits and raw `sk-ant-` keys in diffs |
| Container user | Runs as non‑root (`qauser`, UID 1000) |
| Volume mount | `qa-sessions/` is mounted read‑write (the API writes session metadata back to `manifest.json`); session IDs are validated to reject `/`, `\`, `..` |
| Data residency | Nothing leaves the machine with Ollama; otherwise only the session you generate on is sent to the chosen provider |

> If a real key ever lands in a committed file, **rotate it** at the provider and remove it from history.

---

## Troubleshooting

**"API Offline" in the app**
→ `docker compose up -d` and wait ~15 s for the health check. If you just edited `.env`, use `--force-recreate`.

**Claude says "no API key" even though it's in `.env`**
→ The container was started before the key was set. Run `docker compose up -d --force-recreate`.

**Model 404 (e.g. `model: claude-…` not found)**
→ The pinned model was retired. The app ships current model IDs; if you pinned an old one, pick a current model in the dropdown.

**Playwright test opens `about:blank` / login fails**
→ The session had no captured URL, or the password (never captured) is missing. Open **My Scripts → 🔐 Test credentials** and set `QA_BASE_URL`, `QA_USERNAME`, `QA_PASSWORD`, then re-generate the script. Web sessions recorded **with the browser extension** capture real URLs automatically.

**Playwright: "No tests found"**
→ Fixed — script paths are passed with forward slashes. Update and re‑run. If running manually, `cd qa-scripts` first.

**My Scripts → Run does nothing / errors about Playwright**
→ Click **Install Playwright** once (needs Node.js 18+ on PATH), then Run again.

**Image error: "dimensions exceed max allowed size"**
→ Fixed — screenshots are downscaled before being sent. Rebuild the backend if you're on an old build.

**`python` not found (Windows)**
→ Use `.\.venv\Scripts\python.exe`, or install Python via `uv`.

**No tray icon**
→ Some environments need `pywin32`: `uv pip install pywin32`, then relaunch.

**Screenshots black/empty (macOS)**
→ Grant Screen Recording permission to your terminal in System Settings → Privacy & Security.

---

## License

MIT — see [LICENSE](LICENSE).
