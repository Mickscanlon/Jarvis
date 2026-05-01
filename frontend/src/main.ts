// main.ts - JARVIS frontend entry point
import { Orb, type OrbState } from './orb'
import { VoiceManager, MicCapture } from './voice'
import { JarvisWS } from './ws'
import { SettingsPanel } from './settings'
import { getNotifPrefs, formatModelName } from './notifications'

// ── DOM elements ──────────────────────────────────────────────────────────────
const canvas         = document.getElementById('orb-canvas')      as HTMLCanvasElement
const statusEl       = document.getElementById('status-text')     as HTMLElement
const errorEl        = document.getElementById('error-text')      as HTMLElement
const responseEl     = document.getElementById('response-text')   as HTMLElement
const unlockEl       = document.getElementById('audio-unlock')    as HTMLElement
const textInput      = document.getElementById('text-input')      as HTMLInputElement
const btnSend        = document.getElementById('btn-send')        as HTMLButtonElement
const btnMic         = document.getElementById('btn-mic')         as HTMLButtonElement
const btnMute        = document.getElementById('btn-mute')        as HTMLButtonElement
const btnSettings    = document.getElementById('btn-settings')    as HTMLButtonElement
const settingsPanelEl   = document.getElementById('settings-panel')  as HTMLElement
const settingsOverlay   = document.getElementById('settings-overlay') as HTMLElement
// Notification panel elements
const notifWake      = document.getElementById('notif-wake')!
const notifModel     = document.getElementById('notif-model')!
const notifModelVal  = document.getElementById('notif-model-val')!
const notifCode      = document.getElementById('notif-code')!

// ── App state ─────────────────────────────────────────────────────────────────
let orbState: OrbState = 'idle'
let micActive = false
let responseTimeout: ReturnType<typeof setTimeout> | null = null
let modelHideTimer: ReturnType<typeof setTimeout> | null = null

// ── Init ──────────────────────────────────────────────────────────────────────
const orb      = new Orb(canvas)
const voice    = new VoiceManager()
const ws       = new JarvisWS()
const mic      = new MicCapture()
const settings = new SettingsPanel(settingsPanelEl, settingsOverlay)

function animate() { requestAnimationFrame(animate); orb.update() }
animate()

// ── Audio unlock ──────────────────────────────────────────────────────────────
async function unlock() {
  await voice.init().then(analyser => { if (analyser) orb.connectAnalyser(analyser) })
  await voice.unlock()
  unlockEl.classList.add('hidden')
  setTimeout(() => { unlockEl.style.display = 'none' }, 500)
}
unlockEl.addEventListener('click', unlock)
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') textInput.focus() })
window.addEventListener('click', unlock, { once: true })
window.addEventListener('keydown', unlock, { once: true })

// ── Notification panel ────────────────────────────────────────────────────────

function updateNotifWake(state: string) {
  const p = getNotifPrefs()
  notifWake.classList.toggle('visible', p.enabled && p.wakeWord && state === 'idle')
}

function showModelNotif(model: string, tier: number) {
  const p = getNotifPrefs()
  if (!p.enabled || !p.modelUsed) return
  notifModelVal.textContent = formatModelName(model, tier)
  notifModel.classList.add('visible')
  if (modelHideTimer) clearTimeout(modelHideTimer)
  modelHideTimer = setTimeout(() => notifModel.classList.remove('visible'), 10_000)
}

function showClaudeCodeNotif() {
  const p = getNotifPrefs()
  if (!p.enabled || !p.claudeCode) return
  notifCode.classList.add('visible')
}

function hideClaudeCodeNotif() {
  notifCode.classList.remove('visible')
}

// ── State management ──────────────────────────────────────────────────────────
function setOrbState(state: OrbState) {
  orbState = state
  orb.setState(state)
  statusEl.className = `status-text ${state}`
  statusEl.textContent = state.toUpperCase()
  updateNotifWake(state)
}

function showResponse(text: string) {
  responseEl.textContent = text
  responseEl.classList.add('visible')
  if (responseTimeout) clearTimeout(responseTimeout)
  responseTimeout = setTimeout(() => responseEl.classList.remove('visible'), 8000)
}

function showError(msg: string, duration = 5000) {
  errorEl.textContent = msg
  if (duration > 0) setTimeout(() => { errorEl.textContent = '' }, duration)
}

// ── WebSocket events ──────────────────────────────────────────────────────────
ws.onStateChange((state) => {
  setOrbState(state as OrbState)
  // Clear any persistent "backend not connected" error once WS is live
  if (errorEl.textContent === 'Backend not connected. Start server.py first.') {
    errorEl.textContent = ''
  }
})

ws.onMessage((msg) => {
  if (msg.type === 'audio' && msg.data)
    voice.enqueueAudio(msg.data as string)

  if (msg.type === 'text' && msg.text)
    showResponse(msg.text as string)

  if (msg.type === 'cost_alert')
    showError(`Daily spend alert: $${msg.amount_aud} AUD`, 8000)

  if (msg.type === 'error')
    showError(msg.message as string || 'An error occurred')

  if (msg.type === 'model_used')
    showModelNotif(msg.model as string, msg.tier as number)

  if (msg.type === 'claude_code_start')
    showClaudeCodeNotif()

  if (msg.type === 'claude_code_done')
    hideClaudeCodeNotif()
})

voice.onStart = () => setOrbState('speaking')
voice.onEnd   = () => setOrbState((ws.state as OrbState) === 'working' ? 'working' : 'idle')

// ── Text input ────────────────────────────────────────────────────────────────
function sendText() {
  const text = textInput.value.trim()
  if (!text) return
  textInput.value = ''
  ws.sendTranscript(text)
  showResponse(text)
}
btnSend.addEventListener('click', sendText)
textInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendText() })

// ── Mic toggle ────────────────────────────────────────────────────────────────
btnMic.addEventListener('click', async () => {
  if (!micActive) {
    const ok = await mic.start((base64) => ws.sendAudio(base64))
    if (ok) {
      micActive = true
      btnMic.classList.add('active')
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
  statusEl.classList.toggle('muted', newMuted)
  if (newMuted) setOrbState('idle')
})

// ── Settings ──────────────────────────────────────────────────────────────────
btnSettings.addEventListener('click', () => settings.toggle())

// ── Startup check ─────────────────────────────────────────────────────────────
async function checkFirstRun() {
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const status = await fetch('/api/settings/status').then(r => r.json())
      errorEl.textContent = ''
      if (!status.anthropic_api && !status.llama_cpp && !status.ollama) {
        setTimeout(() => settings.open(), 1000)
        showError('No AI backend configured. Open settings to add an API key.', 10000)
      }
      return
    } catch {
      if (attempt < 4) {
        await new Promise<void>(r => setTimeout(r, 2000))
      } else {
        showError('Backend not connected. Start server.py first.', 0)
      }
    }
  }
}
checkFirstRun()
