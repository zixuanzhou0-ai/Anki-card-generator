import { CheckCircle2, CircleAlert, Loader2, Settings2 } from 'lucide-react'

import type { EnvRepairResult, EnvRepairTarget, EnvStatus, EnvStatusItem } from '../../domain/types'

type EnvSettingsPanelProps = {
  appBusy: boolean
  envRepairing: boolean
  envRepairResult: EnvRepairResult | null
  envStatus: EnvStatus | null
  simpleMode?: boolean
  onCheckEnv: () => void
  onRepairEnv: (target?: EnvRepairTarget) => void
}

const firstRunSteps = ['打开桌面端', '检查环境', '一键修复依赖', '填写 API / TTS', '用示例导出 APKG']

type EnvCapabilityCard = {
  id: EnvRepairTarget | 'generate' | 'export' | 'media' | 'url' | 'anki'
  label: string
  ok: boolean
  detail: string
  repairTarget?: EnvRepairTarget
  repairLabel?: string
}

function getCapabilityCards(envStatus: EnvStatus | null): EnvCapabilityCard[] {
  if (!envStatus) {
    return [
      { id: 'generate', label: '生成卡片', ok: false, detail: '待检查 Python 与 worker' },
      { id: 'export', label: 'APKG 导出', ok: false, detail: '待检查 genanki' },
      { id: 'media', label: '视频/音频切片', ok: false, detail: '待检查 FFmpeg' },
      { id: 'url', label: 'YouTube 导入', ok: false, detail: '待检查 yt-dlp' },
      { id: 'anki', label: 'Anki 桌面端', ok: false, detail: '待检查 Anki 是否安装' },
      { id: 'anki_connect', label: 'AnkiConnect 插件', ok: false, detail: '待检查插件连接' },
    ]
  }
  return [
    {
      id: 'generate',
      label: '生成卡片',
      ok: Boolean(envStatus.python && envStatus.worker),
      detail: envStatus.python ? `Python ${envStatus.python}` : '缺少 Python 或 worker',
      repairTarget: envStatus.python ? undefined : 'python_runtime',
      repairLabel: '安装 Python',
    },
    {
      id: 'export',
      label: 'APKG 导出',
      ok: Boolean(envStatus.genanki),
      detail: envStatus.genanki ? 'genanki 已就绪' : '需要安装 genanki',
      repairTarget: envStatus.genanki ? undefined : 'python_packages',
      repairLabel: '修复依赖',
    },
    {
      id: 'media',
      label: '视频/音频切片',
      ok: Boolean(envStatus.ffmpeg),
      detail: envStatus.ffmpeg ? 'FFmpeg 已就绪' : '需要 FFmpeg',
      repairTarget: envStatus.ffmpeg ? undefined : 'ffmpeg',
      repairLabel: '安装 FFmpeg',
    },
    {
      id: 'url',
      label: 'YouTube 导入',
      ok: Boolean(envStatus.yt_dlp),
      detail: envStatus.yt_dlp ? `yt-dlp ${envStatus.yt_dlp_version ?? ''}`.trim() : '未确认 yt-dlp',
      repairTarget: envStatus.yt_dlp ? undefined : 'python_packages',
      repairLabel: '修复 yt-dlp',
    },
    {
      id: 'anki',
      label: 'Anki 桌面端',
      ok: Boolean(envStatus.anki_installed),
      detail: envStatus.anki_installed
        ? envStatus.anki_running
          ? 'Anki 已安装并正在运行'
          : 'Anki 已安装，尚未打开'
        : '需要安装 Anki 桌面端',
      repairTarget: envStatus.anki_installed ? undefined : 'anki',
      repairLabel: '安装 Anki',
    },
    {
      id: 'anki_connect',
      label: 'AnkiConnect 插件',
      ok: Boolean(envStatus.anki_connect),
      detail: envStatus.anki_connect
        ? 'AnkiConnect 可用'
        : envStatus.anki_installed
          ? envStatus.anki_running
            ? '需要安装或启用插件'
            : '先打开 Anki，再检查插件'
          : '先安装 Anki 桌面端',
      repairTarget: envStatus.anki_connect ? undefined : 'anki_connect',
      repairLabel: envStatus.anki_installed ? '打开/修复插件' : '查看步骤',
    },
  ]
}

function getStatusRepairAction(item: EnvStatusItem): { label: string; target: EnvRepairTarget } | null {
  if (item.status === 'ok') return null
  if (item.id === 'venv' || item.id === 'genanki' || item.id === 'yt_dlp') {
    return { label: item.id === 'yt_dlp' ? '修复 yt-dlp' : '修复 Python 依赖', target: 'python_packages' }
  }
  if (item.id === 'python') {
    return { label: '安装推荐 Python 3.12', target: 'python_runtime' }
  }
  if (item.id === 'ffmpeg') {
    return { label: '尝试安装 FFmpeg', target: 'ffmpeg' }
  }
  if (item.id === 'js_runtime') {
    return { label: '安装 Deno', target: 'js_runtime' }
  }
  if (item.id === 'anki') {
    return { label: '安装 Anki', target: 'anki' }
  }
  if (item.id === 'anki_connect') {
    return { label: '打开 Anki / 插件步骤', target: 'anki_connect' }
  }
  return null
}

function getEnvReadiness(envStatus: EnvStatus | null) {
  if (!envStatus) {
    return {
      detail: '还没有检查本机依赖。先跑一次体检，再判断能不能生成、切片和导出。',
      meta: '检查 Python、FFmpeg、genanki、yt-dlp、Anki 和 AnkiConnect',
      title: '尚未检查',
      tone: 'idle',
    }
  }

  const blockingIssue = envStatus.status_items?.find((item) => item.status === 'blocked')
  const actionIssue = envStatus.status_items?.find((item) => item.status === 'action')
  const coreReady = Boolean(envStatus.python && envStatus.ffmpeg && envStatus.genanki)
  const issue = blockingIssue ?? (!coreReady ? actionIssue : undefined)
  if (issue || !coreReady) {
    return {
      detail: issue?.fix ?? issue?.detail ?? '生成或导出所需依赖还没有全部就绪。',
      meta: envStatus.worker ? 'Worker 已找到，继续补齐缺失依赖' : '需要重新检查运行目录和 Python 环境',
      title: '需要处理',
      tone: 'warn',
    }
  }

  const optionalMissing = [
    !envStatus.yt_dlp ? 'YouTube 导入' : '',
    !envStatus.anki_installed ? 'Anki 桌面端' : '',
    !envStatus.anki_connect ? 'Anki 直连导入' : '',
  ].filter(Boolean)
  if (optionalMissing.length) {
    return {
      detail: `本地生成和 APKG 导出可以继续；${optionalMissing.join('、')}还没有确认。`,
      meta: envStatus.python ? `Python ${envStatus.python}` : '核心依赖已就绪',
      title: '基本可用',
      tone: 'idle',
    }
  }

  return {
    detail: '本地生成、视频切片、APKG 导出和 AnkiConnect 核验所需环境已就绪。',
    meta: envStatus.python ? `Python ${envStatus.python}` : '核心依赖已就绪',
    title: '可以生成并导出',
    tone: 'ok',
  }
}

export function EnvSettingsPanel({
  appBusy,
  envRepairing,
  envRepairResult,
  envStatus,
  simpleMode = false,
  onCheckEnv,
  onRepairEnv,
}: EnvSettingsPanelProps) {
  const readiness = getEnvReadiness(envStatus)
  const capabilityCards = getCapabilityCards(envStatus)
  const hasRepairableIssue = !envStatus || Boolean(envStatus.status_items?.some((item) => item.status !== 'ok'))
  const simpleIssues = envStatus?.status_items?.filter((item) => item.status !== 'ok') ?? []
  const simpleRepairNeeded = Boolean(
    envStatus && (!envStatus.python || !envStatus.ffmpeg || !envStatus.genanki || simpleIssues.length),
  )

  return (
    <section className="settings-section settings-section-single">
      <div className="panel-heading">
        <Settings2 size={20} />
        <h3>本地环境诊断</h3>
      </div>
      <div className={`env-readiness-card ${readiness.tone}`}>
        <div className="env-readiness-icon" aria-hidden="true">
          {appBusy ? (
            <Loader2 className="spin" size={22} />
          ) : readiness.tone === 'ok' ? (
            <CheckCircle2 size={22} />
          ) : readiness.tone === 'warn' ? (
            <CircleAlert size={22} />
          ) : (
            <Settings2 size={22} />
          )}
        </div>
        <div className="env-readiness-copy">
          <span className="label">{simpleMode ? '本地环境' : '本地环境诊断中心'}</span>
          <strong>{readiness.title}</strong>
          <p>{readiness.detail}</p>
          <small>{readiness.meta}</small>
        </div>
        <button className="ghost-button" type="button" onClick={onCheckEnv} disabled={appBusy}>
          {appBusy ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
          {envStatus ? '重新检查环境' : '检查环境'}
        </button>
      </div>
      <p>这里检查的是本机依赖，不包含任何 API Key；模型和 TTS 的连通性请在前两个设置页单独测试。</p>
      {simpleMode ? (
        <div className="settings-simple-env">
          {simpleRepairNeeded ? (
            <button className="primary-button" type="button" onClick={() => onRepairEnv('all')} disabled={appBusy}>
              {envRepairing ? <Loader2 className="spin" size={18} /> : <Settings2 size={18} />}
              修复所需环境
            </button>
          ) : null}
          {simpleIssues.length ? (
            <div className="env-checklist settings-simple-env-issues" aria-label="需要处理的环境项目">
              {simpleIssues.map((item) => (
                <div className={`env-check-item ${item.status}`} key={item.id}>
                  <strong>{item.label}</strong>
                  <span>{item.detail}</span>
                  {item.fix ? <small>{item.fix}</small> : null}
                </div>
              ))}
            </div>
          ) : simpleRepairNeeded ? (
            <div className="env-checklist settings-simple-env-issues" aria-label="需要处理的环境项目">
              <div className="env-check-item blocked">
                <strong>本地生成环境</strong>
                <span>Python、FFmpeg 或 APKG 导出依赖尚未全部就绪。</span>
              </div>
            </div>
          ) : null}
          {envRepairResult ? (
            <div className={`env-repair-log ${envRepairResult.ok ? 'ok' : 'warn'}`} aria-label="环境修复结果">
              <div className="env-repair-log-head">
                <strong>{envRepairResult.ok ? '修复步骤已完成' : '修复步骤需要继续处理'}</strong>
                <span>{envRepairResult.summary}</span>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <>
          <div className="env-repair-toolbar">
            <button
              className="primary-button"
              type="button"
              onClick={() => onRepairEnv('all')}
              disabled={appBusy || !hasRepairableIssue}
            >
              {envRepairing ? <Loader2 className="spin" size={18} /> : <Settings2 size={18} />}
              一键修复全部可修复项
            </button>
            <button className="ghost-button" type="button" onClick={onCheckEnv} disabled={appBusy}>
              重新检查
            </button>
            <small>
              会尝试安装推荐 Python 3.12、修复 Python 依赖、FFmpeg、Deno/Node 和 Anki；AnkiConnect 需要在 Anki
              内确认安装，系统会打开 Anki 并给出插件代码。
            </small>
          </div>
          <div className="env-capability-grid" aria-label="本地能力状态">
            {capabilityCards.map((item) => (
              <div className={`env-capability-card ${item.ok ? 'ok' : 'warn'}`} key={item.id}>
                <strong>{item.label}</strong>
                <span>{item.ok ? '可用' : '待处理'}</span>
                <small>{item.detail}</small>
                {!item.ok && item.repairTarget ? (
                  <button type="button" onClick={() => onRepairEnv(item.repairTarget)} disabled={appBusy}>
                    {envRepairing ? <Loader2 className="spin" size={14} /> : null}
                    {item.repairLabel}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
          <div className="settings-row">
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
                  <span className={envStatus.anki_installed ? 'ok' : 'warn'}>
                    Anki {envStatus.anki_installed ? (envStatus.anki_running ? '运行中' : '已安装') : '未安装'}
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
              {envStatus.status_items.map((item) => {
                const repairAction = getStatusRepairAction(item)
                return (
                  <div className={`env-check-item ${item.status}`} key={item.id}>
                    <strong>{item.label}</strong>
                    <span>{item.detail}</span>
                    {item.status !== 'ok' && item.fix ? <small>{item.fix}</small> : null}
                    {repairAction ? (
                      <button type="button" onClick={() => onRepairEnv(repairAction.target)} disabled={appBusy}>
                        {repairAction.label}
                      </button>
                    ) : null}
                  </div>
                )
              })}
            </div>
          ) : null}
          {envRepairResult ? (
            <div className={`env-repair-log ${envRepairResult.ok ? 'ok' : 'warn'}`} aria-label="环境修复日志">
              <div className="env-repair-log-head">
                <strong>{envRepairResult.ok ? '修复步骤已完成' : '修复步骤需要继续处理'}</strong>
                <span>{envRepairResult.summary}</span>
              </div>
              {envRepairResult.actions.map((action) => (
                <div className={`env-repair-action ${action.status}`} key={`${action.id}-${action.label}`}>
                  <strong>{action.label}</strong>
                  <span>{action.detail}</span>
                  {action.next_step ? <small>{action.next_step}</small> : null}
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
        </>
      )}
    </section>
  )
}
