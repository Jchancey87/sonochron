import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RecordPlugin from 'wavesurfer.js/dist/plugins/record.esm.js'
import HoverPlugin from 'wavesurfer.js/dist/plugins/hover.esm.js'
import { formatRecordingTime } from '../utils'

interface Props {
  onAudioReady: (blob: Blob | null, file: File | null) => void
  onReset: () => void
}

type RecordState = 'idle' | 'recording' | 'stopped'

export function CaptureAudioSection({ onAudioReady, onReset }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const wavesurferRef = useRef<WaveSurfer | null>(null)
  const recordPluginRef = useRef<any>(null)

  const [recordState, setRecordState] = useState<RecordState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Stopped preview playback state
  const [playing, setPlaying] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [audioName, setAudioName] = useState<string>('')

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (wavesurferRef.current) {
        wavesurferRef.current.destroy()
      }
    }
  }, [])

  // Initialize WaveSurfer for Recording or Previewing
  const initWaveSurfer = (isForRecording: boolean) => {
    if (wavesurferRef.current) {
      wavesurferRef.current.destroy()
      wavesurferRef.current = null
    }

    if (!containerRef.current) return

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: 'rgba(28, 26, 24, 0.25)',
      progressColor: '#B8832A',
      cursorColor: '#1C1A18',
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1.5,
      barRadius: 1,
      height: 80,
      plugins: !isForRecording
        ? [
            HoverPlugin.create({
              lineColor: '#B8832A',
              lineWidth: 1.5,
              labelBackground: '#1C1A18',
              labelColor: '#F5F0E8',
              labelSize: '10px',
            }),
          ]
        : [],
    })

    wavesurferRef.current = ws

    if (isForRecording) {
      const record = ws.registerPlugin(
        RecordPlugin.create({
          scrollingWaveform: true,
          scrollingWaveformWindow: 10,
          mimeType: 'audio/webm',
        })
      )
      recordPluginRef.current = record

      record.on('record-end', (blob: Blob) => {
        setAudioName(`Recording (${new Date().toLocaleTimeString()})`)
        const url = URL.createObjectURL(blob)
        
        // Re-initialize wavesurfer in non-recording mode to play the recorded audio
        initWaveSurfer(false)
        if (wavesurferRef.current) {
          wavesurferRef.current.load(url)
        }
        
        onAudioReady(blob, null)
      })
    } else {
      recordPluginRef.current = null
      ws.on('play', () => setPlaying(true))
      ws.on('pause', () => setPlaying(false))
      ws.on('finish', () => setPlaying(false))
    }
  }

  // Handle start recording
  async function startRecording() {
    setError(null)
    setElapsed(0)
    onReset()

    try {
      // First initialize in recording mode
      initWaveSurfer(true)
      
      const record = recordPluginRef.current
      if (!record) throw new Error('Record plugin not initialized')

      await record.startRecording()
      setRecordState('recording')

      timerRef.current = setInterval(() => {
        setElapsed((s) => s + 1)
      }, 1000)
    } catch (err) {
      setError('Microphone access denied. Please allow microphone permission and try again.')
      setRecordState('idle')
      if (wavesurferRef.current) {
        wavesurferRef.current.destroy()
        wavesurferRef.current = null
      }
    }
  }

  // Handle stop recording
  function stopRecording() {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }

    const record = recordPluginRef.current
    if (record && record.isRecording()) {
      record.stopRecording()
    }
    setRecordState('stopped')
  }

  // Reset to idle
  function handleReset() {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (wavesurferRef.current) {
      wavesurferRef.current.destroy()
      wavesurferRef.current = null
    }
    setRecordState('idle')
    setElapsed(0)
    setPlaying(false)
    setIsMuted(false)
    setAudioName('')
    setError(null)
    onReset()
  }

  // Handle file drop/selection
  function loadFile(file: File) {
    setError(null)
    setAudioName(file.name)
    setRecordState('stopped')

    initWaveSurfer(false)
    if (wavesurferRef.current) {
      const url = URL.createObjectURL(file)
      wavesurferRef.current.load(url)
    }

    onAudioReady(null, file)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f && f.type.startsWith('audio/')) {
      loadFile(f)
    } else {
      setError('Please drop a valid audio file.')
    }
  }

  function handlePlayPause() {
    const ws = wavesurferRef.current
    if (ws) {
      if (ws.isPlaying()) {
        ws.pause()
      } else {
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

  const dotClass = `record-dot-wrap${recordState === 'recording' ? ' recording' : ''}`

  return (
    <div className="capture-audio-section">
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
          onKeyDown={(e) =>
            e.key === 'Enter' && (recordState === 'recording' ? stopRecording() : startRecording())
          }
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
      </div>

      {/* Wavesurfer Container (Active during recording or stopped preview) */}
      <div
        className="capture-waveform-wrap"
        style={{
          display: recordState !== 'idle' ? 'block' : 'none',
          width: '100%',
          maxWidth: '540px',
          margin: '24px auto',
        }}
      >
        <div ref={containerRef} className="capture-waveform" />
        {audioName && <div className="capture-audio-filename">{audioName}</div>}

        {recordState === 'stopped' && (
          <div className="capture-preview-controls">
            <button type="button" className="preview-btn-play" onClick={handlePlayPause}>
              {playing ? 'Pause' : 'Play'}
            </button>
            <button type="button" className="preview-btn-mute" onClick={handleMute}>
              {isMuted ? 'Unmute' : 'Mute'}
            </button>
            <button type="button" className="preview-btn-reset" onClick={handleReset}>
              Discard
            </button>
          </div>
        )}
      </div>

      {/* Upload zone — visible when idle */}
      {recordState === 'idle' && (
        <div
          className={`upload-zone${dragOver ? ' drag-over' : ''}`}
          style={{ width: '100%', maxWidth: '540px', margin: '0 auto 32px' }}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
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
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) {
                loadFile(f)
              }
            }}
          />
        </div>
      )}

      {error && (
        <p style={{ fontFamily: 'var(--mono)', fontSize: '12px', color: '#c0392b', textAlign: 'center', marginTop: '8px' }}>
          {error}
        </p>
      )}
    </div>
  )
}
