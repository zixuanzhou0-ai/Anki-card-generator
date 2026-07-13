import { convertFileSrc, invoke } from '@tauri-apps/api/core'
import { appLocalDataDir } from '@tauri-apps/api/path'
import { open as openDialog } from '@tauri-apps/plugin-dialog'
import { isTauriRuntime } from './runtime'

export async function selectSingleFile(filters: Array<{ name: string; extensions: string[] }>) {
  return openDialog({
    multiple: false,
    directory: false,
    filters,
  })
}

export type SelectDirectoryOptions = {
  title?: string
  defaultPath?: string | null
}

export async function defaultExportDirectory() {
  if (!isTauriRuntime()) return null
  try {
    return await appLocalDataDir()
  } catch {
    return null
  }
}

export async function selectDirectory(options: SelectDirectoryOptions = {}) {
  return openDialog({
    directory: true,
    multiple: false,
    ...(options.title ? { title: options.title } : {}),
    ...(options.defaultPath ? { defaultPath: options.defaultPath } : {}),
  })
}

export async function listDirectoryFiles(directory: string) {
  if (!isTauriRuntime()) return []
  return invoke<string[]>('list_directory_files', { directory })
}

export async function preparePreviewAssetUrl(path: string) {
  if (!isTauriRuntime()) return ''
  const authorizedPath = await invoke<string>('allow_preview_asset', { path })
  return convertFileSrc(authorizedPath)
}

export async function suggestSubtitlePath(videoPath: string, language: string) {
  if (!isTauriRuntime()) return null
  return invoke<string | null>('suggest_subtitle_path', { videoPath, language })
}

export async function revealPath(path: string) {
  await invoke('reveal_path', { path })
}

export async function openAnkiImport(apkgPath: string) {
  await invoke('open_anki_import', { apkgPath })
}
