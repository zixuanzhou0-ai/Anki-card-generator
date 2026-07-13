import { convertFileSrc, invoke } from '@tauri-apps/api/core'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { isTauriRuntime } from './runtime'
import { preparePreviewAssetUrl } from './nativeShell'

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
