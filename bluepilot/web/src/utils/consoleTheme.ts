// Custom: Console theme accent for the portal, following the device's BPConsoleAccent param.
import { paramsAPI } from '@/services/api'

const ACCENTS = ['blue', 'teal', 'violet', 'ember'] as const
type Accent = (typeof ACCENTS)[number]
const STORAGE_KEY = 'console-accent'

export function applyConsoleAccent(accent: string | null | undefined): Accent {
  const name = (String(accent ?? 'blue').trim().toLowerCase() as Accent)
  const value: Accent = ACCENTS.includes(name) ? name : 'blue'
  if (value === 'blue') {
    delete document.documentElement.dataset.theme
  } else {
    document.documentElement.dataset.theme = value
  }
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // storage can be unavailable (private mode); the device param is the source of truth
  }
  return value
}

/** Apply the last known accent immediately, then refresh it from the device. */
export async function initConsoleAccent(): Promise<void> {
  try {
    applyConsoleAccent(localStorage.getItem(STORAGE_KEY))
  } catch {
    applyConsoleAccent('blue')
  }
  try {
    const params = await paramsAPI.getAll()
    const p = params?.BPConsoleAccent
    if (p) applyConsoleAccent(String(p.value ?? 'blue'))
  } catch {
    // device offline or param unknown on this build: keep the cached accent
  }
}
