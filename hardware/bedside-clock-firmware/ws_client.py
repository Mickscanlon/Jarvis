"""
ws_client.py - WebSocket connection to main JARVIS server
"""
import asyncio
import json
import logging
import websockets

logger = logging.getLogger(__name__)

JARVIS_WS_URL = "ws://192.168.1.100:8000/ws/remote-device"  # Set your server IP


class JarvisClient:
    def __init__(self):
        self.ws = None
        self._connected = False
        self._on_response = None
        self._retry_delay = 2

    def on_response(self, fn):
        self._on_response = fn

    async def connect(self):
        while True:
            try:
                logger.info(f"[WS] Connecting to {JARVIS_WS_URL}")
                async with websockets.connect(JARVIS_WS_URL) as ws:
                    self.ws = ws
                    self._connected = True
                    self._retry_delay = 2
                    logger.info("[WS] Connected to JARVIS")
                    async for message in ws:
                        try:
                            msg = json.loads(message)
                            if msg.get("type") == "response" and self._on_response:
                                await self._on_response(msg.get("text", ""))
                        except Exception as e:
                            logger.error(f"[WS] Message error: {e}")
            except Exception as e:
                self._connected = False
                logger.error(f"[WS] Connection lost: {e}. Retrying in {self._retry_delay}s")
                await asyncio.sleep(self._retry_delay)
                self._retry_delay = min(self._retry_delay * 2, 30)

    async def send_transcript(self, text: str):
        if self.ws and self._connected:
            try:
                await self.ws.send(json.dumps({"type": "transcript", "text": text}))
            except Exception as e:
                logger.error(f"[WS] Send error: {e}")
                self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected
