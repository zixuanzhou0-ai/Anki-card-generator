import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppErrorBoundary } from './app/AppErrorBoundary'
import App from './App'
import './app.css'
import { recordRendererError } from './services/tauriWorker'

function serializeError(value: unknown) {
  if (value instanceof Error) {
    return {
      name: value.name,
      message: value.message,
      stack: value.stack,
    }
  }
  return {
    message: typeof value === 'string' ? value : JSON.stringify(value),
  }
}

function recordGlobalRendererError(kind: string, payload: Record<string, unknown>) {
  void recordRendererError({
    kind,
    at: new Date().toISOString(),
    url: window.location.href,
    ...payload,
  }).catch(() => {
    // The renderer may be tearing down; crash breadcrumbs are best-effort.
  })
}

window.addEventListener('error', (event) => {
  recordGlobalRendererError('window_error', {
    message: event.message,
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
    error: serializeError(event.error),
  })
})

window.addEventListener('unhandledrejection', (event) => {
  recordGlobalRendererError('unhandledrejection', {
    reason: serializeError(event.reason),
  })
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
)
