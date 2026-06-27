import { useSettings } from '../contexts/SettingsContext'

export function SettingsView() {
  const { settings, updateSettings } = useSettings()

  return (
    <div className="settings-view" id="settings-view">
      <h2 className="settings-heading">Settings</h2>

      <div className="settings-group">
        <div className="settings-item">
          <div className="settings-info">
            <label htmlFor="toggle-mood-themes" className="settings-label">Dynamic Mood Themes</label>
            <span className="settings-desc">Apply unique background colors based on your recorded entry's mood.</span>
          </div>
          <div className="settings-control">
            <input
              id="toggle-mood-themes"
              type="checkbox"
              className="settings-toggle"
              checked={settings.moodThemesEnabled}
              onChange={(e) => updateSettings({ moodThemesEnabled: e.target.checked })}
            />
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-info">
            <label htmlFor="toggle-karaoke" className="settings-label">Transcript Karaoke</label>
            <span className="settings-desc">Highlight words synchronously with audio playback in the expanded view.</span>
          </div>
          <div className="settings-control">
            <input
              id="toggle-karaoke"
              type="checkbox"
              className="settings-toggle"
              checked={settings.transcriptKaraokeEnabled}
              onChange={(e) => updateSettings({ transcriptKaraokeEnabled: e.target.checked })}
            />
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-info">
            <label htmlFor="toggle-spectrogram" className="settings-label">Spectrogram View</label>
            <span className="settings-desc">Render a spectrogram visualization below the waveform.</span>
          </div>
          <div className="settings-control">
            <input
              id="toggle-spectrogram"
              type="checkbox"
              className="settings-toggle"
              checked={settings.spectrogramViewEnabled}
              onChange={(e) => updateSettings({ spectrogramViewEnabled: e.target.checked })}
            />
          </div>
        </div>

        <div className="settings-item">
          <div className="settings-info">
            <label htmlFor="toggle-soundmap" className="settings-label">Sound Map</label>
            <span className="settings-desc">Enable interactive 2D graph view of entries.</span>
          </div>
          <div className="settings-control">
            <input
              id="toggle-soundmap"
              type="checkbox"
              className="settings-toggle"
              checked={settings.soundMapEnabled}
              onChange={(e) => updateSettings({ soundMapEnabled: e.target.checked })}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
