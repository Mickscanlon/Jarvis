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

USEFUL SHELL COMMANDS:
- Open windows: powershell "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object Name, MainWindowTitle | Format-List"
- System info: systeminfo | find "OS Name"
- Volume: powershell "(Get-AudioDevice -List | Where-Object {$_.Type -eq 'Playback' -and $_.Default -eq 'True'}).Volume"
"""

_llama_client = None
_ollama_client = None
_anthropic_client = None


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


def _call_local(messages: list, tools: list = None, model: str = None) -> dict:
    """Call local llama.cpp server."""
    client = _get_llama_client()
    model_name = model or LLAMA_MODEL
    try:
        kwargs = {
            "model": model_name,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "temperature": 0.7,
            "max_tokens": 512,
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
        }
    except Exception as e:
        logger.error(f"[LLM] local error: {e}")
        return {"content": f"Local LLM error: {e}", "tool_calls": [], "model": model_name,
                "input_tokens": 0, "output_tokens": 0}


def _call_ollama(messages: list, tools: list = None) -> dict:
    """Call Ollama server."""
    client = _get_ollama_client()
    try:
        kwargs = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "temperature": 0.7,
            "max_tokens": 512,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return {
            "content": choice.message.content or "",
            "tool_calls": choice.message.tool_calls or [],
            "model": OLLAMA_MODEL,
            "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
            "output_tokens": getattr(resp.usage, "completion_tokens", 0),
        }
    except Exception as e:
        logger.error(f"[LLM] Ollama error: {e}")
        return None  # caller falls back to Claude


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
            "max_tokens": 1024,
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
                # Wrap in OpenAI-compatible structure for unified processing
                class _FakeFn:
                    def __init__(self, name, arguments):
                        self.name = name
                        self.arguments = json.dumps(arguments) if isinstance(arguments, dict) else arguments
                class _FakeTc:
                    def __init__(self, id_, fn):
                        self.id = id_
                        self.function = fn
                tool_calls.append(_FakeTc(block.id, _FakeFn(block.name, block.input)))

        return {
            "content": content_text,
            "tool_calls": tool_calls,
            "model": model,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
    except Exception as e:
        logger.error(f"[LLM] Anthropic error: {e}")
        return {"content": f"API error: {e}. Trying local fallback.", "tool_calls": [],
                "model": model, "input_tokens": 0, "output_tokens": 0}


def chat(messages: list, tools: list = None, tier: int = None, model: str = None) -> dict:
    """
    Unified chat function. Routes to the right backend based on tier.
    Returns: {content, tool_calls, model, input_tokens, output_tokens}
    """
    from router import router

    if tier is None and model is None:
        # Auto-route based on last user message
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

    if tier == 0 or model == "local":
        # Try Ollama first, fall back to llama.cpp
        ollama_avail = os.getenv("OLLAMA_BASE_URL") and router._ollama_available
        if ollama_avail:
            result = _call_ollama(messages, tools)
            if result:
                result["duration_ms"] = int((time.time() - t0) * 1000)
                return result
        result = _call_local(messages, tools)
    elif tier in (1, 2, 3):
        result = _call_anthropic(messages, model, tools)
        if result and result["content"].startswith("API error"):
            # Fall back to local on API failure
            logger.warning("[LLM] Falling back to local model")
            result = _call_local(messages, tools)
    else:
        result = _call_local(messages, tools)

    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result
