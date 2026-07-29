"""
main.py — Host Agent entry point.

Usage
-----
  # System-tray mode (default): right-click icon to start/stop
  python agent/main.py

  # Headless mode: starts recording immediately, Ctrl-C to stop
  python agent/main.py --no-tray

  # Spanish narration with audio recording
  python agent/main.py --lang es --audio

  # After stopping, trigger documentation generation via the Docker backend
  python agent/main.py --generate <session_id>

Environment
-----------
  The agent writes data to ./qa-sessions/<uuid>/ relative to the
  directory from which it is launched (the project root).
"""

import argparse
import signal
import sys
import time
from pathlib import Path

# Allow running as `python agent/main.py` from the project root.
sys.path.insert(0, str(Path(__file__).parent))

from session import Session
from capture import EventCapture
from audio import AudioRecorder
from tray import TrayApp
from uploader import ingest_session, trigger_doc_generation, get_report


# ------------------------------------------------------------------
# Global state (intentionally module-level for signal handler access)
# ------------------------------------------------------------------
_session: Session | None = None
_capture: EventCapture | None = None
_audio: AudioRecorder | None = None
_recording = False


# ------------------------------------------------------------------
# Recording lifecycle
# ------------------------------------------------------------------

def start_recording() -> None:
    global _recording
    if _recording:
        print("[agent] Already recording.")
        return
    _recording = True
    if _capture:
        _capture.start()
    if _audio:
        _audio.start()
    print(f"[agent] Recording started — session: {_session.session_id}")
    print(f"[agent] Data folder : {_session.session_dir.resolve()}")


def stop_recording() -> None:
    global _recording
    if not _recording:
        return
    _recording = False
    print("[agent] Stopping…")
    if _capture:
        _capture.stop()
    if _audio:
        _audio.stop()   # blocks until WAV is saved and transcribed
    if _session:
        _session.end()
        print(f"[agent] Session ended. Events: {_session.event_count}, "
              f"Screenshots: {_session.screenshot_count}")
        # Notify the Docker backend (non-fatal if backend is not running)
        ingest_session(_session.session_id)


def print_status() -> None:
    if _session:
        s = _session.get_status()
        print(f"[agent] Status — events: {s['event_count']}, "
              f"screenshots: {s['screenshot_count']}, "
              f"recording: {_recording}")
    else:
        print("[agent] No active session.")


# ------------------------------------------------------------------
# Signal handler
# ------------------------------------------------------------------

def _handle_sigint(sig, frame) -> None:
    print("\n[agent] Interrupted.")
    stop_recording()
    sys.exit(0)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FullQA.ai Host Agent — capture screen events and generate QA docs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent/main.py                          # tray UI, English
  python agent/main.py --lang es --audio        # tray UI, Spanish + audio
  python agent/main.py --no-tray                # headless, start immediately
  python agent/main.py --generate <session_id>  # generate docs for past session
        """,
    )
    parser.add_argument(
        "--lang",
        choices=["en", "es"],
        default="en",
        help="Language for generated documentation (default: en)",
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help="Enable microphone recording and offline transcription",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Skip the system tray; start recording immediately",
    )
    parser.add_argument(
        "--generate",
        metavar="SESSION_ID",
        help="Trigger documentation generation for an existing session ID and exit",
    )
    return parser.parse_args()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main() -> None:
    global _session, _capture, _audio

    args = _parse_args()

    # ------------------------------------------------------------------
    # --generate mode: just trigger doc gen for an existing session
    # ------------------------------------------------------------------
    if args.generate:
        session_id = args.generate
        print(f"[agent] Requesting documentation generation for session {session_id}…")
        if not trigger_doc_generation(session_id, args.lang):
            sys.exit(1)
        print("[agent] Generation started. Poll http://localhost:3000 for results.")
        sys.exit(0)

    # ------------------------------------------------------------------
    # Normal recording mode
    # ------------------------------------------------------------------
    _session = Session(language=args.lang, audio_enabled=args.audio)
    _capture = EventCapture(_session)
    _audio = AudioRecorder(_session, language=args.lang) if args.audio else None

    signal.signal(signal.SIGINT, _handle_sigint)

    if args.no_tray:
        # Headless: start immediately, block until Ctrl-C.
        start_recording()
        print("[agent] Press Ctrl-C to stop recording.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        stop_recording()
    else:
        # System-tray mode (blocks until Quit is chosen from menu).
        tray = TrayApp(
            on_start=start_recording,
            on_stop=stop_recording,
            on_status=print_status,
            on_quit=lambda: sys.exit(0),
        )
        print("[agent] System tray active — right-click the icon to control recording.")
        tray.run()


if __name__ == "__main__":
    main()
