"""
smart_home.py - Home Assistant integration via REST API
"""
import os
import logging
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env")
logger = logging.getLogger(__name__)

HA_URL = os.getenv("HOMEASSISTANT_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.getenv("HOMEASSISTANT_TOKEN", "")


def _headers() -> dict:
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


def is_configured() -> bool:
    return bool(HA_TOKEN)


def get_entities(domain: str = None) -> list[dict]:
    """Get all HA entities, optionally filtered by domain."""
    if not is_configured():
        return []
    try:
        import requests
        resp = requests.get(f"{HA_URL}/api/states", headers=_headers(), timeout=5)
        states = resp.json()
        if domain:
            return [s for s in states if s["entity_id"].startswith(domain + ".")]
        return states
    except Exception as e:
        logger.error(f"[SmartHome] Get entities error: {e}")
        return []


async def control_device(device: str, action: str, value=None) -> str:
    """Control a Home Assistant device by name."""
    if not is_configured():
        return ("Home Assistant isn't configured, sir. I can help you set it up — "
                "just say 'set up Home Assistant'.")

    # Find entity by name (fuzzy match)
    entities = get_entities()
    target = None
    device_lower = device.lower()
    for entity in entities:
        name = entity.get("attributes", {}).get("friendly_name", "").lower()
        if device_lower in name or name in device_lower:
            target = entity
            break

    if not target:
        return f"No device found matching '{device}', sir."

    entity_id = target["entity_id"]
    domain = entity_id.split(".")[0]

    service_map = {
        ("light", "on"): ("light", "turn_on"),
        ("light", "off"): ("light", "turn_off"),
        ("switch", "on"): ("switch", "turn_on"),
        ("switch", "off"): ("switch", "turn_off"),
        ("media_player", "play"): ("media_player", "media_play"),
        ("media_player", "pause"): ("media_player", "media_pause"),
        ("media_player", "stop"): ("media_player", "media_stop"),
        ("lock", "lock"): ("lock", "lock"),
        ("lock", "unlock"): ("lock", "unlock"),
        ("climate", "on"): ("climate", "turn_on"),
        ("climate", "off"): ("climate", "turn_off"),
    }

    service_info = service_map.get((domain, action.lower()))
    if not service_info:
        # Generic toggle
        service_info = (domain, "toggle")

    svc_domain, svc_name = service_info
    payload = {"entity_id": entity_id}

    if value and domain == "light" and action.lower() == "on":
        if isinstance(value, (int, float)):
            payload["brightness_pct"] = int(value)
    if value and domain == "climate":
        try:
            payload["temperature"] = float(value)
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=5) as client:
            resp = await client.post(
                f"{HA_URL}/api/services/{svc_domain}/{svc_name}",
                json=payload
            )
        device_name = target.get("attributes", {}).get("friendly_name", entity_id)
        return f"Done, sir. {device_name} is now {action}."
    except Exception as e:
        return f"Smart home error: {e}"


async def get_sensor_state(sensor_name: str) -> str:
    """Query a sensor's current state."""
    if not is_configured():
        return "Home Assistant not configured."
    entities = get_entities("sensor")
    for entity in entities:
        name = entity.get("attributes", {}).get("friendly_name", "").lower()
        if sensor_name.lower() in name:
            state = entity.get("state", "unknown")
            unit = entity.get("attributes", {}).get("unit_of_measurement", "")
            friendly = entity.get("attributes", {}).get("friendly_name", sensor_name)
            return f"{friendly}: {state}{unit}"
    return f"Sensor '{sensor_name}' not found."


async def run_automation(name: str) -> str:
    """Trigger a HA automation or script by name."""
    if not is_configured():
        return "Home Assistant not configured."
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=5) as client:
            resp = await client.post(
                f"{HA_URL}/api/services/automation/trigger",
                json={"entity_id": f"automation.{name.lower().replace(' ', '_')}"}
            )
        return f"Automation '{name}' triggered, sir."
    except Exception as e:
        return f"Automation error: {e}"


def setup_guide() -> str:
    return """To set up Home Assistant, sir:

1. Install Home Assistant OS on a Raspberry Pi or VM (https://www.home-assistant.io/installation/)
2. Access the UI at http://homeassistant.local:8123 after setup
3. Go to Profile → Long-Lived Access Tokens → Create Token
4. Add HOMEASSISTANT_TOKEN=<your token> to your .env file
5. Add HOMEASSISTANT_URL=http://homeassistant.local:8123 to .env

For hardware, I'd recommend starting with a Zigbee USB dongle (SONOFF Zigbee 3.0 USB Dongle, ~$20 AUD) and some Sonoff ZBMINI smart switches for your existing lights."""
