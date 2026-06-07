import { useEffect, useState } from 'react'
import type { DiaryEntry, YearArchive } from '../api'
import { api } from '../api'
import { EntryRow } from '../components/EntryRow'
import { MONTHS } from '../utils'

export function TimelineView() {
  const [timeline, setTimeline] = useState<YearArchive[]>([])
  const [entries, setEntries] = useState<DiaryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  const [selectedMonth, setSelectedMonth] = useState<number | null>(null)

  useEffect(() => {
    api.getTimeline().then(years => {
      setTimeline(years)
      // Default to most recent year/month
      if (years.length > 0) {
        const yr = years[0]
        setSelectedYear(yr.year)
        if (yr.months.length > 0) setSelectedMonth(yr.months[0].month)
      }
    }).catch(console.error)
  }, [])

  useEffect(() => {
    setLoading(true)
    api.getEntries(selectedYear ?? undefined, selectedMonth ?? undefined)
      .then(e => { setEntries(e); setLoading(false) })
      .catch(() => setLoading(false))
  }, [selectedYear, selectedMonth])

  const hasEntries = entries.length > 0

  return (
    <div id="timeline-view">
      {/* Year/month nav pills — minimal monospace */}
      {timeline.length > 0 && (
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', marginBottom: '8px' }}>
          {timeline.map(yr => (
            <div key={yr.year}>
              <span
                className="year-heading"
                style={{ cursor: 'pointer', display: 'inline-block', marginRight: '12px' }}
                onClick={() => { setSelectedYear(yr.year); setSelectedMonth(null) }}
              >
                {yr.year}
              </span>
              {yr.months.map(mo => (
                <button
                  key={mo.id}
                  id={`month-${yr.year}-${mo.month}`}
                  onClick={() => { setSelectedYear(yr.year); setSelectedMonth(mo.month) }}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    fontFamily: 'var(--mono)',
                    fontSize: '11px',
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    color: selectedYear === yr.year && selectedMonth === mo.month
                      ? 'var(--amber)' : 'var(--ink-faint)',
                    marginRight: '14px',
                    padding: '2px 0',
                    borderBottom: selectedYear === yr.year && selectedMonth === mo.month
                      ? '1px solid var(--amber)' : '1px solid transparent',
                    transition: 'color 0.2s',
                  }}
                >
                  {MONTHS[mo.month - 1].slice(0, 3)} ({mo.entry_count})
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Month heading */}
      {selectedYear && selectedMonth && (
        <h1 className="month-heading">
          {MONTHS[selectedMonth - 1]} {selectedYear}
        </h1>
      )}
      {selectedYear && !selectedMonth && (
        <h1 className="month-heading">{selectedYear}</h1>
      )}

      {/* Entries */}
      {loading && <div className="loading-state">Loading…</div>}
      {!loading && !hasEntries && (
        <div className="empty-state">
          No recordings yet for this period.
        </div>
      )}
      {!loading && hasEntries && entries.map(e => (
        <EntryRow
          key={e.id}
          entry={e}
          onDeleted={id => setEntries(prev => prev.filter(x => x.id !== id))}
          onUpdated={updated => setEntries(prev => prev.map(x => x.id === updated.id ? updated : x))}
        />
      ))}
    </div>
  )
}
