// orb.ts — Three.js audio-reactive sphere of dots
// Solid sphere of particles fixed on a Fibonacci lattice. Each particle has
// a rest position; audio amplitude pushes individual particles outward,
// producing spikes on the sphere surface during speech.
import * as THREE from 'three'

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'working'

interface StateTarget {
  radius: number          // base sphere radius
  brightness: number      // overall brightness multiplier
  size: number            // particle point size
  spikeAmount: number     // how much audio drives outward spikes
  breathingAmp: number    // subtle radial breathing amplitude
  rotationSpeed: number   // sphere rotation rate (rad/s)
}

const STATE_TARGETS: Record<OrbState, StateTarget> = {
  idle:      { radius: 16, brightness: 0.55, size: 0.55, spikeAmount: 0.0, breathingAmp: 0.3, rotationSpeed: 0.05 },
  listening: { radius: 16, brightness: 0.85, size: 0.62, spikeAmount: 0.0, breathingAmp: 0.5, rotationSpeed: 0.08 },
  thinking:  { radius: 15, brightness: 0.75, size: 0.52, spikeAmount: 0.0, breathingAmp: 0.7, rotationSpeed: 0.22 },
  speaking:  { radius: 16, brightness: 1.00, size: 0.65, spikeAmount: 4.0, breathingAmp: 0.2, rotationSpeed: 0.07 },
  working:   { radius: 15, brightness: 0.90, size: 0.55, spikeAmount: 0.0, breathingAmp: 0.8, rotationSpeed: 0.28 },
}

const COLOR_TARGETS: Record<OrbState, number[]> = {
  idle:      [0x4c / 255, 0xa8 / 255, 0xe8 / 255],
  listening: [0x6e / 255, 0xc4 / 255, 0xff / 255],
  thinking:  [0x22 / 255, 0xc5 / 255, 0x5e / 255],  // bright green (overridden by pulse)
  speaking:  [0x88 / 255, 0xd0 / 255, 0xff / 255],
  working:   [0x7b / 255, 0xc8 / 255, 0xff / 255],
}

// Thinking state pulses between these two greens
const THINKING_GREEN_BRIGHT = [0x22 / 255, 0xc5 / 255, 0x5e / 255]  // #22c55e
const THINKING_GREEN_DEEP   = [0x05 / 255, 0x46 / 255, 0x20 / 255]  // #054620

const NUM_PARTICLES = 1600
const LERP_RATE = 0.04
const COLOR_LERP = 0.03

// Build a soft round sprite once, reuse on every particle.
// Without this, THREE.PointsMaterial draws square dots.
function _makeCircleTexture(): THREE.Texture {
  const size = 64
  const c = document.createElement('canvas')
  c.width = c.height = size
  const ctx = c.getContext('2d')!
  const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  grad.addColorStop(0.00, 'rgba(255,255,255,1)')
  grad.addColorStop(0.45, 'rgba(255,255,255,0.85)')
  grad.addColorStop(0.85, 'rgba(255,255,255,0.10)')
  grad.addColorStop(1.00, 'rgba(255,255,255,0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, size, size)
  const tex = new THREE.CanvasTexture(c)
  tex.needsUpdate = true
  return tex
}

export class Orb {
  private renderer: THREE.WebGLRenderer
  private scene: THREE.Scene
  private camera: THREE.PerspectiveCamera
  private particles!: THREE.Points
  private positions!: Float32Array
  private restDirections!: Float32Array  // unit vectors — each particle's "home" direction on the sphere
  private spikeOffsets!: Float32Array    // current outward offset per particle
  private currentColor = new THREE.Color(0x4ca8e8)
  private currentState: OrbState = 'idle'
  private currentRadius = 16
  private currentBrightness = 0.55
  private currentSize = 0.55
  private currentSpikeAmount = 0.0
  private currentBreathing = 0.4
  private currentRotation = 0.05
  private rotationY = 0
  private clock = new THREE.Clock()
  private analyser: AnalyserNode | null = null
  private analyserData: Uint8Array<ArrayBuffer> | null = null

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    this.renderer.setClearColor(0x050508, 1)

    this.scene = new THREE.Scene()
    this.camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 1, 1000)
    this.camera.position.z = 70

    this._buildSphere()

    window.addEventListener('resize', () => this._onResize(canvas))
    this._onResize(canvas)
  }

  private _buildSphere() {
    const geo = new THREE.BufferGeometry()
    this.positions = new Float32Array(NUM_PARTICLES * 3)
    this.restDirections = new Float32Array(NUM_PARTICLES * 3)
    this.spikeOffsets = new Float32Array(NUM_PARTICLES)

    // Fibonacci sphere — gives a perfectly even point distribution on a sphere surface
    const golden = Math.PI * (3 - Math.sqrt(5))
    for (let i = 0; i < NUM_PARTICLES; i++) {
      const y = 1 - (i / (NUM_PARTICLES - 1)) * 2  // y goes from 1 to -1
      const radiusAtY = Math.sqrt(1 - y * y)
      const theta = golden * i
      const x = Math.cos(theta) * radiusAtY
      const z = Math.sin(theta) * radiusAtY

      this.restDirections[i * 3]     = x
      this.restDirections[i * 3 + 1] = y
      this.restDirections[i * 3 + 2] = z

      this.positions[i * 3]     = x * this.currentRadius
      this.positions[i * 3 + 1] = y * this.currentRadius
      this.positions[i * 3 + 2] = z * this.currentRadius
    }

    geo.setAttribute('position', new THREE.BufferAttribute(this.positions, 3))

    const mat = new THREE.PointsMaterial({
      color: this.currentColor,
      size: this.currentSize,
      map: _makeCircleTexture(),
      alphaTest: 0.05,
      blending: THREE.AdditiveBlending,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      sizeAttenuation: true,
    })

    this.particles = new THREE.Points(geo, mat)
    this.scene.add(this.particles)
  }

  connectAnalyser(analyser: AnalyserNode) {
    this.analyser = analyser
    this.analyserData = new Uint8Array(analyser.frequencyBinCount)
  }

  setState(state: OrbState) {
    this.currentState = state
  }

  private _lerp(a: number, b: number, t: number) { return a + (b - a) * t }

  private _lerpColor(a: THREE.Color, r: number, g: number, b: number, t: number) {
    a.r = this._lerp(a.r, r, t)
    a.g = this._lerp(a.g, g, t)
    a.b = this._lerp(a.b, b, t)
  }

  private _getAudioBins(): Uint8Array | null {
    if (!this.analyser || !this.analyserData) return null
    this.analyser.getByteFrequencyData(this.analyserData)
    return this.analyserData
  }

  update() {
    const t = this.clock.getElapsedTime()
    const dt = Math.min(this.clock.getDelta(), 0.1)
    const target = STATE_TARGETS[this.currentState]
    const colorTarget = COLOR_TARGETS[this.currentState]

    // Lerp state parameters smoothly
    this.currentRadius      = this._lerp(this.currentRadius,      target.radius,        LERP_RATE)
    this.currentBrightness  = this._lerp(this.currentBrightness,  target.brightness,    LERP_RATE)
    this.currentSize        = this._lerp(this.currentSize,        target.size,          LERP_RATE)
    this.currentSpikeAmount = this._lerp(this.currentSpikeAmount, target.spikeAmount,   LERP_RATE)
    this.currentBreathing   = this._lerp(this.currentBreathing,   target.breathingAmp,  LERP_RATE)
    this.currentRotation    = this._lerp(this.currentRotation,    target.rotationSpeed, LERP_RATE)

    if (this.currentState === 'thinking') {
      // Pulse between bright green and deep green
      const pulse = (Math.sin(t * 2.2) + 1) / 2
      const r = THINKING_GREEN_BRIGHT[0] * pulse + THINKING_GREEN_DEEP[0] * (1 - pulse)
      const g = THINKING_GREEN_BRIGHT[1] * pulse + THINKING_GREEN_DEEP[1] * (1 - pulse)
      const b = THINKING_GREEN_BRIGHT[2] * pulse + THINKING_GREEN_DEEP[2] * (1 - pulse)
      this._lerpColor(this.currentColor, r, g, b, COLOR_LERP * 4)
    } else {
      this._lerpColor(this.currentColor, colorTarget[0], colorTarget[1], colorTarget[2], COLOR_LERP)
    }

    // Subtle whole-sphere breathing — tiny radial pulse, always present
    const breathing = Math.sin(t * 1.4) * this.currentBreathing

    // Audio bins — used to drive outward spikes during speaking
    const bins = this._getAudioBins()
    const spikeAmount = this.currentSpikeAmount

    // Update each particle: position = restDirection * (radius + breathing + spike)
    for (let i = 0; i < NUM_PARTICLES; i++) {
      const ix = i * 3, iy = ix + 1, iz = ix + 2
      const dx = this.restDirections[ix]
      const dy = this.restDirections[iy]
      const dz = this.restDirections[iz]

      // Target outward offset for this particle
      let targetSpike = 0
      if (spikeAmount > 0.01 && bins) {
        // Map each particle to a frequency bin (uses x,y,z as a hash → spread evenly)
        const binIdx = Math.abs(((dx * 7.13 + dy * 13.71 + dz * 23.91) * 31) | 0) % bins.length
        const energy = bins[binIdx] / 255  // 0..1
        targetSpike = energy * spikeAmount
      }
      // Smoothly approach target spike (snappy attack, slow decay feels musical)
      const decay = targetSpike > this.spikeOffsets[i] ? 0.5 : 0.08
      this.spikeOffsets[i] = this._lerp(this.spikeOffsets[i], targetSpike, decay)

      const r = this.currentRadius + breathing + this.spikeOffsets[i]
      this.positions[ix] = dx * r
      this.positions[iy] = dy * r
      this.positions[iz] = dz * r
    }

    const pGeo = this.particles.geometry
    ;(pGeo.attributes.position as THREE.BufferAttribute).needsUpdate = true
    const pMat = this.particles.material as THREE.PointsMaterial
    pMat.color.copy(this.currentColor).multiplyScalar(this.currentBrightness)
    pMat.size = this.currentSize

    // Slow Y rotation
    this.rotationY += this.currentRotation * dt
    this.particles.rotation.y = this.rotationY

    // Camera held still — let the rotation come from the sphere itself
    this.camera.lookAt(this.scene.position)

    this.renderer.render(this.scene, this.camera)
  }

  private _onResize(canvas: HTMLCanvasElement) {
    const w = window.innerWidth, h = window.innerHeight
    canvas.width = w; canvas.height = h
    this.renderer.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }
}
