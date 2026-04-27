"""
code_agent.py - Code generation and debugging agent
"""
import logging
from llm import chat

logger = logging.getLogger(__name__)


class CodeAgent:
    def __init__(self, memory=None):
        self.memory = memory

    async def generate(self, task: str, language: str = "python", context: str = "") -> str:
        logger.info(f"[CodeAgent] Generating {language} code for: {task[:60]}")
        prompt = f"""Generate {language} code for: {task}

{f"Context: {context}" if context else ""}

Requirements:
- Clean, production-quality code
- Minimal comments (only where non-obvious)
- No unnecessary abstractions
- Handle errors gracefully
- Include a brief usage example if helpful

Return the code and a one-sentence description."""

        # Use Sonnet for code generation, Opus for complex architecture
        tier = 3 if any(w in task.lower() for w in ["architect", "system", "full application", "complete"]) else 2
        result = chat([{"role": "user", "content": prompt}], tier=tier)
        return result["content"]

    async def debug(self, code: str, error: str) -> str:
        logger.info(f"[CodeAgent] Debugging: {error[:60]}")
        prompt = f"""Debug this code. Error: {error}

Code:
```
{code}
```

Identify the bug, explain why it occurs, and provide the fixed code."""
        result = chat([{"role": "user", "content": prompt}], tier=2)
        return result["content"]

    async def explain(self, code: str) -> str:
        prompt = f"""Explain what this code does concisely. Focus on what it accomplishes, not how each line works.

```
{code[:3000]}
```"""
        result = chat([{"role": "user", "content": prompt}], tier=1)
        return result["content"]
