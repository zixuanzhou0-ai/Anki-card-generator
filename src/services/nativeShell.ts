import { convertFileSrc, invoke } from '@tauri-apps/api/core'
import { open as openDialog } from '@tauri-apps/plugin-dialog'
import { isTauriRuntime } from './runtime'

export async function selectSingleFile(filters: Array<{ name: string; extensions: string[] }>) {
  return openDialog({
    multiple: false,
    directory: false,
    filters,
  })
}

export async function selectDirectory() {
  return openDialog({ directory: true, multiple: false })
}

export function toAssetUrl(path: string) {
  return isTauriRuntime() ? convertFileSrc(path) : ''
}

export async function revealPath(path: string) {
  await invoke('reveal_path', { path })
}

export async function openAnkiImport(apkgPath: string) {
  await invoke('open_anki_import', { apkgPath })
}
