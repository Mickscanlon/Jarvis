// ws.ts - Auto-reconnecting WebSocket with exponential backoff

export type WSState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'working'

export interface WSMessage {
  type: string
  [key: string]: unknown
}

type MessageHandler = (msg: WSMessage) => void
type StateChangeHandler = (state: WSState) => void

const WS_URL = `ws://${location.hostname}:8000/ws/voice`

export class JarvisWS {
  private ws: WebSocket | null = null
  private retryDelay = 1000
  private maxDelay = 30000
  private _state: WSState = 'idle'
  private handlers: MessageHandler[] = []
  private stateHandlers: StateChangeHandler[] = []
  private _connected = false
  private pingInterval: number | null = null

  constructor() {
    this.connect()
  }

  private connect() {
    try {
      this.ws = new WebSocket(WS_URL)

      this.ws.onopen = () => {
        console.log('[WS] Connected')
        this._connected = true
        this.retryDelay = 1000
        this.startPing()
      }

      this.ws.onmessage = (evt) => {
        try {
          const msg: WSMessage = JSON.parse(evt.data)
          if (msg.type === 'status') {
            const newState = msg.state as WSState
            if (newState !== this._state) {
              this._state = newState
              this.stateHandlers.forEach(h => h(newState))
            }
          }
          this.handlers.forEach(h => h(msg))
        } catch { /* ignore parse errors */ }
      }

      this.ws.onclose = () => {
        this._connected = false
        this.stopPing()
        if (this._state !== 'idle') {
          this._state = 'idle'
          this.stateHandlers.forEach(h => h('idle'))
        }
        console.log(`[WS] Disconnected, retrying in ${this.retryDelay}ms`)
        setTimeout(() => this.connect(), this.retryDelay)
        this.retryDelay = Math.min(this.retryDelay * 2, this.maxDelay)
      }

      this.ws.onerror = (err) => {
        console.error('[WS] Error:', err)
      }
    } catch (e) {
      console.error('[WS] Failed to create WebSocket:', e)
      setTimeout(() => this.connect(), this.retryDelay)
      this.retryDelay = Math.min(this.retryDelay * 2, this.maxDelay)
    }
  }

  private startPing() {
    this.pingInterval = window.setInterval(() => {
      this.send({ type: 'ping' })
    }, 20000)
  }

  private stopPing() {
    if (this.pingInterval !== null) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  send(msg: WSMessage) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  sendTranscript(text: string, isFinal = true) {
    this.send({ type: 'transcript', text, isFinal })
  }

  sendAudio(base64: string, format = 'wav') {
    this.send({ type: 'audio_data', data: base64, format })
  }

  onMessage(handler: MessageHandler) {
    this.handlers.push(handler)
  }

  onStateChange(handler: StateChangeHandler) {
    this.stateHandlers.push(handler)
  }

  get state(): WSState { return this._state }
  get connected(): boolean { return this._connected }
}
