"""
main.py - Bedside clock firmware orchestrator
Runs on Raspberry Pi Zero 2W. Connects to JARVIS server over LAN.
"""
import asyncio
import threading
import logging

from ws_client import JarvisClient
from wake_word import WakeWordDetector
from audio_stream import AudioManager
from display import ClockDisplay

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

JARVIS_SERVER_IP = "192.168.1.100"  # ← Set to your JARVIS server IP


async def main():
    display = ClockDisplay(use_oled=True)
    audio = AudioManager()
    ws = JarvisClient()
    wake = WakeWordDetector(threshold=0.5)

    display.set_status("offline")

    # Handle JARVIS responses
    async def on_response(text: str):
        logger.info(f"[Main] JARVIS: {text[:60]}")
        display.set_task(text[:20])
        display.set_status("speaking")
        # Note: for audio playback from server, server sends audio bytes
        # This is handled by the remote-device WebSocket protocol
        await asyncio.sleep(1)
        display.set_status("idle")
        display.set_task("")

    ws.on_response(on_response)

    # Start clock display in background thread
    stop_event = threading.Event()
    clock_thread = threading.Thread(
        target=display.run_clock, args=(stop_event,), daemon=True
    )
    clock_thread.start()

    # Start WS connection in background
    ws_task = asyncio.create_task(ws.connect())

    logger.info("[Main] Waiting for JARVIS server connection...")
    await asyncio.sleep(3)

    if ws.is_connected:
        display.set_status("idle")
        logger.info("[Main] Connected. Waiting for wake word.")
    else:
        display.set_status("offline")

    # Main wake word loop
    loop = asyncio.get_event_loop()
    while True:
        if not ws.is_connected:
            display.set_status("offline")
            await asyncio.sleep(2)
            continue

        # Wait for wake word (blocking in thread to not block asyncio)
        detected = asyncio.Event()
        wake_stop = threading.Event()

        def wake_callback():
            loop.call_soon_threadsafe(detected.set)

        wake_thread = threading.Thread(
            target=wake.listen, args=(wake_callback, wake_stop), daemon=True
        )
        wake_thread.start()
        await detected.wait()
        wake_stop.set()

        # Wake word detected
        display.set_status("listening")
        await asyncio.sleep(0.3)

        # Record audio
        audio_data = await asyncio.to_thread(audio.record_until_silence)
        display.set_status("thinking")

        # Transcribe locally
        text = await asyncio.to_thread(audio.transcribe, audio_data)
        if text:
            logger.info(f"[Main] You: {text}")
            await ws.send_transcript(text)
        else:
            display.set_status("idle")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[Main] Shutting down.")
