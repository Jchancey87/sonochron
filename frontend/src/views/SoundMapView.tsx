import { useEffect, useState, useRef } from 'react'
import { api, DiaryEntry } from '../api'
import { InteractivePlayer } from '../components/InteractivePlayer'
import { useSettings } from '../contexts/SettingsContext'
import { formatDuration, formatBytes } from '../utils'

interface SimNode {
  id: string
  title: string
  date: Date
  mood: string
  location: string
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  entry: DiaryEntry
}

export function SoundMapView() {
  const [entries, setEntries] = useState<DiaryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [, setTick] = useState(0)
  const [layoutMode, setLayoutMode] = useState<'mood' | 'radial' | 'central'>('mood')
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [selectedEntry, setSelectedEntry] = useState<DiaryEntry | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)

  // WaveSurfer synchronization states for the selected entry
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [seekToTime, setSeekToTime] = useState<number | null>(null)

  const { settings } = useSettings()

  const svgRef = useRef<SVGSVGElement | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const draggedNodeIdRef = useRef<string | null>(null)
  const isPanningRef = useRef(false)
  const startPanMouseRef = useRef({ x: 0, y: 0 })
  const startPanRef = useRef({ x: 0, y: 0 })
  const mousePosRef = useRef<{ x: number; y: number } | null>(null)
  const clickStartPosRef = useRef({ x: 0, y: 0 })

  // Keep zoom/pan refs updated for the simulation loop
  const zoomRef = useRef(zoom)
  const panRef = useRef(pan)
  useEffect(() => { zoomRef.current = zoom }, [zoom])
  useEffect(() => { panRef.current = pan }, [pan])

  // Reset player when selection changes
  useEffect(() => {
    setIsPlaying(false)
    setCurrentTime(0)
    setDuration(0)
    setSeekToTime(null)
  }, [selectedEntry?.id])

  // Global play coordinator support
  useEffect(() => {
    function handleGlobalPlay(e: Event) {
      const activeId = (e as CustomEvent).detail
      if (activeId !== selectedEntry?.id) {
        setIsPlaying(false)
      }
    }
    window.addEventListener('sonochron:play', handleGlobalPlay)
    return () => window.removeEventListener('sonochron:play', handleGlobalPlay)
  }, [selectedEntry?.id])

  // Fetch entries on mount
  useEffect(() => {
    setLoading(true)
    api.getEntries()
      .then(data => {
        setEntries(data)
        // Initialize node positions centered but slightly dispersed
        nodesRef.current = data.map((entry) => {
          const angle = Math.random() * Math.PI * 2
          const radius = Math.random() * 80 + 30
          const durationMs = entry.asset?.duration_ms || 5000
          // scale radius organic to duration
          const nodeRadius = Math.min(26, Math.max(16, 16 + (durationMs / 1000) * 0.15))
          return {
            id: entry.id,
            title: entry.title || 'Untitled recording',
            date: new Date(entry.local_capture_time),
            mood: entry.context?.mood || '',
            location: entry.context?.location || '',
            x: 400 + Math.cos(angle) * radius,
            y: 300 + Math.sin(angle) * radius,
            vx: 0,
            vy: 0,
            radius: nodeRadius,
            entry
          }
        })
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to load map entries', err)
        setLoading(false)
      })
  }, [])

  // Physics Simulation Loop
  useEffect(() => {
    let animId: number
    const width = 800
    const height = 600
    const cx = width / 2
    const cy = height / 2

    const tickSim = () => {
      const currentNodes = nodesRef.current
      if (currentNodes.length === 0) return

      // 1. Layout Mode Target Attraction Forces
      if (layoutMode === 'mood') {
        const moodCenters: Record<string, { x: number; y: number }> = {
          calm: { x: 220, y: 180 },
          sad: { x: 220, y: 420 },
          anxious: { x: 580, y: 420 },
          happy: { x: 580, y: 180 },
          default: { x: 400, y: 300 }
        }

        currentNodes.forEach(node => {
          if (node.id === draggedNodeIdRef.current) return
          const m = (node.mood || '').toLowerCase().trim()
          let key = 'default'
          if (['calm', 'chill', 'peaceful'].includes(m)) key = 'calm'
          else if (['sad', 'melancholy', 'blue'].includes(m)) key = 'sad'
          else if (['anxious', 'restless', 'tense'].includes(m)) key = 'anxious'
          else if (['happy', 'excited', 'energetic'].includes(m)) key = 'happy'

          const target = moodCenters[key]
          node.vx += (target.x - node.x) * 0.015
          node.vy += (target.y - node.y) * 0.015
        })
      } else if (layoutMode === 'radial') {
        const times = currentNodes.map(n => n.date.getTime())
        const minTime = Math.min(...times)
        const maxTime = Math.max(...times)
        const timeSpan = maxTime - minTime || 1

        currentNodes.forEach(node => {
          if (node.id === draggedNodeIdRef.current) return
          // Angle maps to 24 hours (Midnight at top)
          const hours = node.date.getHours() + node.date.getMinutes() / 60 + node.date.getSeconds() / 3600
          const angle = (hours / 24) * 2 * Math.PI - Math.PI / 2

          // Radius maps to date: newer entries are closer to center (90px), older further out (270px)
          const normTime = (node.date.getTime() - minTime) / timeSpan
          const targetRadius = 270 - normTime * 180

          const targetX = cx + Math.cos(angle) * targetRadius
          const targetY = cy + Math.sin(angle) * targetRadius

          node.vx += (targetX - node.x) * 0.025
          node.vy += (targetY - node.y) * 0.025
        })
      } else {
        // Central Gravity
        currentNodes.forEach(node => {
          if (node.id === draggedNodeIdRef.current) return
          node.vx += (cx - node.x) * 0.012
          node.vy += (cy - node.y) * 0.012
        })
      }

      // 2. Pairwise Repulsion Force
      for (let i = 0; i < currentNodes.length; i++) {
        const nodeI = currentNodes[i]
        for (let j = i + 1; j < currentNodes.length; j++) {
          const nodeJ = currentNodes[j]

          const dx = nodeJ.x - nodeI.x
          const dy = nodeJ.y - nodeI.y
          const distSq = dx * dx + dy * dy || 1
          const dist = Math.sqrt(distSq)
          const minDist = nodeI.radius + nodeJ.radius + 15

          if (dist < minDist) {
            const force = (minDist - dist) * 0.08
            const pushX = (dx / dist) * force
            const pushY = (dy / dist) * force

            if (nodeI.id !== draggedNodeIdRef.current) {
              nodeI.vx -= pushX
              nodeI.vy -= pushY
            }
            if (nodeJ.id !== draggedNodeIdRef.current) {
              nodeJ.vx += pushX
              nodeJ.vy += pushY
            }
          }
        }
      }

      // 3. Update position, apply friction and boundaries
      currentNodes.forEach(node => {
        if (node.id === draggedNodeIdRef.current) {
          if (mousePosRef.current) {
            node.x = (mousePosRef.current.x - panRef.current.x) / zoomRef.current
            node.y = (mousePosRef.current.y - panRef.current.y) / zoomRef.current
            node.vx = 0
            node.vy = 0
          }
          return
        }

        node.x += node.vx
        node.y += node.vy

        // Friction decay
        node.vx *= 0.84
        node.vy *= 0.84

        // Boundaries check
        const margin = node.radius + 10
        if (node.x < margin) { node.x = margin; node.vx = 0 }
        if (node.x > width - margin) { node.x = width - margin; node.vx = 0 }
        if (node.y < margin) { node.y = margin; node.vy = 0 }
        if (node.y > height - margin) { node.y = height - margin; node.vy = 0 }
      })

      // Trigger React render
      setTick(t => t + 1)
    }

    const loop = () => {
      tickSim()
      animId = requestAnimationFrame(loop)
    }

    loop()
    return () => cancelAnimationFrame(animId)
  }, [layoutMode])

  // Get mood colors mapping (parchment palette)
  const getMoodColor = (mood: string) => {
    const m = mood.toLowerCase().trim()
    if (['calm', 'chill', 'peaceful'].includes(m)) return '#C8DBC8' // sage
    if (['sad', 'melancholy', 'blue'].includes(m)) return '#C6D3DC' // slate blue
    if (['anxious', 'restless', 'tense'].includes(m)) return '#E2DACD' // warm gray
    if (['happy', 'excited', 'energetic'].includes(m)) return '#EEDDA8' // warm amber
    return '#DFD3BC' // default parchment
  }

  // Pointer Interaction Handlers
  const handleNodePointerDown = (e: React.PointerEvent, nodeId: string) => {
    e.stopPropagation()
    try {
      (e.target as Element).setPointerCapture(e.pointerId)
    } catch {}
    draggedNodeIdRef.current = nodeId
    clickStartPosRef.current = { x: e.clientX, y: e.clientY }

    const svg = svgRef.current
    if (svg) {
      const rect = svg.getBoundingClientRect()
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      mousePosRef.current = { x: mouseX, y: mouseY }
    }
  }

  const handlePointerMove = (e: React.PointerEvent) => {
    const svg = svgRef.current
    if (!svg) return

    const rect = svg.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    if (draggedNodeIdRef.current) {
      mousePosRef.current = { x: mouseX, y: mouseY }
    } else if (isPanningRef.current) {
      const dx = e.clientX - startPanMouseRef.current.x
      const dy = e.clientY - startPanMouseRef.current.y
      setPan({
        x: startPanRef.current.x + dx,
        y: startPanRef.current.y + dy
      })
    }
  }

  const handlePointerUp = (e: React.PointerEvent, node?: SimNode) => {
    if (draggedNodeIdRef.current) {
      try {
        (e.target as Element).releasePointerCapture(e.pointerId)
      } catch {}
      draggedNodeIdRef.current = null

      // Check if it's a click or a drag
      const dx = e.clientX - clickStartPosRef.current.x
      const dy = e.clientY - clickStartPosRef.current.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist < 5 && node) {
        setSelectedEntry(node.entry)
      }
    }
    isPanningRef.current = false
  }

  const handleBgPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return // Only primary mouse click
    isPanningRef.current = true
    startPanMouseRef.current = { x: e.clientX, y: e.clientY }
    startPanRef.current = { ...pan }
  }

  // Zoom controls
  const handleZoom = (factor: number) => {
    setZoom(z => Math.min(4, Math.max(0.25, z * factor)))
  }

  const handleReset = () => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const zoomFactor = 1.08
    const nextZoom = e.deltaY < 0 ? zoom * zoomFactor : zoom / zoomFactor
    const boundedZoom = Math.min(4, Math.max(0.25, nextZoom))

    const svg = svgRef.current
    if (svg) {
      const rect = svg.getBoundingClientRect()
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top

      const svgX = (mouseX - pan.x) / zoom
      const svgY = (mouseY - pan.y) / zoom

      const nextPan = {
        x: mouseX - svgX * boundedZoom,
        y: mouseY - svgY * boundedZoom
      }

      setZoom(boundedZoom)
      setPan(nextPan)
    }
  }

  // Rendering background lines for Radial mode
  const renderRadialGrid = () => {
    if (layoutMode !== 'radial') return null
    return (
      <g className="radial-grid" style={{ pointerEvents: 'none', opacity: 0.8 }}>
        {/* Concentric rings */}
        <circle cx="400" cy="300" r="90" fill="none" stroke="var(--divider)" strokeDasharray="3,3" />
        <circle cx="400" cy="300" r="180" fill="none" stroke="var(--divider)" strokeDasharray="3,3" />
        <circle cx="400" cy="300" r="270" fill="none" stroke="var(--divider)" strokeDasharray="3,3" />

        {/* Ring labels */}
        <text x="405" y="205" className="radial-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '9px', fill: 'var(--ink-faint)' }}>RECENT</text>
        <text x="405" y="115" className="radial-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '9px', fill: 'var(--ink-faint)' }}>EARLIER</text>
        <text x="405" y="25" className="radial-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '9px', fill: 'var(--ink-faint)' }}>PAST</text>

        {/* Hour lines */}
        {/* Midnight / 12 AM (top) */}
        <line x1="400" y1="300" x2="400" y2="25" stroke="var(--divider)" strokeDasharray="2,4" />
        <text x="400" y="20" textAnchor="middle" className="radial-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '9px', fill: 'var(--ink-muted)' }}>MIDNIGHT</text>

        {/* 6 AM (right) */}
        <line x1="400" y1="300" x2="675" y2="300" stroke="var(--divider)" strokeDasharray="2,4" />
        <text x="685" y="303" className="radial-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '9px', fill: 'var(--ink-muted)' }}>6 AM</text>

        {/* Noon / 12 PM (bottom) */}
        <line x1="400" y1="300" x2="400" y2="575" stroke="var(--divider)" strokeDasharray="2,4" />
        <text x="400" y="590" textAnchor="middle" className="radial-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '9px', fill: 'var(--ink-muted)' }}>NOON</text>

        {/* 6 PM (left) */}
        <line x1="400" y1="300" x2="125" y2="300" stroke="var(--divider)" strokeDasharray="2,4" />
        <text x="95" y="303" className="radial-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '9px', fill: 'var(--ink-muted)' }}>6 PM</text>
      </g>
    )
  }

  // Rendering background titles for Mood mode
  const renderMoodGrid = () => {
    if (layoutMode !== 'mood') return null
    return (
      <g className="mood-grid" style={{ pointerEvents: 'none', opacity: 0.5 }}>
        {/* Quadrant grid separators */}
        <line x1="400" y1="30" x2="400" y2="570" stroke="var(--divider)" strokeDasharray="2,4" />
        <line x1="30" y1="300" x2="770" y2="300" stroke="var(--divider)" strokeDasharray="2,4" />

        <text x="60" y="55" className="mood-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '11px', fill: 'var(--ink-muted)', letterSpacing: '0.1em' }}>SAGE / CALM</text>
        <text x="740" y="55" textAnchor="end" className="mood-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '11px', fill: 'var(--ink-muted)', letterSpacing: '0.1em' }}>AMBER / HAPPY</text>
        <text x="60" y="560" className="mood-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '11px', fill: 'var(--ink-muted)', letterSpacing: '0.1em' }}>SLATE / SAD</text>
        <text x="740" y="560" textAnchor="end" className="mood-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '11px', fill: 'var(--ink-muted)', letterSpacing: '0.1em' }}>WARM / ANXIOUS</text>
        <text x="400" y="315" textAnchor="middle" className="mood-grid-label" style={{ fontFamily: 'var(--mono)', fontSize: '10px', fill: 'var(--ink-faint)', letterSpacing: '0.08em' }}>DEFAULT</text>
      </g>
    )
  }

  if (loading) {
    return <div className="loading-state">Loading Sound Map…</div>
  }

  if (entries.length === 0) {
    return (
      <div className="empty-state">
        <p>No audio entries available to display on the map.</p>
        <p style={{ marginTop: '12px', fontSize: '15px', color: 'var(--ink-muted)' }}>
          Record some sounds in the <strong>Capture</strong> tab first!
        </p>
      </div>
    )
  }

  // Pre-calculate Word Highlight stats for selected drawer entry
  const notesText = selectedEntry?.context?.notes || ''
  const isTranscript = notesText.startsWith('[Transcript] ')
  const showKaraoke = settings.transcriptKaraokeEnabled && isTranscript
  const transcriptText = isTranscript ? notesText.substring(13) : ''
  const words = showKaraoke ? transcriptText.split(/\s+/).filter(Boolean) : []
  const audioDuration = duration || (selectedEntry?.asset?.duration_ms ? selectedEntry.asset.duration_ms / 1000 : 0)
  const activeWordIndex = showKaraoke && audioDuration > 0 && words.length > 0
    ? Math.min(Math.floor(currentTime / (audioDuration / words.length)), words.length - 1)
    : -1

  const handleWordClick = (wordIndex: number) => {
    if (audioDuration > 0 && words.length > 0) {
      const targetTime = wordIndex * (audioDuration / words.length)
      setSeekToTime(targetTime)
    }
  }

  return (
    <div className="soundmap-view" id="soundmap-view">
      <div className="soundmap-header">
        <h2 className="soundmap-title">Sound Map</h2>
        <p className="soundmap-subtitle">
          A spatial landscape of your auditory recordings. Drag entries to organize, pan and zoom to explore.
        </p>
      </div>

      <div className="soundmap-container">
        {/* SVG Visualization Canvas */}
        <svg
          ref={svgRef}
          className="soundmap-canvas"
          width="100%"
          height="550"
          onPointerMove={handlePointerMove}
          onPointerUp={(e) => handlePointerUp(e)}
          onPointerLeave={(e) => handlePointerUp(e)}
          onPointerDown={handleBgPointerDown}
          onWheel={handleWheel}
          style={{ cursor: isPanningRef.current ? 'grabbing' : 'grab' }}
        >
          {/* Grid Background Patterns (in SVG coordinate space) */}
          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            {renderRadialGrid()}
            {renderMoodGrid()}
            
            {/* Center crosshair for radial/reference */}
            <circle cx="400" cy="300" r="3" fill="var(--ink-faint)" opacity="0.3" />

            {/* Nodes */}
            {nodesRef.current.map((node) => {
              const isSelected = selectedEntry?.id === node.id
              const isDragged = draggedNodeIdRef.current === node.id
              const moodColor = getMoodColor(node.mood)

              return (
                <g
                  key={node.id}
                  style={{ cursor: isDragged ? 'grabbing' : 'pointer' }}
                  onPointerDown={(e) => handleNodePointerDown(e, node.id)}
                  onPointerUp={(e) => handlePointerUp(e, node)}
                >
                  {/* Subtle outer aura/glow if selected */}
                  {isSelected && (
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={node.radius + 6}
                      fill="none"
                      stroke="var(--amber)"
                      strokeWidth="1"
                      strokeDasharray="2,2"
                      className="selected-aura"
                    />
                  )}

                  {/* Node Circle */}
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={node.radius}
                    fill={moodColor}
                    stroke={isSelected ? 'var(--amber)' : 'var(--ink)'}
                    strokeWidth={isSelected ? 2.5 : 1.5}
                    className={`soundmap-node ${isSelected ? 'selected' : ''}`}
                  />

                  {/* Centered Node Label */}
                  <text
                    x={node.x}
                    y={node.y}
                    dy={node.radius + 14}
                    textAnchor="middle"
                    className="soundmap-node-label"
                    style={{
                      fontFamily: 'var(--mono)',
                      fontSize: isSelected ? '10.5px' : '9px',
                      fontWeight: isSelected ? 'bold' : 'normal',
                      fill: isSelected ? 'var(--amber)' : 'var(--ink)',
                      paintOrder: 'stroke',
                      stroke: 'var(--bg)',
                      strokeWidth: '2.5px',
                      strokeLinejoin: 'round',
                      pointerEvents: 'none'
                    }}
                  >
                    {node.title.length > 15 ? `${node.title.slice(0, 12)}…` : node.title}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>

        {/* Floating Canvas Toolbar Controls */}
        <div className="soundmap-controls">
          <div className="control-group">
            <span className="control-label">Layout:</span>
            <button
              className={`control-btn ${layoutMode === 'mood' ? 'active' : ''}`}
              onClick={() => setLayoutMode('mood')}
            >
              Moods
            </button>
            <button
              className={`control-btn ${layoutMode === 'radial' ? 'active' : ''}`}
              onClick={() => setLayoutMode('radial')}
            >
              Radial (Time)
            </button>
            <button
              className={`control-btn ${layoutMode === 'central' ? 'active' : ''}`}
              onClick={() => setLayoutMode('central')}
            >
              Central
            </button>
          </div>

          <div className="control-divider" />

          <div className="control-group">
            <button className="control-btn" onClick={() => handleZoom(1.2)} title="Zoom In">
              ＋
            </button>
            <button className="control-btn" onClick={() => handleZoom(0.8)} title="Zoom Out">
              －
            </button>
            <button className="control-btn" onClick={handleReset} title="Reset Scale & Center">
              ☉ Reset
            </button>
          </div>
        </div>

        {/* Selected Entry Detail Drawer popup */}
        {selectedEntry && (
          <div className="soundmap-drawer">
            <div className="drawer-header">
              <span className="drawer-date">
                {new Date(selectedEntry.local_capture_time).toLocaleDateString(undefined, {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric'
                })}
              </span>
              <button className="drawer-close" onClick={() => setSelectedEntry(null)} aria-label="Close details">
                ×
              </button>
            </div>

            <div className="drawer-content">
              <h3 className="drawer-title">{selectedEntry.title || 'Untitled recording'}</h3>
              
              {/* Badge tags section */}
              <div className="drawer-tags">
                {selectedEntry.context?.mood && (
                  <span className="drawer-tag tag-mood" style={{ background: getMoodColor(selectedEntry.context.mood) }}>
                    {selectedEntry.context.mood}
                  </span>
                )}
                {selectedEntry.context?.location && (
                  <span className="drawer-tag tag-loc">
                    📍 {selectedEntry.context.location}
                  </span>
                )}
                {selectedEntry.context?.companions?.map(comp => (
                  <span key={comp} className="drawer-tag tag-comp">
                    👤 {comp}
                  </span>
                ))}
              </div>

              {/* Waveform Player */}
              <div className="drawer-player-container">
                <InteractivePlayer
                  entryId={selectedEntry.id}
                  durationMs={selectedEntry.asset?.duration_ms ?? undefined}
                  playing={isPlaying}
                  onPlayStateChange={setIsPlaying}
                  onTimeUpdate={setCurrentTime}
                  onDurationChange={setDuration}
                  seekToTime={seekToTime}
                  onSeekComplete={() => setSeekToTime(null)}
                />
              </div>

              {/* Transcription / Notes with Karaoke support */}
              <div className="drawer-notes-section">
                <h4 className="section-subtitle">Notes & Transcript</h4>
                {selectedEntry.context?.notes ? (
                  showKaraoke ? (
                    <div className="karaoke-container">
                      {words.map((word, i) => {
                        const isActive = i === activeWordIndex
                        return (
                          <span
                            key={i}
                            className={`karaoke-word${isActive ? ' active' : ''}`}
                            onClick={() => handleWordClick(i)}
                            style={{ cursor: 'pointer' }}
                          >
                            {word}
                          </span>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="drawer-notes">"{selectedEntry.context.notes}"</p>
                  )
                ) : (
                  <p className="drawer-notes-empty">No transcription notes available.</p>
                )}
              </div>

              {/* Meta information summary */}
              <div className="drawer-meta-list">
                {selectedEntry.asset?.duration_ms && (
                  <div className="meta-item">
                    <span className="meta-label">Duration:</span>
                    <span className="meta-value">{formatDuration(selectedEntry.asset.duration_ms)}</span>
                  </div>
                )}
                {selectedEntry.asset?.byte_size && (
                  <div className="meta-item">
                    <span className="meta-label">File Size:</span>
                    <span className="meta-value">{formatBytes(selectedEntry.asset.byte_size)}</span>
                  </div>
                )}
                {selectedEntry.asset?.bpm && (
                  <div className="meta-item">
                    <span className="meta-label">Tempo:</span>
                    <span className="meta-value">{Math.round(selectedEntry.asset.bpm)} BPM</span>
                  </div>
                )}
                {selectedEntry.asset?.musical_key && (
                  <div className="meta-item">
                    <span className="meta-label">Musical Key:</span>
                    <span className="meta-value">{selectedEntry.asset.musical_key}</span>
                  </div>
                )}
                <div className="meta-item">
                  <span className="meta-label">Captured:</span>
                  <span className="meta-value">
                    {new Date(selectedEntry.local_capture_time).toLocaleTimeString(undefined, {
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
