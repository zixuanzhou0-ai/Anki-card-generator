import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { isTauriRuntime } from './runtime'

export type StopListening = () => void

/**
 * Bridges OS-level close requests (Alt+F4, taskbar and system menu) into the
 * same guarded renderer flow used by the custom title-bar close button.
 */
export async function listenForNativeCloseRequest(handler: () => void | Promise<void>): Promise<StopListening> {
  if (!isTauriRuntime()) return () => undefined
  return getCurrentWindow().listen('app-close-requested', () => {
    void handler()
  })
}

/**
 * Arms exactly one native close attempt after renderer safety checks pass.
 */
export async function allowNextNativeWindowClose(): Promise<void> {
  if (!isTauriRuntime()) return
  await invoke('allow_next_window_close')
}

/** Clears an armed close permission if the native close call itself fails. */
export async function revokeNativeWindowClosePermission(): Promise<void> {
  if (!isTauriRuntime()) return
  await invoke('disallow_next_window_close')
}
