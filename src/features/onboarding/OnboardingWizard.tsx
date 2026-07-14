import { useEffect, useRef, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Cpu,
  HardDrive,
  LockKeyhole,
  MessageSquareText,
  Sparkles,
  Volume2,
} from 'lucide-react'

import type { EnvStatus } from '../../domain/types'

type OnboardingWizardProps = {
  apiReady: boolean
  envStatus: EnvStatus | null
  open: boolean
  ttsReady: boolean
  ttsRequired: boolean
  onCheckEnv: () => void
  onComplete: () => void
  onOpenApiSettings: () => void
  onOpenTtsSettings: () => void
  onSkip: () => void
}

const stepLabels = ['欢迎', '本地环境', '模型', '语音']

export function OnboardingWizard({
  apiReady,
  envStatus,
  open,
  ttsReady,
  ttsRequired,
  onCheckEnv,
  onComplete,
  onOpenApiSettings,
  onOpenTtsSettings,
  onSkip,
}: OnboardingWizardProps) {
  const [step, setStep] = useState(0)
  const checkedOnOpenRef = useRef(false)
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (!open) {
      checkedOnOpenRef.current = false
      return
    }
    headingRef.current?.focus()
    if (!checkedOnOpenRef.current) {
      checkedOnOpenRef.current = true
      onCheckEnv()
    }
  }, [onCheckEnv, open])

  if (!open) return null

  const envChecks = [
    ['Python', Boolean(envStatus?.python)],
    ['FFmpeg', Boolean(envStatus?.ffmpeg)],
    ['genanki', Boolean(envStatus?.genanki)],
    ['yt-dlp', Boolean(envStatus?.yt_dlp)],
    ['Anki', Boolean(envStatus?.anki_installed)],
    ['AnkiConnect', Boolean(envStatus?.anki_connect)],
  ] as const
  const coreEnvironmentReady = Boolean(envStatus?.python && envStatus.ffmpeg && envStatus.genanki)
  const atLastStep = step === stepLabels.length - 1

  return (
    <div className="onboarding-backdrop">
      <section
        className="onboarding-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        onKeyDown={(event) => {
          if (event.key === 'Escape') onSkip()
        }}
      >
        <aside className="onboarding-rail" aria-label="启动向导步骤">
          <div className="onboarding-brand">
            <span className="onboarding-mark">
              <Sparkles size={22} />
            </span>
            <span>
              <small>Anki Card Generator</small>
              <strong>开始可靠制卡</strong>
            </span>
          </div>
          <ol>
            {stepLabels.map((label, index) => (
              <li key={label} className={index === step ? 'active' : index < step ? 'complete' : ''}>
                <span>{index < step ? '✓' : index + 1}</span>
                <strong>{label}</strong>
              </li>
            ))}
          </ol>
          <p>所有偏好留在本机。模型与 TTS 只在你主动点击测试时发起请求。</p>
        </aside>

        <div className="onboarding-content">
          {step === 0 ? (
            <div className="onboarding-step">
              <span className="onboarding-step-icon"><MessageSquareText size={24} /></span>
              <p className="eyebrow">4 个短步骤</p>
              <h2 id="onboarding-title" ref={headingRef} tabIndex={-1}>先确认外部能力，再开始第一张卡片</h2>
              <p className="onboarding-lead">
                视频、字幕和导出文件在本机处理；只有学习点抽取、卡片内容和语音生成会按你的配置调用模型服务。
              </p>
              <div className="onboarding-principles">
                <span><LockKeyhole size={19} /><strong>密钥不写入 UI 偏好</strong><small>向导只保存完成状态和显示模式。</small></span>
                <span><HardDrive size={19} /><strong>失败不会输出半成品</strong><small>环境、模型、TTS 都有独立闸门。</small></span>
              </div>
            </div>
          ) : null}

          {step === 1 ? (
            <div className="onboarding-step">
              <span className="onboarding-step-icon"><HardDrive size={24} /></span>
              <p className="eyebrow">本地环境</p>
              <h2 id="onboarding-title" ref={headingRef} tabIndex={-1}>生成与 Anki 核验能力</h2>
              <p className="onboarding-lead">已自动执行只读检查。缺少的项目可以稍后在设置中逐项或一键修复。</p>
              <div className="onboarding-check-grid">
                {envChecks.map(([label, ready]) => (
                  <span key={label} className={ready ? 'ready' : 'unknown'}>
                    {ready ? <CheckCircle2 size={18} /> : <Cpu size={18} />}
                    <strong>{label}</strong>
                    <small>{ready ? '可用' : envStatus ? '未就绪' : '检查中'}</small>
                  </span>
                ))}
              </div>
              <button type="button" className="ghost-button onboarding-inline-action" onClick={onCheckEnv}>
                重新检查
              </button>
              <p className={'onboarding-summary ' + (coreEnvironmentReady ? 'ready' : 'warning')}>
                {coreEnvironmentReady ? '核心生成环境已就绪。' : '核心环境尚未完全就绪，继续不会伪造完成状态。'}
              </p>
            </div>
          ) : null}

          {step === 2 ? (
            <div className="onboarding-step">
              <span className="onboarding-step-icon"><Sparkles size={24} /></span>
              <p className="eyebrow">模型</p>
              <h2 id="onboarding-title" ref={headingRef} tabIndex={-1}>优先使用本机 Hermes Grok 4.5</h2>
              <p className="onboarding-lead">
                推荐方案会连接你本机的 Hermes 代理；OpenAI、DeepSeek、通义和自定义兼容服务仍可在设置中选择。
              </p>
              <div className="onboarding-recommendation">
                <span className="recommendation-badge">本机推荐</span>
                <strong>Hermes · Grok 4.5</strong>
                <small>适合高可靠学习点抽取与卡片正文生成。保存配置后必须主动测试。</small>
                <span className={apiReady ? 'readiness-pill ready' : 'readiness-pill warning'}>
                  {apiReady ? '模型连接已验证' : '模型尚未验证'}
                </span>
              </div>
              <button type="button" className="primary-button onboarding-inline-action" onClick={onOpenApiSettings}>
                配置并测试模型
              </button>
            </div>
          ) : null}

          {step === 3 ? (
            <div className="onboarding-step">
              <span className="onboarding-step-icon"><Volume2 size={24} /></span>
              <p className="eyebrow">语音 / TTS</p>
              <h2 id="onboarding-title" ref={headingRef} tabIndex={-1}>让整句和目标表达都有可验证语音</h2>
              <p className="onboarding-lead">
                视频语言卡默认要求整句 TTS 与表达 TTS。仅保存授权不算就绪，必须完成一次真实测试。
              </p>
              <div className="onboarding-recommendation">
                <strong>{ttsRequired ? '当前卡片类型需要 TTS' : '当前方案可暂不使用 TTS'}</strong>
                <small>测试不会自动发生，也不会因为存在密钥就显示为成功。</small>
                <span className={ttsReady ? 'readiness-pill ready' : 'readiness-pill warning'}>
                  {ttsReady ? 'TTS 已验证' : 'TTS 尚未验证'}
                </span>
              </div>
              <button type="button" className="primary-button onboarding-inline-action" onClick={onOpenTtsSettings}>
                配置并测试 TTS
              </button>
            </div>
          ) : null}

          <footer className="onboarding-footer">
            <button type="button" className="text-button" onClick={onSkip}>稍后设置</button>
            <div>
              {step > 0 ? (
                <button type="button" className="ghost-button" onClick={() => setStep((current) => current - 1)}>
                  <ArrowLeft size={18} />上一步
                </button>
              ) : null}
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  if (atLastStep) onComplete()
                  else setStep((current) => current + 1)
                }}
              >
                {atLastStep ? '进入素材选择' : '继续'}
                {!atLastStep ? <ArrowRight size={18} /> : null}
              </button>
            </div>
          </footer>
        </div>
      </section>
    </div>
  )
}