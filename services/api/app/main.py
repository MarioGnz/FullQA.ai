"""
main.py — FastAPI backend for FullQA.ai.

Endpoints
---------
  GET  /health                               Liveness probe
  POST /sessions/{id}/ingest                 Register a session from the shared volume
  POST /sessions/{id}/generate               Kick off async Claude doc generation
  GET  /sessions                             List all known sessions
  GET  /sessions/{id}                        Detail for one session
  GET  /sessions/{id}/events                 Return parsed events array
  GET  /sessions/{id}/screenshots/{fname}    Serve a screenshot PNG
  GET  /sessions/{id}/report                 Fetch the generated Markdown report

Security notes
--------------
  - Bound to 127.0.0.1:8000 by Docker (never 0.0.0.0).
  - CORS restricted to localhost origins only.
  - Sessions volume is read-only (:ro) inside the container.
  - Runs as non-root user (see Dockerfile).
"""

import json
import os
import re
import shutil
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import (
    delete_session as delete_session_db,
    get_project_context,
    get_session,
    init_db,
    list_project_names,
    list_sessions,
    set_project_context,
    set_session_meta,
    update_session_status,
    upsert_session,
)
from claude_gen import generate_more_test_cases, generate_qa_docs

# Shared sessions volume (read-only mount from host)
SESSIONS_BASE = Path("/app/sessions")

app = FastAPI(title="FullQA.ai API", version="1.0.0", docs_url="/docs")

# CORS: only allow requests from the local web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Startup
# ------------------------------------------------------------------

@app.on_event("startup")
def _startup() -> None:
    init_db()


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------------
# Provider connectivity (Ollama)
# ------------------------------------------------------------------

@app.get("/providers/ollama/models")
def ollama_models():
    """Probe the Ollama server the SAME WAY generation will (from inside the
    container, via OLLAMA_BASE_URL) and return the list of installed models.

    Returns {ok, base_url, models:[{name,family,size_gb,vision}], error}.
    """
    import httpx

    base_url = os.environ.get(
        "OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1"
    )
    # /api/tags lives at the server root, not under the OpenAI /v1 path
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    tags_url = f"{root}/api/tags"

    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
            resp = client.get(tags_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "base_url": base_url, "models": [], "error": str(exc)}

    models = []
    for m in data.get("models", []):
        name = m.get("name", "")
        details = m.get("details", {}) or {}
        family = details.get("family", "")
        size_gb = round(m.get("size", 0) / 1e9, 1) if m.get("size") else None
        low = name.lower()
        # Embedding/reranker models can't chat — picking one only errors out.
        if ("embed" in low or "rerank" in low or "bge-" in low
                or low.startswith(("nomic-", "snowflake-arctic", "all-minilm"))
                or "bert" in family.lower()):
            continue
        vision = (
            "vl" in low or "vision" in low or low.startswith("llava")
            or "minicpm-v" in low or family in ("qwen25vl", "mllama")
        )
        models.append({
            "name": name,
            "family": family,
            "size_gb": size_gb,
            "vision": vision,
        })
    return {"ok": True, "base_url": base_url, "models": models, "error": None}


@app.get("/providers/ollama-cloud/models")
def ollama_cloud_models():
    """List models available on Ollama Cloud for the configured OLLAMA_API_KEY.

    Same shape as the local Ollama probe. Ollama Cloud speaks the same native
    API, so this hits {OLLAMA_CLOUD_BASE_URL}/api/tags with a bearer token.
    Falls back to a small curated list if the catalog can't be fetched, so the
    dropdown is never empty once the key is set.
    """
    import httpx

    api_key = os.environ.get("OLLAMA_API_KEY", "")
    if not api_key:
        return {"ok": False, "models": [],
                "error": "OLLAMA_API_KEY is not set."}

    base_url = os.environ.get("OLLAMA_CLOUD_BASE_URL", "https://ollama.com")
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]

    # Curated fallback — the models Ollama Cloud commonly exposes. The live
    # /api/tags call replaces this when it succeeds.
    curated = [
        {"name": "qwen3-vl:235b",     "vision": True},
        {"name": "qwen3-vl:32b",      "vision": True},
        {"name": "gpt-oss:120b",      "vision": False},
        {"name": "gpt-oss:20b",       "vision": False},
        {"name": "deepseek-v3.1:671b","vision": False},
        {"name": "qwen3-coder:480b",  "vision": False},
    ]
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = client.get(f"{root}/api/tags",
                              headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            data = resp.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            low = name.lower()
            vision = ("vl" in low or "vision" in low or low.startswith("llava")
                      or "minicpm-v" in low)
            models.append({"name": name, "vision": vision})
        if not models:
            models = curated
        return {"ok": True, "models": models, "error": None}
    except Exception as exc:
        # Key is set but the catalog call failed — still offer the curated list.
        return {"ok": True, "models": curated, "error": str(exc)}


@app.get("/providers/gemini/models")
def gemini_models():
    """List Gemini models available to the configured GEMINI_API_KEY.

    Same shape as the Ollama probe: {ok, models:[{name,vision}], error}.
    """
    import httpx

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"ok": False, "models": [],
                "error": "GEMINI_API_KEY is not set."}
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": api_key},
                params={"pageSize": 200},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "models": [], "error": str(exc)}

    models = []
    for m in data.get("models", []):
        name = (m.get("name") or "").removeprefix("models/")
        methods = m.get("supportedGenerationMethods", []) or []
        if "generateContent" not in methods or not name.startswith("gemini"):
            continue
        models.append({"name": name, "vision": True})
    # Newest first tends to be most useful in a dropdown.
    models.sort(key=lambda m: m["name"], reverse=True)
    return {"ok": True, "models": models, "error": None}


# ------------------------------------------------------------------
# Ingest
# ------------------------------------------------------------------

@app.post("/sessions/{session_id}/ingest")
def ingest_session(session_id: str):
    """Read the manifest from the shared volume and register in SQLite."""
    _validate_session_id(session_id)
    session_dir = _session_dir(session_id)
    manifest_path = session_dir / "manifest.json"

    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Session manifest not found on volume.")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=422, detail="Could not parse manifest.json.")

    upsert_session(manifest)
    return {"status": "ingested", "session_id": session_id}


# ------------------------------------------------------------------
# Documentation generation (async background task)
# ------------------------------------------------------------------

class GenerateRequest(BaseModel):
    language: str = "en"
    title: str = ""
    description: str = ""
    sections: list[str] = []   # e.g. ["test_cases", "test_plan", "jira"]
    provider: str = "anthropic"  # "anthropic" | "ollama" | "groq" | "gemini"
    model: str = ""             # empty = use provider default


def _run_generation(
    session_id: str,
    language: str,
    title: str = "",
    description: str = "",
    sections: list[str] | None = None,
    provider: str = "anthropic",
    model: str = "",
) -> None:
    """Background task: call AI and write report.md to the session folder."""
    session_dir = _session_dir(session_id)
    report_dir = Path("/app/data/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{session_id}.md"

    update_session_status(session_id, "generating")
    try:
        report = generate_qa_docs(
            session_dir,
            language=language,
            title=title,
            description=description,
            sections=sections or [],
            provider=provider,
            model=model,
            project_context=_project_context_for(session_id),
        )
        report_path.write_text(report, encoding="utf-8")
        update_session_status(session_id, "done", str(report_path))
    except Exception as exc:
        update_session_status(session_id, f"error: {exc}")


def _project_context_for(session_id: str) -> str:
    """Resolve a session's project and return that project's saved context."""
    project = ""
    rec = get_session(session_id)
    if rec:
        project = (rec.get("project") or "").strip()
    if not project:
        manifest_path = _session_dir(session_id) / "manifest.json"
        if manifest_path.exists():
            try:
                project = (json.loads(manifest_path.read_text(encoding="utf-8"))
                           .get("project") or "").strip()
            except Exception:
                project = ""
    return get_project_context(project) if project else ""


@app.post("/sessions/{session_id}/generate")
def generate_docs(
    session_id: str,
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
):
    """Accept a documentation generation request; run it in the background."""
    _validate_session_id(session_id)
    session_dir = _session_dir(session_id)

    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session directory not found.")

    # Auto-ingest if not yet in DB
    if not get_session(session_id):
        manifest_path = session_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                upsert_session(manifest)
            except Exception:
                pass

    background_tasks.add_task(
        _run_generation,
        session_id,
        req.language,
        req.title,
        req.description,
        req.sections,
        req.provider,
        req.model,
    )
    return {"status": "generating", "session_id": session_id}


# ------------------------------------------------------------------
# Additional test cases (append to an existing report)
# ------------------------------------------------------------------

class MoreCasesRequest(BaseModel):
    language: str = "en"
    count: int = 5
    title: str = ""
    description: str = ""
    provider: str = "anthropic"
    model: str = ""


def _run_more_cases(session_id: str, req: MoreCasesRequest) -> None:
    """Background task: generate extra test cases and append to report.md."""
    session_dir = _session_dir(session_id)
    report_path = _report_path(session_id)
    update_session_status(session_id, "generating")
    try:
        existing = report_path.read_text(encoding="utf-8")
        extra = generate_more_test_cases(
            session_dir,
            existing_report=existing,
            language=req.language,
            count=max(1, min(req.count, 20)),
            title=req.title,
            description=req.description,
            provider=req.provider,
            model=req.model,
            project_context=_project_context_for(session_id),
        )
        report_path.write_text(existing + "\n\n---\n\n" + extra, encoding="utf-8")
        update_session_status(session_id, "done", str(report_path))
    except Exception as exc:
        # The original report is untouched on failure.
        update_session_status(session_id, f"error: {exc}")


@app.post("/sessions/{session_id}/report/more-cases")
def more_test_cases(
    session_id: str,
    req: MoreCasesRequest,
    background_tasks: BackgroundTasks,
):
    """Append N new (non-duplicate) test cases to an existing report."""
    _validate_session_id(session_id)
    if not _report_path(session_id).exists():
        raise HTTPException(status_code=404,
                            detail="Report not generated yet — generate it first.")
    if not _session_dir(session_id).exists():
        raise HTTPException(status_code=404, detail="Session directory not found.")
    background_tasks.add_task(_run_more_cases, session_id, req)
    return {"status": "generating", "session_id": session_id}


# ------------------------------------------------------------------
# Playwright script (deterministic — no AI)
# ------------------------------------------------------------------

@app.get("/sessions/{session_id}/playwright")
def get_playwright(session_id: str, language: str = "es"):
    """Generate a Playwright spec from the session's recorded events."""
    _validate_session_id(session_id)
    session_dir = _session_dir(session_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session directory not found.")
    # Use the session's name/project for a meaningful describe()/test() title.
    name, project = "", ""
    rec = get_session(session_id)
    if rec:
        name, project = (rec.get("name") or ""), (rec.get("project") or "")
    if not (name and project):
        manifest_path = session_dir / "manifest.json"
        if manifest_path.exists():
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                name = name or (m.get("name") or "")
                project = project or (m.get("project") or "")
            except Exception:
                pass
    from playwright_gen import generate_playwright
    return {"code": generate_playwright(
        session_dir, language=language, name=name, project=project)}


# ------------------------------------------------------------------
# Session metadata (name / project)
# ------------------------------------------------------------------

class MetaRequest(BaseModel):
    name: str = ""
    project: str = ""


@app.post("/sessions/{session_id}/meta")
def set_meta(session_id: str, req: MetaRequest):
    """Set a friendly name and project label for a session.

    Persists to the DB and mirrors the values into manifest.json so they
    survive a DB reset and show up in filesystem-only listings.
    """
    _validate_session_id(session_id)
    session_dir = _session_dir(session_id)

    # Ensure the session is in the DB (auto-ingest its manifest if present).
    if not get_session(session_id):
        manifest_path = session_dir / "manifest.json"
        if manifest_path.exists():
            try:
                upsert_session(json.loads(manifest_path.read_text(encoding="utf-8")))
            except Exception:
                pass

    name = req.name.strip() or None
    project = req.project.strip() or None
    set_session_meta(session_id, name, project)

    # Mirror into manifest.json (best effort).
    manifest_path = session_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["name"] = name
            manifest["project"] = project
            manifest_path.write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    return {"status": "ok", "session_id": session_id,
            "name": name, "project": project}


# ------------------------------------------------------------------
# Project context (per-project markdown that steers the AI)
# ------------------------------------------------------------------

class ContextRequest(BaseModel):
    context: str = ""


@app.get("/projects")
def get_projects():
    """List known project names (from saved context + sessions)."""
    return {"projects": list_project_names()}


@app.get("/projects/{name}/context")
def get_context(name: str):
    return {"name": name, "context": get_project_context(name)}


@app.put("/projects/{name}/context")
def put_context(name: str, req: ContextRequest):
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required.")
    set_project_context(name, req.context)
    return {"status": "ok", "name": name}


# ------------------------------------------------------------------
# Session listing
# ------------------------------------------------------------------

@app.get("/sessions")
def get_sessions():
    """Return all sessions — merging DB records with filesystem discovery."""
    db_sessions = list_sessions()
    known_ids = {s["session_id"] for s in db_sessions}

    # Discover sessions on the volume that are not yet in the DB
    extra: list[dict] = []
    if SESSIONS_BASE.exists():
        # Search flat layout (legacy) and one level of date subfolders
        candidates: list[Path] = []
        for entry in SESSIONS_BASE.iterdir():
            if not entry.is_dir():
                continue
            if re.match(r'^\d{4}-\d{2}-\d{2}$', entry.name):
                # Date subfolder — recurse one level
                for sub in entry.iterdir():
                    if sub.is_dir():
                        candidates.append(sub)
            else:
                candidates.append(entry)

        for session_dir in candidates:
            if session_dir.name in known_ids:
                continue
            manifest_path = session_dir / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest.setdefault("status", "captured")
                    extra.append(manifest)
                except Exception:
                    pass

    return db_sessions + extra


# ------------------------------------------------------------------
# Session detail
# ------------------------------------------------------------------

@app.get("/sessions/{session_id}")
def get_session_detail(session_id: str):
    _validate_session_id(session_id)
    session_dir = _session_dir(session_id)
    db_record = get_session(session_id)

    if session_dir.exists():
        manifest_path = session_dir / "manifest.json"
        if manifest_path.exists():
            try:
                detail = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                detail = db_record or {}
        else:
            detail = db_record or {}
    elif db_record:
        detail = db_record
    else:
        raise HTTPException(status_code=404, detail="Session not found.")

    detail["status"] = db_record.get("status", "captured") if db_record else "captured"
    detail["has_report"] = _report_path(session_id).exists()
    return detail


# ------------------------------------------------------------------
# Events log
# ------------------------------------------------------------------

@app.get("/sessions/{session_id}/events")
def get_events(session_id: str):
    """Return the parsed events array from events.jsonl."""
    _validate_session_id(session_id)
    events_file = _session_dir(session_id) / "events.jsonl"
    if not events_file.exists():
        return {"events": []}
    events = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return {"events": events}


# ------------------------------------------------------------------
# Screenshot serving
# ------------------------------------------------------------------

@app.get("/sessions/{session_id}/screenshots/{filename}")
def get_screenshot(session_id: str, filename: str):
    """Serve a single screenshot PNG from the shared volume."""
    _validate_session_id(session_id)
    if not re.match(r'^[\w.\-]+\.png$', filename, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    img_path = _session_dir(session_id) / "screenshots" / filename
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    return FileResponse(str(img_path), media_type="image/png")


# ------------------------------------------------------------------
# Report retrieval
# ------------------------------------------------------------------

@app.get("/sessions/{session_id}/report")
def get_report(session_id: str):
    _validate_session_id(session_id)
    report_path = _report_path(session_id)
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not yet generated.")
    return {"report": report_path.read_text(encoding="utf-8")}


# ------------------------------------------------------------------
# Delete session
# ------------------------------------------------------------------

@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """Remove a session from the DB, delete its report, and delete the session folder."""
    _validate_session_id(session_id)
    # 1. Delete report file
    _report_path(session_id).unlink(missing_ok=True)
    # 2. Remove from DB
    delete_session_db(session_id)
    # 3. Remove session folder from shared volume
    session_dir = _session_dir(session_id)
    if session_dir.exists():
        shutil.rmtree(session_dir)
    return {"status": "deleted", "session_id": session_id}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _report_path(session_id: str) -> Path:
    return Path("/app/data/reports") / f"{session_id}.md"


def _validate_session_id(session_id: str) -> None:
    """Reject session IDs that contain path traversal characters."""
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        raise HTTPException(status_code=400, detail="Invalid session ID.")


def _session_dir(session_id: str) -> Path:
    """Locate the session directory, searching one level of date subfolders.

    New layout: qa-sessions/YYYY-MM-DD/{uuid}/
    Legacy layout: qa-sessions/{uuid}/   (still supported)
    """
    # Fast path — legacy flat layout
    flat = SESSIONS_BASE / session_id
    if flat.exists():
        return flat
    # New layout — scan one level of date subdirs
    if SESSIONS_BASE.exists():
        for date_dir in SESSIONS_BASE.iterdir():
            if date_dir.is_dir() and re.match(r'^\d{4}-\d{2}-\d{2}$', date_dir.name):
                candidate = date_dir / session_id
                if candidate.exists():
                    return candidate
    # Not found — return the flat path (callers handle .exists() checks)
    return flat
