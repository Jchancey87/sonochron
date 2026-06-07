// api.ts — Sonochron API client

const BASE = import.meta.env.VITE_API_URL || ''

export interface EntryContext {
  mood: string | null
  location: string | null
  companions: string[]
  notes: string | null
}

export interface SampleAsset {
  id: string
  filename: string
  filepath: string
  checksum_sha256: string | null
  duration_ms: number | null
  byte_size: number | null
}

export interface DiaryEntry {
  id: string
  local_capture_time: string
  utc_capture_time: string | null
  title: string | null
  stage: string
  created_at: string
  updated_at: string
  context: EntryContext | null
  asset: SampleAsset | null
}

export interface MonthArchive {
  id: string
  year: number
  month: number
  entry_count: number
}

export interface YearArchive {
  year: number
  months: MonthArchive[]
}

export interface Timeline {
  years: YearArchive[]
}

export interface SearchResult {
  entry_id: string
  score: number
  title: string | null
  mood: string | null
  location: string | null
  year: number | null
  month: number | null
}

export interface WaveformData {
  entry_id: string
  peaks: number[]
  num_bars: number
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json()
}

export const api = {
  getTimeline: (): Promise<YearArchive[]> =>
    get('/api/timeline'),

  getEntries: (year?: number, month?: number): Promise<DiaryEntry[]> => {
    const params = new URLSearchParams()
    if (year != null) params.set('year', String(year))
    if (month != null) params.set('month', String(month))
    return get(`/api/entries?${params}`)
  },

  getEntry: (id: string): Promise<DiaryEntry> =>
    get(`/api/entries/${id}`),

  getAudioUrl: (id: string): string =>
    `${BASE}/api/entries/${id}/audio`,

  searchText: (q: string): Promise<SearchResult[]> =>
    get(`/api/search?q=${encodeURIComponent(q)}&limit=20`),

  searchSimilar: (id: string): Promise<SearchResult[]> =>
    get(`/api/entries/${id}/similar?limit=10`),

  getWaveform: (id: string, bars = 100): Promise<WaveformData> =>
    get(`/api/entries/${id}/waveform?bars=${bars}`),

  patchEntry: async (id: string, patch: {
    title?: string
    mood?: string
    location?: string
    companions?: string[]
    notes?: string
  }): Promise<DiaryEntry> => {
    const res = await fetch(`${BASE}/api/entries/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!res.ok) throw new Error(`Patch failed: ${res.status}`)
    return res.json()
  },

  deleteEntry: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE}/api/entries/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`Delete failed: ${res.status}`)
  },

  createEntry: async (opts: {
    file: File
    localCaptureTime: string
    title?: string
    mood?: string
    location?: string
    companions?: string
    notes?: string
    idempotencyKey: string
  }): Promise<DiaryEntry> => {
    const form = new FormData()
    form.append('file', opts.file)
    form.append('local_capture_time', opts.localCaptureTime)
    if (opts.title)      form.append('title', opts.title)
    if (opts.mood)       form.append('mood', opts.mood)
    if (opts.location)   form.append('location', opts.location)
    if (opts.companions) form.append('companions', opts.companions)
    if (opts.notes)      form.append('notes', opts.notes)

    const res = await fetch(`${BASE}/api/entries`, {
      method: 'POST',
      headers: { 'X-Idempotency-Key': opts.idempotencyKey },
      body: form,
    })
    if (!res.ok) {
      const err = await res.text()
      throw new Error(`Upload failed: ${err}`)
    }
    return res.json()
  },
}
