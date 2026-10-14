// Custom: Console theme for the portal, following the device's BPConsoleAccent and BPConsoleMode params.
import { paramsAPI } from '@/services/api'

const ACCENTS = ['blue', 'teal', 'violet', 'ember'] as const
type Accent = (typeof ACCENTS)[number]
const MODES = ['auto', 'day', 'night'] as const
type Mode = (typeof MODES)[number]
const STORAGE_KEY = 'console-accent'
const MODE_KEY = 'console-mode'

let currentMode: Mode = 'auto'
const lightQuery = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // storage can be unavailable (private mode); the device param is the source of truth
  }
}

function load(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function applyConsoleAccent(accent: string | null | undefined): Accent {
  const name = (String(accent ?? 'blue').trim().toLowerCase() as Accent)
  const value: Accent = ACCENTS.includes(name) ? name : 'blue'
  if (value === 'blue') {
    delete document.documentElement.dataset.theme
  } else {
    document.documentElement.dataset.theme = value
  }
  store(STORAGE_KEY, value)
  return value
}

function resolveMode() {
  // Auto on the portal follows the phone or laptop viewing it; the truck screen uses its own light level
  const light = currentMode === 'day' || (currentMode === 'auto' && !!lightQuery?.matches)
  document.documentElement.dataset.mode = light ? 'light' : 'dark'
}

export function applyConsoleMode(mode: string | null | undefined): Mode {
  const name = (String(mode ?? 'auto').trim().toLowerCase() as Mode)
  currentMode = MODES.includes(name) ? name : 'auto'
  resolveMode()
  store(MODE_KEY, currentMode)
  return currentMode
}

/** Apply the last known accent and mode immediately, then refresh them from the device. */
export async function initConsoleAccent(): Promise<void> {
  applyConsoleAccent(load(STORAGE_KEY))
  applyConsoleMode(load(MODE_KEY))
  lightQuery?.addEventListener?.('change', resolveMode)
  try {
    const params = await paramsAPI.getAll()
    const accent = params?.BPConsoleAccent
    if (accent) applyConsoleAccent(String(accent.value ?? 'blue'))
    const mode = params?.BPConsoleMode
    if (mode) applyConsoleMode(String(mode.value ?? 'auto'))
  } catch {
    // device offline or params unknown on this build: keep the cached values
  }
}
