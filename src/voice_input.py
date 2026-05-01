"""
voice_input.py - Wake word detection + STT (faster-whisper primary, Groq optional)
"""
import os
import re
import time
import threading
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeWordModel
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env", override=True)

WAKE_WORD = os.getenv("WAKE_WORD", "hey jarvis")
SAMPLE_RATE = 16000
WAKE_CHUNK = 1280
MIC_DEVICE = int(os.getenv("MIC_DEVICE", "1"))
OUTPUT_DEVICE = int(os.getenv("OUTPUT_DEVICE", "3"))

# Session-based listening: after wake word detected, stay active for this many seconds
SESSION_DURATION = 30  # seconds

# Stop command keywords - if any of these appear in transcription, it's a stop command
STOP_KEYWORDS = ["stop"]

# Global session state
session_active_until: float = 0.0
_session_lock = threading.Lock()


def _get_mic_channels(device: int) -> int:
    """Return a channel count the device will actually accept at SAMPLE_RATE."""
    try:
        info = sd.query_devices(device, "input")
        reported = max(1, int(info["max_input_channels"]))
    except Exception:
        reported = 1
    for ch in dict.fromkeys([reported, 1, 2]):
        try:
            sd.check_input_settings(device=device, channels=ch, dtype="float32",
                                    samplerate=SAMPLE_RATE)
            return ch
        except Exception:
            continue
    return reported


STT_CORRECTIONS = {
    r"\bcloud\b": "Claude",
    r"\bjarves\b": "JARVIS",
    r"\btravis\b": "JARVIS",
    r"\bcloud code\b": "Claude Code",
}

# Common Whisper / Whisper-large hallucinations from silence and TTS bleed.
WHISPER_HALLUCINATIONS = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching.",
    "thanks for watching!", "you", "you.", ".", "!", "...", "bye",
    "thank you for watching", "subscribe", "thanks", "thanks.",
    "please subscribe", "thank you very much", "okay", "ok", "uh", "um",
    "i'll see you next time", "see you next time",
    "i'd love for you", "you have your watch or phone here",
}


def _is_likely_hallucination(text: str) -> bool:
    """Filter out Whisper's known phantom outputs from silence / TTS bleed."""
    if not text:
        return True
    stripped = text.strip().strip('.,!? ').lower()
    if stripped in WHISPER_HALLUCINATIONS:
        return True
    ascii_chars = sum(1 for c in stripped if ord(c) < 128)
    if len(stripped) > 0 and ascii_chars / len(stripped) < 0.7:
        return True
    if len(stripped.split()) < 2 and stripped not in {"yes", "no", "stop", "cancel"}:
        return True
    words = stripped.split()
    long_no_vowel = sum(1 for w in words if len(w) > 8 and not any(v in w for v in "aeiou"))
    if long_no_vowel >= 1:
        return True
    return False


def _apply_stt_corrections(text: str) -> str:
    """Apply regex-based corrections to common STT errors."""
    for pattern, replacement in STT_CORRECTIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def is_session_active() -> bool:
    """Return True if we are currently in an active listening session."""
    with _session_lock:
        return time.time() < session_active_until


def extend_session() -> None:
    """Extend (or start) the listening session for SESSION_DURATION seconds."""
    global session_active_until
    with _session_lock:
        session_active_until = time.time() + SESSION_DURATION


def end_session() -> None:
    """Immediately end the current listening session."""
    global session_active_until
    with _session_lock:
        session_active_until = 0.0


# ---------------------------------------------------------------------------
# Whisper model (loaded once at import time)
# ---------------------------------------------------------------------------
_whisper_model: WhisperModel | None = None
_whisper_lock = threading.Lock()


def _get_whisper_model() -> WhisperModel:
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            model_size = os.getenv("WHISPER_MODEL", "base")
            _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _whisper_model


# ---------------------------------------------------------------------------
# Stop command detection
# ---------------------------------------------------------------------------

def detect_stop_command(duration: float = 2.5) -> bool:
    """
    Listen for a short audio snippet and check whether the user said a stop phrase.

    The function records audio for *duration* seconds (default 2.5 s), transcribes
    it with faster-whisper, and returns True if any word in STOP_KEYWORDS is found
    in the transcription.  All errors are caught so that the function never raises
    and never blocks the main loop for longer than ~(duration + 2) seconds.

    Parameters
    ----------
    duration : float
        How many seconds of audio to record.  Clamped to [0.5, 3.0].

    Returns
    -------
    bool
        True  – a stop keyword was detected.
        False – no stop keyword, or an error occurred.
    """
    duration = max(0.5, min(3.0, duration))

    try:
        num_frames = int(SAMPLE_RATE * duration)
        channels = _get_mic_channels(MIC_DEVICE)

        # Record a short audio burst directly (blocking call with a hard timeout)
        audio_data: np.ndarray | None = None

        def _record() -> None:
            nonlocal audio_data
            try:
                recording = sd.rec(
                    num_frames,
                    samplerate=SAMPLE_RATE,
                    channels=channels,
                    dtype="float32",
                    device=MIC_DEVICE,
                )
                sd.wait()
                audio_data = recording
            except Exception as exc:
                print(f"[detect_stop_command] Recording error: {exc}")

        record_thread = threading.Thread(target=_record, daemon=True)
        record_thread.start()
        # Give the recording thread at most duration + 1 s to finish
        record_thread.join(timeout=duration + 1.0)

        if audio_data is None:
            return False

        # Convert to mono float32 numpy array expected by faster-whisper
        if audio_data.ndim > 1:
            mono = audio_data.mean(axis=1)
        else:
            mono = audio_data.flatten()

        mono = mono.astype(np.float32)

        # Transcribe with faster-whisper
        model = _get_whisper_model()
        segments, _ = model.transcribe(
            mono,
            language="en",
            beam_size=1,
            vad_filter=True,
        )

        transcription = " ".join(seg.text for seg in segments).strip().lower()
        print(f"[detect_stop_command] Transcription: '{transcription}'")

        if not transcription:
            return False

        # Check for any stop keyword in the transcription
        for keyword in STOP_KEYWORDS:
            if keyword.lower() in transcription:
                print(f"[detect_stop_command] Stop keyword '{keyword}' detected.")
                return True

        return False

    except Exception as exc:
        print(f"[detect_stop_command] Unexpected error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Core STT helpers
# ---------------------------------------------------------------------------

def transcribe_audio(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe a numpy audio array using faster-whisper."""
    try:
        model = _get_whisper_model()
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)

        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=True,
        )
        raw = " ".join(seg.text for seg in segments).strip()

        if _is_likely_hallucination(raw):
            return ""

        corrected = _apply_stt_corrections(raw)
        return corrected

    except Exception as exc:
        print(f"[transcribe_audio] Error: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Wake-word + session-based listening loop
# ---------------------------------------------------------------------------

def listen_for_wake_word(callback) -> None:
    """
    Continuously listen for the wake word.  When detected, extend the session
    and call *callback* with the transcribed follow-up utterance (if any).

    This function blocks indefinitely and is intended to be run in a thread.
    """
    try:
        oww_model = WakeWordModel(
            wakeword_models=["hey_jarvis"],
            inference_framework="onnx",
        )
    except Exception as exc:
        print(f"[listen_for_wake_word] Failed to load wake-word model: {exc}")
        return

    channels = _get_mic_channels(MIC_DEVICE)
    print(f"[listen_for_wake_word] Listening on device {MIC_DEVICE} "
          f"({channels} ch) for '{WAKE_WORD}' …")

    audio_buffer: list[np.ndarray] = []

    def audio_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            print(f"[audio_callback] Status: {status}")
        # Convert to mono int16 for openwakeword
        mono = indata.mean(axis=1) if indata.ndim > 1 else indata.flatten()
        chunk_int16 = (mono * 32767).astype(np.int16)
        prediction = oww_model.predict(chunk_int16)

        triggered = any(
            score > 0.5
            for model_name, score in prediction.items()
            if "hey_jarvis" in model_name.lower()
        )

        if triggered:
            print("[listen_for_wake_word] Wake word detected!")
            extend_session()
            # Snapshot current buffer for potential follow-up transcription
            if audio_buffer:
                combined = np.concatenate(audio_buffer)
                audio_buffer.clear()
                text = transcribe_audio(combined)
                if text:
                    callback(text)
            else:
                callback("")
        else:
            # Keep a rolling ~3-second buffer for follow-up transcription
            audio_buffer.append(mono.copy())
            max_chunks = int(SAMPLE_RATE * 3 / WAKE_CHUNK)
            while len(audio_buffer) > max_chunks:
                audio_buffer.pop(0)

    try:
        with sd.InputStream(
            device=MIC_DEVICE,
            channels=channels,
            samplerate=SAMPLE_RATE,
            blocksize=WAKE_CHUNK,
            dtype="float32",
            callback=audio_callback,
        ):
            while True:
                time.sleep(0.1)
    except Exception as exc:
        print(f"[listen_for_wake_word] Stream error: {exc}")


def listen_once(timeout: float = 10.0) -> str:
    """
    Record until silence or *timeout* seconds, then return the transcription.
    Intended to be called after the wake word is detected.
    """
    duration = min(timeout, SESSION_DURATION)
    channels = _get_mic_channels(MIC_DEVICE)

    try:
        num_frames = int(SAMPLE_RATE * duration)
        recording = sd.rec(
            num_frames,
            samplerate=SAMPLE_RATE,
            channels=channels,
            dtype="float32",
            device=MIC_DEVICE,
        )
        sd.wait()
        return transcribe_audio(recording)
    except Exception as exc:
        print(f"[listen_once] Error: {exc}")
        return ""