import React, { createContext, useContext, useState } from 'react'

export interface AppSettings {
  moodThemesEnabled: boolean
  transcriptKaraokeEnabled: boolean
  spectrogramViewEnabled: boolean
}

const DEFAULT_SETTINGS: AppSettings = {
  moodThemesEnabled: true,
  transcriptKaraokeEnabled: true,
  spectrogramViewEnabled: false,
}

interface SettingsContextType {
  settings: AppSettings
  updateSettings: (newSettings: Partial<AppSettings>) => void
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined)

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(() => {
    try {
      const saved = localStorage.getItem('sonochron:settings')
      if (saved) {
        const parsed = JSON.parse(saved)
        return { ...DEFAULT_SETTINGS, ...parsed }
      }
    } catch (e) {
      console.error('Failed to parse settings from localStorage', e)
    }
    return DEFAULT_SETTINGS
  })

  const updateSettings = (newSettings: Partial<AppSettings>) => {
    setSettings((prev) => {
      const updated = { ...prev, ...newSettings }
      localStorage.setItem('sonochron:settings', JSON.stringify(updated))
      return updated
    })
  }

  return (
    <SettingsContext.Provider value={{ settings, updateSettings }}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const context = useContext(SettingsContext)
  if (!context) {
    throw new Error('useSettings must be used within a SettingsProvider')
  }
  return context
}
