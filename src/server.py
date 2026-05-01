"""
server.py - JARVIS FastAPI backend with WebSocket voice interface
"""
import os
import sys
import json
import asyncio
import logging
import base64
import re
import time
import threading
from typing import Optional
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env", override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from router import router as model_router
from llm import chat
from memory import Memory
from tools import TOOL_DEFINITIONS, dispatch_tool
from skills_manager import load_skills, create_skill
from voice_input import detect_stop_command

# ── Startup ───────────────────────────────────────────────────────────────────

START_TIME = time.time()
memory = Memory()
_ws_clients: set[WebSocket] = set()
_remote_clients: set[WebSocket] = set()
_state = {"status": "idle"}
_main_loop: asyncio.AbstractEventLoop | None = None  # set in lifespan, used by voice thread

ACTION_RE = re.compile(r'\[ACTION:(\w+)\]\s*([^\[]*)', re.DOTALL)
STT_CORRECTIONS = {
    r"\bcloud\b": "Claude",
    r"\bjarves\b": "JARVIS",
    r"\btravis\b": "JARVIS",
    r"\bcloud code\b": "Claude Code",
}

MAX_TOOL_LOOPS = 12


# ── Voice output ──────────────────────────────────────────────────────────────

_voice_out = None
def _get_voice_out():
    global _voice_out
    if _voice_out is None:
        try:
            from voice_output import VoiceOutput
            _voice_out = VoiceOutput()
        except Exception as e:
            logger.warning(f"Voice output not available: {e}")
    return _voice_out


def _speak_with_stop_listener(voice_out, text: str):
    """Call voice_out.speak(text) and simultaneously listen for a stop command in a background thread."""
    stop_flag = threading.Event()

    def stop_listener():
        while not stop_flag.is_set():
            try:
                if detect_stop_command():
                    logger.info("Stop command detected — interrupting speech.")
                    voice_out.stop_speech()
                    break
            except Exception as e:
                logger.warning(f"Error in stop listener thread: {e}")
                break

    listener_thread = threading.Thread(target=stop_listener, daemon=True)
    listener_thread.start()

    try:
        voice_out.speak(text)
    finally:
        stop_flag.set()
        listener_thread.join(timeout=2)


# ── WebSocket manager ─────────────────────────────────────────────────────────

async def broadcast(msg: dict, clients=None):
    if clients is None:
        clients = _ws_clients
    # Snapshot — clients set may be mutated by disconnect handlers mid-iteration
    snapshot = list(clients)
    dead = []
    text = json.dumps(msg)
    for ws in snapshot:
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def set_state(status: str):
    _state["status"] = status
    await broadcast({"type": "status", "state": status})


# ── Action tag parser ─────────────────────────────────────────────────────────

def parse_actions(response: str) -> tuple[str, list[dict]]:
    """Extract [ACTION:TYPE] tags from response. Returns (clean_text, actions)."""
    actions = []
    for m in ACTION_RE.finditer(response):
        actions.append({"type": m.group(1), "content": m.group(2).strip()})
    clean = ACTION_RE.sub("", response).strip()
    return clean, actions


async def execute_action(action: dict):
    """Execute a parsed action tag."""
    action_type = action.get("type", "").upper()
    content = action.get("content", "")

    if action_type == "SEARCH":
        logger.info(f"Action SEARCH: {content}")
        await broadcast({"type": "action", "action": "search", "query": content})
    elif action_type == "OPEN":
        logger.info(f"Action OPEN: {content}")
        await broadcast({"type": "action", "action": "open", "target": content})
    elif action_type == "REMINDER":
        logger.info(f"Action REMINDER: {content}")
        await broadcast({"type": "action", "action": "reminder", "content": content})
    else:
        logger.info(f"Unknown action type: {action_type} — {content}")


# ── Command processing ────────────────────────────────────────────────────────

async def process_command(text: str, source: str = "unknown") -> str:
    """Core command handler used by both WebSocket and voice loop."""
    await set_state("thinking")

    corrected = text
    for pattern, replacement in STT_CORRECTIONS.items():
        corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)

    if corrected != text:
        logger.info(f"STT correction: '{text}' -> '{corrected}'")

    memory.add("user", corrected)
    messages = memory.get_messages()

    skills = load_skills()
    skill_descriptions = ""
    if skills:
        skill_descriptions = "\nAvailable custom skills:\n" + "\n".join(
            f"- {s['name']}: {s.get('description', 'No description')}" for s in skills
        )

    system_prompt = (
        "You are JARVIS, an advanced AI assistant. "
        "Be concise, helpful, and direct. "
        "You have access to tools for real-time information and actions."
        + skill_descriptions
    )

    tool_loop_count = 0
    final_response = ""

    while tool_loop_count < MAX_TOOL_LOOPS:
        tool_loop_count += 1
        response = await chat(
            messages=messages,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
        )

        if response.get("type") == "tool_use":
            tool_name = response.get("name")
            tool_input = response.get("input", {})
            tool_use_id = response.get("id")

            logger.info(f"Tool call [{tool_loop_count}/{MAX_TOOL_LOOPS}]: {tool_name}({tool_input})")
            await broadcast({"type": "tool_call", "tool": tool_name, "input": tool_input})

            tool_result = await dispatch_tool(tool_name, tool_input)
            logger.info(f"Tool result: {str(tool_result)[:200]}")

            messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": tool_use_id, "name": tool_name, "input": tool_input}]})
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": str(tool_result)}]})
            continue

        final_response = response.get("text", "")
        break

    if not final_response:
        final_response = "I encountered an issue processing your request."

    clean_response, actions = parse_actions(final_response)

    for action in actions:
        await execute_action(action)

    memory.add("assistant", clean_response)

    voice_out = _get_voice_out()
    if voice_out:
        await set_state("speaking")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            _speak_with_stop_listener,
            voice_out,
            clean_response,
        )

    await set_state("idle")
    return clean_response


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    logger.info("JARVIS server starting up...")
    yield
    logger.info("JARVIS server shutting down...")


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="JARVIS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(model_router)

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── REST endpoints ────────────────────────────────────────────────────────────

class CommandRequest(BaseModel):
    text: str
    source: str = "api"


@app.get("/health")
async def health():
    uptime = time.time() - START_TIME
    return {"status": "ok", "uptime": round(uptime, 2), "state": _state["status"]}


@app.post("/command")
async def command_endpoint(req: CommandRequest):
    response = await process_command(req.text, source=req.source)
    return {"response": response}


@app.post("/skill/create")
async def skill_create(name: str, description: str, code: str):
    result = create_skill(name, description, code)
    return result


@app.get("/skills")
async def list_skills():
    return {"skills": load_skills()}


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    logger.info(f"WebSocket client connected: {ws.client}")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"type": "command", "text": raw}

            msg_type = data.get("type", "command")

            if msg_type == "command":
                text = data.get("text", "").strip()
                if not text:
                    continue
                response = await process_command(text, source="websocket")
                await ws.send_text(json.dumps({"type": "response", "text": response}))

            elif msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            else:
                logger.warning(f"Unknown WS message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {ws.client}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        _ws_clients.discard(ws)


# ── Remote WebSocket endpoint ─────────────────────────────────────────────────

@app.websocket("/remote")
async def remote_ws_endpoint(ws: WebSocket):
    await ws.accept()
    _remote_clients.add(ws)
    logger.info(f"Remote client connected: {ws.client}")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"type": "command", "text": raw}

            msg_type = data.get("type", "command")

            if msg_type == "command":
                text = data.get("text", "").strip()
                if not text:
                    continue
                response = await process_command(text, source="remote")
                await ws.send_text(json.dumps({"type": "response", "text": response}))

            elif msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        logger.info(f"Remote client disconnected: {ws.client}")
    except Exception as e:
        logger.error(f"Remote WebSocket error: {e}")
    finally:
        _remote_clients.discard(ws)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)