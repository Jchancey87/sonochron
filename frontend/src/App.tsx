import { useState } from 'react'
import { TimelineView } from './views/TimelineView'
import { CaptureView } from './views/CaptureView'
import { SearchView } from './views/SearchView'
import { DriveImportView } from './views/DriveImportView'
import { SettingsView } from './views/SettingsView'

type Tab = 'capture' | 'timeline' | 'search' | 'import' | 'settings'

export default function App() {
  const [tab, setTab] = useState<Tab>('timeline')
  const [toast, setToast] = useState<string | null>(null)

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 2800)
  }

  return (
    <div className="app">
      <nav>
        <button
          id="nav-capture"
          className={tab === 'capture' ? 'active' : ''}
          onClick={() => setTab('capture')}
        >Capture</button>
        <button
          id="nav-timeline"
          className={tab === 'timeline' ? 'active' : ''}
          onClick={() => setTab('timeline')}
        >Timeline</button>
        <button
          id="nav-search"
          className={tab === 'search' ? 'active' : ''}
          onClick={() => setTab('search')}
        >Search</button>
        <button
          id="nav-import"
          className={tab === 'import' ? 'active' : ''}
          onClick={() => setTab('import')}
        >Import</button>
        <button
          id="nav-settings"
          className={tab === 'settings' ? 'active' : ''}
          onClick={() => setTab('settings')}
        >Settings</button>
      </nav>

      {tab === 'timeline' && <TimelineView />}
      {tab === 'capture'  && <CaptureView onSaved={() => { showToast('Entry saved'); setTab('timeline') }} />}
      {tab === 'search'   && <SearchView />}
      {tab === 'import'   && <DriveImportView />}
      {tab === 'settings' && <SettingsView />}

      <div className={`toast${toast ? ' visible' : ''}`}>{toast}</div>
    </div>
  )
}

