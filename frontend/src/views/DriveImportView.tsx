import { useCallback, useEffect, useRef, useState } from 'react'

interface DriveFile {
  id: string
  name: string
  size?: string
  createdTime?: string
  mimeType?: string
  already_imported: boolean
}

interface SyncState {
  last_run: string | null
  last_count: number
  last_error: string | null
  running: boolean
}

interface DriveStatus {
  authenticated: boolean
  folder_id: string | null
  sync: SyncState
}

function formatBytes(bytes?: string): string {
  if (!bytes) return '—'
  const n = parseInt(bytes)
  if (isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso?: string): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

export function DriveImportView() {
  const [status, setStatus]         = useState<DriveStatus | null>(null)
  const [files, setFiles]           = useState<DriveFile[]>([])
  const [loading, setLoading]       = useState(false)
  const [importing, setImporting]   = useState<Set<string>>(new Set())
  const [imported, setImported]     = useState<Set<string>>(new Set())
  const [syncing, setSyncing]       = useState(false)
  const [syncMsg, setSyncMsg]       = useState<string | null>(null)
  const [error, setError]           = useState<string | null>(null)
  const pollRef                     = useRef<ReturnType<typeof setInterval> | null>(null)

  // Check for ?drive=connected redirect from OAuth callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('drive') === 'connected') {
      window.history.replaceState({}, '', '/')
      fetchStatus()
    }
  }, [])

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/drive/status')
      const data: DriveStatus = await res.json()
      setStatus(data)
      if (data.authenticated && files.length === 0) {
        fetchFiles()
      }
    } catch (e) {
      setError('Could not reach API')
    }
  }, [files.length])

  const fetchFiles = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/drive/files')
      if (!res.ok) throw new Error(await res.text())
      const data: DriveFile[] = await res.json()
      setFiles(data)
      setImported(new Set(data.filter(f => f.already_imported).map(f => f.id)))
    } catch (e: any) {
      setError(e.message || 'Failed to load Drive files')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
    pollRef.current = setInterval(fetchStatus, 60_000) // refresh status every 60s
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const handleConnect = () => {
    window.location.href = '/api/drive/auth'
  }

  const handleRevoke = async () => {
    await fetch('/api/drive/auth', { method: 'DELETE' })
    setStatus(s => s ? { ...s, authenticated: false } : null)
    setFiles([])
  }

  const handleImport = async (file: DriveFile) => {
    setImporting(prev => new Set([...prev, file.id]))
    setError(null)
    try {
      const res = await fetch(
        `/api/drive/import/${file.id}?filename=${encodeURIComponent(file.name)}`,
        { method: 'POST' }
      )
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Import failed')
      }
      setImported(prev => new Set([...prev, file.id]))
    } catch (e: any) {
      setError(`Failed to import "${file.name}": ${e.message}`)
    } finally {
      setImporting(prev => { const n = new Set(prev); n.delete(file.id); return n })
    }
  }

  const handleImportAll = async () => {
    const pending = files.filter(f => !imported.has(f.id) && !importing.has(f.id))
    for (const f of pending) {
      await handleImport(f)
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    setSyncMsg(null)
    setError(null)
    try {
      const res = await fetch('/api/drive/sync', { method: 'POST' })
      const data = await res.json()
      setSyncMsg(`Sync complete — ${data.imported} new file${data.imported !== 1 ? 's' : ''} imported`)
      await fetchFiles()
      await fetchStatus()
    } catch (e: any) {
      setError('Sync failed: ' + e.message)
    } finally {
      setSyncing(false)
    }
  }

  const newFiles    = files.filter(f => !imported.has(f.id))
  const doneFiles   = files.filter(f => imported.has(f.id))
  const pendingCount = files.filter(f => !imported.has(f.id)).length

  // ── Unauthenticated state ──────────────────────────────────────────────
  if (!status) {
    return (
      <div id="drive-import-view" style={{ paddingTop: '32px' }}>
        <p style={{ color: 'var(--ink-faint)', fontFamily: 'var(--mono)', fontSize: '12px' }}>
          Checking Drive connection…
        </p>
      </div>
    )
  }

  if (!status.authenticated) {
    return (
      <div id="drive-import-view" style={{ paddingTop: '32px', maxWidth: '480px' }}>
        <h1 style={{ fontFamily: 'var(--serif)', fontSize: '22px', marginBottom: '8px' }}>
          Import from Google Drive
        </h1>
        <p style={{ color: 'var(--ink-faint)', fontSize: '14px', lineHeight: 1.6, marginBottom: '28px' }}>
          Connect your Google account to import iPhone Voice Memos (or any audio files)
          from your Drive folder. Files are automatically converted to 16-bit 44.1 kHz WAV.
        </p>
        <button
          id="drive-connect-btn"
          onClick={handleConnect}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '10px',
            background: 'var(--amber)',
            color: '#1a1510',
            border: 'none',
            borderRadius: '2px',
            padding: '10px 22px',
            fontFamily: 'var(--mono)',
            fontSize: '12px',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          <GoogleIcon /> Connect Google Drive
        </button>
      </div>
    )
  }

  // ── Authenticated state ────────────────────────────────────────────────
  return (
    <div id="drive-import-view" style={{ paddingTop: '24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ fontFamily: 'var(--serif)', fontSize: '22px', margin: 0 }}>
            Import from Google Drive
          </h1>
          {status.folder_id && (
            <p style={{ margin: '4px 0 0', fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--ink-faint)', letterSpacing: '0.06em' }}>
              FOLDER: {status.folder_id.slice(0, 20)}…
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            id="drive-sync-btn"
            onClick={handleSync}
            disabled={syncing}
            style={pillStyle(syncing)}
          >
            {syncing ? 'Syncing…' : '↻ Sync Now'}
          </button>
          {pendingCount > 0 && (
            <button
              id="drive-import-all-btn"
              onClick={handleImportAll}
              style={{ ...pillStyle(false), background: 'var(--amber)', color: '#1a1510' }}
            >
              Import All ({pendingCount})
            </button>
          )}
          <button
            id="drive-revoke-btn"
            onClick={handleRevoke}
            style={{ ...pillStyle(false), color: 'var(--ink-faint)' }}
          >
            Disconnect
          </button>
        </div>
      </div>

      {/* Sync status bar */}
      {(syncMsg || status.sync.last_run) && (
        <div style={{
          fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--ink-faint)',
          marginBottom: '16px', letterSpacing: '0.04em',
        }}>
          {syncMsg
            ? <span style={{ color: 'var(--amber)' }}>{syncMsg}</span>
            : status.sync.last_run
              ? `Last synced: ${formatDate(status.sync.last_run)} — ${status.sync.last_count} file${status.sync.last_count !== 1 ? 's' : ''} imported`
              : null}
          {status.sync.last_error && (
            <span style={{ color: '#c0392b', marginLeft: '12px' }}>
              Error: {status.sync.last_error}
            </span>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{
          background: 'rgba(192,57,43,0.12)', border: '1px solid rgba(192,57,43,0.3)',
          borderRadius: '2px', padding: '10px 14px', marginBottom: '16px',
          fontFamily: 'var(--mono)', fontSize: '12px', color: '#e74c3c',
        }}>
          {error}
        </div>
      )}

      {/* File list */}
      {loading ? (
        <p style={{ color: 'var(--ink-faint)', fontFamily: 'var(--mono)', fontSize: '12px' }}>
          Loading Drive files…
        </p>
      ) : files.length === 0 ? (
        <div style={{ color: 'var(--ink-faint)', fontSize: '14px', paddingTop: '16px' }}>
          No audio files found in your Drive folder.
          <br />
          <span style={{ fontFamily: 'var(--mono)', fontSize: '11px' }}>
            Share voice memos to Drive, then click ↻ Sync Now.
          </span>
        </div>
      ) : (
        <>
          {newFiles.length > 0 && (
            <FileSection
              title={`New (${newFiles.length})`}
              files={newFiles}
              importing={importing}
              imported={imported}
              onImport={handleImport}
            />
          )}
          {doneFiles.length > 0 && (
            <FileSection
              title={`Already Imported (${doneFiles.length})`}
              files={doneFiles}
              importing={importing}
              imported={imported}
              onImport={handleImport}
              dimmed
            />
          )}
        </>
      )}

      {/* Refresh button */}
      {status.authenticated && !loading && (
        <button
          id="drive-refresh-btn"
          onClick={fetchFiles}
          style={{ ...pillStyle(false), marginTop: '20px', color: 'var(--ink-faint)' }}
        >
          ↻ Refresh file list
        </button>
      )}
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function FileSection({
  title, files, importing, imported, onImport, dimmed = false,
}: {
  title: string
  files: DriveFile[]
  importing: Set<string>
  imported: Set<string>
  onImport: (f: DriveFile) => void
  dimmed?: boolean
}) {
  return (
    <div style={{ marginBottom: '28px' }}>
      <p style={{
        fontFamily: 'var(--mono)', fontSize: '10px', letterSpacing: '0.12em',
        textTransform: 'uppercase', color: 'var(--ink-faint)', marginBottom: '10px',
      }}>
        {title}
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {files.map(f => (
          <DriveFileRow
            key={f.id}
            file={f}
            isImporting={importing.has(f.id)}
            isDone={imported.has(f.id)}
            onImport={onImport}
            dimmed={dimmed}
          />
        ))}
      </div>
    </div>
  )
}

function DriveFileRow({
  file, isImporting, isDone, onImport, dimmed,
}: {
  file: DriveFile
  isImporting: boolean
  isDone: boolean
  onImport: (f: DriveFile) => void
  dimmed: boolean
}) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '10px 14px',
      borderRadius: '2px',
      background: 'var(--bg-entry)',
      border: '1px solid var(--divider)',
      opacity: dimmed ? 0.5 : 1,
      gap: '12px',
    }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{
          fontFamily: 'var(--mono)', fontSize: '12px',
          color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          {file.name}
        </div>
        <div style={{
          fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--ink-faint)',
          marginTop: '2px', letterSpacing: '0.04em',
        }}>
          {formatBytes(file.size)} · {formatDate(file.createdTime)}
        </div>
      </div>
      <div style={{ flexShrink: 0 }}>
        {isDone ? (
          <span style={{
            fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--amber)',
            letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>
            ✓ Imported
          </span>
        ) : (
          <button
            id={`drive-import-${file.id}`}
            onClick={() => onImport(file)}
            disabled={isImporting}
            style={{
              background: 'none',
              border: '1px solid var(--divider)',
              borderRadius: '2px',
              padding: '5px 12px',
              fontFamily: 'var(--mono)',
              fontSize: '11px',
              letterSpacing: '0.06em',
              color: isImporting ? 'var(--ink-faint)' : 'var(--ink)',
              cursor: isImporting ? 'default' : 'pointer',
              whiteSpace: 'nowrap',
              transition: 'border-color 0.2s, color 0.2s',
            }}
            onMouseEnter={e => { if (!isImporting) (e.target as HTMLButtonElement).style.borderColor = 'var(--amber)' }}
            onMouseLeave={e => { (e.target as HTMLButtonElement).style.borderColor = 'var(--divider)' }}
          >
            {isImporting ? 'Importing…' : 'Import'}
          </button>
        )}
      </div>
    </div>
  )
}

function pillStyle(disabled: boolean): React.CSSProperties {
  return {
    background: 'none',
    border: '1px solid var(--divider)',
    borderRadius: '2px',
    padding: '5px 14px',
    fontFamily: 'var(--mono)',
    fontSize: '11px',
    letterSpacing: '0.06em',
    color: disabled ? 'var(--ink-faint)' : 'var(--ink)',
    cursor: disabled ? 'default' : 'pointer',
    whiteSpace: 'nowrap' as const,
    transition: 'border-color 0.2s',
  }
}

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#1a1510"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#1a1510"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#1a1510"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#1a1510"/>
    </svg>
  )
}
