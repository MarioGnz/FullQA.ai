"""
audio.py — Optional background audio recording and offline transcription.

Recording:
  - Captures microphone input in a daemon thread using sounddevice.
  - Saves a 16 kHz mono WAV to ./qa-sessions/{id}/audio.wav on stop.

Transcription:
  - Uses faster-whisper (runs 100% offline, CPU-only).
  - Model downloaded once to ./models/ on first use.
  - Language: "en" or "es" (or None for auto-detect).
  - Transcript written to ./qa-sessions/{id}/transcript.txt.
"""

import threading
from pathlib import Path

import numpy as np
import scipy.io.wavfile as wav_io
import sounddevice as sd

SAMPLE_RATE = 16_000   # Hz — matches Whisper's native rate
CHANNELS = 1
DTYPE = "int16"


class AudioRecorder:
    """Records microphone audio and transcribes it with faster-whisper."""

    def __init__(self, session, language: str = "en", device: int | None = None):
        self.session = session
        self.language = language if language in ("en", "es") else None
        self.device = device

        self._frames: list[np.ndarray] = []
        self._recording = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _record_loop(self) -> None:
        def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            if self._recording:
                with self._lock:
                    self._frames.append(indata.copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            device=self.device,
            callback=_callback,
        ):
            while self._recording:
                sd.sleep(100)

    def start(self) -> None:
        self._recording = True
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._recording = False
        if self._thread:
            self._thread.join(timeout=5)
        self._save_audio()

    # ------------------------------------------------------------------
    # Save + transcribe
    # ------------------------------------------------------------------

    def _save_audio(self) -> None:
        with self._lock:
            frames = list(self._frames)

        if not frames:
            return

        audio_path = self.session.session_dir / "audio.wav"
        audio_data = np.concatenate(frames, axis=0)
        wav_io.write(str(audio_path), SAMPLE_RATE, audio_data)
        print(f"[audio] Saved: {audio_path}")
        self._transcribe(audio_path)

    def _transcribe(self, audio_path: Path) -> None:
        try:
            from faster_whisper import WhisperModel

            model_dir = Path("./models")
            model_dir.mkdir(exist_ok=True)
            print("[audio] Loading Whisper model (downloads on first run)…")

            model = WhisperModel(
                "base",
                download_root=str(model_dir),
                device="cpu",
                compute_type="int8",
            )
            segments, info = model.transcribe(
                str(audio_path),
                language=self.language,
                beam_size=5,
            )
            transcript_lines = [seg.text.strip() for seg in segments]
            transcript = "\n".join(transcript_lines)

            transcript_path = self.session.session_dir / "transcript.txt"
            transcript_path.write_text(transcript, encoding="utf-8")
            print(f"[audio] Transcript saved ({info.language}, {len(transcript_lines)} segments)")

        except ImportError:
            print("[audio] faster-whisper not installed — skipping transcription.")
        except Exception as exc:
            print(f"[audio] Transcription error: {exc}")
