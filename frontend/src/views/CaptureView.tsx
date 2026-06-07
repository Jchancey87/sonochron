import { useState, useRef, useEffect } from 'react'
import { api } from '../api'
import { uuid, formatRecordingTime } from '../utils'

interface Props {
  onSaved: () => void
}

type RecordState = 'idle' | 'recording' | 'stopped'

export function CaptureView({ onSaved }: Props) {
  const [recordState, setRecordState] = useState<RecordState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const [audioURL, setAudioURL] = useState<string | null>(null)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form fields
  const [title, setTitle] = useState('')
  const [mood, setMood] = useState('')
  const [location, setLocation] = useState('')
  const [companions, setCompanions] = useState('')
  const [notes, setNotes] = useState('')

  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Cleanup on unmount
  useEffect(() => () => {
    timerRef.current && clearInterval(timerRef.current)
    audioURL && URL.revokeObjectURL(audioURL)
  }, [audioURL])

  async function startRecording() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      mediaRef.current = mr
      chunksRef.current = []
      mr.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        const url = URL.createObjectURL(blob)
        setAudioBlob(blob)
        setAudioURL(url)
        stream.getTracks().forEach(t => t.stop())
      }
      mr.start()
      setRecordState('recording')
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
    } catch {
      setError('Microphone access denied. Please allow microphone permission and try again.')
    }
  }

  function stopRecording() {
    timerRef.current && clearInterval(timerRef.current)
    mediaRef.current?.stop()
    setRecordState('stopped')
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f && f.type.startsWith('audio/')) {
      setUploadFile(f)
      setAudioURL(URL.createObjectURL(f))
      setRecordState('stopped')
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    const file: File | null = uploadFile
      ?? (audioBlob ? new File([audioBlob], `recording-${Date.now()}.webm`, { type: 'audio/webm' }) : null)

    if (!file) { setError('No audio to submit.'); return }

    setSubmitting(true)
    try {
      await api.createEntry({
        file,
        localCaptureTime: new Date().toISOString(),
        title: title || undefined,
        mood: mood || undefined,
        location: location || undefined,
        companions: companions || undefined,
        notes: notes || undefined,
        idempotencyKey: uuid(),
      })
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submit failed')
    } finally {
      setSubmitting(false)
    }
  }

  const dotClass = `record-dot-wrap${recordState === 'recording' ? ' recording' : ''}`

  return (
    <div className="capture-view" id="capture-view">
      <div className="record-area">
        {/* Record dot */}
        <div
          id="record-dot"
          className={dotClass}
          onClick={recordState === 'recording' ? stopRecording : startRecording}
          title={recordState === 'recording' ? 'Stop recording' : 'Start recording'}
          role="button"
          aria-label={recordState === 'recording' ? 'Stop recording' : 'Start recording'}
          tabIndex={0}
          onKeyDown={e => e.key === 'Enter' && (recordState === 'recording' ? stopRecording() : startRecording())}
        >
          <div className="record-dot" />
        </div>

        <span className="record-label">
          {recordState === 'idle' && 'Tap to record'}
          {recordState === 'recording' && 'Recording — tap to stop'}
          {recordState === 'stopped' && 'Recording complete'}
        </span>

        {recordState === 'recording' && (
          <div className="record-timer">{formatRecordingTime(elapsed)}</div>
        )}

        {audioURL && recordState === 'stopped' && (
          <audio controls src={audioURL} style={{ marginTop: '8px', height: '32px', opacity: 0.7 }} />
        )}
      </div>

      {/* Upload zone — visible when idle and no blob */}
      {recordState === 'idle' && (
        <div
          className={`upload-zone${dragOver ? ' drag-over' : ''}`}
          style={{ width: '100%', maxWidth: '540px', marginBottom: '32px' }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => document.getElementById('file-input')?.click()}
        >
          <p>Drop an audio file here, or click to browse</p>
          <input
            id="file-input"
            type="file"
            accept="audio/*"
            style={{ display: 'none' }}
            onChange={e => {
              const f = e.target.files?.[0]
              if (f) { setUploadFile(f); setAudioURL(URL.createObjectURL(f)); setRecordState('stopped') }
            }}
          />
        </div>
      )}

      {/* Metadata form — always visible */}
      <form className="capture-form" onSubmit={handleSubmit} id="capture-form">
        <div className="form-field">
          <label htmlFor="f-title">Title</label>
          <input
            id="f-title"
            type="text"
            placeholder="What are you capturing?"
            value={title}
            onChange={e => setTitle(e.target.value)}
          />
        </div>

        <div className="form-row">
          <div className="form-field">
            <label htmlFor="f-mood">Mood</label>
            <input id="f-mood" type="text" placeholder="curious, restless…" value={mood} onChange={e => setMood(e.target.value)} />
          </div>
          <div className="form-field">
            <label htmlFor="f-location">Location</label>
            <input id="f-location" type="text" placeholder="Back garden, train…" value={location} onChange={e => setLocation(e.target.value)} />
          </div>
        </div>

        <div className="form-field">
          <label htmlFor="f-companions">With</label>
          <input id="f-companions" type="text" placeholder="Alice, alone…" value={companions} onChange={e => setCompanions(e.target.value)} />
        </div>

        <div className="form-field">
          <label htmlFor="f-notes">Notes</label>
          <textarea
            id="f-notes"
            rows={3}
            placeholder="What does this moment feel like?"
            value={notes}
            onChange={e => setNotes(e.target.value)}
          />
        </div>

        {error && (
          <p style={{ fontFamily: 'var(--mono)', fontSize: '12px', color: '#c0392b' }}>{error}</p>
        )}

        <button
          id="submit-entry"
          type="submit"
          className="submit-btn"
          disabled={submitting || (recordState === 'idle' && !uploadFile)}
        >
          {submitting ? 'Saving…' : 'Save entry'}
        </button>
      </form>
    </div>
  )
}
