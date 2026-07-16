import { convertFileSrc, invoke } from '@tauri-apps/api/core'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { isTauriRuntime } from './runtime'
import { inspectRecoveryFile, preparePreviewAssetUrl } from './nativeShell'

vi.mock('@tauri-apps/api/core', () => ({ convertFileSrc: vi.fn(), invoke: vi.fn() }))
vi.mock('@tauri-apps/api/path', () => ({ appLocalDataDir: vi.fn() }))
vi.mock('@tauri-apps/plugin-dialog', () => ({ open: vi.fn() }))
vi.mock('./runtime', () => ({ isTauriRuntime: vi.fn() }))

const convertFileSrcMock = vi.mocked(convertFileSrc)
const invokeMock = vi.mocked(invoke)
const isTauriRuntimeMock = vi.mocked(isTauriRuntime)

describe('preparePreviewAssetUrl', () => {
  beforeEach(() => {
    convertFileSrcMock.mockReset()
    invokeMock.mockReset()
    isTauriRuntimeMock.mockReset()
  })

  it('authorizes the exact local video before converting it to an asset URL', async () => {
    isTauriRuntimeMock.mockReturnValue(true)
    invokeMock.mockResolvedValue('E:\\lesson\\clip.mp4')
    convertFileSrcMock.mockReturnValue('http://asset.localhost/clip.mp4')

    await expect(preparePreviewAssetUrl('E:\\lesson\\clip.mp4')).resolves.toBe('http://asset.localhost/clip.mp4')
    expect(invokeMock).toHaveBeenCalledWith('allow_preview_asset', { path: 'E:\\lesson\\clip.mp4' })
    expect(convertFileSrcMock).toHaveBeenCalledWith('E:\\lesson\\clip.mp4')
  })

  it('does not expose a browser-only path', async () => {
    isTauriRuntimeMock.mockReturnValue(false)

    await expect(preparePreviewAssetUrl('E:\\lesson\\clip.mp4')).resolves.toBe('')
    expect(invokeMock).not.toHaveBeenCalled()
    expect(convertFileSrcMock).not.toHaveBeenCalled()
  })
})

describe('inspectRecoveryFile', () => {
  beforeEach(() => {
    invokeMock.mockReset()
    isTauriRuntimeMock.mockReset()
  })

  it('requests SHA-256 evidence for an APKG through the native read-only command', async () => {
    const evidence = {
      ok: true,
      exists: true,
      isFile: true,
      size: 123,
      modifiedAtMs: 1_000,
      sha256: 'abc123',
      error: null,
    }
    isTauriRuntimeMock.mockReturnValue(true)
    invokeMock.mockResolvedValue(evidence)

    await expect(inspectRecoveryFile('E:\\cards\\lesson.apkg', true)).resolves.toEqual(evidence)
    expect(invokeMock).toHaveBeenCalledWith('inspect_recovery_file', {
      path: 'E:\\cards\\lesson.apkg',
      computeSha256: true,
    })
  })

  it('returns a structured error outside the desktop runtime', async () => {
    isTauriRuntimeMock.mockReturnValue(false)

    await expect(inspectRecoveryFile('E:\\cards\\lesson.apkg')).resolves.toMatchObject({
      ok: false,
      exists: false,
      isFile: false,
      error: {
        code: 'NATIVE_RUNTIME_REQUIRED',
        retryable: false,
      },
    })
    expect(invokeMock).not.toHaveBeenCalled()
  })
})
