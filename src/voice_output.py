"""
voice_output.py - TTS: Kokoro ONNX (primary) -> ElevenLabs (optional) -> pyttsx3 (fallback)
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
USE_ELEVENLABS = os.getenv("USE_ELEVENLABS", "false").lower() == "true"
TTS_VOICE = os.getenv("TTS_VOICE", "af_sarah")

IS_SPEAKING = False
SHOULD_STOP_SPEAKING = False
SPEAKING_LOCK = threading.Lock()
STOP_LOCK = threading.Lock()

# Kokoro model singleton
_kokoro = None
_kokoro_lock = threading.Lock()

# Natural pause durations (seconds)
PAUSE_AFTER = {
    "sir.": 0.60, "sir!": 0.60, "sir?": 0.60,
    "sir,": 0.25,
    "...": 0.35,
    ",": 0.18,
    ".": 0.45,
    "!": 0.45,
    "?": 0.45,
}


def _get_kokoro():
    global _kokoro
    with _kokoro_lock:
        if _kokoro is None:
            try:
                from kokoro_onnx import Kokoro
                model_path = "C:/Users/micha/jarvis/models/kokoro-v0_19.onnx"
                voices_path = "C:/Users/micha/jarvis/models/voices.json"
                _kokoro = Kokoro(model_path, voices_path)
            except Exception as e:
                print(f"[TTS] Kokoro init failed: {e}")
                _kokoro = None
    return _kokoro


def _clean_for_speech(text: str) -> str:
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'`+', '', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\[ACTION:[^\]]+\][^\n]*', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _split_into_chunks(text: str) -> list:
    """Split on natural sentence boundaries for lower perceived latency."""
    chunks = []
    current = ""
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        sentence = sentence.strip()
        if not sentence:
            continue
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
    elif lower.endswith("..."):
        time.sleep(0.35)
    elif lower.endswith((".", "!", "?")):
        time.sleep(0.45)
    elif lower.endswith(","):
        time.sleep(0.18)


def _speak_elevenlabs(text: str):
    """Speak using ElevenLabs cloud TTS."""
    import requests
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=15)
    resp.raise_for_status()

    audio_bytes = b""
    for chunk in resp.iter_content(chunk_size=4096):
        if chunk:
            audio_bytes += chunk

    import io
    import soundfile as sf
    data, samplerate = sf.read(io.BytesIO(audio_bytes))
    if data.ndim > 1:
        data = data[:, 0]
    sd.play(data.astype(np.float32), samplerate=samplerate, device=OUTPUT_DEVICE)
    sd.wait()


def _speak_kokoro(text: str):
    """Speak using local Kokoro ONNX TTS."""
    # Always read TTS_VOICE fresh from env so live switching works
    voice = os.getenv("TTS_VOICE", "af_sarah")
    speed = float(os.getenv("TTS_SPEED", "1.0"))
    kokoro = _get_kokoro()
    if kokoro is None:
        raise RuntimeError("Kokoro not available")
    samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    sd.play(samples.astype(np.float32), samplerate=sample_rate, device=OUTPUT_DEVICE)
    sd.wait()


def _speak_pyttsx3(text: str):
    """Fallback TTS using pyttsx3."""
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    # Try to pick a male voice if TTS_VOICE suggests male (am_ prefix)
    voice = os.getenv("TTS_VOICE", "af_sarah")
    if voice.startswith("am_") and voices:
        for v in voices:
            if "male" in v.name.lower() or "david" in v.name.lower() or "mark" in v.name.lower():
                engine.setProperty("voice", v.id)
                break
    engine.setProperty("rate", int(200 * float(os.getenv("TTS_SPEED", "1.0"))))
    engine.say(text)
    engine.runAndWait()


class VoiceOutput:
    def speak(self, text: str):
        global IS_SPEAKING, SHOULD_STOP_SPEAKING
        text = _clean_for_speech(text)
        if not text:
            return

        with SPEAKING_LOCK:
            IS_SPEAKING = True
        with STOP_LOCK:
            SHOULD_STOP_SPEAKING = False

        try:
            chunks = _split_into_chunks(text)
            for chunk in chunks:
                with STOP_LOCK:
                    if SHOULD_STOP_SPEAKING:
                        break
                try:
                    if USE_ELEVENLABS and ELEVENLABS_KEY:
                        _speak_elevenlabs(chunk)
                    else:
                        _speak_kokoro(chunk)
                except Exception as e:
                    print(f"[TTS] Primary TTS failed ({e}), trying pyttsx3")
                    try:
                        _speak_pyttsx3(chunk)
                    except Exception as e2:
                        print(f"[TTS] pyttsx3 also failed: {e2}")
                _pause_after_chunk(chunk)
        finally:
            with SPEAKING_LOCK:
                IS_SPEAKING = False

    def stop_speech(self):
        global SHOULD_STOP_SPEAKING
        with STOP_LOCK:
            SHOULD_STOP_SPEAKING = True
        try:
            sd.stop()
        except Exception:
            pass


# Module-level convenience wrappers
_instance = VoiceOutput()


def speak(text: str):
    _instance.speak(text)


def stop_speech():
    _instance.stop_speech()
