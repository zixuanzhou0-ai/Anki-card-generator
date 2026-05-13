import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { EnvSettingsPanel } from './EnvSettingsPanel'

describe('EnvSettingsPanel', () => {
  it('shows unchecked state and can trigger environment check', () => {
    const onCheckEnv = vi.fn()

    render(<EnvSettingsPanel appBusy={false} envStatus={null} onCheckEnv={onCheckEnv} />)

    fireEvent.click(screen.getByRole('button', { name: /检查环境/ }))

    expect(screen.getByText('尚未检查')).toBeInTheDocument()
    expect(screen.getByText('运行 setup_runtime.ps1')).toBeInTheDocument()
    expect(onCheckEnv).toHaveBeenCalledOnce()
  })

  it('renders dependency and diagnostic details', () => {
    render(
      <EnvSettingsPanel
        appBusy={false}
        envStatus={{
          anki_connect: false,
          ffmpeg: true,
          genanki: true,
          python: '3.12.0',
          python_executable: 'E:\\ANKI\\.venv\\Scripts\\python.exe',
          status_items: [{ detail: '已安装', id: 'python', label: 'Python', status: 'ok' }],
          worker: 'E:\\ANKI\\workers\\anki_worker.py',
          yt_dlp: true,
          yt_dlp_js_runtime: 'node',
          yt_dlp_version: '2026.03.17',
        }}
        onCheckEnv={vi.fn()}
      />,
    )

    expect(screen.getByText('Python 3.12.0')).toBeInTheDocument()
    expect(screen.getByText('yt-dlp 2026.03.17')).toBeInTheDocument()
    expect(screen.getByText(/Worker: E:\\ANKI\\workers\\anki_worker.py/)).toBeInTheDocument()
  })
})
