import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { isTauriRuntime } from './runtime'
import { allowNextNativeWindowClose, listenForNativeCloseRequest } from './nativeCloseEvents'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: vi.fn() }))
vi.mock('./runtime', () => ({ isTauriRuntime: vi.fn() }))

const invokeMock = vi.mocked(invoke)
const getCurrentWindowMock = vi.mocked(getCurrentWindow)
const isTauriRuntimeMock = vi.mocked(isTauriRuntime)

describe('listenForNativeCloseRequest', () => {
  beforeEach(() => {
    invokeMock.mockReset()
    getCurrentWindowMock.mockReset()
    isTauriRuntimeMock.mockReset()
  })

  it('subscribes to the native guarded-close event in Tauri', async () => {
    const unlisten = vi.fn()
    const listen = vi.fn(async (_event: string, listener: () => void) => {
      listener()
      return unlisten
    })
    const handler = vi.fn()
    isTauriRuntimeMock.mockReturnValue(true)
    getCurrentWindowMock.mockReturnValue({ listen } as never)

    await expect(listenForNativeCloseRequest(handler)).resolves.toBe(unlisten)
    expect(listen).toHaveBeenCalledWith('app-close-requested', expect.any(Function))
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('is a no-op in browser tests', async () => {
    isTauriRuntimeMock.mockReturnValue(false)
    const handler = vi.fn()

    const unlisten = await listenForNativeCloseRequest(handler)
    unlisten()

    expect(getCurrentWindowMock).not.toHaveBeenCalled()
    expect(handler).not.toHaveBeenCalled()
  })

  it('arms native close only in Tauri', async () => {
    isTauriRuntimeMock.mockReturnValue(true)
    invokeMock.mockResolvedValue(undefined)

    await allowNextNativeWindowClose()

    expect(invokeMock).toHaveBeenCalledWith('allow_next_window_close')
  })
})
