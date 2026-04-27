"""
skills_manager.py - Hot-reload dynamic skills from data/skills/
"""
import os
import py_compile
import importlib.util
import logging
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env")

logger = logging.getLogger(__name__)

SKILLS_DIR = os.getenv("SKILLS_DIR", "C:/Users/micha/jarvis/data/skills")


def load_skills() -> tuple[list, dict]:
    """
    Load all Python files from SKILLS_DIR as callable tools.
    Returns (tool_definitions, tool_callables).
    Hot-reload safe: call every turn.
    """
    skill_defs = []
    skill_fns = {}

    os.makedirs(SKILLS_DIR, exist_ok=True)

    for filename in os.listdir(SKILLS_DIR):
        if not filename.endswith(".py"):
            continue

        skill_name = filename[:-3]
        skill_path = os.path.join(SKILLS_DIR, filename)

        try:
            spec = importlib.util.spec_from_file_location(skill_name, skill_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "run"):
                continue

            doc = (module.__doc__ or f"Custom skill: {skill_name}").strip()
            # Try to read parameter schema from module
            params_schema = getattr(module, "PARAMS", {
                "type": "object",
                "properties": {"params": {"type": "object", "description": "Skill parameters"}},
                "required": []
            })

            skill_defs.append({
                "type": "function",
                "function": {
                    "name": f"skill_{skill_name}",
                    "description": doc,
                    "parameters": params_schema,
                }
            })
            skill_fns[f"skill_{skill_name}"] = module.run

        except Exception as e:
            logger.warning(f"[Skills] Failed to load {filename}: {e}")

    if skill_defs:
        logger.info(f"[Skills] Loaded {len(skill_defs)}: {[s['function']['name'] for s in skill_defs]}")

    return skill_defs, skill_fns


def create_skill(name: str, description: str, code: str) -> str:
    """Save a new skill, validate it compiles, return status message."""
    os.makedirs(SKILLS_DIR, exist_ok=True)
    skill_path = os.path.join(SKILLS_DIR, f"{name}.py")

    try:
        full_code = f'"""\nSkill: {name}\nDescription: {description}\n"""\n\n{code}'
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(full_code)

        py_compile.compile(skill_path, doraise=True)
        logger.info(f"[Skills] Created skill: {name}")
        return f"Skill '{name}' created and validated. Available from next message."

    except py_compile.PyCompileError as e:
        os.remove(skill_path)
        return f"Skill syntax error: {e}"
    except Exception as e:
        return f"Skill creation failed: {e}"
