# JARVIS v2.0

A locally-hosted AI assistant with wake-word detection, voice I/O, and a live 3D orb interface. JARVIS routes each request to the cheapest model that can handle it — local llama.cpp → Claude Haiku → Claude Sonnet → Claude Opus — And keeps track of API spend amounts and warns you once you hit a certain amount. Jarvis can also read/write files, control Windows, search the web, fetch news, run stock analysis, control smart home devices, and edit its own source code.

---

## What it does

| Capability | Detail |
|---|---|
| **Wake word** | Say "Hey JARVIS" — detected locally via openWakeWord (no cloud) |
| **Voice input** | Transcribed by faster-whisper (local) or Groq Whisper API |
| **Voice output** | Kokoro ONNX (local, no API key) or ElevenLabs (optional upgrade) |
| **Text chat** | Persistent input bar in the UI — type long prompts, press Enter |
| **Model routing** | Tier 0: local llama.cpp → Tier 1: Haiku → Tier 2: Sonnet → Tier 3: Opus |
| **File access** | Read, write, list, and AI-edit any file on your PC |
| **Self-editing** | Tell JARVIS to edit its own source; it calls Claude Sonnet/Opus to do it |
| **News** | Fetches headlines from ABC, BBC, Reuters, Guardian via RSS |
| **Stocks** | Price, analysis, and portfolio summaries via yfinance |
| **Smart home** | Home Assistant integration for lights, switches, etc. |
| **Screen OCR** | Read visible text from screen via Tesseract |
| **System control** | Open apps, set volume, clipboard, notifications |
| **Memory** | Persistent notes, tasks, and fact extraction across sessions |
| **Research agent** | Deep web research with summarisation |
| **Skills** | Define reusable Python tools at runtime |
| **Discord** | Send/receive messages via a bot |
| **Budget** | Log and query spending categories |

### Orb states

| State | Colour | Meaning |
|---|---|---|
| Idle | Blue | Waiting for wake word |
| Listening | Bright blue | Recording your voice |
| Thinking | Green pulse | Claude is processing |
| Working | Orange pulse | Running a tool or long task |
| Speaking | Blue-white | Playing response audio |

---

## Prerequisites

### Required software

| Software | Minimum version | Notes |
|---|---|---|
| Python | 3.11+ | 3.12 recommended |
| Node.js | 18+ | For the Vite frontend |
| npm | 9+ | Comes with Node |
| Tesseract OCR | 5.x | Only needed for screen reading |

**Install Tesseract:** https://github.com/UB-Mannheim/tesseract/wiki  
Default install path expected: `C:\Program Files\Tesseract-OCR\tesseract.exe`

### Required files NOT in this repo

These are too large for GitHub and must be downloaded separately:

| File | Size | Purpose | Where to get it |
|---|---|---|---|
| `models/qwen2.5-7b-instruct.gguf` | ~4.4 GB | Local LLM (Tier 0) | [HuggingFace Qwen2.5-7B-GGUF](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF) [Q4 usually the best](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/blob/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf) but is hardware dependent |
| `kokoro-v1.0.onnx` | ~310 MB | Local TTS engine | [kokoro-v1.0.onnx](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx) |
| `voices-v1.0.bin` | ~28 MB | Kokoro voice data | [voices-v1.0.bin](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin) |
| `llama/` | ~200 MB | llama.cpp server binaries | [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases) |

Place all files at the paths shown, relative to the repo root. Ensure file and folder names match above

---

## Setup

### 1. Clone the repo

```
git clone https://github.com/Mickscanlon/Jarvis.git
cd Jarvis
```

### 2. Create the Python virtual environment

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

This installs FastAPI, the Anthropic SDK, faster-whisper, openWakeWord, Kokoro, sounddevice, yfinance, discord.py, and all other dependencies.

### 3. Install frontend dependencies

```
cd frontend
npm install
cd ..
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your keys:

```
copy .env.example .env
```

Open `.env` and set at minimum:

```
ANTHROPIC_API_KEY=sk-ant-...       # Required — all Claude calls go through here
```

Everything else is optional. See `.env.example` for the full list with comments. If not Anthropic api is set complex queries will likely fail or not return the desired result based on the local model run.

### 5. Set your audio device indices

Run this once in a Python shell to find your mic and speaker numbers:

```python
import sounddevice as sd
print(sd.query_devices())
```

Then update `.env`:

```
MIC_DEVICE=1          # index of your microphone
OUTPUT_DEVICE=3       # index of your speakers or headphones
```

---

## Running JARVIS

### One command

```
start.bat
```

This does everything in order:

1. Activates the Python virtual environment
2. Starts the llama.cpp local model server on port 8080 (optional — JARVIS falls back to Claude if it's not running)
3. Starts the FastAPI backend on port 8000
4. Starts the Vite dev server on port 5173
5. Opens Chrome at `http://localhost:5173`

Click the screen once when Chrome opens to enable audio, then say **"Hey JARVIS"**. You can also type into the chat bar at the bottom of the screen.

### Running components individually

**Backend only:**
```
venv\Scripts\activate
cd src
python server.py
```

**Frontend only (separate terminal):**
```
cd frontend
npm run dev
```

**Local LLM server only (optional):**
```
start_llama.bat
```

---

## Model routing

JARVIS automatically picks the cheapest model that can handle the request:

| Tier | Model | Used for |
|---|---|---|
| 0 | Local llama.cpp (Qwen 2.5 7B) | Simple queries, timers, app control |
| 1 | Claude Haiku | Tasks, reminders, quick lookups |
| 2 | Claude Sonnet | Research, news, email, code, analysis |
| 3 | Claude Opus | Financial analysis, deep reports, complex architecture |

If llama.cpp is not running, Tier 0 automatically falls through to Tier 1.

---

## Project structure

```
jarvis/
├── src/
│   ├── server.py          # FastAPI backend + WebSocket + voice pipeline
│   ├── llm.py             # Unified LLM client (llama.cpp / Ollama / Claude)
│   ├── router.py          # Smart model routing (Tier 0-3)
│   ├── tools.py           # Tool registry: files, shell, screen, news, etc.
│   ├── memory.py          # SQLite-backed notes, tasks, facts, usage log
│   ├── voice_input.py     # Wake word detection + STT
│   ├── voice_output.py    # Kokoro / ElevenLabs TTS
│   ├── skills_manager.py  # Dynamic skill loader
│   ├── agents/            # Research, stock, code, scheduler agents
│   └── integrations/      # News, email, stocks, smart home, Discord, etc.
├── frontend/
│   ├── src/
│   │   ├── main.ts        # App entry, WebSocket handling, UI state
│   │   ├── orb.ts         # Three.js particle orb with state-based colours
│   │   ├── voice.ts       # Browser audio capture + TTS playback
│   │   ├── ws.ts          # WebSocket client
│   │   └── settings.ts    # Settings panel
│   ├── index.html
│   └── style.css
├── hardware/
│   └── bedside-clock-firmware/   # Raspberry Pi remote mic client
├── skills/                # User-created skill scripts
├── data/                  # Usage logs, skill storage
├── requirements.txt
├── .env.example           # Copy this to .env and fill in your keys
└── start.bat              # One-click launcher
```

---

## Optional integrations

All optional. JARVIS works without any of them.

| Integration | Required env vars | What it enables |
|---|---|---|
| ElevenLabs TTS | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Higher-quality voice output |
| Groq Whisper STT | `GROQ_API_KEY` | Very accurate STT with minimal latency |
| Discord | `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` | Send/receive Discord messages |
| Home Assistant | `HOMEASSISTANT_URL`, `HOMEASSISTANT_TOKEN` | Control smart home devices |
| Email | `EMAIL_IMAP_SERVER`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD` | Read and summarise email |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | Enhanced stock data |
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Alternative local LLM backend |

---

## Bedside clock / remote mic

`hardware/bedside-clock-firmware/` contains a Python client for a Raspberry Pi (or similar) that connects to JARVIS over WebSocket and acts as a remote microphone and display — trigger JARVIS from another room without being near your PC.

```
cd hardware/bedside-clock-firmware
pip install -r requirements.txt
python main.py
```

Point it at your PC's IP on port 8000 via the `JARVIS_SERVER_URL` config variable.
