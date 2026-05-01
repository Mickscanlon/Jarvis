// settings.ts - Settings panel: API keys, voice, integrations, portfolio, budget, usage
import { getNotifPrefs, saveNotifPrefs, type NotifPrefs, NOTIF_KEY } from './notifications'

interface IntegrationStatus {
  anthropic_api: boolean
  groq: boolean
  elevenlabs: boolean
  home_assistant: boolean
  email: boolean
  alpha_vantage: boolean
  discord: boolean
  ollama: boolean
  llama_cpp: boolean
}

interface UsageStats {
  today: { cost_aud: number; input_tokens: number; output_tokens: number }
  week: { cost_aud: number }
  month: { cost_aud: number }
  all_time: { cost_aud: number }
}

export class SettingsPanel {
  private panel: HTMLElement
  private overlay: HTMLElement
  private _open = false

  constructor(panelEl: HTMLElement, overlayEl: HTMLElement) {
    this.panel = panelEl
    this.overlay = overlayEl
    this._render()
    this._bindClose()
  }

  toggle() {
    this._open ? this.close() : this.open()
  }

  open() {
    this._open = true
    this.panel.classList.add('open')
    this.overlay.classList.add('visible')
    this._loadLiveData()
  }

  close() {
    this._open = false
    this.panel.classList.remove('open')
    this.overlay.classList.remove('visible')
  }

  private _bindClose() {
    this.overlay.addEventListener('click', () => this.close())
  }

  private _render() {
    this.panel.innerHTML = `
      <button class="settings-close" id="settings-close-btn">✕</button>
      <h1>SETTINGS</h1>

      <h2>Notifications</h2>
      <div class="settings-section">
        ${this._notifToggle('enabled',    'All Notifications',  'Master switch for the left-side status panel')}
        ${this._notifToggle('wakeWord',   'Wake Word Reminder', "Shows 'Hey JARVIS' prompt when idle")}
        ${this._notifToggle('modelUsed',  'Model Used',         'Shows which model was used for each request')}
        ${this._notifToggle('claudeCode', 'Claude Code Active', 'Shows indicator when Claude Code is running')}
      </div>

      <h2>Model Routing</h2>
      <div class="settings-section">
        ${this._toggleRow('USE_ANTHROPIC', 'Anthropic API', 'Cloud Claude (Haiku/Sonnet/Opus). OFF = local llama.cpp only.')}
        ${this._toggleRow('USE_GROQ', 'Groq STT', 'Cloud Whisper (fast). OFF = local faster-whisper.')}
        ${this._toggleRow('USE_ELEVENLABS', 'ElevenLabs TTS', 'Cloud premium voice. OFF = local Kokoro.')}
      </div>

      <h2>API Keys</h2>
      <div class="settings-section">
        ${this._keyField('ANTHROPIC_API_KEY', 'Anthropic API Key', 'sk-ant-...')}
        ${this._keyField('GROQ_API_KEY', 'Groq API Key (fast STT)', 'gsk_...')}
        ${this._keyField('ELEVENLABS_API_KEY', 'ElevenLabs API Key', 'optional')}
        ${this._keyField('ALPHA_VANTAGE_API_KEY', 'Alpha Vantage (stocks)', 'optional')}
        ${this._keyField('HOMEASSISTANT_TOKEN', 'Home Assistant Token', 'optional')}
        ${this._keyField('DISCORD_BOT_TOKEN', 'Discord Bot Token', 'optional')}
        ${this._keyField('DISCORD_CHANNEL_ID', 'Discord Channel ID', 'optional')}
        <button class="settings-btn" id="save-keys-btn">Save Keys</button>
      </div>

      <h2>Voice</h2>
      <div class="settings-section">
        ${this._selectField('tts_voice', 'TTS Voice', [
          { value: 'af_sarah', label: 'Sarah (default)' },
          { value: 'af_bella', label: 'Bella' },
          { value: 'am_adam', label: 'Adam (male)' },
        ])}
        ${this._inputField('TTS_SPEED', 'TTS Speed', '1.0', '0.5–2.0')}
        ${this._inputField('WAKE_WORD', 'Wake Word', 'hey jarvis')}
        <button class="settings-btn" id="save-voice-btn">Save Voice Settings</button>
      </div>

      <h2>User Profile</h2>
      <div class="settings-section">
        ${this._inputField('USER_NAME', 'Name', 'Michael')}
        ${this._inputField('USER_LOCATION', 'Location', 'Bendigo, Victoria, Australia')}
        ${this._inputField('DAILY_SPEND_ALERT_AUD', 'Daily Spend Alert (AUD)', '2.00')}
        <button class="settings-btn" id="save-prefs-btn">Save Profile</button>
      </div>

      <h2>Email</h2>
      <div class="settings-section">
        ${this._inputField('EMAIL_IMAP_SERVER', 'IMAP Server', 'imap.gmail.com')}
        ${this._inputField('EMAIL_ADDRESS', 'Email Address', 'your@email.com')}
        ${this._keyField('EMAIL_PASSWORD', 'App Password', 'use app password not account password')}
        <button class="settings-btn" id="save-email-btn">Save Email Config</button>
      </div>

      <h2>Integration Status</h2>
      <div class="settings-section" id="integration-status">
        <div style="color:rgba(14,165,233,0.4);font-size:12px">Loading...</div>
      </div>

      <h2>Usage Stats</h2>
      <div class="settings-section" id="usage-stats">
        <div style="color:rgba(14,165,233,0.4);font-size:12px">Loading...</div>
      </div>

      <h2>Local Mode</h2>
      <div class="settings-section">
        ${this._selectField('LOCAL_MODE', 'Mode', [
          { value: 'false', label: 'Hybrid (API + Local)' },
          { value: 'true', label: 'Local Only (offline)' },
        ])}
        <button class="settings-btn" id="save-mode-btn">Save Mode</button>
      </div>

      <div style="margin-top:24px;padding-top:16px;border-top:1px solid rgba(14,165,233,0.1);font-size:10px;color:rgba(14,165,233,0.25);letter-spacing:2px;text-align:center;">
        JARVIS v2.0 — Click outside to close
      </div>
    `

    // Bind close button
    this.panel.querySelector('#settings-close-btn')?.addEventListener('click', () => this.close())

    // Bind save buttons
    this.panel.querySelector('#save-keys-btn')?.addEventListener('click', () => this._saveKeys())
    this.panel.querySelector('#save-voice-btn')?.addEventListener('click', () => this._saveVoice())
    this.panel.querySelector('#save-prefs-btn')?.addEventListener('click', () => this._savePrefs())
    this.panel.querySelector('#save-email-btn')?.addEventListener('click', () => this._saveEmail())
    this.panel.querySelector('#save-mode-btn')?.addEventListener('click', () => this._saveMode())

    // Bind toggles — flip on click and save immediately
    this.panel.querySelectorAll<HTMLDivElement>('.toggle').forEach(el => {
      el.addEventListener('click', () => this._handleToggleClick(el))
    })

    this.panel.querySelectorAll<HTMLDivElement>('.notif-toggle').forEach(el => {
      el.addEventListener('click', () => this._handleNotifToggle(el))
    })
  }

  private _toggleRow(envKey: string, name: string, hint: string): string {
    return `
      <div class="toggle-row">
        <div class="toggle-label">
          <span class="toggle-name">${name}</span>
          <span class="toggle-hint">${hint}</span>
        </div>
        <div class="toggle" id="toggle_${envKey}" data-key="${envKey}"></div>
      </div>
    `
  }

  private async _handleToggleClick(el: HTMLDivElement) {
    const key = el.dataset.key
    if (!key) return
    const newOn = !el.classList.contains('on')
    el.classList.toggle('on', newOn)

    // USE_ANTHROPIC isn't a real env var on the backend — it maps to LOCAL_MODE inverted
    if (key === 'USE_ANTHROPIC') {
      await this._postKey('LOCAL_MODE', newOn ? 'false' : 'true')
    } else {
      await this._postKey(key, newOn ? 'true' : 'false')
    }
  }

  private _notifToggle(key: keyof NotifPrefs, name: string, hint: string): string {
    const prefs = getNotifPrefs()
    const isOn = prefs[key]
    return `
      <div class="toggle-row">
        <div class="toggle-label">
          <span class="toggle-name">${name}</span>
          <span class="toggle-hint">${hint}</span>
        </div>
        <div class="toggle notif-toggle ${isOn ? 'on' : ''}" id="ntog_${key}" data-notif-key="${key}"></div>
      </div>
    `
  }

  private _handleNotifToggle(el: HTMLDivElement) {
    const key = el.dataset.notifKey as keyof NotifPrefs
    if (!key) return
    const newOn = !el.classList.contains('on')
    el.classList.toggle('on', newOn)
    const prefs = getNotifPrefs()
    ;(prefs as any)[key] = newOn
    saveNotifPrefs(prefs)
  }

  private async _postKey(key: string, value: string) {
    try {
      await fetch('/api/settings/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      })
    } catch { /* server may be offline */ }
  }

  private _keyField(key: string, label: string, placeholder: string): string {
    return `
      <div class="settings-row">
        <label>${label}</label>
        <input type="password" id="key_${key}" placeholder="${placeholder}" autocomplete="off" />
      </div>
    `
  }

  private _inputField(key: string, label: string, placeholder: string, hint = ''): string {
    return `
      <div class="settings-row">
        <label>${label}${hint ? ` <span style="opacity:0.5">(${hint})</span>` : ''}</label>
        <input type="text" id="pref_${key}" placeholder="${placeholder}" autocomplete="off" />
      </div>
    `
  }

  private _selectField(key: string, label: string, options: { value: string; label: string }[]): string {
    const opts = options.map(o => `<option value="${o.value}">${o.label}</option>`).join('')
    return `
      <div class="settings-row">
        <label>${label}</label>
        <select id="pref_${key}">${opts}</select>
      </div>
    `
  }

  private _val(id: string): string {
    return (this.panel.querySelector(`#${id}`) as HTMLInputElement)?.value?.trim() || ''
  }

  private async _saveKey(key: string) {
    const value = this._val(`key_${key}`)
    if (!value) return
    try {
      await fetch('/api/settings/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      })
    } catch { /* offline */ }
  }

  private async _saveKeys() {
    const keys = ['ANTHROPIC_API_KEY', 'GROQ_API_KEY', 'ELEVENLABS_API_KEY',
                  'ALPHA_VANTAGE_API_KEY', 'HOMEASSISTANT_TOKEN',
                  'DISCORD_BOT_TOKEN', 'DISCORD_CHANNEL_ID']
    await Promise.all(keys.map(k => this._saveKey(k)))
    this._flash('#save-keys-btn', 'Saved ✓')
  }

  private async _saveVoice() {
    const keys = ['TTS_SPEED', 'WAKE_WORD']
    for (const k of keys) {
      const v = this._val(`pref_${k}`)
      if (v) await fetch('/api/settings/keys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: k, value: v }),
      }).catch(() => {})
    }
    this._flash('#save-voice-btn', 'Saved ✓')
  }

  private async _savePrefs() {
    const keys = ['USER_NAME', 'USER_LOCATION', 'DAILY_SPEND_ALERT_AUD']
    for (const k of keys) {
      const v = this._val(`pref_${k}`)
      if (v) await fetch('/api/settings/keys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: k, value: v }),
      }).catch(() => {})
    }
    this._flash('#save-prefs-btn', 'Saved ✓')
  }

  private async _saveEmail() {
    const keys = ['EMAIL_IMAP_SERVER', 'EMAIL_ADDRESS', 'EMAIL_PASSWORD']
    for (const k of keys) {
      const v = this._val(`key_${k}`) || this._val(`pref_${k}`)
      if (v) await fetch('/api/settings/keys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: k, value: v }),
      }).catch(() => {})
    }
    this._flash('#save-email-btn', 'Saved ✓')
  }

  private async _saveMode() {
    const v = this._val('pref_LOCAL_MODE')
    if (v) {
      await fetch('/api/settings/keys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'LOCAL_MODE', value: v }),
      }).catch(() => {})
    }
    this._flash('#save-mode-btn', 'Saved ✓')
  }

  private _flash(selector: string, text: string) {
    const btn = this.panel.querySelector(selector) as HTMLButtonElement
    if (!btn) return
    const orig = btn.textContent || ''
    btn.textContent = text
    setTimeout(() => { btn.textContent = orig }, 2000)
  }

  private async _loadLiveData() {
    try {
      const [status, usage, prefs] = await Promise.all([
        fetch('/api/settings/status').then(r => r.json()),
        fetch('/api/usage').then(r => r.json()),
        fetch('/api/settings/prefs').then(r => r.json()),
      ])
      this._renderIntegrationStatus(status as IntegrationStatus)
      this._renderUsageStats(usage as UsageStats)
      this._applyPrefs(prefs)
    } catch { /* server may not be available */ }
  }

  private _applyPrefs(p: any) {
    // Toggles
    const set = (id: string, on: boolean) => {
      const el = this.panel.querySelector(`#toggle_${id}`)
      if (el) el.classList.toggle('on', on)
    }
    set('USE_ANTHROPIC', p.local_mode !== 'true')
    set('USE_GROQ', !!p.use_groq)
    set('USE_ELEVENLABS', !!p.use_elevenlabs)

    // Text/select fields
    const setVal = (id: string, val: any) => {
      const el = this.panel.querySelector(`#${id}`) as HTMLInputElement | HTMLSelectElement | null
      if (el && val != null) el.value = String(val)
    }
    setVal('pref_TTS_SPEED', p.tts_speed)
    setVal('pref_WAKE_WORD', p.wake_word)
    setVal('pref_USER_NAME', p.user_name)
    setVal('pref_USER_LOCATION', p.user_location)
    setVal('pref_DAILY_SPEND_ALERT_AUD', p.daily_spend_alert)
    setVal('pref_LOCAL_MODE', p.local_mode)
  }

  private _renderIntegrationStatus(status: IntegrationStatus) {
    const el = this.panel.querySelector('#integration-status')
    if (!el) return
    const rows = [
      ['Claude API', status.anthropic_api],
      ['Groq STT', status.groq],
      ['ElevenLabs TTS', status.elevenlabs],
      ['Home Assistant', status.home_assistant],
      ['Email', status.email],
      ['Alpha Vantage', status.alpha_vantage],
      ['Discord', status.discord],
      ['Ollama (local)', status.ollama],
      ['llama.cpp', status.llama_cpp],
    ] as [string, boolean][]

    el.innerHTML = rows.map(([name, ok]) => `
      <div class="integration-row">
        <span class="status-dot ${ok ? 'green' : ''}"></span>
        ${name}
      </div>
    `).join('')
  }

  private _renderUsageStats(stats: UsageStats) {
    const el = this.panel.querySelector('#usage-stats')
    if (!el) return
    el.innerHTML = `
      <div class="usage-grid">
        <div class="usage-card">
          <div class="period">TODAY</div>
          <div class="amount">$${stats.today?.cost_aud?.toFixed(4) ?? '0.0000'}</div>
        </div>
        <div class="usage-card">
          <div class="period">THIS WEEK</div>
          <div class="amount">$${stats.week?.cost_aud?.toFixed(4) ?? '0.0000'}</div>
        </div>
        <div class="usage-card">
          <div class="period">THIS MONTH</div>
          <div class="amount">$${stats.month?.cost_aud?.toFixed(4) ?? '0.0000'}</div>
        </div>
        <div class="usage-card">
          <div class="period">ALL TIME</div>
          <div class="amount">$${stats.all_time?.cost_aud?.toFixed(4) ?? '0.0000'}</div>
        </div>
      </div>
      <div style="margin-top:8px;font-size:11px;color:rgba(14,165,233,0.4)">
        Today tokens: ${(stats.today?.input_tokens ?? 0).toLocaleString()} in / ${(stats.today?.output_tokens ?? 0).toLocaleString()} out
      </div>
    `
  }
}
