import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import TimelinePlugin from 'wavesurfer.js/dist/plugins/timeline.esm.js'
import HoverPlugin from 'wavesurfer.js/dist/plugins/hover.esm.js'
import SpectrogramPlugin from 'wavesurfer.js/dist/plugins/spectrogram.esm.js'
import { api } from '../api'
import { formatRecordingTime } from '../utils'
import { useSettings } from '../contexts/SettingsContext'

interface Props {
  entryId: string
  durationMs?: number
  playing: boolean
  onPlayStateChange: (playing: boolean) => void
  onTimeUpdate?: (time: number) => void
  onDurationChange?: (duration: number) => void
  seekToTime?: number | null
  onSeekComplete?: () => void
}

export function InteractivePlayer({
  entryId,
  durationMs,
  playing,
  onPlayStateChange,
  onTimeUpdate,
  onDurationChange,
  seekToTime,
  onSeekComplete,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const spectrogramRef = useRef<HTMLDivElement>(null)
  const wavesurferRef = useRef<WaveSurfer | null>(null)

  const { settings } = useSettings()

  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState((durationMs || 0) / 1000)
  const [zoom, setZoom] = useState(10)
  const [isMuted, setIsMuted] = useState(false)
  const [loading, setLoading] = useState(true)

  // Fetch peaks from API on mount/entryId change
  const [peaks, setPeaks] = useState<number[] | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.getWaveform(entryId, 300)
      .then(data => {
        if (!cancelled && data.peaks && data.peaks.length > 0) {
          setPeaks(data.peaks)
        }
      })
      .catch(() => {
        // Fallback to null (wavesurfer will decode automatically)
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [entryId])

  // Initialize WaveSurfer after peaks state is determined
  useEffect(() => {
    if (!containerRef.current || loading) return

    const plugins: any[] = [
      HoverPlugin.create({
        lineColor: '#B8832A',
        lineWidth: 1.5,
        labelBackground: '#1C1A18',
        labelColor: '#F5F0E8',
        labelSize: '10px',
      }),
      TimelinePlugin.create({
        container: timelineRef.current || undefined,
        height: 18,
        style: {
          fontSize: '10px',
          fontFamily: 'var(--mono)',
          color: 'var(--ink-muted)',
        },
      }),
    ]

    if (settings.spectrogramViewEnabled) {
      plugins.push(
        SpectrogramPlugin.create({
          container: spectrogramRef.current || undefined,
          labels: true,
          height: 64,
        })
      )
    }

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: 'rgba(28, 26, 24, 0.25)',
      progressColor: '#B8832A',
      cursorColor: '#1C1A18',
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1.5,
      barRadius: 1,
      height: 64,
      normalize: true,
      plugins,
    })

    wavesurferRef.current = ws

    const audioUrl = api.getAudioUrl(entryId)
    const durationSec = durationMs ? durationMs / 1000 : undefined

    // Load audio with pre-computed peaks if available to bypass network decode step
    if (peaks && peaks.length > 0) {
      ws.load(audioUrl, [peaks], durationSec)
    } else {
      ws.load(audioUrl)
    }

    // Synchronize play state
    ws.on('play', () => onPlayStateChange(true))
    ws.on('pause', () => onPlayStateChange(false))
    ws.on('timeupdate', (time) => {
      setCurrentTime(time)
      onTimeUpdate?.(time)
    })
    ws.on('ready', (dur) => {
      setDuration(dur)
      onDurationChange?.(dur)
      // Apply initial play state
      if (playing) {
        ws.play().catch(() => {})
      }
    })

    return () => {
      ws.destroy()
      wavesurferRef.current = null
    }
  }, [entryId, loading, settings.spectrogramViewEnabled]) // Re-init if entryId changes, loading changes, or spectrogram setting changes

  // Control playback from props
  useEffect(() => {
    const ws = wavesurferRef.current
    if (!ws) return

    if (playing && !ws.isPlaying()) {
      ws.play().catch(() => {})
    } else if (!playing && ws.isPlaying()) {
      ws.pause()
    }
  }, [playing])

  // Handle seeking from props
  useEffect(() => {
    if (seekToTime !== undefined && seekToTime !== null && wavesurferRef.current) {
      wavesurferRef.current.setTime(seekToTime)
      onSeekComplete?.()
    }
  }, [seekToTime, onSeekComplete])

  // Handle zoom changes
  useEffect(() => {
    const ws = wavesurferRef.current
    if (ws) {
      ws.zoom(zoom)
    }
  }, [zoom])

  function handlePlayPause() {
    const ws = wavesurferRef.current
    if (ws) {
      if (ws.isPlaying()) {
        ws.pause()
      } else {
        window.dispatchEvent(new CustomEvent('sonochron:play', { detail: entryId }))
        ws.play().catch(() => {})
      }
    }
  }

  function handleMute() {
    const ws = wavesurferRef.current
    if (ws) {
      ws.setMuted(!isMuted)
      setIsMuted(!isMuted)
    }
  }

  return (
    <div className="interactive-player">
      <div className="player-waveform-wrap">
        <div ref={containerRef} className="player-waveform" />
        {settings.spectrogramViewEnabled && (
          <div ref={spectrogramRef} className="player-spectrogram" />
        )}
        <div ref={timelineRef} className="player-timeline" />
      </div>

      <div className="player-controls">
        <button
          type="button"
          className="player-btn-play"
          onClick={handlePlayPause}
          title={playing ? 'Pause' : 'Play'}
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? 'Pause' : 'Play'}
        </button>

        <button
          type="button"
          className="player-btn-mute"
          onClick={handleMute}
          title={isMuted ? 'Unmute' : 'Mute'}
          aria-label={isMuted ? 'Unmute' : 'Mute'}
        >
          {isMuted ? 'Unmute' : 'Mute'}
        </button>

        <div className="player-time">
          {formatRecordingTime(Math.round(currentTime))} / {formatRecordingTime(Math.round(duration))}
        </div>

        <div className="player-zoom-control">
          <label htmlFor={`zoom-${entryId}`}>Zoom</label>
          <input
            id={`zoom-${entryId}`}
            type="range"
            min="10"
            max="150"
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
          />
        </div>
      </div>
    </div>
  )
}
