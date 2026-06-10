// utils.ts — helpers

export const MONTHS = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December'
]

export function formatDate(iso: string): string {
  const d = new Date(iso)
  const day = String(d.getDate()).padStart(2,'0')
  const mon = MONTHS[d.getMonth()].slice(0,3).toUpperCase()
  return `${day} ${mon}`
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function formatDuration(ms: number | null): string {
  if (!ms) return '—'
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2,'0')}`
}

export function formatBytes(b: number | null): string {
  if (!b) return '—'
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

export function buildMeta(entry: import('./api').DiaryEntry): string {
  const parts: string[] = []
  if (entry.context?.mood) parts.push(entry.context.mood)
  if (entry.context?.location) parts.push(entry.context.location)
  if (entry.context?.companions && entry.context.companions.length > 0) {
    parts.push(entry.context.companions.join(', '))
  }
  if (entry.context?.notes) parts.push(entry.context.notes)
  return parts.join(' · ')
}

/** Deterministic fake waveform bars from entry id */
export function fakeWaveform(id: string, bars = 60): number[] {
  const seed = id.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
  return Array.from({ length: bars }, (_, i) => {
    const v = Math.sin(seed * 0.1 + i * 0.4) * 0.5
      + Math.sin(seed * 0.3 + i * 0.9) * 0.3
      + Math.sin(i * 0.2) * 0.2
    return Math.max(0.08, Math.abs(v))
  })
}

export function uuid(): string {
  return crypto.randomUUID()
}

export function formatRecordingTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
}
