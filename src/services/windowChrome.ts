import { getCurrentWindow } from '@tauri-apps/api/window'
import type { MouseEvent } from 'react'
import type { ResizeDirection } from '../domain/types'
import { isTauriRuntime } from './runtime'

export async function runWindowAction(action: 'minimize' | 'toggleMaximize' | 'close') {
  if (!isTauriRuntime()) return
  const appWindow = getCurrentWindow()
  if (action === 'minimize') {
    await appWindow.minimize()
  } else if (action === 'toggleMaximize') {
    await appWindow.toggleMaximize()
  } else {
    await appWindow.close()
  }
}

export async function startWindowDrag(event: MouseEvent<HTMLElement>) {
  if (!isTauriRuntime() || event.detail > 1) return
  await getCurrentWindow().startDragging()
}

export async function startWindowResize(direction: ResizeDirection, event: MouseEvent<HTMLDivElement>) {
  if (!isTauriRuntime()) return
  event.preventDefault()
  await getCurrentWindow().startResizeDragging(direction)
}
