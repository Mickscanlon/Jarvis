"""
tools.py - Core tool registry: screen, shell, files, windows, notifications
"""
import os
import subprocess
import logging
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env")

logger = logging.getLogger(__name__)

pytesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "read_screen",
        "description": "Capture the screen and OCR all visible text. Use when asked what's on screen.",
        "parameters": {"type": "object", "properties": {
            "region": {"type": "string", "description": "full, top, bottom, left, right"}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Run a Windows shell command and return output. Use for system info, app launching, file ops.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "cmd.exe command"}
        }, "required": ["command"]}
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from disk.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Full file path"}
        }, "required": ["path"]}
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write content to a file on disk.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"}
        }, "required": ["path", "content"]}
    }},
    {"type": "function", "function": {
        "name": "fetch_news",
        "description": "Fetch the latest news headlines from RSS feeds (ABC, BBC, Reuters, Guardian). Returns titles and summaries. Call this when asked for news or headlines.",
        "parameters": {"type": "object", "properties": {
            "max_items": {"type": "integer", "description": "Max headlines to return (default 10)"}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "list_directory",
        "description": "List files and subdirectories in a directory. Defaults to the JARVIS home directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory path (defaults to JARVIS home)"}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "edit_file_with_ai",
        "description": "Use Claude Sonnet or Opus to make a targeted edit to a file. Provide the file path and a plain-English instruction describing what to change. The model reads the file, applies the edit, and writes it back.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Full file path to edit"},
            "instruction": {"type": "string", "description": "Plain-English description of the edit to make"},
            "model": {"type": "string", "description": "claude-sonnet-4-6 (default) or claude-opus-4-7"}
        }, "required": ["path", "instruction"]}
    }},
    {"type": "function", "function": {
        "name": "create_skill",
        "description": "Create a new reusable Python skill tool. Code must define run(params: dict) -> str.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "snake_case skill name"},
            "description": {"type": "string"},
            "code": {"type": "string", "description": "Complete Python defining run(params)"}
        }, "required": ["name", "description", "code"]}
    }},
    {"type": "function", "function": {
        "name": "list_open_windows",
        "description": "List all open app windows on this computer.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }},
    {"type": "function", "function": {
        "name": "open_app",
        "description": "Open an application by name (chrome, vscode, terminal, spotify, discord, etc).",
        "parameters": {"type": "object", "properties": {
            "app_name": {"type": "string"}
        }, "required": ["app_name"]}
    }},
    {"type": "function", "function": {
        "name": "get_clipboard",
        "description": "Read the current clipboard text content.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }},
    {"type": "function", "function": {
        "name": "set_clipboard",
        "description": "Write text to the clipboard.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}
        }, "required": ["text"]}
    }},
    {"type": "function", "function": {
        "name": "send_notification",
        "description": "Send a Windows desktop notification.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"}
        }, "required": ["title", "message"]}
    }},
    {"type": "function", "function": {
        "name": "get_system_info",
        "description": "Get system info: CPU, RAM, disk, battery, uptime.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }},
    {"type": "function", "function": {
        "name": "set_volume",
        "description": "Set system volume (0-100).",
        "parameters": {"type": "object", "properties": {
            "level": {"type": "integer", "description": "0-100"}
        }, "required": ["level"]}
    }},
    {"type": "function", "function": {
        "name": "run_claude_code",
        "description": (
            "Delegate a complex, multi-file, or architectural task to Claude Code CLI. "
            "Use this when the task involves editing multiple files, running tests, "
            "installing packages, restructuring code, or any change that would exceed "
            "a single write_file operation. Claude Code will handle the full task "
            "autonomously and return a summary. "
            "Examples: 'refactor the router to add caching', "
            "'add a new REST endpoint and wire it to the frontend', "
            "'fix all TypeScript errors in the frontend'."
        ),
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description": "Plain-English description of what Claude Code should do. Be specific and include file paths where relevant."},
            "working_dir": {"type": "string", "description": "Directory to run in (default: C:/Users/micha/jarvis)"}
        }, "required": ["task"]}
    }},
]


# ── Implementations ────────────────────────────────────────────────────────────

def read_screen(region: str = "full") -> str:
    try:
        import mss
        from PIL import Image
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = pytesseract_cmd

        with mss.mss() as sct:
            monitor = dict(sct.monitors[1])
            if region == "top":
                monitor["height"] = monitor["height"] // 2
            elif region == "bottom":
                monitor["top"] += monitor["height"] // 2
                monitor["height"] = monitor["height"] // 2
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img = img.convert("L").resize((img.width // 2, img.height // 2))
            text = pytesseract.image_to_string(img)
            cleaned = "\n".join(l for l in text.splitlines() if l.strip())
            if not cleaned:
                return "No text detected on screen."
            return cleaned[:2000] + ("\n[...truncated]" if len(cleaned) > 2000 else "")
    except Exception as e:
        return f"Screen read error: {e}"


def run_shell(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        output = (result.stdout + result.stderr).strip()
        if not output:
            return "Command ran with no output."
        return output[:2000] + ("\n[...truncated]" if len(output) > 2000 else "")
    except subprocess.TimeoutExpired:
        return "Command timed out after 15 seconds."
    except Exception as e:
        return f"Shell error: {e}"


def list_open_windows() -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Get-Process | Where-Object {$_.MainWindowTitle -ne ""} | '
             'Select-Object Name, MainWindowTitle | Format-List'],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        return output or "No windows with titles found."
    except Exception as e:
        return f"Error listing windows: {e}"


def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return content[:3000] + ("\n[...truncated]" if len(content) > 3000 else "")
    except Exception as e:
        return f"File read error: {e}"


def write_file(path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"File write error: {e}"


def fetch_news(max_items: int = 10) -> str:
    try:
        from integrations.news import fetch_all_news
        items = fetch_all_news(max_per_feed=3)
        if not items:
            return "No news available right now."
        lines = [
            f"[{item['source']}] {item['title']} — {item.get('summary', '')[:120]}"
            for item in items[:max_items]
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"News fetch error: {e}"


JARVIS_HOME = "C:/Users/micha/jarvis"


def list_directory(path: str = "") -> str:
    target = path.strip() if path.strip() else JARVIS_HOME
    try:
        entries = os.listdir(target)
        lines = []
        for name in sorted(entries):
            full = os.path.join(target, name)
            tag = "/" if os.path.isdir(full) else ""
            lines.append(f"{name}{tag}")
        return f"{target}:\n" + "\n".join(lines) if lines else f"{target}: (empty)"
    except Exception as e:
        return f"Directory error: {e}"


def edit_file_with_ai(path: str, instruction: str, model: str = "claude-sonnet-4-6") -> str:
    try:
        import anthropic
        content = read_file(path)
        if content.startswith("File read error"):
            return content
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        result = client.messages.create(
            model=model,
            max_tokens=8192,
            system="You are a precise code editor. Return ONLY the complete edited file content. No explanation, no markdown fences, no commentary.",
            messages=[{
                "role": "user",
                "content": f"Instruction: {instruction}\n\nFile path: {path}\n\n```\n{content}\n```"
            }]
        )
        new_content = result.content[0].text.strip()
        # Strip accidental markdown fences
        if new_content.startswith("```"):
            new_content = "\n".join(new_content.splitlines()[1:])
            if new_content.endswith("```"):
                new_content = new_content[:-3].strip()
        return write_file(path, new_content)
    except Exception as e:
        return f"AI edit error: {e}"


def create_skill(name: str, description: str, code: str) -> str:
    from skills_manager import create_skill as _create
    return _create(name, description, code)


def open_app(app_name: str) -> str:
    known = {
        "chrome": "chrome.exe", "firefox": "firefox.exe",
        "vscode": "code", "code": "code",
        "terminal": "wt.exe", "windows terminal": "wt.exe",
        "explorer": "explorer.exe", "notepad": "notepad.exe",
        "spotify": "spotify.exe", "discord": "discord.exe",
        "steam": "steam.exe", "calculator": "calc.exe",
        "word": "winword.exe", "excel": "excel.exe",
        "paint": "mspaint.exe", "snipping tool": "SnippingTool.exe",
    }
    exe = known.get(app_name.lower().strip())
    try:
        if exe:
            subprocess.Popen([exe], shell=True)
        else:
            subprocess.Popen(["start", "", app_name], shell=True)
        return f"Opening {app_name}."
    except Exception as e:
        return f"Could not open {app_name}: {e}"


def get_clipboard() -> str:
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or "(clipboard empty)"
    except Exception as e:
        return f"Clipboard error: {e}"


def set_clipboard(text: str) -> str:
    try:
        subprocess.run(
            ["powershell", "-Command", f'Set-Clipboard -Value "{text}"'],
            timeout=5
        )
        return "Clipboard updated."
    except Exception as e:
        return f"Clipboard write error: {e}"


def send_notification(title: str, message: str) -> str:
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(title, message, duration=5, threaded=True)
        return f"Notification sent: {title}"
    except Exception:
        try:
            subprocess.run([
                "powershell", "-Command",
                f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, '
                f'ContentType = WindowsRuntime] > $null; '
                f'$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02; '
                f'$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template); '
                f'$xml.GetElementsByTagName("text")[0].AppendChild($xml.CreateTextNode("{title}")); '
                f'$xml.GetElementsByTagName("text")[1].AppendChild($xml.CreateTextNode("{message}")); '
                f'$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); '
                f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("JARVIS").Show($toast);'
            ], timeout=5)
            return f"Notification sent: {title}"
        except Exception as e:
            return f"Notification failed: {e}"


def get_system_info() -> str:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:/")
        info = [
            f"CPU: {cpu:.0f}%",
            f"RAM: {ram.percent:.0f}% used ({ram.used // 1024**3:.1f}/{ram.total // 1024**3:.1f} GB)",
            f"Disk C: {disk.percent:.0f}% used ({disk.used // 1024**3:.0f}/{disk.total // 1024**3:.0f} GB)",
        ]
        try:
            battery = psutil.sensors_battery()
            if battery:
                info.append(f"Battery: {battery.percent:.0f}% {'charging' if battery.power_plugged else 'on battery'}")
        except Exception:
            pass
        return "\n".join(info)
    except Exception as e:
        return f"System info error: {e}"


def set_volume(level: int) -> str:
    level = max(0, min(100, level))
    try:
        subprocess.run([
            "powershell", "-Command",
            f"$vol = {level / 100.0}; "
            "Add-Type -TypeDefinition @'\nusing System.Runtime.InteropServices;\n"
            "[Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
            "interface IAudioEndpointVolume { void _VtblGap1_6(); [PreserveSig] int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext); }\n"
            "@' -PassThru; "
        ], timeout=5)
        # Simpler approach via nircmd if available
        result = run_shell(f"nircmd.exe setsysvolume {int(level * 655.35)}")
        if "error" in result.lower():
            return run_shell(f'powershell "(New-Object -comobject WScript.Shell).SendKeys([char]174)"')
        return f"Volume set to {level}%"
    except Exception as e:
        return f"Volume error: {e}"


# ── Claude Code delegation ────────────────────────────────────────────────────

def run_claude_code(task: str, working_dir: str = None) -> str:
    """
    Open a visible Windows Terminal running Claude Code for complex tasks.
    Returns immediately — Claude Code runs in the foreground terminal window.
    No Anthropic API tokens consumed since Claude Code uses its own auth.
    """
    cwd = working_dir or r"C:\Users\micha\jarvis"
    # Sanitize for safe command-line passing
    task_clean = task.replace('"', "'").replace('\n', ' ').replace('\r', '').strip()
    task_arg = task_clean[:500]

    launched = False
    # Prefer Windows Terminal (wt.exe) for nicer experience
    try:
        subprocess.Popen(
            ['wt.exe', '-d', cwd, 'cmd.exe', '/k',
             f'echo [JARVIS → CLAUDE CODE] & echo. & claude --dangerously-skip-permissions "{task_arg}"'],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        launched = True
    except FileNotFoundError:
        pass

    if not launched:
        # Fallback: new CMD console window
        subprocess.Popen(
            ['cmd.exe', '/k',
             f'cd /d "{cwd}" && echo [JARVIS - CLAUDE CODE] && claude --dangerously-skip-permissions "{task_arg}"'],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

    return f"Claude Code terminal opened. Task: {task_arg[:120]}"


# ── Skills ────────────────────────────────────────────────────────────────────

def load_skills() -> tuple[list, dict]:
    from skills_manager import load_skills as _load
    return _load()


def dispatch_tool(name: str, args: dict, skill_fns: dict = None) -> str:
    handlers = {
        "read_screen": lambda: read_screen(args.get("region", "full")),
        "run_shell": lambda: run_shell(args.get("command", "")),
        "read_file": lambda: read_file(args.get("path", "")),
        "write_file": lambda: write_file(args.get("path", ""), args.get("content", "")),
        "fetch_news": lambda: fetch_news(args.get("max_items", 10)),
        "list_directory": lambda: list_directory(args.get("path", "")),
        "edit_file_with_ai": lambda: edit_file_with_ai(
            args.get("path", ""), args.get("instruction", ""), args.get("model", "claude-sonnet-4-6")),
        "create_skill": lambda: create_skill(
            args.get("name", ""), args.get("description", ""), args.get("code", "")),
        "list_open_windows": lambda: list_open_windows(),
        "open_app": lambda: open_app(args.get("app_name", "")),
        "get_clipboard": lambda: get_clipboard(),
        "set_clipboard": lambda: set_clipboard(args.get("text", "")),
        "send_notification": lambda: send_notification(
            args.get("title", "JARVIS"), args.get("message", "")),
        "get_system_info": lambda: get_system_info(),
        "set_volume": lambda: set_volume(args.get("level", 50)),
        "run_claude_code": lambda: run_claude_code(
            args.get("task", ""), args.get("working_dir", "")),
    }

    if name in handlers:
        return handlers[name]()
    if skill_fns and name in skill_fns:
        return skill_fns[name](args.get("params", {}))
    return f"Unknown tool: {name}"
