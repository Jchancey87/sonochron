import { useState, useRef } from 'react'
import type { DiaryEntry } from '../api'
import { api } from '../api'
import { Waveform } from './Waveform'
import { formatDate, formatDuration, formatBytes, buildMeta } from '../utils'

interface Props {
  entry: DiaryEntry
  onDeleted?: (id: string) => void
  onUpdated?: (entry: DiaryEntry) => void
}

export function EntryRow({ entry: initialEntry, onDeleted, onUpdated }: Props) {
  const [entry, setEntry] = useState<DiaryEntry>(initialEntry)
  const [open, setOpen] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  // Edit form state
  const [editTitle, setEditTitle]         = useState(entry.title ?? '')
  const [editMood, setEditMood]           = useState(entry.context?.mood ?? '')
  const [editLocation, setEditLocation]   = useState(entry.context?.location ?? '')
  const [editCompanions, setEditCompanions] = useState(entry.context?.companions?.join(', ') ?? '')
  const [editNotes, setEditNotes]         = useState(entry.context?.notes ?? '')

  const meta = buildMeta(entry)
  const title = entry.title ?? 'Untitled recording'

  function togglePlay(e: React.MouseEvent) {
    e.stopPropagation()
    if (!audioRef.current) {
      const a = new Audio(api.getAudioUrl(entry.id))
      audioRef.current = a
      a.ontimeupdate = () => { if (a.duration) setProgress(a.currentTime / a.duration) }
      a.onended = () => { setPlaying(false); setProgress(0) }
    }
    if (playing) { audioRef.current.pause(); setPlaying(false) }
    else { audioRef.current.play(); setPlaying(true) }
  }

  async function handleSave() {
    setSaving(true)
    try {
      const updated = await api.patchEntry(entry.id, {
        title: editTitle || undefined,
        mood: editMood || undefined,
        location: editLocation || undefined,
        companions: editCompanions ? editCompanions.split(',').map(s => s.trim()).filter(Boolean) : [],
        notes: editNotes || undefined,
      })
      setEntry(updated)
      setEditing(false)
      onUpdated?.(updated)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await api.deleteEntry(entry.id)
      onDeleted?.(entry.id)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Delete failed')
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  function startEdit(e: React.MouseEvent) {
    e.stopPropagation()
    setEditTitle(entry.title ?? '')
    setEditMood(entry.context?.mood ?? '')
    setEditLocation(entry.context?.location ?? '')
    setEditCompanions(entry.context?.companions?.join(', ') ?? '')
    setEditNotes(entry.context?.notes ?? '')
    setEditing(true)
  }

  return (
    <div className="entry-row">
      <button
        id={`entry-${entry.id}`}
        className="entry-summary"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span className="entry-date">{formatDate(entry.local_capture_time)}</span>
        <div className="entry-main">
          <div className="entry-title">{title}</div>
          <Waveform entryId={entry.id} />
          {meta && <div className="entry-meta">{meta}</div>}
        </div>
        <button
          id={`play-${entry.id}`}
          className={`play-btn${playing ? ' playing' : ''}`}
          onClick={togglePlay}
          title={playing ? 'Pause' : 'Play'}
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? '▪' : '▶'}
        </button>
      </button>

      {open && (
        <div className="entry-detail">
          {/* Audio progress bar */}
          {playing && (
            <div className="audio-bar">
              <div className="audio-progress">
                <div className="audio-progress-fill" style={{ width: `${progress * 100}%` }} />
              </div>
            </div>
          )}

          {/* ── Read view ── */}
          {!editing && (
            <>
              {entry.context?.notes && (
                <p className="detail-notes">"{entry.context.notes}"</p>
              )}
              <div className="detail-meta-grid">
                {entry.context?.mood && (
                  <div className="detail-field"><label>Mood</label><span>{entry.context.mood}</span></div>
                )}
                {entry.context?.location && (
                  <div className="detail-field"><label>Location</label><span>{entry.context.location}</span></div>
                )}
                {entry.context?.companions?.length ? (
                  <div className="detail-field"><label>With</label><span>{entry.context.companions.join(', ')}</span></div>
                ) : null}
                {entry.asset?.duration_ms && (
                  <div className="detail-field"><label>Duration</label><span>{formatDuration(entry.asset.duration_ms)}</span></div>
                )}
                {entry.asset?.byte_size && (
                  <div className="detail-field"><label>Size</label><span>{formatBytes(entry.asset.byte_size)}</span></div>
                )}
                <div className="detail-field">
                  <label>Captured</label>
                  <span>{new Date(entry.local_capture_time).toLocaleString()}</span>
                </div>
              </div>
              <div className="detail-stage">
                Pipeline <span className="stage-badge">{entry.stage}</span>
              </div>
              <div className="detail-actions">
                <button id={`edit-${entry.id}`} onClick={startEdit}>Edit</button>
                <button
                  id={`similar-${entry.id}`}
                  onClick={() => window.dispatchEvent(new CustomEvent('sonochron:similar', { detail: entry.id }))}
                >Similar sounds</button>
                {!confirmDelete ? (
                  <button
                    id={`delete-${entry.id}`}
                    onClick={e => { e.stopPropagation(); setConfirmDelete(true) }}
                    style={{ color: 'var(--ink-faint)', borderColor: 'var(--ink-faint)' }}
                  >Delete</button>
                ) : (
                  <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: '#c0392b' }}>
                      Are you sure?
                    </span>
                    <button
                      id={`confirm-delete-${entry.id}`}
                      onClick={handleDelete}
                      disabled={deleting}
                      style={{ borderColor: '#c0392b', color: '#c0392b' }}
                    >{deleting ? 'Deleting…' : 'Yes, delete'}</button>
                    <button onClick={() => setConfirmDelete(false)}>Cancel</button>
                  </span>
                )}
              </div>
            </>
          )}

          {/* ── Edit view ── */}
          {editing && (
            <div className="edit-form">
              <div className="form-field">
                <label htmlFor={`ef-title-${entry.id}`}>Title</label>
                <input
                  id={`ef-title-${entry.id}`}
                  type="text"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  placeholder="Untitled recording"
                />
              </div>
              <div className="form-row" style={{ marginTop: '12px' }}>
                <div className="form-field">
                  <label htmlFor={`ef-mood-${entry.id}`}>Mood</label>
                  <input
                    id={`ef-mood-${entry.id}`}
                    type="text"
                    value={editMood}
                    onChange={e => setEditMood(e.target.value)}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor={`ef-loc-${entry.id}`}>Location</label>
                  <input
                    id={`ef-loc-${entry.id}`}
                    type="text"
                    value={editLocation}
                    onChange={e => setEditLocation(e.target.value)}
                  />
                </div>
              </div>
              <div className="form-field" style={{ marginTop: '12px' }}>
                <label htmlFor={`ef-comp-${entry.id}`}>With (comma-separated)</label>
                <input
                  id={`ef-comp-${entry.id}`}
                  type="text"
                  value={editCompanions}
                  onChange={e => setEditCompanions(e.target.value)}
                />
              </div>
              <div className="form-field" style={{ marginTop: '12px' }}>
                <label htmlFor={`ef-notes-${entry.id}`}>Notes</label>
                <textarea
                  id={`ef-notes-${entry.id}`}
                  rows={3}
                  value={editNotes}
                  onChange={e => setEditNotes(e.target.value)}
                />
              </div>
              <div className="detail-actions" style={{ marginTop: '16px' }}>
                <button
                  id={`save-${entry.id}`}
                  onClick={handleSave}
                  disabled={saving}
                  style={{ background: 'var(--ink)', color: 'var(--bg)', borderColor: 'var(--ink)' }}
                >{saving ? 'Saving…' : 'Save'}</button>
                <button onClick={() => setEditing(false)}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
