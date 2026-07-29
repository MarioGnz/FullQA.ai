"""
uploader.py — Sends session metadata to the Docker backend API.

All communication is to http://localhost:8000 only.
No data leaves the local machine.
"""

import requests

API_BASE = "http://localhost:8000"
_TIMEOUT_SHORT = 15   # seconds — for lightweight calls
_TIMEOUT_LONG  = 300  # seconds — doc generation can be slow


def ingest_session(session_id: str) -> bool:
    """
    Tell the API to read the session manifest from the shared volume
    and register it in the SQLite database.
    Returns True on success.
    """
    try:
        resp = requests.post(
            f"{API_BASE}/sessions/{session_id}/ingest",
            timeout=_TIMEOUT_SHORT,
        )
        resp.raise_for_status()
        print(f"[uploader] Session {session_id} ingested by API.")
        return True
    except requests.RequestException as exc:
        print(f"[uploader] Ingest failed: {exc}")
        return False


def trigger_doc_generation(session_id: str, language: str = "en") -> bool:
    """
    Ask the API to kick off async Claude documentation generation.
    Returns True if the request was accepted (HTTP 200).
    Poll /sessions/{id} for status == 'done' separately.
    """
    try:
        resp = requests.post(
            f"{API_BASE}/sessions/{session_id}/generate",
            json={"language": language},
            timeout=_TIMEOUT_SHORT,
        )
        resp.raise_for_status()
        print(f"[uploader] Doc generation started for session {session_id}.")
        return True
    except requests.RequestException as exc:
        print(f"[uploader] Doc generation request failed: {exc}")
        return False


def get_report(session_id: str) -> str | None:
    """
    Fetch the generated Markdown report.  Returns None if not ready.
    """
    try:
        resp = requests.get(
            f"{API_BASE}/sessions/{session_id}/report",
            timeout=_TIMEOUT_SHORT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("report", "")
    except requests.RequestException as exc:
        print(f"[uploader] Fetch report failed: {exc}")
        return None
