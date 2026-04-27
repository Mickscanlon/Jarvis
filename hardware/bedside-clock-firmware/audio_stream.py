"""
audio_stream.py - Microphone capture and speaker playback for Pi
"""
import numpy as np
import sounddevice as sd
import soundfile as sf
import io
import time
import threading
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
MIC_DEVICE = None  # None = default
SPK_DEVICE = None  # None = default


class AudioManager:
    def __init__(self):
        print("[Audio] Loading Whisper tiny.en on CPU...")
        self.whisper = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        self._is_playing = False
        print("[Audio] Ready.")

    def record_until_silence(self, max_seconds: int = 8) -> np.ndarray:
        frames = []
        silence_threshold = 0.01
        silence_count = [0]
        max_silence = 20

        def callback(indata, frame_count, time_info, status):
            frames.append(indata.copy())
            rms = float(np.sqrt(np.mean(indata ** 2)))
            silence_count[0] = silence_count[0] + 1 if rms < silence_threshold else 0

        print("[Audio] Recording...")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=1024, device=MIC_DEVICE, callback=callback):
            start = time.time()
            while time.time() - start < max_seconds:
                time.sleep(0.05)
                if silence_count[0] > max_silence and len(frames) > 10:
                    break

        return np.concatenate(frames).flatten() if frames else np.array([])

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) == 0:
            return ""
        segments, _ = self.whisper.transcribe(audio, beam_size=1, language="en", vad_filter=True)
        text = " ".join(s.text for s in segments).strip()
        print(f"[Audio] Heard: {text}")
        return text

    def play_audio_bytes(self, audio_bytes: bytes):
        """Play raw audio bytes (WAV format)."""
        try:
            data, rate = sf.read(io.BytesIO(audio_bytes))
            self._is_playing = True
            sd.play(data, rate, device=SPK_DEVICE)
            sd.wait()
        except Exception as e:
            print(f"[Audio] Playback error: {e}")
        finally:
            self._is_playing = False

    @property
    def is_playing(self) -> bool:
        return self._is_playing
