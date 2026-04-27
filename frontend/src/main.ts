// main.ts - JARVIS frontend entry point
import { Orb, type OrbState } from './orb'
import { VoiceManager, MicCapture } from './voice'
import { JarvisWS } from './ws'
import { SettingsPanel } from './settings'

// ── DOM elements ──────────────────────────────────────────────────────────────
const canvas      = document.getElementById('orb-canvas')     as HTMLCanvasElement
const statusEl    = document.getElementById('status-text')    as HTMLElement
const errorEl     = document.getElementById('error-text')     as HTMLElement
const responseEl  = document.getElementById('response-text')  as HTMLElement
const unlockEl    = document.getElementById('audio-unlock')   as HTMLElement
const inputBar    = document.getElementById('input-bar')      as HTMLElement
const textInput   = document.getElementById('text-input')     as HTMLInputElement
const btnSend     = document.getElementById('btn-send')       as HTMLButtonElement
const btnMic      = document.getElementById('btn-mic')        as HTMLButtonElement
const btnMute     = document.getElementById('btn-mute')       as HTMLButtonElement
const btnSettings = document.getElementById('btn-settings')   as HTMLButtonElement
const settingsPanelEl  = document.getElementById('settings-panel')  as HTMLElement
const settingsOverlay  = document.getElementById('settings-overlay') as HTMLElement

// ── App state ─────────────────────────────────────────────────────────────────
let orbState: OrbState = 'idle'
let micActive = false
let responseTimeout: ReturnType<typeof setTimeout> | null = null

// ── Init ──────────────────────────────────────────────────────────────────────
const orb = new Orb(canvas)
const voice = new VoiceManager()
const ws = new JarvisWS()
const mic = new MicCapture()
const settings = new SettingsPanel(settingsPanelEl, settingsOverlay)

// Animation loop
function animate() {
  requestAnimationFrame(animate)
  orb.update()
}
animate()

// ── Audio unlock ──────────────────────────────────────────────────────────────
async function unlock() {
  await voice.init().then(analyser => {
    if (analyser) orb.connectAnalyser(analyser)
  })
  await voice.unlock()
  unlockEl.classList.add('hidden')
  setTimeout(() => { unlockEl.style.display = 'none' }, 500)
}

unlockEl.addEventListener('click', unlock)
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    inputBar.classList.toggle('visible')
    if (inputBar.classList.contains('visible')) textInput.focus()
  }
})

// Auto-unlock attempt (may fail on some browsers without user gesture)
window.addEventListener('click', unlock, { once: true })
window.addEventListener('keydown', unlock, { once: true })

// ── State management ──────────────────────────────────────────────────────────
function setOrbState(state: OrbState) {
  orbState = state
  orb.setState(state)
  statusEl.className = `status-text ${state}`
  statusEl.textContent = state.toUpperCase()
}

function showResponse(text: string) {
  responseEl.textContent = text
  responseEl.classList.add('visible')
  if (responseTimeout) clearTimeout(responseTimeout)
  responseTimeout = setTimeout(() => {
    responseEl.classList.remove('visible')
  }, 8000)
}

function showError(msg: string, duration = 5000) {
  errorEl.textContent = msg
  setTimeout(() => { errorEl.textContent = '' }, duration)
}

// ── WebSocket events ──────────────────────────────────────────────────────────
ws.onStateChange((state) => setOrbState(state as OrbState))

ws.onMessage((msg) => {
  if (msg.type === 'audio' && msg.data) {
    voice.enqueueAudio(msg.data as string)
  }
  if (msg.type === 'text' && msg.text) {
    showResponse(msg.text as string)
  }
  if (msg.type === 'cost_alert') {
    showError(`Daily spend alert: $${msg.amount_aud} AUD`, 8000)
  }
  if (msg.type === 'error') {
    showError(msg.message as string || 'An error occurred')
  }
  if (msg.type === 'model_used') {
    const tier = msg.tier as number
    const model = msg.model as string
    const cost = msg.cost_aud as number
    console.log(`[Router] Tier ${tier} — ${model} — $${cost?.toFixed(6)} AUD`)
  }
})

voice.onStart = () => setOrbState('speaking')
voice.onEnd = () => setOrbState('idle')

// ── Text input ────────────────────────────────────────────────────────────────
function sendText() {
  const text = textInput.value.trim()
  if (!text) return
  textInput.value = ''
  ws.sendTranscript(text)
  showResponse(text)
  inputBar.classList.remove('visible')
}

btnSend.addEventListener('click', sendText)
textInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendText()
  if (e.key === 'Escape') inputBar.classList.remove('visible')
})

// ── Mic toggle ────────────────────────────────────────────────────────────────
btnMic.addEventListener('click', async () => {
  if (!micActive) {
    const ok = await mic.start((base64) => {
      ws.sendAudio(base64)
    })
    if (ok) {
      micActive = true
      btnMic.classList.add('active')
      // Press-to-talk: start recording
      mic.startRecording()
      setOrbState('listening')
    } else {
      showError('Microphone permission denied')
    }
  } else {
    mic.stopRecording()
    micActive = false
    btnMic.classList.remove('active')
    setOrbState('thinking')
  }
})

// ── Mute toggle ───────────────────────────────────────────────────────────────
btnMute.addEventListener('click', () => {
  const newMuted = !voice.isMuted
  voice.setMuted(newMuted)
  btnMute.classList.toggle('muted', newMuted)
  if (newMuted) {
    statusEl.classList.add('muted')
    setOrbState('idle')
  } else {
    statusEl.classList.remove('muted')
  }
})

// ── Settings ──────────────────────────────────────────────────────────────────
btnSettings.addEventListener('click', () => settings.toggle())

// ── Startup check ─────────────────────────────────────────────────────────────
async function checkFirstRun() {
  try {
    const status = await fetch('/api/settings/status').then(r => r.json())
    if (!status.anthropic_api && !status.llama_cpp && !status.ollama) {
      // No backends configured — open settings
      setTimeout(() => settings.open(), 1000)
      showError('No AI backend configured. Open settings to add an API key.', 10000)
    }
  } catch {
    showError('Backend not connected. Start server.py first.', 0)
  }
}

checkFirstRun()
