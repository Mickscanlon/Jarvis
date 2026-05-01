// notifications.ts — shared notification preference storage

export const NOTIF_KEY = 'jarvis_notif'

export interface NotifPrefs {
  enabled: boolean
  wakeWord: boolean
  modelUsed: boolean
  claudeCode: boolean
}

export function getNotifPrefs(): NotifPrefs {
  try {
    const s = JSON.parse(localStorage.getItem(NOTIF_KEY) || '{}')
    return {
      enabled:    s.enabled    !== false,
      wakeWord:   s.wakeWord   !== false,
      modelUsed:  s.modelUsed  !== false,
      claudeCode: s.claudeCode !== false,
    }
  } catch {
    return { enabled: true, wakeWord: true, modelUsed: true, claudeCode: true }
  }
}

export function saveNotifPrefs(prefs: NotifPrefs): void {
  localStorage.setItem(NOTIF_KEY, JSON.stringify(prefs))
}

export function formatModelName(model: string, tier: number): string {
  if (tier === 0) {
    if (model.includes('ollama') || model.includes('qwen') || model.includes('llama')) {
      return 'LOCAL · ' + model.split(':')[0].toUpperCase().substring(0, 12)
    }
    return 'LOCAL'
  }
  if (model.includes('haiku'))        return 'HAIKU 4.5'
  if (model.includes('sonnet'))       return 'SONNET 4.6'
  if (model.includes('opus-4-7'))     return 'OPUS 4.7'
  if (model.includes('opus'))         return 'OPUS 4.6'
  return model.toUpperCase().substring(0, 14)
}
