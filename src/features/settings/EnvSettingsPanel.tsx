import { CheckCircle2, Loader2, Settings2 } from 'lucide-react'

import type { EnvStatus } from '../../domain/types'

type EnvSettingsPanelProps = {
  appBusy: boolean
  envStatus: EnvStatus | null
  onCheckEnv: () => void
}

const firstRunSteps = ['解压发布包', '运行 setup_runtime.ps1', '打开 exe', '填写 API Key 并测试', '用内置示例导出 APKG']

export function EnvSettingsPanel({ appBusy, envStatus, onCheckEnv }: EnvSettingsPanelProps) {
  return (
    <section className="settings-section settings-section-single">
      <div className="panel-heading">
        <Settings2 size={20} />
        <h3>本地环境</h3>
      </div>
      <p>首次启动按顺序检查 Python venv、FFmpeg、yt-dlp、genanki、AnkiConnect 和 YouTube challenge solver。不含任何 API Key。</p>
      <div className="settings-row">
        <button className="ghost-button" type="button" onClick={onCheckEnv} disabled={appBusy}>
          {appBusy ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
          检查环境
        </button>
        <div className="env-grid">
          {envStatus ? (
            <>
              <span>Python {envStatus.python ?? '-'}</span>
              <span className={envStatus.ffmpeg ? 'ok' : 'warn'}>ffmpeg</span>
              <span className={envStatus.genanki ? 'ok' : 'warn'}>genanki</span>
              <span className={envStatus.yt_dlp ? 'ok' : 'warn'}>yt-dlp {envStatus.yt_dlp_version ?? ''}</span>
              <span className={envStatus.yt_dlp_js_runtime ? 'ok' : 'warn'}>
                JS {envStatus.yt_dlp_js_runtime || '未配置'}
              </span>
              <span className={envStatus.anki_connect ? 'ok' : 'warn'}>
                AnkiConnect {envStatus.anki_connect ? '可用' : '未连接'}
              </span>
            </>
          ) : (
            <span>尚未检查</span>
          )}
        </div>
      </div>
      <div className="first-run-steps" aria-label="普通用户 5 步安装">
        {firstRunSteps.map((step, index) => (
          <span key={step}>
            <strong>{index + 1}</strong>
            {step}
          </span>
        ))}
      </div>
      {envStatus?.status_items?.length ? (
        <div className="env-checklist" aria-label="环境检查明细">
          {envStatus.status_items.map((item) => (
            <div className={`env-check-item ${item.status}`} key={item.id}>
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
              {item.status !== 'ok' && item.fix ? <small>{item.fix}</small> : null}
            </div>
          ))}
        </div>
      ) : null}
      {envStatus?.worker ? (
        <small className="diagnostic-footnote">
          Worker: {envStatus.worker}
          {envStatus.python_executable ? ` · Python: ${envStatus.python_executable}` : ''}
        </small>
      ) : null}
    </section>
  )
}
