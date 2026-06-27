import { useState } from 'react'
import { api } from '../api'
import { uuid } from '../utils'
import { CaptureAudioSection } from '../components/CaptureAudioSection'

interface Props {
  onSaved: () => void
}

export function CaptureView({ onSaved }: Props) {
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form fields
  const [title, setTitle] = useState('')
  const [mood, setMood] = useState('')
  const [location, setLocation] = useState('')
  const [companions, setCompanions] = useState('')
  const [notes, setNotes] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    const file: File | null = uploadFile
      ?? (audioBlob ? new File([audioBlob], `recording-${Date.now()}.webm`, { type: 'audio/webm' }) : null)

    if (!file) {
      setError('No audio to submit.')
      return
    }

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

  return (
    <div className="capture-view" id="capture-view">
      <CaptureAudioSection
        onAudioReady={(blob, file) => {
          setAudioBlob(blob)
          setUploadFile(file)
        }}
        onReset={() => {
          setAudioBlob(null)
          setUploadFile(null)
        }}
      />

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
          <p style={{ fontFamily: 'var(--mono)', fontSize: '12px', color: '#c0392b', textAlign: 'center', marginTop: '12px' }}>{error}</p>
        )}

        <button
          id="submit-entry"
          type="submit"
          className="submit-btn"
          disabled={submitting || (!audioBlob && !uploadFile)}
        >
          {submitting ? 'Saving…' : 'Save entry'}
        </button>
      </form>
    </div>
  )
}

