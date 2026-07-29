"""
session.py — Session lifecycle management.

Creates the on-disk directory structure, writes/updates manifest.json,
and provides a thread-safe method for appending events to events.jsonl.
"""

import json
import platform
import threading
import uuid
import datetime
import pathlib


class Session:
    """Represents a single QA recording session."""

    def __init__(self, language: str = "en", audio_enabled: bool = False):
        self.session_id: str = str(uuid.uuid4())
        self.language: str = language
        self.audio_enabled: bool = audio_enabled
        self.started_at: str = datetime.datetime.utcnow().isoformat() + "Z"
        self.ended_at: str | None = None
        self.event_count: int = 0
        self.screenshot_count: int = 0
        self.os_name: str = "win" if platform.system() == "Windows" else "mac"

        date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        self.session_dir = pathlib.Path(f"./qa-sessions/{date_str}/{self.session_id}")
        self.screenshots_dir = self.session_dir / "screenshots"
        self.events_log = self.session_dir / "events.jsonl"

        self._lock = threading.Lock()
        self._create_dirs()
        self._write_manifest()

    # ------------------------------------------------------------------
    # Directory / manifest helpers
    # ------------------------------------------------------------------

    def _create_dirs(self) -> None:
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def _write_manifest(self) -> None:
        manifest = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "os": self.os_name,
            "language": self.language,
            "audio_enabled": self.audio_enabled,
            "event_count": self.event_count,
            "screenshot_count": self.screenshot_count,
        }
        with open(self.session_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    # ------------------------------------------------------------------
    # Event logging (thread-safe)
    # ------------------------------------------------------------------

    def log_event(self, event: dict) -> None:
        """Append one event dict as a JSONL line; update counters."""
        with self._lock:
            with open(self.events_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
            self.event_count += 1
            if event.get("screenshot"):
                self.screenshot_count += 1

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def end(self) -> None:
        """Stamp the end time and flush the manifest to disk."""
        self.ended_at = datetime.datetime.utcnow().isoformat() + "Z"
        self._write_manifest()

    def get_status(self) -> dict:
        return {
            "session_id": self.session_id,
            "event_count": self.event_count,
            "screenshot_count": self.screenshot_count,
            "started_at": self.started_at,
        }
