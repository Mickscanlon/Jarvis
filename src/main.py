"""
main.py - JARVIS CLI mode (no web server). For testing or headless use.
For full server mode with UI, run src/server.py instead.
"""
import os
import sys
import json
import re

sys.path.insert(0, os.path.dirname(__file__))

from llm import chat
from voice_input import VoiceInput
from voice_output import VoiceOutput
from tools import TOOL_DEFINITIONS, dispatch_tool, load_skills
from memory import Memory
from router import router as model_router

MAX_TOOL_LOOPS = 5

STT_CORRECTIONS = {
    r"\bcloud\b": "Claude", r"\bjarves\b": "JARVIS",
    r"\btravis\b": "JARVIS", r"\bcloud code\b": "Claude Code",
}


def apply_corrections(text: str) -> str:
    for p, r in STT_CORRECTIONS.items():
        text = re.sub(p, r, text, flags=re.IGNORECASE)
    return text


def parse_text_tool_calls(content: str) -> list:
    calls = []
    pattern = r'(run_shell|read_screen|read_file|write_file|create_skill|list_open_windows|open_app)\s*[\("\']*([^)"\'`\n]*)[\)"\'`]*'
    for tool_name, args_str in re.findall(pattern, content):
        args_str = args_str.strip().strip('"\'')
        if tool_name == "run_shell":
            calls.append({"name": "run_shell", "args": {"command": args_str}})
        elif tool_name == "read_screen":
            calls.append({"name": "read_screen", "args": {"region": "full"}})
        elif tool_name == "read_file":
            calls.append({"name": "read_file", "args": {"path": args_str}})
        elif tool_name == "open_app":
            calls.append({"name": "open_app", "args": {"app_name": args_str}})
    return calls


def run_agent(user_text: str, history: list, memory: Memory, skill_fns: dict, all_tools: list) -> str:
    mem_context = memory.get_context_for(user_text)
    enriched = f"{user_text}\n\n[Memory:{mem_context}]" if mem_context else user_text
    messages = history[-18:] + [{"role": "user", "content": enriched}]

    decision = model_router.route(user_text)
    print(f"[Router] tier={decision.tier} model={decision.model}")

    for loop in range(MAX_TOOL_LOOPS):
        result = chat(messages, tools=all_tools, tier=decision.tier, model=decision.model)
        content = result["content"]
        tool_calls = result.get("tool_calls", [])

        memory.log_usage(
            model=result.get("model", decision.model),
            tier=decision.tier,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            cost_aud=decision.estimated_cost_aud,
            duration_ms=result.get("duration_ms", 0)
        )

        if not tool_calls and content:
            text_calls = parse_text_tool_calls(content)
            if text_calls:
                print(f"[Agent] Intercepted {len(text_calls)} text-format tool call(s)")
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
            messages.append({
                "role": "assistant", "content": content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            })
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                print(f"[Tool] {tc.function.name}({args})")
                res = dispatch_tool(tc.function.name, args, skill_fns)
                print(f"[Tool] → {res[:120]}{'...' if len(res) > 120 else ''}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": res})
        else:
            # Strip action tags from spoken response
            final = re.sub(r'\[ACTION:\w+\][^\[]*', '', content).strip()
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": final})
            if len(history) > 20:
                history[:] = history[-20:]
            return final

    return "Slight hiccup, sir. Give me a moment."


def main():
    print("=" * 50)
    print("  JARVIS — Local AI Assistant (CLI mode)")
    print("=" * 50)
    print()

    model_router.probe_backends()
    memory = Memory()
    voice_in = VoiceInput()
    voice_out = VoiceOutput()

    skill_defs, skill_fns = load_skills()
    all_tools = TOOL_DEFINITIONS + skill_defs
    history = []

    startup_msg = model_router.startup_message()
    print(f"[JARVIS] {startup_msg}")
    voice_out.speak(startup_msg)

    print(f"[JARVIS] Say '{os.getenv('WAKE_WORD', 'hey jarvis')}' or type a message. Type 'quit' to exit.\n")

    while True:
        try:
            mode = input("[Mode] ENTER=voice, type=text, quit=exit: ").strip()

            if mode.lower() in ("quit", "exit", "q"):
                memory.extract_and_store(history)
                print("[JARVIS] Goodbye, sir.")
                voice_out.speak("Goodbye, sir.")
                break

            user_text = voice_in.get_voice_input() if mode == "" else apply_corrections(mode)

            if not user_text:
                print("[JARVIS] Didn't catch that.")
                continue

            print(f"\n[You] {user_text}")

            # Reload skills each turn
            skill_defs, skill_fns = load_skills()
            all_tools = TOOL_DEFINITIONS + skill_defs

            response = run_agent(user_text, history, memory, skill_fns, all_tools)
            print(f"[JARVIS] {response}\n")
            voice_out.speak(response)

        except KeyboardInterrupt:
            memory.extract_and_store(history)
            print("\n[JARVIS] Interrupted. Goodbye.")
            break
        except Exception as e:
            print(f"[Error] {e}")


if __name__ == "__main__":
    main()
