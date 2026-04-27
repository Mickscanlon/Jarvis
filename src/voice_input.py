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


def _get_mic_channels(device: int) -> int:
    """Return the input channel count the device actually supports (min 1)."""
    try:
        info = sd.query_devices(device, "input")
        return max(1, int(info["max_input_channels"]))
    except Exception:
        return 1

STT_CORRECTIONS = {
    r"\bcloud\b": "Claude",
    r"\bjarves\b": "JARVIS",
    r"\btravis\b": "JARVIS",
    r"\bcloud code\b": "Claude Code",
}

# Common Whisper / Whisper-large hallucinations from silence and TTS bleed.
# These appear when the model is given audio with no real speech content.
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
    # Non-ASCII (Whisper sometimes emits Japanese / Korean / Chinese from noise)
    ascii_chars = sum(1 for c in stripped if ord(c) < 128)
    if len(stripped) > 0 and ascii_chars / len(stripped) < 0.7:
        return True
    # Very short utterances are usually hallucinations after the wake word
    if len(stripped.split()) < 2 and stripped not in {"yes", "no", "stop", "cancel"}:
        return True
    # Gibberish detector: long words with no vowels, or mash-ups
    # ("placesoded費aledailedalngjil" — Whisper concatenating fragments)
    words = stripped.split()
    long_no_vowel = sum(1 for w in words if len(w) > 8 and not any(v in w for v in "aeiou"))
    if long_no_vowel >= 1:
        return True
    # Words containing 4+ consecutive consonants (rare in real English)
    import re as _re
    if _re.search(r'[bcdfghjklmnpqrstvwxyz]{5,}', stripped):
        return True
    # Sentence fragments that don't start with a capital after wake word
    # (TTS bleed often captures mid-sentence: "like golf, which aligns...")
    if stripped.startswith(("like ", "which ", "and ", "but ", "or ", "that ",
                            "with ", "for ", "from ", "into ", "of the ")):
        return True
    return False


class VoiceInput:
    def __init__(self):
        print("[Voice] Loading Whisper model (tiny.en)...")
        self.whisper = WhisperModel("tiny.en", device="cpu", compute_type="int8")

        print("[Voice] Loading wake word model...")
        self.wakeword = WakeWordModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")

        # Note: GROQ_API_KEY and USE_GROQ are re-read on every transcribe()
        # call so toggling them in the UI takes effect immediately.
        self._stop_event = threading.Event()
        initial_backend = ("Groq API"
                           if (os.getenv("GROQ_API_KEY") and
                               os.getenv("USE_GROQ", "true").lower() == "true")
                           else "faster-whisper (local)")
        print(f"[Voice] STT backend: {initial_backend} (toggleable at runtime)")

        print(f"[Voice] Mic device {MIC_DEVICE} | Output device {OUTPUT_DEVICE}")
        print(f"[Voice] Ready. Say '{WAKE_WORD}' to activate.")

    def _apply_corrections(self, text: str) -> str:
        for pattern, replacement in STT_CORRECTIONS.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _auto_detect_mic(self) -> int:
        """Fallback: scan for Realtek microphone by name."""
        try:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if "realtek" in d["name"].lower() and d["max_input_channels"] > 0:
                    return i
        except Exception:
            pass
        return MIC_DEVICE

    def _record_until_silence(self, max_seconds: int = 10, min_seconds: float = 1.5) -> np.ndarray:
        import voice_output  # for IS_SPEAKING live read
        frames = []
        # Realtek mic float32 amplitude: ambient ~0.00141 RMS, speech ~0.003–0.007 peak.
        speech_threshold = 0.0030
        silence_counter = [0]
        speech_detected = [False]
        max_silence_chunks = 24  # ~1.5s of post-speech silence

        def callback(indata, frame_count, time_info, status):
            frames.append(indata.copy())
            rms = float(np.sqrt(np.mean(indata ** 2)))
            if rms >= speech_threshold:
                speech_detected[0] = True
                silence_counter[0] = 0
            elif speech_detected[0]:
                silence_counter[0] += 1

        ch = _get_mic_channels(MIC_DEVICE)
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=ch, dtype="float32",
                            blocksize=1024, device=MIC_DEVICE, callback=callback):
            start = time.time()
            while time.time() - start < max_seconds:
                time.sleep(0.05)

                # Hard abort: if JARVIS starts speaking, we're recording our own TTS.
                # Drop everything and return empty so transcribe() sees no signal.
                if voice_output.IS_SPEAKING:
                    return np.array([])

                elapsed = time.time() - start
                if (elapsed >= min_seconds
                        and speech_detected[0]
                        and silence_counter[0] >= max_silence_chunks):
                    break

            # If no speech ever detected, return empty so transcribe() returns ""
            # rather than handing Whisper ambient noise to hallucinate from.
            if not speech_detected[0]:
                return np.array([])

        if not frames:
            return np.array([])
        audio = np.concatenate(frames)
        # downmix to mono if device opened with >1 channel
        return audio.mean(axis=1) if audio.ndim > 1 and audio.shape[1] > 1 else audio.flatten()

    def _transcribe_local(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) == 0:
            return ""
        # vad_filter=False: Silero VAD rejects the Realtek mic's naturally low
        # float32 amplitude (~0.007 peak) as non-speech → always returns "".
        # We do our own silence gating in _record_until_silence instead.
        segments, _ = self.whisper.transcribe(audio, beam_size=1, language="en", vad_filter=False)
        return " ".join(s.text for s in segments).strip()

    def _transcribe_groq(self, audio: np.ndarray) -> str:
        try:
            import io
            import soundfile as sf
            from groq import Groq
            buf = io.BytesIO()
            sf.write(buf, audio, SAMPLE_RATE, format="wav")
            buf.seek(0)
            client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
            result = client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=("audio.wav", buf),
                response_format="text"
            )
            return result.strip()
        except Exception as e:
            print(f"[Voice] Groq STT failed, falling back to local: {e}")
            return self._transcribe_local(audio)

    def transcribe(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) == 0:
            return ""
        # Normalise amplitude before transcription.
        # Realtek mic peak is ~0.007; Whisper expects speech-level audio (~0.3–0.9).
        # Normalise to 0.9 peak so Whisper can distinguish speech from silence correctly.
        peak = float(np.max(np.abs(audio)))
        if peak > 0.0005:  # only normalise if there's actual signal, not pure silence
            audio = (audio / peak * 0.9).astype(np.float32)
        else:
            return ""  # truly silent — nothing to transcribe

        # Backend toggle: re-read every call so UI changes take effect immediately
        groq_key = os.getenv("GROQ_API_KEY", "")
        use_groq = os.getenv("USE_GROQ", "true").lower() == "true"
        if groq_key and use_groq:
            text = self._transcribe_groq(audio)
        else:
            text = self._transcribe_local(audio)
        text = self._apply_corrections(text)

        # Filter out hallucinated content (Whisper invents speech from silence/echo)
        if _is_likely_hallucination(text):
            print(f"[Voice] Filtered hallucination: {text!r}")
            return ""

        print(f"[Voice] Heard: {text!r}")
        return text

    def listen_for_wake_word(self) -> bool:
        """Block until wake word detected (or stop event set)."""
        import voice_output  # import module so IS_SPEAKING is re-read every iteration
        buffer = []
        last_speaking_at = [0.0]   # tracks when IS_SPEAKING last went True
        POST_SPEAK_COOLDOWN = 2.5  # seconds to ignore wake words after TTS ends

        time.sleep(0.8)  # let any prior TTS ring-out clear before opening the stream

        def callback(indata, frame_count, time_info, status):
            buffer.append(indata.copy())

        ch = _get_mic_channels(MIC_DEVICE)
        print("[Voice] Waiting for wake word...")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=ch, dtype="float32",
                            blocksize=WAKE_CHUNK, device=MIC_DEVICE, callback=callback):
            time.sleep(0.5)
            buffer.clear()

            while not self._stop_event.is_set():
                time.sleep(0.08)

                if voice_output.IS_SPEAKING:
                    # Flush accumulated chunks so stale TTS audio doesn't
                    # score the wake-word model the moment speaking ends.
                    buffer.clear()
                    last_speaking_at[0] = time.time()
                    continue

                # Short cooldown after TTS finishes — speaker ring-out can
                # still look like "hey jarvis" to the model for ~0.5–1s.
                if time.time() - last_speaking_at[0] < POST_SPEAK_COOLDOWN:
                    buffer.clear()
                    continue

                if buffer:
                    chunk = buffer.pop(0)
                    # downmix to mono if device opened with >1 channel
                    mono = chunk.mean(axis=1) if chunk.ndim > 1 and chunk.shape[1] > 1 else chunk.flatten()
                    audio_int16 = (mono * 32767).astype(np.int16)
                    prediction = self.wakeword.predict(audio_int16)
                    for _, score in prediction.items():
                        if score > 0.5:
                            print(f"[Voice] Wake word! (score={score:.2f})")
                            return True
        return False

    def get_voice_input(self) -> str:
        """One-shot: wait for wake word, record, transcribe."""
        if not self.listen_for_wake_word():
            return ""
        time.sleep(0.4)  # let wake-word audio tail clear before recording
        audio = self._record_until_silence()
        return self.transcribe(audio)

    def start_loop(self, on_transcript):
        """Continuous loop: wake word → record → transcribe → callback. Blocking."""
        while not self._stop_event.is_set():
            try:
                if self.listen_for_wake_word():
                    time.sleep(0.4)  # let wake-word audio tail clear before recording
                    audio = self._record_until_silence()
                    text = self.transcribe(audio)
                    if text:
                        on_transcript(text)
            except Exception as e:
                print(f"[Voice] Error in loop: {e}")
                time.sleep(1)

    def stop(self):
        self._stop_event.set()
