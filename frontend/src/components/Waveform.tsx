import { useState, useEffect } from 'react'
import { api } from '../api'
import { fakeWaveform } from '../utils'

interface Props {
  entryId: string
  bars?: number
}

export function Waveform({ entryId, bars = 60 }: Props) {
  const [heights, setHeights] = useState<number[]>(() => fakeWaveform(entryId, bars))
  const [real, setReal] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.getWaveform(entryId, bars)
      .then(data => {
        if (!cancelled && data.peaks.length > 0) {
          setHeights(data.peaks)
          setReal(true)
        }
      })
      .catch(() => {
        // Keep fake waveform on error (entry may still be processing)
      })
    return () => { cancelled = true }
  }, [entryId, bars])

  return (
    <div className="waveform" aria-hidden="true" title={real ? 'Real waveform' : 'Placeholder waveform'}>
      {heights.map((h, i) => (
        <div
          key={i}
          className="waveform-bar"
          style={{ height: `${Math.round(h * 28)}px` }}
        />
      ))}
    </div>
  )
}
