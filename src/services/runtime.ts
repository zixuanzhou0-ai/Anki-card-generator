export function isTauriRuntime() {
  if (typeof window === 'undefined') return false
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__)
}
