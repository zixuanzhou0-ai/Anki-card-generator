import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { EnvSettingsPanel } from './EnvSettingsPanel'

afterEach(() => cleanup())

describe('EnvSettingsPanel', () => {
  it('shows unchecked state and can trigger environment check', () => {
    const onCheckEnv = vi.fn()

    render(
      <EnvSettingsPanel
        appBusy={false}
        envRepairing={false}
        envRepairResult={null}
        envStatus={null}
        onCheckEnv={onCheckEnv}
        onRepairEnv={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /检查环境/ }))

    expect(screen.getByText('本地环境诊断中心')).toBeInTheDocument()
    expect(screen.getAllByText('尚未检查').length).toBeGreaterThan(0)
    expect(screen.getByText('一键修复依赖')).toBeInTheDocument()
    expect(onCheckEnv).toHaveBeenCalledOnce()
  })

  it('renders dependency and diagnostic details', () => {
    render(
      <EnvSettingsPanel
        appBusy={false}
        envRepairing={false}
        envRepairResult={null}
        envStatus={{
          anki_connect: false,
          anki_installed: true,
          anki_path: 'C:\\Program Files\\Anki\\anki.exe',
          anki_running: false,
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
        onRepairEnv={vi.fn()}
      />,
    )

    expect(screen.getAllByText('Python 3.12.0').length).toBeGreaterThan(0)
    expect(screen.getByText('基本可用')).toBeInTheDocument()
    expect(screen.getAllByText('yt-dlp 2026.03.17').length).toBeGreaterThan(0)
    expect(screen.getByText(/Worker: E:\\ANKI\\workers\\anki_worker.py/)).toBeInTheDocument()
  })

  it('keeps technical paths out of simple mode while preserving them in advanced mode', () => {
    const envStatus = {
      anki_connect: true,
      anki_installed: true,
      ffmpeg: true,
      genanki: true,
      python: '3.12.0',
      python_executable: 'E:\\ANKI\\.venv\\Scripts\\python.exe',
      worker: 'E:\\ANKI\\workers\\anki_worker.py',
      yt_dlp: true,
    }
    const props = {
      appBusy: false,
      envRepairing: false,
      envRepairResult: null,
      envStatus,
      onCheckEnv: vi.fn(),
      onRepairEnv: vi.fn(),
    }
    const { rerender } = render(<EnvSettingsPanel {...props} simpleMode />)

    expect(screen.getByText('本地环境')).toBeInTheDocument()
    expect(screen.queryByText(/Worker:/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Python: E:\\ANKI\\.venv/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText('本地能力状态')).not.toBeInTheDocument()

    rerender(<EnvSettingsPanel {...props} simpleMode={false} />)

    expect(screen.getByText(/Worker: E:\\ANKI\\workers\\anki_worker.py/)).toBeInTheDocument()
    expect(screen.getByText(/Python: E:\\ANKI\\.venv\\Scripts\\python.exe/)).toBeInTheDocument()
    expect(screen.getByLabelText('本地能力状态')).toBeInTheDocument()
  })

  it('shows repair actions and calls the repair handler', () => {
    const onRepairEnv = vi.fn()
    render(
      <EnvSettingsPanel
        appBusy={false}
        envRepairing={false}
        envRepairResult={{
          ok: true,
          target: 'all',
          summary: '已执行 2 个修复步骤；失败 0 个，需手动处理 0 个。',
          actions: [{ detail: '已安装依赖', id: 'python_packages', label: '安装/更新 worker Python 依赖', status: 'success' }],
        }}
        envStatus={{
          ffmpeg: false,
          genanki: false,
          python: '3.12.0',
          status_items: [
            { detail: '缺少 genanki。', fix: '运行 scripts/setup_runtime.ps1', id: 'genanki', label: 'genanki APKG 导出', status: 'blocked' },
            { detail: '未在 PATH 找到 ffmpeg。', fix: '安装 FFmpeg', id: 'ffmpeg', label: 'FFmpeg 视频切片', status: 'blocked' },
          ],
          worker: 'E:\\ANKI\\workers\\anki_worker.py',
          yt_dlp: false,
        }}
        onCheckEnv={vi.fn()}
        onRepairEnv={onRepairEnv}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /一键修复全部可修复项/ }))
    fireEvent.click(screen.getAllByRole('button', { name: /安装 FFmpeg/ })[0])

    expect(onRepairEnv).toHaveBeenCalledWith('all')
    expect(onRepairEnv).toHaveBeenCalledWith('ffmpeg')
    expect(screen.getByLabelText('环境修复日志')).toBeInTheDocument()
    expect(screen.getByText('已安装依赖')).toBeInTheDocument()
  })

  it('offers native Python runtime repair when Python is missing', () => {
    const onRepairEnv = vi.fn()
    render(
      <EnvSettingsPanel
        appBusy={false}
        envRepairing={false}
        envRepairResult={null}
        envStatus={{
          ffmpeg: false,
          genanki: false,
          python: '',
          status_items: [
            {
              detail: '没有找到可用 Python；worker 无法启动。',
              fix: '点击一键修复安装推荐 Python 3.12。',
              id: 'python',
              label: 'Python 运行环境',
              status: 'blocked',
            },
          ],
          worker: 'E:\\ANKI\\workers\\anki_worker.py',
          yt_dlp: false,
        }}
        onCheckEnv={vi.fn()}
        onRepairEnv={onRepairEnv}
      />,
    )

    fireEvent.click(screen.getAllByRole('button', { name: /安装推荐 Python 3.12|安装 Python/ })[0])

    expect(onRepairEnv).toHaveBeenCalledWith('python_runtime')
  })
})
