"""
router.py - Smart model routing: Tier 0 (local) → Tier 1 (Haiku) → Tier 2 (Sonnet) → Tier 3 (Opus)
"""
import os
import re
import logging
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env", override=True)

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
LLAMA_SERVER_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080")


@dataclass
class RouteDecision:
    tier: int
    model: str
    reasoning: str
    estimated_cost_aud: float


TIER_MODELS = {
    0: "local",
    1: "claude-haiku-4-5-20251001",
    2: "claude-sonnet-4-6",
    3: "claude-opus-4-6",
}

# AUD cost per 1M input tokens (conservative estimates)
TIER_INPUT_COSTS = {0: 0.0, 1: 0.0004, 2: 0.004, 3: 0.040}
TIER_OUTPUT_COSTS = {0: 0.0, 1: 0.002, 2: 0.020, 3: 0.200}

_OPUS_RE = re.compile(
    r'\b(stock analysis|investment|portfolio|P/E ratio|dividend|ASX|financial analysis|'
    r'budget analysis|year.end|tax strateg|complex architect|design software|build a complete|'
    r'think carefully|be thorough|deep analysis|comprehensive report|full report)\b',
    re.IGNORECASE
)

_SONNET_RE = re.compile(
    r'\b(research|analys[ei]|compare|summarize|summarise|email|news|briefing|'
    r'explain|debug|build|create|write a|smart home|integrat|generate code|'
    r'hardware|design|plan|draft|review|read this|pdf|image)\b',
    re.IGNORECASE
)

_HAIKU_RE = re.compile(
    r'\b(open|close|todo|task|timer|remind|weather|time|date|volume|'
    r'screenshot|clipboard|lock|what.s open|list my|my tasks|'
    r'turn on|turn off|play|pause|stop|set a|add a|delete|complete)\b',
    re.IGNORECASE
)


class RouterAgent:
    def __init__(self):
        self._ollama_available: Optional[bool] = None
        self._llama_available: Optional[bool] = None

    def probe_backends(self):
        """Check which inference backends are available. Call once at startup."""
        import httpx
        try:
            r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
            self._ollama_available = r.status_code == 200
        except Exception:
            self._ollama_available = False

        try:
            r = httpx.get(f"{LLAMA_SERVER_URL}/health", timeout=2.0)
            self._llama_available = r.status_code == 200
        except Exception:
            self._llama_available = False

        logger.info(f"[Router] Ollama={self._ollama_available} llama.cpp={self._llama_available}")
        return self._ollama_available, self._llama_available

    def _estimate_cost(self, tier: int, input_len: int, output_len: int = 100) -> float:
        input_tokens = input_len / 4
        output_tokens = output_len
        cost = (TIER_INPUT_COSTS[tier] * input_tokens + TIER_OUTPUT_COSTS[tier] * output_tokens) / 1_000_000
        return round(cost, 6)

    def route(self, message: str, force_tier: Optional[int] = None) -> RouteDecision:
        if force_tier is not None:
            model = TIER_MODELS.get(force_tier, TIER_MODELS[2])
            return RouteDecision(
                tier=force_tier, model=model, reasoning="forced",
                estimated_cost_aud=self._estimate_cost(force_tier, len(message))
            )

        local_mode = os.getenv("LOCAL_MODE", "false").lower() == "true"
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

        if local_mode or not api_key:
            return RouteDecision(
                tier=0, model="local", reasoning="local mode / no API key",
                estimated_cost_aud=0.0
            )

        msg = message.strip()

        if _OPUS_RE.search(msg):
            tier, reasoning = 3, "financial/complex keyword"
        elif _SONNET_RE.search(msg):
            tier, reasoning = 2, "research/create keyword"
        elif _HAIKU_RE.search(msg):
            tier, reasoning = 1, "simple command keyword"
        elif len(msg.split()) <= 8:
            tier, reasoning = 1, "short message"
        else:
            tier, reasoning = 2, "default"

        model = TIER_MODELS[tier]
        cost = self._estimate_cost(tier, len(message))
        logger.debug(f"[Router] tier={tier} model={model} reason={reasoning}")
        return RouteDecision(tier=tier, model=model, reasoning=reasoning, estimated_cost_aud=cost)

    def startup_message(self) -> str:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        local_mode = os.getenv("LOCAL_MODE", "false").lower() == "true"
        if local_mode or not api_key:
            return "Running in local mode, sir."
        if self._ollama_available:
            return "Running in hybrid mode, sir."
        return "Running in cloud mode, sir."


router = RouterAgent()
