// voice.ts - Web Audio API for TTS playback + microphone capture
export class VoiceManager {
  private ctx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private queue: ArrayBuffer[] = []
  private playing = false
  private muted = false
  private currentSource: AudioBufferSourceNode | null = null
  private onAnalyserReady?: (analyser: AnalyserNode) => void
  private onPlaybackEnd?: () => void
  private onPlaybackStart?: () => void

  async init(): Promise<AnalyserNode | null> {
    try {
      this.ctx = new AudioContext()
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 256
      this.analyser.connect(this.ctx.destination)
      if (this.ctx.state === 'suspended') {
        await this.ctx.resume()
      }
      return this.analyser
    } catch (e) {
      console.error('[Voice] AudioContext error:', e)
      return null
    }
  }

  async unlock(): Promise<void> {
    if (this.ctx?.state === 'suspended') {
      await this.ctx.resume()
    }
  }

  enqueueAudio(base64: string): void {
    const binary = atob(base64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    this.queue.push(bytes.buffer)
    if (!this.playing) this._playNext()
  }

  private async _playNext(): Promise<void> {
    if (this.muted || this.queue.length === 0) {
      this.playing = false
      return
    }

    this.playing = true
    const buffer = this.queue.shift()!

    try {
      const audioBuffer = await this.ctx!.decodeAudioData(buffer)
      const source = this.ctx!.createBufferSource()
      source.buffer = audioBuffer

      if (this.analyser) {
        source.connect(this.analyser)
      } else {
        source.connect(this.ctx!.destination)
      }

      this.currentSource = source
      this.onPlaybackStart?.()

      source.onended = () => {
        this.currentSource = null
        // 800ms delay before resuming listening
        setTimeout(() => {
          if (this.queue.length > 0) {
            this._playNext()
          } else {
            this.playing = false
            this.onPlaybackEnd?.()
          }
        }, 800)
      }

      source.start()
    } catch (e) {
      console.error('[Voice] Playback error:', e)
      this.playing = false
      if (this.queue.length > 0) this._playNext()
    }
  }

  stopPlayback(): void {
    this.queue.length = 0
    if (this.currentSource) {
      try { this.currentSource.stop() } catch { /* may already be stopped */ }
      this.currentSource = null
    }
    this.playing = false
  }

  setMuted(muted: boolean): void {
    this.muted = muted
    if (muted) this.stopPlayback()
  }

  get isMuted(): boolean { return this.muted }
  get isPlaying(): boolean { return this.playing }

  set onAnalyser(fn: (a: AnalyserNode) => void) { this.onAnalyserReady = fn }
  set onEnd(fn: () => void) { this.onPlaybackEnd = fn }
  set onStart(fn: () => void) { this.onPlaybackStart = fn }
}

// ── Microphone capture ────────────────────────────────────────────────────────

export class MicCapture {
  private mediaRecorder: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: BlobPart[] = []
  private active = false
  private onAudioChunk?: (base64: string) => void

  async start(onChunk: (base64: string) => void): Promise<boolean> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      this.onAudioChunk = onChunk
      this.mediaRecorder = new MediaRecorder(this.stream, { mimeType: 'audio/webm' })

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.chunks.push(e.data)
      }

      this.mediaRecorder.onstop = async () => {
        const blob = new Blob(this.chunks, { type: 'audio/webm' })
        this.chunks = []
        const buf = await blob.arrayBuffer()
        const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)))
        this.onAudioChunk?.(b64)
      }

      this.active = true
      return true
    } catch (e) {
      console.error('[Mic] Permission denied or error:', e)
      return false
    }
  }

  startRecording(): void {
    if (!this.mediaRecorder || this.mediaRecorder.state === 'recording') return
    this.chunks = []
    this.mediaRecorder.start()
  }

  stopRecording(): void {
    if (this.mediaRecorder?.state === 'recording') {
      this.mediaRecorder.stop()
    }
  }

  stop(): void {
    this.stopRecording()
    this.stream?.getTracks().forEach(t => t.stop())
    this.active = false
  }

  get isActive(): boolean { return this.active }
}
