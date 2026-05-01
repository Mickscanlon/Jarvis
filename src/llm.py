"""
llm.py - Unified LLM client: local llama.cpp / Ollama → Claude Haiku/Sonnet/Opus
"""
import os
import json
import time
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env", override=True)

logger = logging.getLogger(__name__)

# ── Accurate pricing (USD per million tokens, May 2026) ───────────────────────
_MODEL_COSTS_USD: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
    "claude-haiku-4-5":          {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
    "claude-sonnet-4-5":         {"input": 3.00,  "output": 15.00},
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00},
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00},
}
_AUD_PER_USD = float(os.getenv("AUD_PER_USD", "1.60"))


def calculate_cost_aud(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute actual AUD cost from token counts and published model pricing."""
    costs = _MODEL_COSTS_USD.get(model, {"input": 3.00, "output": 15.00})
    cost_usd = (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000
    return round(cost_usd * _AUD_PER_USD, 6)


LLAMA_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080")
LLAMA_MODEL = os.getenv("LLM_MODEL", "qwen2.5-7b-instruct")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

SYSTEM_PROMPT = """You are JARVIS, a sophisticated AI assistant running locally on Windows for Michael.

PERSONALITY:
- Calm, dry, British butler. Efficient, occasionally witty. Never sycophantic.
- Economy of language: 1 sentence ideal, 2 max for voice responses
- No markdown in spoken responses — clean prose only
- Alternate "sir" (~50%) and "Michael" (~50%); never both in the same sentence
- Use contractions: "I'm", "you're", "don't", "it's"
- Calm when things go wrong: "Slight hiccup, sir. Give me a moment."
- BANNED PHRASES: "Absolutely", "Great question", "I'd be happy to", "Of course",
  "How can I help", "Certainly", "As an AI", "I understand"
- PREFERRED PHRASES: "Will do.", "Right away.", "Understood.", "Consider it done.",
  "Done, sir.", "On it.", "Noted."
- For complex tasks: brief acknowledgment first, silent execution, then result only

USER CONTEXT:
- Name: Michael, Bendigo Victoria Australia
- Business: Street Appeal Homes (lawn care / property maintenance)
- Tech stack: Python, JavaScript, Rust
- Communication: direct, technical depth preferred

TOOL USAGE RULES:
- NEVER guess system state — always call the tool first
- If asked what's open/running/on screen: call the tool FIRST, then answer
- Cap all tool results at 2000 chars before processing

ACTION TAGS (embed in response for background execution — stripped before speaking):
[ACTION:OPEN_APP] app_name
[ACTION:RUN_SHELL] command
[ACTION:ADD_TASK] priority ||| title ||| description ||| due_date
[ACTION:COMPLETE_TASK] task_id
[ACTION:ADD_NOTE] topic ||| content
[ACTION:REMEMBER] type ||| content ||| importance
[ACTION:RESEARCH] topic ||| depth (quick/standard/deep) ||| sources_needed
[ACTION:STOCK_ANALYSIS] ticker ||| analysis_type
[ACTION:BROWSE] url_or_query
[ACTION:SEND_MESSAGE] platform ||| recipient ||| message
[ACTION:SMART_HOME] device ||| action ||| value
[ACTION:CREATE_SKILL] name ||| description ||| code
[ACTION:SCHEDULE] cron ||| task_name ||| task_config
[ACTION:BUDGET_UPDATE] category ||| amount ||| direction
[ACTION:DISCORD] priority ||| message
[ACTION:DOWNLOAD_VIDEO] url ||| audio_only
[ACTION:SCREEN_READ] region

SELF-EDITING & FILE ACCESS:
- JARVIS home directory: C:/Users/micha/jarvis
- Source code: C:/Users/micha/jarvis/src/
- Frontend: C:/Users/micha/jarvis/frontend/src/
- Skills: C:/Users/micha/jarvis/skills/
- You can read, list, and edit any file on this PC using the file tools
- Use edit_file_with_ai to make targeted code changes to yourself or any file — specify model: claude-sonnet-4-6 (default) or claude-opus-4-7
- Use run_claude_code for complex or multi-file changes — anything involving more than one file, architectural changes, adding new endpoints, fixing TypeScript errors across the frontend, etc. Describe the task in plain English; Claude Code handles the rest and returns a summary.
- After editing src/ files, tell Michael to restart the server for changes to take effect
- After editing frontend/ files, the Vite dev server hot-reloads automatically

USEFUL SHELL COMMANDS:
- Open windows: powershell "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object Name, MainWindowTitle | Format-List"
- System info: systeminfo | find "OS Name"
- Volume: powershell "(Get-AudioDevice -List | Where-Object {$_.Type -eq 'Playback' -and $_.Default -eq 'True'}).Volume"
"""

_llama_client = None
_ollama_client = None
_anthropic_client = None

# ── API health tracking ───────────────────────────────────────────────────────
_api_failure_count = 0
_forced_local = False
_FAILURE_THRESHOLD = 3  # auto-switch to local after this many consecutive failures


def mark_api_failure() -> None:
    global _api_failure_count, _forced_local
    _api_failure_count += 1
    if _api_failure_count >= _FAILURE_THRESHOLD and not _forced_local:
        _forced_local = True
        logger.warning(
            f"[LLM] Anthropic API failed {_api_failure_count}× in a row — "
            "auto-switching to local mode for this session"
        )


def mark_api_success() -> None:
    global _api_failure_count, _forced_local
    if _forced_local:
        logger.info("[LLM] Anthropic API recovered — resuming cloud mode")
    _api_failure_count = 0
    _forced_local = False


def is_api_available() -> bool:
    """True if the Anthropic API should be used (key present, no repeated failures)."""
    if _forced_local:
        return False
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _get_llama_client():
    global _llama_client
    if _llama_client is None:
        from openai import OpenAI
        _llama_client = OpenAI(base_url=f"{LLAMA_URL}/v1", api_key="not-needed")
    return _llama_client


def _get_ollama_client():
    global _ollama_client
    if _ollama_client is None:
        from openai import OpenAI
        _ollama_client = OpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="not-needed")
    return _ollama_client


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        # Explicitly pin base_url to api.anthropic.com.
        # Why: the user's Windows env has ANTHROPIC_BASE_URL=http://localhost:11434/v1
        # (set up for Ollama compatibility), which the SDK reads automatically and
        # would otherwise route every Claude call into the Ollama server.
        _anthropic_client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            base_url="https://api.anthropic.com",
        )
    return _anthropic_client


def _tools_to_anthropic(tools: list) -> list:
    """Convert OpenAI tool format to Anthropic tool format."""
    result = []
    for t in tools:
        fn = t.get("function", t)
        result.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _messages_to_anthropic(messages: list) -> list:
    """Convert OpenAI messages format to Anthropic format."""
    out = []
    for m in messages:
        role = m["role"]
        if role == "system":
            continue  # system prompt handled separately
        if role == "tool":
            # Tool result — find the last user block or create one
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append({
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", "unknown"),
                    "content": str(m["content"]),
                })
            else:
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", "unknown"),
                        "content": str(m["content"]),
                    }]
                })
        elif role == "assistant" and m.get("tool_calls"):
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                fn = tc["function"] if isinstance(tc, dict) else tc.function
                name = fn["name"] if isinstance(fn, dict) else fn.name
                args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tc_id = tc["id"] if isinstance(tc, dict) else tc.id
                blocks.append({"type": "tool_use", "id": tc_id, "name": name, "input": args})
            out.append({"role": "assistant", "content": blocks})
        else:
            content = m.get("content", "")
            if isinstance(content, list):
                out.append({"role": role, "content": content})
            else:
                out.append({"role": role, "content": str(content)})
    return out


def _best_ollama_model() -> str:
    """Return the best available Ollama model, preferring larger qwen2.5 variants."""
    configured = OLLAMA_MODEL
    try:
        import httpx
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        if resp.status_code == 200:
            names = [m["name"] for m in resp.json().get("models", [])]
            # Prefer larger models in priority order
            for preferred in [
                "qwen2.5-coder:14B", "qwen2.5-coder:14b",
                "qwen2.5:14b", "qwen2.5:latest",
                "qwen2.5-coder:7b", "qwen2.5:7b",
            ]:
                if preferred in names:
                    return preferred
    except Exception:
        pass
    return configured


def _call_local(messages: list, tools: list = None, model: str = None) -> dict:
    """Call local llama.cpp server."""
    client = _get_llama_client()
    model_name = model or LLAMA_MODEL
    try:
        kwargs = {
            "model": model_name,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "temperature": 0.7,
            "max_tokens": 2048,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return {
            "content": choice.message.content or "",
            "tool_calls": choice.message.tool_calls or [],
            "model": model_name,
            "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
            "output_tokens": getattr(resp.usage, "completion_tokens", 0),
            "cost_aud": 0.0,
        }
    except Exception as e:
        logger.error(f"[LLM] llama.cpp error: {e}")
        return {"content": f"Local LLM error: {e}", "tool_calls": [], "model": model_name,
                "input_tokens": 0, "output_tokens": 0, "cost_aud": 0.0}


def _call_ollama(messages: list, tools: list = None, model: str = None) -> dict | None:
    """Call Ollama server. Returns None if unavailable so caller can fall through."""
    client = _get_ollama_client()
    model_name = model or OLLAMA_MODEL
    try:
        kwargs = {
            "model": model_name,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "temperature": 0.7,
            "max_tokens": 2048,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return {
            "content": choice.message.content or "",
            "tool_calls": choice.message.tool_calls or [],
            "model": model_name,
            "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
            "output_tokens": getattr(resp.usage, "completion_tokens", 0),
            "cost_aud": 0.0,
        }
    except Exception as e:
        logger.error(f"[LLM] Ollama error: {e}")
        return None


def _call_best_local(messages: list, tools: list = None) -> dict:
    """Try Ollama first (better models), fall through to llama.cpp."""
    from router import router
    if router._ollama_available:
        result = _call_ollama(messages, tools)
        if result is not None:
            return result
    return _call_local(messages, tools)


def _call_anthropic(messages: list, model: str, tools: list = None) -> dict:
    """Call Claude via Anthropic SDK."""
    client = _get_anthropic_client()
    anthropic_messages = _messages_to_anthropic(messages)
    if not anthropic_messages:
        anthropic_messages = [{"role": "user", "content": "Hello"}]

    try:
        kwargs = {
            "model": model,
            "system": SYSTEM_PROMPT,
            "messages": anthropic_messages,
            "max_tokens": 4096,
        }
        if tools:
            kwargs["tools"] = _tools_to_anthropic(tools)

        resp = client.messages.create(**kwargs)

        content_text = ""
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                class _FakeFn:
                    def __init__(self, name, arguments):
                        self.name = name
                        self.arguments = json.dumps(arguments) if isinstance(arguments, dict) else arguments
                class _FakeTc:
                    def __init__(self, id_, fn):
                        self.id = id_
                        self.function = fn
                tool_calls.append(_FakeTc(block.id, _FakeFn(block.name, block.input)))

        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        mark_api_success()
        return {
            "content": content_text,
            "tool_calls": tool_calls,
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_aud": calculate_cost_aud(model, in_tok, out_tok),
        }
    except Exception as e:
        mark_api_failure()
        logger.error(f"[LLM] Anthropic error: {e}")
        return {"content": f"API error: {e}", "tool_calls": [],
                "model": model, "input_tokens": 0, "output_tokens": 0, "cost_aud": 0.0}


def chat(messages: list, tools: list = None, tier: int = None, model: str = None) -> dict:
    """
    Unified chat function. Routes to the right backend based on tier.
    Returns: {content, tool_calls, model, input_tokens, output_tokens, local_fallback?}
    """
    from router import router

    if tier is None and model is None:
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if isinstance(last_user, list):
            last_user = " ".join(str(b) for b in last_user)
        decision = router.route(str(last_user))
        tier = decision.tier
        model = decision.model
    elif tier is not None and model is None:
        from router import TIER_MODELS
        model = TIER_MODELS.get(tier, "local")

    t0 = time.time()

    # If the API has repeatedly failed, force everything to local
    if tier > 0 and not is_api_available():
        logger.info("[LLM] API unavailable — routing to local")
        tier = 0
        model = "local"

    if tier == 0 or model == "local":
        result = _call_best_local(messages, tools)
    elif tier in (1, 2, 3):
        result = _call_anthropic(messages, model, tools)
        if result["content"].startswith("API error"):
            logger.warning("[LLM] API failed — falling back to local")
            result = _call_best_local(messages, tools)
            result["local_fallback"] = True
    else:
        result = _call_best_local(messages, tools)

    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result
