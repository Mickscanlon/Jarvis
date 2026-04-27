# JARVIS — Intelligent Local AI Assistant for Windows
## Claude Code Build Specification

You are Claude Code. Your job is to build or upgrade JARVIS — a fully-featured, 
voice-first AI assistant running natively on Windows 11. 

You may either:
- Build fresh in a new folder (recommended if starting clean)
- Upgrade the existing project at C:\Users\micha\jarvis\ (preserve working 
  voice loop, tools, and memory modules — upgrade and extend them)

Evaluate the existing folder first. If the architecture is compatible, extend it. 
If starting fresh is cleaner, do that and migrate the working components.

When the build is complete, print:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JARVIS is ready, sir.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

---

## Hardware & Environment Context

- OS: Windows 11
- GPU: AMD RX 6600 XT 8GB (Vulkan, not CUDA)
- CPU: AMD Ryzen 5700G
- RAM: 16GB
- Python: 3.12 or 3.13 (check what's installed)
- All paths use Windows conventions (C:\Users\micha\jarvis\)
- Do NOT use WSL, Linux paths, or AppleScript — Windows native only
- llama.cpp Vulkan build available at C:\Users\micha\jarvis\llama\
- Existing GGUF models in C:\Users\micha\jarvis\models\

---

## Intelligence Architecture — Hybrid Model Routing

JARVIS uses a smart routing layer that selects the right model for each task. 
This balances cost, speed, and capability automatically.

### Model Tiers

TIER 0 — Local Ollama (zero cost, instant):
- Use for: intent classification, wake word post-processing, casual chitchat 
  under 2 sentences, simple yes/no questions, routing decisions themselves
- Model: qwen2.5:7b via Ollama (fall back to llama.cpp if Ollama unavailable)
- When Ollama is not running or model not available, fall through to Haiku

TIER 1 — Claude Haiku (claude-haiku-4-5-20251001, cheapest API):
- Use for: casual conversation, todo management, app control commands, 
  timer/reminder setting, simple factual questions, weather, time, 
  opening applications, sending messages, reading back stored data
- Trigger: intent score "simple" from router

TIER 2 — Claude Sonnet (claude-sonnet-4-6):
- Use for: email summaries, news briefings, medium-complexity code generation,
  research tasks under 5 sources, debugging sessions, writing tasks,
  smart home integration planning, explaining hardware concepts,
  generating skill code for self-modification
- Trigger: intent score "moderate" from router

TIER 3 — Claude Opus (claude-opus-4-6):
- Use for: stock research and investment analysis, complex financial reasoning,
  budgeting and accounting logic, multi-file architecture decisions,
  generating complete software modules, deep research across many sources,
  tasks explicitly requiring maximum intelligence
- Trigger: intent score "complex" or user says "think carefully" / "be thorough"

### Router Implementation

Build a RouterAgent class that:
1. Takes the user's message
2. Runs a fast local classification (Ollama or regex heuristics as fallback)
3. Returns (tier, model_name, reasoning)
4. Logs the routing decision and estimated cost
5. Never calls Opus for anything a Sonnet can handle
6. Never calls Sonnet for anything Haiku can handle
7. Exposes a /api/model-stats endpoint showing spend per tier per day

Router heuristics (use these as fallback if local model unavailable):
- Contains financial/stock/investment keywords → Opus
- Contains "build", "create", "architect", "design software" → Opus or Sonnet based on complexity
- Contains "research", "analyse", "compare" → Sonnet
- Single sentence question, no tool needed → Haiku
- App control, todo, timer → Haiku
- Everything else → Sonnet

### Cost Tracking

Track every API call:
- Model used, input tokens, output tokens, estimated cost AUD
- Store in SQLite usage_log table
- Surface in UI as daily/weekly/monthly spend
- Alert (voice + UI) if daily spend exceeds $2 AUD

### Local Mode (Offline Operation)

JARVIS supports a fully offline mode when ANTHROPIC_API_KEY is absent 
or when LOCAL_MODE=true is set in .env.

Local Mode Stack:
- LLM: Ollama (primary) → llama.cpp Vulkan (fallback)
  - Ollama endpoint: http://localhost:11434 (auto-detect if running)
  - llama.cpp endpoint: http://localhost:8080 (existing setup)
  - Model preference order: qwen2.5:14b → qwen2.5:7b → any loaded model
  - All tier routing still applies — just routes to local instead of API
  - Tool-call text parsing (parse_text_tool_calls) always active in local mode
    since smaller models rarely emit structured JSON tool calls

- TTS: Kokoro ONNX (already primary — no change needed)
- STT: faster-whisper tiny.en on CPU (already primary — no change needed)
- Embeddings: all-MiniLM-L6-v2 on CPU (already primary — no change needed)

Hybrid Mode (default, recommended):
- LOCAL_MODE=false but OLLAMA_BASE_URL configured
- Router uses Tier 0 (local) for intent classification and casual chat
- Falls through to Claude API for Tier 1/2/3 tasks
- If API call fails (network down, quota hit): fall back to local model
  with a brief spoken notice: "Running offline, sir. Local model only."

Mode detection at startup:
1. Check for ANTHROPIC_API_KEY — if absent, force LOCAL_MODE=true
2. Check for Ollama running — ping http://localhost:11434/api/tags
3. Check for llama-server running — ping http://localhost:8080/health
4. Log which inference backends are available
5. Speak on startup: "Running in [hybrid/local/cloud] mode, sir."

---

## Backend Architecture

Stack: FastAPI + Python, WebSocket communication, SQLite storage

### File Structure
jarvis/
├── CLAUDE.md                    ← this file
├── .env                         ← API keys and config
├── .env.example                 ← template
├── requirements.txt
├── start.bat                    ← launches everything
├── start_llama.bat              ← llama.cpp server only
├── data/
│   ├── jarvis.db                ← main SQLite database
│   ├── usage_log.jsonl          ← append-only cost log
│   └── skills/                  ← agent-written Python skills (hot-reload)
├── models/                      ← GGUF files
├── llama/                       ← llama.cpp binaries
├── src/
│   ├── main.py                  ← entry point
│   ├── server.py                ← FastAPI app + WebSocket handler
│   ├── router.py                ← model routing logic
│   ├── llm.py                   ← unified LLM client (local + API)
│   ├── voice_input.py           ← STT pipeline
│   ├── voice_output.py          ← TTS pipeline
│   ├── tools.py                 ← core tool registry
│   ├── memory.py                ← three-tier memory system
│   ├── skills_manager.py        ← dynamic skill loader
│   ├── agents/
│   │   ├── researcher.py        ← deep research agent
│   │   ├── stock_agent.py       ← financial analysis agent
│   │   ├── code_agent.py        ← code generation agent
│   │   └── scheduler.py        ← background task scheduler
│   ├── integrations/
│   │   ├── email_windows.py     ← Windows mail integration
│   │   ├── news.py              ← news aggregation
│   │   ├── smart_home.py        ← Home Assistant bridge
│   │   ├── stocks.py            ← market data fetching
│   │   ├── budget.py            ← budgeting engine
│   │   └── messaging.py        ← Windows messaging (Teams, WhatsApp Web)
│   └── hardware/
│       └── bedside_clock.py     ← clock hardware advisor
└── frontend/
├── index.html
├── package.json
└── src/
├── main.ts
├── orb.ts               ← Three.js particle orb
├── voice.ts             ← audio input/output
├── ws.ts                ← WebSocket client
├── settings.ts          ← settings panel
└── style.css

---

## Personality & Voice Identity

JARVIS has a calm, dry, British butler personality. Not sycophantic — efficient 
and occasionally witty. Learns the user's name (Michael) and preferences over time.

PERSONALITY RULES:
- Economy of language — 1 sentence ideal, 2 max for voice responses
- No markdown in spoken responses — prose only
- Mix "sir" (~50%) and "Michael" (~50%), never both in same sentence
- Use contractions: "I'm", "you're", "don't"
- Use "..." for natural pauses, em dashes for pivots
- Calm when things go wrong: "Slight hiccup, sir. Give me a moment."
- BANNED PHRASES: "Absolutely", "Great question", "I'd be happy to", 
  "Of course", "How can I help", "Certainly", "As an AI"
- PREFERRED PHRASES: "Will do.", "Right away.", "Understood.", 
  "Consider it done.", "Done, sir.", "On it."
- For complex tasks: brief acknowledgment first, then silent execution, 
  then result. Never narrate every step aloud.

STYLE LEARNING:
JARVIS learns Michael's preferences over time by:
- Tracking which suggestions he accepts vs rejects
- Noting his typical working hours and energy patterns
- Learning his tech stack preferences (Python, JavaScript, Rust)
- Tracking his business context (Street Appeal Homes, lawn care)
- Storing communication style preferences (direct, technical depth)
- After 10+ interactions, begin proactively surfacing relevant context
- Style profile stored in SQLite, updated after each session

---

## Voice Pipeline (Windows Native)

### Speech-to-Text

Primary: faster-whisper with tiny.en model on CPU
- Device: Microphone (Realtek(R) Audio) — device index 1
- Sample rate: 16000Hz
- Wake word: openwakeword with hey_jarvis model
- After wake word: record until silence (threshold 0.01, 20 chunks silence = done)
- Buffer flush: 0.8s sleep + buffer.clear() after stream opens (prevents false triggers)
- IS_SPEAKING guard: ignore wake word detections while TTS is playing

Secondary (if Groq API key present): Groq Whisper whisper-large-v3-turbo
- Sub-300ms latency, more accurate than local tiny.en
- Falls back to local faster-whisper if Groq unavailable or rate limited

STT Corrections dictionary (apply before processing):
```python
STT_CORRECTIONS = {
    r"\bcloud\b": "Claude",
    r"\bjarves\b": "JARVIS", 
    r"\btravis\b": "JARVIS",
    r"\bcloud code\b": "Claude Code",
}
```

Echo filter: before processing transcript, compare word overlap with last 
JARVIS response. If overlap ratio > 0.45 and words > 4, discard as echo.

### Text-to-Speech

Primary: Kokoro ONNX (kokoro-v1.0.onnx + voices-v1.0.bin in project root)
- Voice: af_sarah
- Output device: Speakers (Realtek(R) Audio) — device index 3
- Runs entirely on CPU, leaves GPU for LLM

Secondary (if ElevenLabs API key present): ElevenLabs Turbo v2.5
- Voice ID: JBFqnCBsd6RMkjVDRZzb (British "George" voice)
- Falls back to Kokoro if ElevenLabs fails or quota hit

Fallback: Windows SAPI via pyttsx3

Natural speech chunking:
- Split on sentence boundaries, "sir", em dashes
- Pause durations: after "sir." = 0.6s, after sentence = 0.45s, 
  after em dash = 0.25s, after comma = 0.18s
- Synthesize and play chunk by chunk for lower perceived latency
- IS_SPEAKING flag set True during playback, False + 0.4s buffer after

---

## Three-Tier Memory System

### Tier 1: Immediate History
- Last 20 conversation turns in memory
- Passed as messages[] to every LLM call

### Tier 2: Session Summary  
- Rolling Haiku-generated summary of older messages
- Updated every 5 turns when history exceeds 20
- Appended to system prompt as context

### Tier 3: Persistent SQLite Memory

Tables:
```sql
memories (id, type, content, source, importance 1-10, created_at, 
          last_accessed, access_count)
-- types: 'fact', 'preference', 'project', 'person', 'decision', 'style'

tasks (id, title, description, priority, status, due_date, due_time, 
       project, tags, notes, created_at, completed_at)
-- priorities: 'critical', 'high', 'medium', 'low'

notes (id, title, content, topic, tags, created_at, updated_at)

style_profile (id, category, key, value, confidence, updated_at)
-- tracks: preferred_models, working_hours, tech_preferences, 
--         communication_style, rejected_suggestions

usage_log (id, ts, date, model, input_tokens, output_tokens, cost_aud, 
           task_type, duration_ms)

scheduled_tasks (id, name, cron_expression, last_run, next_run, 
                 enabled, task_type, task_config)

FTS5 virtual tables for memory_fts, task_fts, note_fts
```

Memory extraction: after every user message > 15 chars, async Haiku call 
extracts concrete facts (preferences, decisions, names, dates, plans). 
Store with appropriate type and importance score.

Build context for each query: retrieve top 5 relevant memories via FTS + 
semantic similarity, inject into system prompt.

---

## Tool Registry & Action System

### Action Tag System

JARVIS embeds structured action tags in responses, parsed server-side:
[ACTION:OPEN_APP] app_name
[ACTION:RUN_SHELL] command
[ACTION:ADD_TASK] priority ||| title ||| description ||| due_date
[ACTION:COMPLETE_TASK] task_id
[ACTION:ADD_NOTE] topic ||| content
[ACTION:REMEMBER] type ||| content ||| importance
[ACTION:RESEARCH] topic ||| depth (quick|deep) ||| sources_needed
[ACTION:STOCK_ANALYSIS] ticker ||| analysis_type
[ACTION:BROWSE] url_or_query
[ACTION:SEND_MESSAGE] platform ||| recipient ||| message
[ACTION:SMART_HOME] device ||| action ||| value
[ACTION:CREATE_SKILL] name ||| description ||| code
[ACTION:SCHEDULE] cron ||| task_name ||| task_config
[ACTION:BUDGET_UPDATE] category ||| amount ||| direction
[ACTION:HARDWARE_ADVICE] project_type ||| requirements
[ACTION:SCREEN_READ] region (full|top|bottom)
[ACTION:TELEGRAM] priority ||| message

Extract action tag from LLM response, return (clean_speech_text, action_dict).
Execute actions in background — never block voice response delivery.

### Fast Intent Detection (no LLM needed)

Detect these patterns with regex before routing to any model:
- "what time" / "what's the time" → system time
- "open [app]" → open_app tool
- "my tasks" / "todo" → list_tasks tool
- "what's on my screen" → read_screen tool
- "what do I have open" → list_open_windows tool
- "weather" → weather tool (wttr.in, no auth)
- "set a timer for X minutes" → timer tool
- "remind me" → reminder tool
- "what's my spending" / "api cost" → usage_stats tool

### Core Tools

All tools live in tools.py and expose OpenAI-compatible function definitions:

```python
# System control
list_open_windows()   # PowerShell Get-Process with MainWindowTitle
run_shell(command)    # subprocess, 15s timeout, 2000 char output cap
read_screen(region)   # mss screenshot + pytesseract OCR
open_app(app_name)    # subprocess start or PowerShell Start-Process
write_file(path, content)
read_file(path)

# Agent-created skills (hot-reload from data/skills/)
create_skill(name, description, code)  # validates with py_compile, registers

# Windows-specific
send_windows_notification(title, message)  # win10toast or Windows Runtime
get_clipboard()
set_clipboard(text)
```

### Text Tool Fallback Parser

The 7B local model writes tool calls as plain text instead of JSON. 
Implement parse_text_tool_calls() that extracts tool invocations via regex 
matching these patterns:
- tool_name("arg")
- tool_name('arg') 
- tool_name "arg"
- tool_name: arg

Intercept, execute, feed result back as user message for final answer.
Log: "[Agent] Intercepted N text-format tool call(s)"

---

## Feature Modules

### 1. News Briefings

File: src/integrations/news.py

- Aggregate from RSS feeds: ABC News AU, Reuters, BBC, ABC Finance, 
  custom user-defined feeds stored in settings
- Morning briefing: triggered by schedule or voice command
- Summarise top 5 stories in 3 sentences each using Sonnet
- Highlight anything relevant to user's known interests (tech, business, 
  local Bendigo news)
- Voice delivery with natural pacing
- Store briefings in SQLite with timestamp

### 2. Email Integration (Windows)

File: src/integrations/email_windows.py

Approach: IMAP/POP3 (works with Gmail, Outlook, any provider)
- Connect via imaplib with credentials from .env
- Fetch unread count, recent messages, unread messages
- Summarise email threads using Sonnet
- Search by sender/subject/date
- Read full message (truncate to 3000 chars)
- Reply drafting (draft only, never send without explicit confirmation)
- Store credentials encrypted in .env
- Format summaries for voice: "You have 3 unread, sir. One from [name] 
  about [subject]."

### 3. Stock Research & Investment Analysis

File: src/integrations/stocks.py + src/agents/stock_agent.py

Data sources (all free tiers):
- yfinance: price history, fundamentals, financial statements
- Alpha Vantage free tier: real-time quotes (requires free API key)
- RSS feeds: Reuters Markets, Yahoo Finance, Bloomberg RSS

StockAgent uses Opus for all analysis. For each analysis request:

Fundamental analysis:
- P/E ratio, P/B ratio, debt-to-equity, current ratio
- Revenue growth YoY, earnings growth YoY
- Free cash flow, profit margins
- Dividend yield and history

Technical analysis:
- 50/200 day moving averages, RSI, MACD
- Volume trends, support/resistance levels
- Recent price action narrative

Sentiment analysis:
- Recent news sentiment (last 7 days)
- Analyst consensus from available sources

Risk factors:
- Sector headwinds/tailwinds
- Company-specific risks
- Macroeconomic exposure (AUD/USD sensitivity for ASX stocks)

Output: structured voice summary + full report saved to notes
Always include: "This is research only, not financial advice, sir."
Support both ASX (append .AX) and US market tickers

Portfolio tracking:
- Store holdings in SQLite (ticker, units, avg_buy_price)
- Daily portfolio valuation on request
- Alert on > 5% single-day moves in held positions

### 4. Budgeting & Accounting

File: src/integrations/budget.py

Personal budgeting:
- Income and expense categories (customisable)
- Monthly budget targets per category
- Transaction logging via voice ("I spent $45 on fuel")
- Budget vs actual reporting
- Savings rate tracking
- Voice alerts when category is over budget

Business accounting module (Street Appeal Homes context):
- Job/invoice tracking (job number, client, amount, status)
- Expense categorisation for tax purposes
- P&L summary by period
- GST tracking (10% Australian GST)
- BAS-ready quarterly summary
- Export to CSV for accountant

Both store in SQLite. Sonnet handles natural language transaction parsing.
Opus handles year-end analysis and tax strategy questions.

### 5. Smart Home Integration

File: src/integrations/smart_home.py

Primary: Home Assistant integration
- Connect via HA REST API (http://homeassistant.local:8123/api/)
- API token stored in .env (HOMEASSISTANT_TOKEN)
- Discover and list all entities on first connection
- Control lights, switches, climate, locks, media players
- Run HA scripts and automations by name
- Query sensor states (temperature, humidity, motion, etc.)

Voice command examples:
- "Turn off the living room lights"
- "Set the thermostat to 22 degrees"
- "Is the front door locked?"
- "Run the goodnight routine"

If Home Assistant not configured, guide the user through setup:
- Explain what HA is and how to install it
- Provide exact config steps for their network
- Suggest compatible hardware (Zigbee dongle, smart plugs, etc.)

JARVIS can also advise on building custom smart home hardware — 
this routes to the hardware advisor module.

### 6. Bedside Clock & Hardware Advisor

File: src/hardware/bedside_clock.py

When user asks about the bedside clock project or any hardware:

Generate complete hardware specifications:
- Component list with exact part names and AliExpress/Core Electronics links
- Wiring diagram described in text (with ASCII art where helpful)
- Total cost estimate in AUD
- Difficulty rating and required tools

Bedside Clock default spec:
- Raspberry Pi Zero 2W (~$20 AUD)
- Small OLED or TFT display 2.8" (~$10 AUD)  
- MEMS microphone module (INMP441 I2S, ~$5 AUD)
- Small speaker + PAM8302 amplifier (~$8 AUD)
- USB-C power supply
- 3D-printable case (provide STL design description)

Software architecture for the clock:
- Runs lightweight Python client on Pi
- Connects to JARVIS server on main PC via WebSocket over local network
- Wake word detection runs locally on Pi (openwakeword, CPU-only)
- Audio streamed to JARVIS server for transcription and processing
- Response audio streamed back to Pi for playback
- Display shows: time, date, JARVIS status indicator, current task/reminder

Generate all firmware code for the Pi client:
- ws_client.py: WebSocket connection to main JARVIS server
- wake_word.py: openwakeword detection
- audio_stream.py: mic capture and speaker playback
- display.py: clock face and status display
- main.py: orchestrator

Also generate the server-side additions needed:
- WebSocket endpoint for remote clients (/ws/remote-device)
- Audio transcoding for Pi's compressed format
- Device registry (track connected clocks/devices)

JARVIS can design other hardware on request:
- Voice-activated desk lamp controller
- Presence detection for smart home
- Custom sensor nodes
- Anything the user describes

### 7. App Control & System Automation (Windows)

File: src/integrations/windows_control.py

Open applications:
```python
apps = {
    "chrome": "chrome.exe",
    "firefox": "firefox.exe", 
    "vscode": "code",
    "terminal": "wt.exe",  # Windows Terminal
    "explorer": "explorer.exe",
    "notepad": "notepad.exe",
    "spotify": "spotify.exe",
    "discord": "discord.exe",
    "steam": "steam.exe",
    "calculator": "calc.exe",
}
# Fall back to subprocess.Popen(["start", app_name], shell=True) for unknown apps
```

System actions:
- Volume control via pycaw
- Screen brightness via screen-brightness-control
- Lock workstation: subprocess ctypes.windll.user32.LockWorkStation()
- Sleep/shutdown with confirmation
- Take screenshot and save to Desktop
- Get/set clipboard content

Window management:
- List all open windows with titles (PowerShell Get-Process)
- Focus specific window by title (pywin32)
- Minimise/maximise/close window

### 8. Messaging & Notifications

File: src/integrations/messaging.py

Discord (primary notification and command channel):
- Use discord.py to run a lightweight Discord bot
- Bot token and channel ID stored in .env (DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID)
- JARVIS posts notifications to configured channel:
  🔴 critical alerts (spend alerts, errors, urgent reminders)
  🟠 medium priority (task completions, briefing delivery)
  🔵 low priority (background task results, portfolio updates)
- JARVIS listens for commands in the channel — any message starting with 
  "jarvis" or mentioning the bot is processed as a voice-equivalent command
- This enables controlling JARVIS from your phone via Discord
- Morning briefing delivered to Discord channel automatically
- Rich embeds for stock reports, budget summaries, research results
- ACTION tag: [ACTION:DISCORD] priority ||| message

Discord bot runs as a background asyncio task alongside FastAPI.
If DISCORD_BOT_TOKEN not set: skip silently, log that Discord is disabled.

Windows native notifications (secondary):
- win10toast or Windows Runtime notifications
- Used for reminders and alerts when JARVIS UI is not open

### 9. Research Agent

File: src/agents/researcher.py

Deep research using Sonnet (or Opus for financial topics):
- DuckDuckGo HTML search (no API key needed)
- Fetch and parse top N results via httpx + BeautifulSoup
- Synthesise across sources
- Save research report to notes with full citations
- Voice: brief summary, full report available on request

Research depth levels:
- quick: 3 sources, 200 word summary
- standard: 5 sources, 500 word summary  
- deep: 10 sources, full report with sections

### 10. Scheduler & Proactive Features

File: src/agents/scheduler.py

Background thread running scheduled tasks:
- Morning briefing: 7:30am (news + weather + tasks + calendar)
- Market open alert: 10am AEST on weekdays (portfolio check if holdings exist)
- Evening summary: 6pm (tasks completed, reminders for tomorrow)
- Custom user schedules stored in SQLite

Morning briefing sequence:
1. Weather for Bendigo, Victoria
2. Top 3 news stories
3. Today's tasks (by priority)
4. Any calendar events (if Google Calendar connected)
5. Portfolio check (if holdings configured)
6. One proactive suggestion based on context


### 10b. Vision & Media Module

File: src/integrations/vision.py

PDF Reading:
- Use PyMuPDF (fitz) to extract text from PDFs
- Voice command: "read this PDF" or "summarise [filename].pdf"
- Extract page by page, summarise with Sonnet if > 5 pages
- Store summary in notes with source filename
- ACTION tag: [ACTION:READ_PDF] filepath

Image Analysis:
- pytesseract for OCR on any image file or screenshot region
- Optional: pass image to Claude vision API (claude-sonnet-4-6 supports vision)
  for richer interpretation when pytesseract returns low-confidence text
- Voice commands: "read this", "what does this say", "what's in this image"
- ACTION tag: [ACTION:READ_IMAGE] filepath_or_clipboard

Camera Capture (optional, if webcam present):
- cv2 (OpenCV) to capture a still from default webcam
- Pipe directly to pytesseract or Claude vision
- Voice command: "look at this", "what am I holding"
- Gracefully skip if no camera detected — log warning, do not error

Screen Read enhancement:
- Existing ACTION:SCREEN_READ uses mss + pytesseract (keep this)
- Add a secondary path: if pytesseract confidence < 60%, pass screenshot 
  to Claude vision API for interpretation
- This catches stylised text, dark mode UIs, and image-heavy screens


### 10c. Media Download Tools

File: src/integrations/media_downloader.py

YouTube Download:
- Use yt-dlp (preferred over youtube-dl, actively maintained)
- Default: best quality MP4 to C:\Users\micha\Downloads\JARVIS\Video\
- Audio-only mode: best quality MP3 to C:\Users\micha\Downloads\JARVIS\Music\
- Voice commands: 
  "download this video" (uses clipboard URL if no URL spoken)
  "download audio from [URL]"
  "download [song name]" (searches YouTube, downloads top result)
- Progress reported via Windows notification, not voice (non-blocking)
- ACTION tag: [ACTION:DOWNLOAD_VIDEO] url ||| audio_only (true/false)

Instagram Download:
- Use instaloader for posts, reels, and stories
- Download to C:\Users\micha\Downloads\JARVIS\Instagram\
- Voice commands:
  "download this Instagram post" (from clipboard URL)
  "save this reel"
- Credentials optional — public content works without login
- ACTION tag: [ACTION:DOWNLOAD_INSTAGRAM] url

General download:
- Simple httpx-based file downloader for direct URLs (.mp3, .mp4, .pdf, .zip)
- Detects filetype from URL, routes to appropriate folder
- ACTION tag: [ACTION:DOWNLOAD_FILE] url ||| destination_folder (optional)


---

## Frontend — Particle Orb UI

Stack: Vite + TypeScript + Three.js
Served on http://localhost:5173 in development, static build for production

### index.html

Minimal: canvas fullscreen, controls top-right, status text bottom-center,
JARVIS label bottom-center smaller, error text top-center.

### style.css

Theme: near-black background #050508, cyan accent #0ea5e9
- Canvas: fixed, full viewport
- Status text: fixed bottom 40px, rgba(14,165,233,0.5), 13px uppercase, 
  2px letter-spacing
- JARVIS label: fixed bottom 16px, rgba(14,165,233,0.2), 10px, 4px spacing
- Controls: top-right, 36x36px buttons, cyan border rgba(14,165,233,0.15)
- Settings panel: 420px slide-in from right, glass-morphism, backdrop blur 24px
- Muted state: red tint
- Thinking state: slightly faster pulse animation on status text

### orb.ts — Three.js Particle Orb

2000 particles, WebGL renderer, antialias, clearColor #050508
Camera: PerspectiveCamera(45°, aspect, 1, 1000), z=80

Particle material: PointsMaterial, color #4ca8e8, size 0.4, 
AdditiveBlending, transparent, opacity 0.6, no depthWrite

Connection lines: LineSegments, 8000 max segments, same color, 
AdditiveBlending

Electron particles: 200 max, white #ffffff, size 0.8 (thinking state only)

State targets:
| State     | Radius | Speed | Brightness | Size | Lines | Electrons |
|-----------|--------|-------|-----------|------|-------|-----------|
| idle      | 28     | 0.2   | 0.5       | 0.35 | 0.15  | 0         |
| listening | 22     | 0.3   | 0.65      | 0.4  | 0.4   | 0         |
| thinking  | 16     | 0.5   | 0.7       | 0.3  | 1.0   | 0.015     |
| speaking  | 18     | 0.2   | 0.7       | 0.4  | 0.8   | 0         |
| working   | 14     | 0.6   | 0.75      | 0.28 | 1.0   | 0.02      |

All values lerp at 0.02/frame.

Audio analysis: AnalyserNode fftSize 256, bass bins 0-7, mid bins 8-23.
Bass pushes particles outward. Mid creates pulse in speaking state.

Particle physics:
- Sine/cosine noise motion influenced by position and time
- Central attraction pull toward target radius
- Drag: 0.992/frame
- Transition tumble on state change: energy=1.0, decay 0.985/frame

Connection lines: max distance 8*(1+bass*0.5), test every 4th particle.

Electrons (thinking only): max 3 alive, spawn every ~1s, travel along 
connection lines, remove at t>=1.

Color shifts (lerp 0.015/frame):
- thinking: #6ec4ff
- speaking: #5ab8f0  
- working: #7bc8ff
- default: #4ca8e8

Camera orbit: x=sin(t*0.02)*5, y=cos(t*0.03)*3

### voice.ts

Web Audio API for output, MediaRecorder for input (fallback to WebSocket 
audio streaming if Groq STT is active).

Audio queue: decode base64 → AudioBuffer → play sequentially.
Pause uses abort() not stop() — critical to prevent echo.
800ms delay on resuming after audio playback ends.

AnalyserNode connected to orb for audio-reactive visualization.

Autoplay unlock overlay: "CLICK TO ENABLE AUDIO" if AudioContext suspended.

### ws.ts

Auto-reconnecting WebSocket with exponential backoff (1s → 30s cap).
JSON parse all messages. Connection change events on state transitions only.

### settings.ts

Sliding panel from right with sections:
1. API Keys (Anthropic, Groq, ElevenLabs, Telegram, Alpha Vantage, HA token)
2. Voice Settings (wake word sensitivity, TTS voice, TTS speed)
3. Integrations Status (dots: green/red for each service)
4. Personal Profile (name, location for weather, working hours)
5. Email Config (IMAP server, username — password stored encrypted)
6. Portfolio Holdings (ticker, units, avg price — add/remove)
7. Budget Categories (income/expense categories and monthly targets)
8. Scheduled Tasks (enable/disable morning briefing, times)
9. Usage Stats (today/week/month spend per model tier)

First-time setup wizard (opens if no ANTHROPIC_API_KEY):
Step 1: Anthropic API key (required)
Step 2: Optional keys (Groq for fast STT, ElevenLabs for premium voice)
Step 3: Name and location
Step 4: Done — plays intro greeting

### WebSocket Protocol

Client → Server:
```json
{"type": "transcript", "text": "...", "isFinal": true}
{"type": "audio_data", "data": "<base64 wav>", "format": "wav"}
{"type": "ping"}
```

Server → Client:
```json
{"type": "audio", "data": "<base64 mp3>", "text": "spoken text", "state": "speaking"}
{"type": "status", "state": "idle|listening|thinking|speaking|working"}
{"type": "text", "text": "fallback text response"}
{"type": "action_queued", "action": "RESEARCH", "target": "..."}
{"type": "task_complete", "name": "...", "summary": "..."}
{"type": "cost_alert", "amount_aud": 2.10, "period": "today"}
{"type": "notification", "title": "...", "body": "...", "priority": "medium"}
{"type": "model_used", "tier": 1, "model": "haiku", "cost_aud": 0.001}
{"type": "error", "message": "..."}
```

State machine: idle → listening → thinking → speaking → idle
Working state: for background agent tasks that take > 3 seconds

---

## REST API Endpoints
GET  /api/health          → status, version, uptime
GET  /api/usage           → token usage and costs (today/week/month/all)
GET  /api/tasks           → all open tasks
POST /api/tasks           → create task
PUT  /api/tasks/{id}      → update task
DELETE /api/tasks/{id}    → delete/complete task
GET  /api/memories        → recent memories
GET  /api/notes           → recent notes
GET  /api/portfolio       → current holdings and valuations
GET  /api/budget          → current budget status
GET  /api/news            → latest briefing content
GET  /api/model-stats     → routing stats and costs per tier
GET  /api/settings/status → integration health check
POST /api/settings/keys   → save API key to .env
GET  /api/settings/prefs  → user preferences
POST /api/settings/prefs  → save user preferences
POST /api/restart         → restart server
GET  /api/devices         → connected remote devices (bedside clock, etc.)
WS   /ws/voice            → main voice WebSocket
WS   /ws/remote-device    → remote hardware client WebSocket

CORS: allow localhost:5173, localhost:8080, 127.0.0.1 variants.

---

## start.bat — Windows Launcher

```bat
@echo off
echo Starting JARVIS...
echo.

REM Start llama.cpp server in background (for local model routing)
start "JARVIS-LLM" /min cmd /c "C:\Users\micha\jarvis\start_llama.bat"
timeout /t 5 /nobreak > nul

REM Activate venv
call C:\Users\micha\jarvis\venv\Scripts\activate.bat

REM Start FastAPI backend
start "JARVIS-Backend" /min cmd /c "python C:\Users\micha\jarvis\src\server.py"
timeout /t 3 /nobreak > nul

REM Start frontend
start "JARVIS-Frontend" /min cmd /c "cd C:\Users\micha\jarvis\frontend && npm run dev"
timeout /t 4 /nobreak > nul

REM Open browser
start chrome http://localhost:5173

echo JARVIS is starting. Check the browser window.
```

---

## .env.example
Required
ANTHROPIC_API_KEY=your-key-here
Strongly recommended
GROQ_API_KEY=your-key-here          # free tier, fast STT
Optional voice
ELEVENLABS_API_KEY=your-key-here
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb
Notifications
Finance
ALPHA_VANTAGE_API_KEY=your-key-here  # free tier
Smart home
HOMEASSISTANT_TOKEN=your-long-lived-token
HOMEASSISTANT_URL=http://homeassistant.local:8123
Email
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_ADDRESS=your@email.com
EMAIL_PASSWORD=your-app-password     # use app password, not account password
User
USER_NAME=Michael
USER_LOCATION=Bendigo, Victoria, Australia
Cost management
DAILY_SPEND_ALERT_AUD=2.00
Local model (optional, if Ollama running)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
Llama.cpp fallback
LLAMA_SERVER_URL=http://localhost:8080
LOCAL_MODE=false   # set true to force offline, false for hybrid/cloud
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_CHANNEL_ID=your-channel-id

---

## Requirements.txt
Core
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
websockets>=13.0
python-dotenv>=1.0.0
httpx>=0.27.0
pydantic>=2.0.0
LLM
anthropic>=0.39.0
openai>=1.0.0          # for Ollama OpenAI-compatible endpoint
Voice
faster-whisper
pyaudio
openwakeword
sounddevice
soundfile
kokoro-onnx
numpy
Screen
mss
pytesseract
pillow
Memory
sentence-transformers
Data & Finance
yfinance
pandas
beautifulsoup4
feedparser
System
psutil
pywin32
pycaw
screen-brightness-control
win10toast
requests
Optional
groq
python-telegram-bot>=21.0
imaplib2
Dev
pytest
yt-dlp
instaloader
pymupdf
opencv-python
discord.py>=2.4.0

---

## Implementation Notes

1. Test every component as you build it. Run the server after each major 
   module is added. Fix errors before proceeding.

2. The model router is the most critical piece — build and test it first 
   before any feature modules.

3. For the particle orb: copy the Three.js implementation exactly as 
   specified. Every number in the physics and state tables matters.

4. Windows audio devices are hardcoded (mic=1, speakers=3) based on 
   Michael's current setup. Add a device auto-detection fallback that 
   scans available devices and picks the best match by name if these 
   indices fail.

5. All tool results must be capped at 2000 chars before passing to LLM 
   to prevent context overflow.

6. The skills directory (data/skills/) must be hot-reloaded every turn — 
   agent-created skills become available immediately in the next message.

7. For financial features: always append "This is research only, not 
   financial advice, sir." Voice version only, do not write it in 
   written reports.

8. Smart home: gracefully degrade if Home Assistant not configured. 
   Don't error — offer to help set it up.

9. Build the bedside clock firmware as a separate subfolder: 
   hardware/bedside-clock-firmware/ with its own README.md containing 
   the full parts list, wiring diagram, and setup instructions.

10. All scheduled tasks run in a background thread, never block the 
    voice loop.

11. On first run with no .env: open the settings panel automatically 
    and walk through the setup wizard before doing anything else.

12. Usage tracking must be accurate. Round AUD to 4 decimal places. 
    Display 0.0000 not 0 for sub-cent costs.

13. For the text tool call parser: log every interception so the user 
    can see when the local model is routing tool calls correctly vs 
    when API models are needed for structured output.