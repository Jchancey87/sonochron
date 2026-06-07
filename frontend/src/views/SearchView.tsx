import { useState, useEffect, useRef } from 'react'
import type { SearchResult } from '../api'
import { api } from '../api'
import { MONTHS } from '../utils'

export function SearchView() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Handle "similar sounds" event from EntryRow
  useEffect(() => {
    function onSimilar(e: Event) {
      const id = (e as CustomEvent<string>).detail
      setQuery(`~similar:${id}`)
      setLoading(true)
      setSearched(true)
      api.searchSimilar(id)
        .then(r => { setResults(r); setLoading(false) })
        .catch(() => setLoading(false))
    }
    window.addEventListener('sonochron:similar', onSimilar)
    return () => window.removeEventListener('sonochron:similar', onSimilar)
  }, [])

  function handleSearch(q: string) {
    setQuery(q)
    debounceRef.current && clearTimeout(debounceRef.current)
    if (!q.trim() || q.startsWith('~similar:')) return
    debounceRef.current = setTimeout(() => {
      setLoading(true)
      setSearched(true)
      api.searchText(q.trim())
        .then(r => { setResults(r); setLoading(false) })
        .catch(() => setLoading(false))
    }, 400)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!query.trim() || query.startsWith('~similar:')) return
    debounceRef.current && clearTimeout(debounceRef.current)
    setLoading(true)
    setSearched(true)
    api.searchText(query.trim())
      .then(r => { setResults(r); setLoading(false) })
      .catch(() => setLoading(false))
  }

  return (
    <div className="search-view" id="search-view">
      <form onSubmit={handleSubmit}>
        <div className="search-input-wrap">
          <input
            id="search-input"
            className="search-input"
            type="text"
            placeholder="Search your diary…"
            value={query.startsWith('~similar:') ? 'Similar sounds' : query}
            onChange={e => handleSearch(e.target.value)}
            autoFocus
          />
          <div className="search-hint">
            {query.startsWith('~similar:')
              ? 'showing audio similarity results'
              : 'semantic search over titles, notes, mood, and location'}
          </div>
        </div>
      </form>

      {loading && <div className="loading-state">Searching…</div>}

      {!loading && searched && results.length === 0 && (
        <div className="empty-state">Nothing found.</div>
      )}

      {!loading && results.length > 0 && (
        <div>
          {results.map((r, i) => (
            <div key={r.entry_id} className="entry-row" id={`result-${r.entry_id}`}>
              <div className="entry-summary" style={{ cursor: 'default' }}>
                <span className="entry-date" style={{ paddingTop: '5px' }}>
                  {r.year && r.month ? `${MONTHS[r.month - 1].slice(0, 3).toUpperCase()} ${r.year}` : '—'}
                </span>
                <div className="entry-main">
                  <div className="entry-title">{r.title ?? 'Untitled'}</div>
                  <div className="entry-meta">
                    {[r.mood, r.location].filter(Boolean).join(' · ')}
                    <span style={{ marginLeft: '16px', color: 'var(--amber)', fontFamily: 'var(--mono)', fontSize: '10px' }}>
                      score {r.score.toFixed(3)}
                    </span>
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'flex-end' }}>
                  <span style={{
                    fontFamily: 'var(--mono)',
                    fontSize: '10px',
                    color: 'var(--ink-faint)',
                    letterSpacing: '0.05em',
                  }}>
                    #{i + 1}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {!searched && (
        <div className="empty-state" style={{ paddingTop: '32px' }}>
          Start typing to search your sound diary.
        </div>
      )}
    </div>
  )
}
