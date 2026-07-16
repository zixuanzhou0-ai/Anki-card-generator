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

export type OutputDirectoryAvailability = 'writable' | 'missing' | 'not_writable'

export async function checkOutputDirectory(directory: string): Promise<OutputDirectoryAvailability> {
  if (!isTauriRuntime()) return 'not_writable'
  return invoke<OutputDirectoryAvailability>('check_output_directory', { directory })
}

export type RecoveryFileInspectionError = {
  code:
    | 'INVALID_PATH'
    | 'UNSAFE_PATH'
    | 'METADATA_UNAVAILABLE'
    | 'UNSAFE_FILE_TYPE'
    | 'NOT_REGULAR_FILE'
    | 'MODIFIED_TIME_UNAVAILABLE'
    | 'HASH_READ_FAILED'
    | 'FILE_CHANGED_DURING_INSPECTION'
    | 'NATIVE_RUNTIME_REQUIRED'
  message: string
  retryable: boolean
}

export type RecoveryFileInspection = {
  ok: boolean
  exists: boolean
  isFile: boolean
  size: number | null
  modifiedAtMs: number | null
  sha256: string | null
  error: RecoveryFileInspectionError | null
}

export async function inspectRecoveryFile(path: string, computeSha256 = false): Promise<RecoveryFileInspection> {
  if (!isTauriRuntime()) {
    return {
      ok: false,
      exists: false,
      isFile: false,
      size: null,
      modifiedAtMs: null,
      sha256: null,
      error: {
        code: 'NATIVE_RUNTIME_REQUIRED',
        message: '文件恢复证据只能在桌面端检查。',
        retryable: false,
      },
    }
  }
  return invoke<RecoveryFileInspection>('inspect_recovery_file', { path, computeSha256 })
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

export async function ensureAnkiRunning() {
  await invoke('ensure_anki_running')
}
