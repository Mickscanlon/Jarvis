"""
wake_word.py - Local wake word detection on Raspberry Pi
"""
import numpy as np
import sounddevice as sd
from openwakeword.model import Model as WakeWordModel

SAMPLE_RATE = 16000
CHUNK = 1280


class WakeWordDetector:
    def __init__(self, threshold: float = 0.5):
        print("[WakeWord] Loading model...")
        self.model = WakeWordModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self.threshold = threshold
        print("[WakeWord] Ready.")

    def listen(self, callback, stop_event=None):
        """Block until wake word detected, then call callback()."""
        import threading
        buffer = []

        def stream_callback(indata, frames, time, status):
            buffer.append(indata.copy())

        print("[WakeWord] Listening for 'hey jarvis'...")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=CHUNK, callback=stream_callback):
            import time as _time
            _time.sleep(0.5)
            buffer.clear()

            while not (stop_event and stop_event.is_set()):
                _time.sleep(0.08)
                if buffer:
                    chunk = buffer.pop(0).flatten()
                    audio_int16 = (chunk * 32767).astype(np.int16)
                    prediction = self.model.predict(audio_int16)
                    for _, score in prediction.items():
                        if score > self.threshold:
                            print(f"[WakeWord] Detected! score={score:.2f}")
                            callback()
                            return
