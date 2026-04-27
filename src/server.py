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

MAX_TOOL_LOOPS = 5


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
    """Execute a parsed action tag in background."""
    atype = action["type"]
    content = action["content"]

    try:
        if atype == "OPEN_APP":
            from integrations.windows_control import open_app
            open_app(content.strip())

        elif atype == "RUN_SHELL":
            from tools import run_shell
            result = run_shell(content.strip())
            await broadcast({"type": "task_complete", "name": "shell", "summary": result[:200]})

        elif atype == "ADD_TASK":
            parts = [p.strip() for p in content.split("|||")]
            priority = parts[0] if parts else "medium"
            title = parts[1] if len(parts) > 1 else content
            description = parts[2] if len(parts) > 2 else ""
            due_date = parts[3] if len(parts) > 3 else None
            tid = memory.add_task(title, description, priority, due_date)
            await broadcast({"type": "task_complete", "name": "add_task",
                             "summary": f"Task added: {title} (id={tid})"})

        elif atype == "COMPLETE_TASK":
            try:
                memory.complete_task(int(content.strip()))
            except ValueError:
                pass

        elif atype == "ADD_NOTE":
            parts = [p.strip() for p in content.split("|||")]
            topic = parts[0] if parts else ""
            note_content = parts[1] if len(parts) > 1 else content
            memory.add_note(topic, note_content, topic)

        elif atype == "REMEMBER":
            parts = [p.strip() for p in content.split("|||")]
            mem_type = parts[0] if parts else "fact"
            mem_content = parts[1] if len(parts) > 1 else content
            importance = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 6
            memory.add_memory(mem_content, mem_type=mem_type, importance=importance)

        elif atype == "RESEARCH":
            parts = [p.strip() for p in content.split("|||")]
            topic = parts[0] if parts else content
            depth = parts[1] if len(parts) > 1 else "standard"
            await broadcast({"type": "action_queued", "action": "RESEARCH", "target": topic})
            asyncio.create_task(_run_research(topic, depth))

        elif atype == "STOCK_ANALYSIS":
            parts = [p.strip() for p in content.split("|||")]
            ticker = parts[0] if parts else content
            analysis_type = parts[1] if len(parts) > 1 else "full"
            asyncio.create_task(_run_stock_analysis(ticker, analysis_type))

        elif atype == "DISCORD":
            parts = [p.strip() for p in content.split("|||")]
            priority = parts[0] if parts else "low"
            message = parts[1] if len(parts) > 1 else content
            asyncio.create_task(_send_discord(priority, message))

        elif atype == "DOWNLOAD_VIDEO":
            parts = [p.strip() for p in content.split("|||")]
            url = parts[0] if parts else content
            audio_only = parts[1].lower() == "true" if len(parts) > 1 else False
            asyncio.create_task(_download_media(url, audio_only))

        elif atype == "SMART_HOME":
            parts = [p.strip() for p in content.split("|||")]
            if len(parts) >= 2:
                from integrations.smart_home import control_device
                asyncio.create_task(control_device(parts[0], parts[1],
                                                   parts[2] if len(parts) > 2 else None))

        elif atype == "BUDGET_UPDATE":
            parts = [p.strip() for p in content.split("|||")]
            if len(parts) >= 3:
                from integrations.budget import log_transaction
                log_transaction(memory, parts[0], float(parts[1]), parts[2])

    except Exception as e:
        logger.error(f"[Action] Error executing {atype}: {e}")


async def _run_research(topic: str, depth: str):
    await set_state("working")
    try:
        from agents.researcher import ResearchAgent
        agent = ResearchAgent(memory)
        report = await agent.research(topic, depth)
        summary = report[:400] + "..." if len(report) > 400 else report
        await broadcast({"type": "task_complete", "name": "research", "summary": summary})
        await speak_and_broadcast(summary)
    except Exception as e:
        logger.error(f"[Research] {e}")
        await speak_and_broadcast("Research hit a snag, sir. I'll try again shortly.")
    finally:
        await set_state("idle")


async def _run_stock_analysis(ticker: str, analysis_type: str):
    await set_state("working")
    try:
        from agents.stock_agent import StockAgent
        agent = StockAgent(memory)
        report = await agent.analyse(ticker, analysis_type)
        summary = report[:400] + "..." if len(report) > 400 else report
        await broadcast({"type": "task_complete", "name": "stock_analysis", "summary": summary})
        await speak_and_broadcast(f"{ticker} analysis complete. {summary}")
    except Exception as e:
        logger.error(f"[StockAgent] {e}")
        await speak_and_broadcast(f"Couldn't complete the {ticker} analysis, sir.")
    finally:
        await set_state("idle")


async def _send_discord(priority: str, message: str):
    try:
        from integrations.messaging import post_to_discord
        await post_to_discord(priority, message)
    except Exception as e:
        logger.error(f"[Discord] {e}")


async def _download_media(url: str, audio_only: bool):
    try:
        from integrations.media_downloader import download_video
        download_video(url, audio_only)
    except Exception as e:
        logger.error(f"[Download] {e}")


# ── Agent runner ──────────────────────────────────────────────────────────────

_conversation_history: list[dict] = []
_last_response = ""
_processing_lock = asyncio.Lock()  # only one transcript processed at a time


def apply_stt_corrections(text: str) -> str:
    for pattern, replacement in STT_CORRECTIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def is_echo(text: str, last_response: str) -> bool:
    if not last_response or len(text.split()) < 4:
        return False
    t_words = set(text.lower().split())
    r_words = set(last_response.lower().split())
    if not r_words:
        return False
    overlap = len(t_words & r_words) / len(r_words)
    return overlap > 0.45


def parse_text_tool_calls(content: str) -> list:
    calls = []
    pattern = r'(run_shell|read_screen|read_file|write_file|create_skill|list_open_windows)\s*[\("\']*([^)"\'`\n]*)[\)"\'`]*'
    for tool_name, args_str in re.findall(pattern, content):
        args_str = args_str.strip().strip('"\'')
        if tool_name == "run_shell":
            calls.append({"name": "run_shell", "args": {"command": args_str}})
        elif tool_name == "read_screen":
            calls.append({"name": "read_screen", "args": {"region": "full"}})
        elif tool_name == "read_file":
            calls.append({"name": "read_file", "args": {"path": args_str}})
    return calls


async def run_agent(user_text: str, on_working=None) -> str:
    global _last_response

    skill_defs, skill_fns = load_skills()
    all_tools = TOOL_DEFINITIONS + skill_defs

    mem_context = memory.get_context_for(user_text)
    enriched = f"{user_text}\n\n[Memory:{mem_context}]" if mem_context else user_text

    messages = _conversation_history[-18:] + [{"role": "user", "content": enriched}]

    # Route to appropriate model
    decision = model_router.route(user_text)
    await broadcast({
        "type": "model_used",
        "tier": decision.tier,
        "model": decision.model,
        "cost_aud": decision.estimated_cost_aud
    })

    for loop in range(MAX_TOOL_LOOPS):
        result = chat(messages, tools=all_tools, tier=decision.tier, model=decision.model)
        content = result["content"]
        tool_calls = result.get("tool_calls", [])

        # Log usage
        memory.log_usage(
            model=result.get("model", decision.model),
            tier=decision.tier,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            cost_aud=decision.estimated_cost_aud,
            duration_ms=result.get("duration_ms", 0)
        )

        # Check spend alert
        alert_amount = memory.check_daily_spend_alert()
        if alert_amount:
            await broadcast({"type": "cost_alert", "amount_aud": alert_amount, "period": "today"})

        # Text-format tool call fallback
        if not tool_calls and content:
            text_calls = parse_text_tool_calls(content)
            if text_calls:
                logger.info(f"[Agent] Intercepted {len(text_calls)} text-format tool call(s)")
                clean = re.sub(r'```[^`]*```', '', content, flags=re.DOTALL).strip() or "Checking..."
                messages.append({"role": "assistant", "content": clean})
                for call in text_calls:
                    res = dispatch_tool(call["name"], call["args"], skill_fns)
                    messages.append({
                        "role": "user",
                        "content": f"Tool result for {call['name']}:\n{res}\n\nAnswer using this result."
                    })
                continue

        if tool_calls:
            # On the first tool call: speak acknowledgement and switch to working state
            if loop == 0 and on_working:
                ack = content.strip() if content and len(content.strip()) > 5 else ""
                await on_working(ack)

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            })
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_result = dispatch_tool(tool_name, args, skill_fns)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
        else:
            # Final response
            clean_text, actions = parse_actions(content)
            final = clean_text.strip() or content.strip()

            _conversation_history.append({"role": "user", "content": user_text})
            _conversation_history.append({"role": "assistant", "content": final})
            if len(_conversation_history) > 20:
                del _conversation_history[:2]

            _last_response = final

            # Execute actions in background
            for action in actions:
                asyncio.create_task(execute_action(action))

            # Async fact extraction
            asyncio.create_task(memory.async_extract_facts(user_text))

            return final

    return "Slight hiccup, sir. Give me a moment."


# ── TTS helper ────────────────────────────────────────────────────────────────

async def speak_and_broadcast(text: str):
    """Synthesize speech, play locally, and send audio to WS clients.

    Priority: ElevenLabs (API key set) → Kokoro ONNX (local fallback).
    IS_SPEAKING is raised at the START of synthesis so the wake-word detector
    suppresses itself for the entire duration including browser playback latency.
    """
    import voice_output as _vo_module
    import sounddevice as _sd
    import io, soundfile as sf

    vo = _get_voice_out()
    # Snapshot client count NOW — if a client disconnects mid-broadcast
    # _ws_clients drops to 0, and the local-playback check below would
    # play through speakers while the browser is still finishing what it
    # already received → double audio.
    had_browser_client = len(_ws_clients) > 0

    # Raise IS_SPEAKING NOW — before any audio leaves this function.
    # Browser playback has 100–500ms latency over WS, and we don't want
    # the wake-word detector to fire during that window.
    _vo_module.IS_SPEAKING = True
    await set_state("speaking")
    await broadcast({"type": "text", "text": text})

    clean = text.replace("**", "").replace("*", "").replace("`", "").strip()
    if not clean:
        _vo_module.IS_SPEAKING = False
        await set_state("idle")
        return

    samples = None
    sample_rate = 24000
    eleven_key = os.getenv("ELEVENLABS_API_KEY", "")
    eleven_voice = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    use_eleven = os.getenv("USE_ELEVENLABS", "true").lower() == "true"

    # ── Try ElevenLabs first ──────────────────────────────────────────────────
    if eleven_key and use_eleven:
        try:
            import httpx
            resp = await asyncio.to_thread(
                lambda: httpx.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{eleven_voice}",
                    headers={"xi-api-key": eleven_key,
                             "Content-Type": "application/json",
                             "Accept": "audio/mpeg"},
                    json={"text": clean,
                          "model_id": "eleven_turbo_v2_5",
                          "voice_settings": {"stability": 0.45,
                                             "similarity_boost": 0.80}},
                    timeout=15.0,
                )
            )
            if resp.status_code == 200:
                import numpy as np
                audio_data, sample_rate = sf.read(io.BytesIO(resp.content))
                samples = audio_data.astype(np.float32)
                if samples.ndim > 1:
                    samples = samples[:, 0]  # mono
                audio_b64 = base64.b64encode(resp.content).decode()
                await broadcast({"type": "audio", "data": audio_b64,
                                 "text": text, "state": "speaking",
                                 "format": "mp3"})
                logger.info("[TTS] ElevenLabs ✓")
            else:
                logger.warning(f"[TTS] ElevenLabs {resp.status_code} — falling back to Kokoro")
        except Exception as e:
            logger.warning(f"[TTS] ElevenLabs failed ({e}) — falling back to Kokoro")

    # ── Kokoro fallback ───────────────────────────────────────────────────────
    if samples is None and vo:
        try:
            samples, sample_rate = vo.kokoro.create(
                clean, voice=vo.voice, speed=float(os.getenv("TTS_SPEED", "1.0")),
                lang="en-us"
            )
            buf = io.BytesIO()
            sf.write(buf, samples, sample_rate, format="wav")
            audio_b64 = base64.b64encode(buf.getvalue()).decode()
            await broadcast({"type": "audio", "data": audio_b64,
                             "text": text, "state": "speaking",
                             "format": "wav"})
            logger.info("[TTS] Kokoro ✓")
        except Exception as e:
            logger.error(f"[TTS] Kokoro failed: {e}")

    # ── Play locally ONLY if no browser client is connected ───────────────────
    # IS_SPEAKING was already raised at the top of this function so the wake
    # word loop has been suppressed since synthesis began.
    try:
        if samples is not None:
            if not had_browser_client:
                # Headless / CLI mode — server plays through local speaker
                await asyncio.to_thread(
                    _play_blocking, samples, sample_rate,
                    int(os.getenv("OUTPUT_DEVICE", "3"))
                )
                # Local playback finishes synchronously; small ring-out buffer.
                await asyncio.sleep(0.8)
            else:
                # Browser plays — wait the audio duration PLUS extra slack:
                #   - 0.8s upfront WS / decode latency (browser hasn't started yet)
                #   - 1.5s trailing latency (playback ends slightly after duration)
                #   - 0.8s ring-out so speaker bleed clears the mic
                duration = len(samples) / float(sample_rate)
                await asyncio.sleep(0.8 + duration + 1.5 + 0.8)
        else:
            logger.error("[TTS] No audio generated — both ElevenLabs and Kokoro failed.")
    finally:
        _vo_module.IS_SPEAKING = False
        await set_state("idle")


def _play_blocking(samples, sample_rate: int, device: int):
    """Play audio synchronously (runs in a thread via asyncio.to_thread)."""
    import sounddevice as _sd
    _sd.play(samples, sample_rate, device=device)
    _sd.wait()


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    # Capture uvicorn's event loop NOW — must be done here, not in __main__,
    # because uvicorn creates its own loop. We pass it to the voice thread so
    # run_coroutine_threadsafe has a valid loop to schedule onto.
    _main_loop = asyncio.get_running_loop()

    logger.info("[JARVIS] Starting up...")
    model_router.probe_backends()

    # Start local voice pipeline thread (wake word + mic)
    voice_thread = threading.Thread(target=_voice_loop_thread, name="_voice_loop_thread", daemon=True)
    voice_thread.start()

    # Start background services
    asyncio.create_task(_start_scheduler())
    asyncio.create_task(_start_discord_bot())

    startup_msg = model_router.startup_message()
    logger.info(f"[JARVIS] {startup_msg}")

    # Speak startup message after brief delay
    async def _delayed_startup():
        await asyncio.sleep(1.5)
        await speak_and_broadcast(startup_msg)
    asyncio.create_task(_delayed_startup())

    yield
    logger.info("[JARVIS] Shutting down.")


app = FastAPI(title="JARVIS", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080",
                   "http://127.0.0.1:5173", "http://127.0.0.1:8080", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend build if it exists
frontend_build = "C:/Users/micha/jarvis/frontend/dist"
if os.path.isdir(frontend_build):
    app.mount("/app", StaticFiles(directory=frontend_build, html=True), name="frontend")


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    await websocket.send_text(json.dumps({"type": "status", "state": _state["status"]}))
    logger.info(f"[WS] Client connected ({len(_ws_clients)} total)")

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "ping":
                try:
                    await websocket.send_text(json.dumps({"type": "pong"}))
                except Exception:
                    # Half-closed socket — break out of the loop, the
                    # finally clause will remove this client cleanly.
                    break

            elif msg_type == "transcript":
                text = msg.get("text", "").strip()
                if not text or not msg.get("isFinal", True):
                    continue
                text = apply_stt_corrections(text)
                if is_echo(text, _last_response):
                    logger.debug(f"[WS] Echo filtered: {text[:50]}")
                    continue
                await set_state("thinking")
                try:
                    async def _on_working(ack_text: str):
                        spoken = ack_text or "Understood. Working on that now, sir."
                        await speak_and_broadcast(spoken)
                        await set_state("working")

                    response = await run_agent(text, on_working=_on_working)
                    await speak_and_broadcast(response)
                except Exception as e:
                    logger.error(f"[WS] Agent error: {e}")
                    await set_state("idle")

            elif msg_type == "audio_data":
                # Browser-streamed audio — transcribe via Groq or Whisper
                audio_b64 = msg.get("data", "")
                if audio_b64:
                    asyncio.create_task(_handle_audio(websocket, audio_b64))

    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)
        logger.info(f"[WS] Client disconnected ({len(_ws_clients)} remaining)")


@app.websocket("/ws/remote-device")
async def ws_remote(websocket: WebSocket):
    await websocket.accept()
    _remote_clients.add(websocket)
    device_id = f"device_{len(_remote_clients)}"
    logger.info(f"[WS] Remote device connected: {device_id}")

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "transcript":
                text = msg.get("text", "").strip()
                if text:
                    await set_state("thinking")
                    async def _on_working_remote(ack_text: str):
                        spoken = ack_text or "Understood. Working on that now, sir."
                        await speak_and_broadcast(spoken)
                        await set_state("working")
                    response = await run_agent(text, on_working=_on_working_remote)
                    # Send audio back to the remote device
                    await websocket.send_text(json.dumps({
                        "type": "response", "text": response
                    }))
                    await speak_and_broadcast(response)
                    await set_state("idle")
    except WebSocketDisconnect:
        pass
    finally:
        _remote_clients.discard(websocket)


async def _handle_audio(ws: WebSocket, audio_b64: str):
    """Transcribe browser-sent audio via Groq or local Whisper."""
    try:
        audio_bytes = base64.b64decode(audio_b64)
        groq_key = os.getenv("GROQ_API_KEY", "")
        if groq_key:
            from groq import Groq
            client = Groq(api_key=groq_key)
            import io
            result = client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=("audio.wav", io.BytesIO(audio_bytes)),
                response_format="text"
            )
            text = result.strip()
        else:
            import tempfile, numpy as np, soundfile as sf
            from faster_whisper import WhisperModel
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name
            model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(tmp_path, beam_size=1, language="en")
            text = " ".join(s.text for s in segments).strip()
            os.unlink(tmp_path)

        if text:
            await ws.send_text(json.dumps({"type": "transcript_result", "text": text}))
            text = apply_stt_corrections(text)
            if not is_echo(text, _last_response):
                await set_state("thinking")
                async def _on_working_audio(ack_text: str):
                    spoken = ack_text or "Understood. Working on that now, sir."
                    await speak_and_broadcast(spoken)
                    await set_state("working")
                response = await run_agent(text, on_working=_on_working_audio)
                await speak_and_broadcast(response)
    except Exception as e:
        logger.error(f"[STT] Audio handling error: {e}")


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "uptime_seconds": round(time.time() - START_TIME),
        "state": _state["status"],
    }


@app.get("/api/usage")
def usage():
    return memory.get_usage_stats()


@app.get("/api/model-stats")
def model_stats():
    stats = memory.get_usage_stats()
    ollama, llama = model_router._ollama_available, model_router._llama_available
    return {
        "usage": stats,
        "backends": {"ollama": ollama, "llama_cpp": llama,
                     "claude_api": bool(os.getenv("ANTHROPIC_API_KEY"))}
    }


@app.get("/api/tasks")
def get_tasks(status: str = "open"):
    return memory.get_tasks(status)


class TaskIn(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: Optional[str] = None
    project: str = ""


@app.post("/api/tasks")
def create_task(task: TaskIn):
    tid = memory.add_task(task.title, task.description, task.priority,
                          task.due_date, task.project)
    return {"id": tid, "status": "created"}


@app.put("/api/tasks/{task_id}/complete")
def complete_task(task_id: int):
    memory.complete_task(task_id)
    return {"status": "completed"}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    import sqlite3
    from memory import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.get("/api/memories")
def get_memories(q: str = "", limit: int = 20):
    if q:
        return memory.search_memories(q, top_k=limit)
    conn = __import__("sqlite3").connect(memory.__class__.__module__)
    from memory import DB_PATH
    conn = __import__("sqlite3").connect(DB_PATH)
    rows = conn.execute(
        "SELECT content, type, importance, created_at FROM memories ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"content": r[0], "type": r[1], "importance": r[2], "created_at": r[3]} for r in rows]


@app.get("/api/notes")
def get_notes(limit: int = 20):
    return memory.get_notes(limit)


@app.get("/api/portfolio")
def get_portfolio():
    from memory import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM portfolio").fetchall()
    conn.close()
    return [{"id": r[0], "ticker": r[1], "units": r[2], "avg_buy_price": r[3],
             "currency": r[4]} for r in rows]


@app.get("/api/budget")
def get_budget():
    try:
        from integrations.budget import get_budget_summary
        return get_budget_summary(memory)
    except Exception:
        return {"error": "Budget integration not configured"}


@app.get("/api/news")
def get_news():
    try:
        from integrations.news import get_latest_briefing
        return get_latest_briefing(memory)
    except Exception:
        return {"error": "News not available"}


@app.get("/api/settings/status")
def settings_status():
    return {
        "anthropic_api": bool(os.getenv("ANTHROPIC_API_KEY")),
        "groq": bool(os.getenv("GROQ_API_KEY")),
        "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
        "home_assistant": bool(os.getenv("HOMEASSISTANT_TOKEN")),
        "email": bool(os.getenv("EMAIL_ADDRESS")),
        "alpha_vantage": bool(os.getenv("ALPHA_VANTAGE_API_KEY")),
        "discord": bool(os.getenv("DISCORD_BOT_TOKEN")),
        "ollama": model_router._ollama_available,
        "llama_cpp": model_router._llama_available,
    }


class KeyIn(BaseModel):
    key: str
    value: str


@app.post("/api/settings/keys")
def save_key(payload: KeyIn):
    env_path = "C:/Users/micha/jarvis/.env"
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
        updated = False
        for i, line in enumerate(lines):
            # Match KEY= at start of line (allow optional leading whitespace)
            if line.lstrip().startswith(f"{payload.key}="):
                lines[i] = f"{payload.key}={payload.value}\n"
                updated = True
                break
        if not updated:
            # Ensure the previous line ends with \n before appending,
            # otherwise the new entry gets glued onto the last line.
            if lines and not lines[-1].endswith("\n"):
                lines[-1] = lines[-1] + "\n"
            lines.append(f"{payload.key}={payload.value}\n")
        with open(env_path, "w") as f:
            f.writelines(lines)
        os.environ[payload.key] = payload.value
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/settings/prefs")
def get_prefs():
    return {
        "user_name": os.getenv("USER_NAME", "Michael"),
        "user_location": os.getenv("USER_LOCATION", "Bendigo, Victoria, Australia"),
        "tts_speed": os.getenv("TTS_SPEED", "1.0"),
        "daily_spend_alert": os.getenv("DAILY_SPEND_ALERT_AUD", "2.00"),
        "local_mode": os.getenv("LOCAL_MODE", "false"),
        "wake_word": os.getenv("WAKE_WORD", "hey jarvis"),
        "use_groq": os.getenv("USE_GROQ", "true").lower() == "true",
        "use_elevenlabs": os.getenv("USE_ELEVENLABS", "true").lower() == "true",
    }


@app.get("/api/devices")
def get_devices():
    return {
        "connected": len(_remote_clients),
        "devices": [f"device_{i+1}" for i in range(len(_remote_clients))]
    }


@app.post("/api/restart")
async def restart_server():
    asyncio.create_task(_delayed_restart())
    return {"status": "restarting"}


async def _delayed_restart():
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ── Background services ───────────────────────────────────────────────────────

async def _start_scheduler():
    try:
        from agents.scheduler import Scheduler
        scheduler = Scheduler(memory)
        await scheduler.run()
    except Exception as e:
        logger.error(f"[Scheduler] Failed to start: {e}")


async def _start_discord_bot():
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        logger.info("[Discord] No token configured, skipping.")
        return
    try:
        from integrations.messaging import start_discord_bot
        await start_discord_bot(run_agent, broadcast)
    except Exception as e:
        logger.error(f"[Discord] Failed to start: {e}")


# ── Local voice pipeline thread ───────────────────────────────────────────────

def _voice_loop_thread():
    """Run the local wake-word + mic pipeline in a background thread.

    asyncio.run_coroutine_threadsafe needs the *main* event loop, which is
    captured into _main_loop inside the lifespan coroutine before this thread
    is started.  Never call asyncio.get_event_loop() from here — this thread
    has no loop of its own.
    """
    try:
        from voice_input import VoiceInput
        vi = VoiceInput()

        def _on_transcript(text: str):
            if _main_loop is None:
                logger.warning("[Voice] Event loop not ready yet, dropping transcript.")
                return
            asyncio.run_coroutine_threadsafe(
                _handle_local_transcript(text),
                _main_loop
            )

        vi.start_loop(on_transcript=_on_transcript)
    except Exception as e:
        logger.error(f"[Voice] Pipeline thread failed: {e}")


async def _handle_local_transcript(text: str):
    # Drop concurrent triggers — one response at a time.
    # This prevents the TTS bleed from spawning a second agent call
    # while the first response is still being spoken.
    if _processing_lock.locked():
        logger.debug(f"[Voice] Busy — dropping transcript: {text[:60]!r}")
        return
    async with _processing_lock:
        text = apply_stt_corrections(text)
        if is_echo(text, _last_response):
            logger.debug(f"[Voice] Echo filtered: {text[:60]!r}")
            return
        if not text.strip():
            return
        await set_state("thinking")
        async def _on_working_local(ack_text: str):
            spoken = ack_text or "Understood. Working on that now, sir."
            await speak_and_broadcast(spoken)
            await set_state("working")
        response = await run_agent(text, on_working=_on_working_local)
        await speak_and_broadcast(response)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    # Voice thread is started inside lifespan() so it has access to the
    # running event loop. Do NOT start it here.
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
