"""
voice_output.py - TTS: Kokoro ONNX (primary) → ElevenLabs (optional) → pyttsx3 (fallback)
Natural speech chunking with pause durations.
"""
import os
import re
import time
import threading
import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env", override=True)

TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))
OUTPUT_DEVICE = int(os.getenv("OUTPUT_DEVICE", "3"))
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

IS_SPEAKING = False
SPEAKING_LOCK = threading.Lock()

# Natural pause durations (seconds) after each boundary
PAUSE_AFTER = {
    "sir.": 0.60, "sir!": 0.60, "sir?": 0.60,
    "sir,": 0.25,
    "...": 0.35,
    "—": 0.25,
    ",": 0.18,
    ".": 0.45,
    "!": 0.45,
    "?": 0.45,
}

CHUNK_RE = re.compile(r'(?<=[.!?])\s+|(?<=,\s)(?=[A-Z])|(?=\s—\s)|(?<=sir[.,!?])\s*')


def _clean_for_speech(text: str) -> str:
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'`+', '', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\[ACTION:[^\]]+\][^\n]*', '', text)
    return text.strip()


def _split_into_chunks(text: str) -> list[str]:
    """Split on natural sentence boundaries for lower perceived latency."""
    chunks = []
    current = ""
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        sentence = sentence.strip()
        if not sentence:
            continue
        # Keep short sentences together
        if len(current) + len(sentence) < 150:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks or [text]


def _pause_after_chunk(chunk: str):
    """Sleep the appropriate pause duration after a spoken chunk."""
    lower = chunk.lower().rstrip()
    if lower.endswith(("sir.", "sir!", "sir?")):
        time.sleep(0.60)
    elif lower.endswith(("...",)):
        time.sleep(0.35)
    elif lower.endswith((".", "!", "?")):
        time.sleep(0.45)
    elif lower.endswith(","):
        time.sleep(0.18)


class VoiceOutput:
    def __init__(self):
        print("[TTS] Loading Kokoro model...")
        from kokoro_onnx import Kokoro
        self.kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
        self.voice = "af_sarah"
        self._output_device = self._detect_output_device()
        print(f"[TTS] Kokoro ready (output device {self._output_device}).")

    def _detect_output_device(self) -> int:
        """Use configured device, fall back to scanning for Realtek."""
        try:
            devices = sd.query_devices()
            # Try configured index first
            d = devices[OUTPUT_DEVICE]
            if d["max_output_channels"] > 0:
                return OUTPUT_DEVICE
        except Exception:
            pass
        # Scan for Realtek speakers
        try:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if "realtek" in d["name"].lower() and d["max_output_channels"] > 0:
                    return i
        except Exception:
            pass
        return OUTPUT_DEVICE

    def _speak_kokoro(self, text: str):
        global IS_SPEAKING
        chunks = _split_into_chunks(text)

        with SPEAKING_LOCK:
            IS_SPEAKING = True

        try:
            for chunk in chunks:
                if not chunk.strip():
                    continue
                samples, sample_rate = self.kokoro.create(
                    chunk, voice=self.voice, speed=TTS_SPEED, lang="en-us"
                )
                sd.play(samples, sample_rate, device=self._output_device)
                sd.wait()
                _pause_after_chunk(chunk)
        finally:
            with SPEAKING_LOCK:
                IS_SPEAKING = False
            time.sleep(0.4)

    def _speak_elevenlabs(self, text: str):
        global IS_SPEAKING
        try:
            import httpx
            headers = {
                "xi-api-key": ELEVENLABS_KEY,
                "Content-Type": "application/json",
            }
            payload = {
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            }
            resp = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                json=payload, headers=headers, timeout=10.0
            )
            if resp.status_code == 200:
                import io, soundfile as sf, numpy as np
                data, rate = sf.read(io.BytesIO(resp.content))
                with SPEAKING_LOCK:
                    IS_SPEAKING = True
                try:
                    sd.play(data.astype(np.float32), rate, device=self._output_device)
                    sd.wait()
                finally:
                    with SPEAKING_LOCK:
                        IS_SPEAKING = False
                    time.sleep(0.4)
                return True
        except Exception as e:
            print(f"[TTS] ElevenLabs failed: {e}")
        return False

    def _speak_fallback(self, text: str):
        global IS_SPEAKING
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            with SPEAKING_LOCK:
                IS_SPEAKING = True
            try:
                engine.say(text)
                engine.runAndWait()
            finally:
                with SPEAKING_LOCK:
                    IS_SPEAKING = False
                time.sleep(0.4)
        except Exception as e:
            print(f"[TTS] pyttsx3 fallback failed: {e}")

    def speak(self, text: str):
        if not text or not text.strip():
            return

        clean = _clean_for_speech(text)
        if not clean:
            return

        print(f"[TTS] {clean[:90]}{'...' if len(clean) > 90 else ''}")

        try:
            self._speak_kokoro(clean)
        except Exception as e:
            print(f"[TTS] Kokoro failed: {e}")
            if ELEVENLABS_KEY:
                if not self._speak_elevenlabs(clean):
                    self._speak_fallback(clean)
            else:
                self._speak_fallback(clean)

    def generate_audio_bytes(self, text: str) -> tuple[np.ndarray, int]:
        """Generate audio samples without playing. Returns (samples, sample_rate)."""
        clean = _clean_for_speech(text)
        return self.kokoro.create(clean, voice=self.voice, speed=TTS_SPEED, lang="en-us")
