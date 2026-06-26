import type { ComponentProps, RefObject } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Boxes, CheckCircle2, CircleAlert, Loader2, PlugZap, Settings2, X } from 'lucide-react'

import type { SettingsTab } from '../../domain/types'
import { AboutSettingsPanel } from './AboutSettingsPanel'
import { ApiSettingsPanel } from './ApiSettingsPanel'
import { EnvSettingsPanel } from './EnvSettingsPanel'
import { TtsSettingsPanel } from './TtsSettingsPanel'

type SettingsDialogProps = {
  apiSettings: ComponentProps<typeof ApiSettingsPanel>
  dialogRef: RefObject<HTMLElement | null>
  envSettings: ComponentProps<typeof EnvSettingsPanel>
  motionDuration: number
  open: boolean
  prefersReducedMotion: boolean
  settingsTab: SettingsTab
  ttsSettings: ComponentProps<typeof TtsSettingsPanel>
  onClose: () => void
  onSettingsTabChange: (tab: SettingsTab) => void
}

type HealthTone = 'idle' | 'ok' | 'testing' | 'warn'

type SettingsHealthCard = {
  icon: 'api' | 'env' | 'tts'
  message: string
  meta: string
  status: string
  tab: SettingsTab
  title: string
  tone: HealthTone
}

function normalizeHealthTone(tone: string): HealthTone {
  if (tone === 'ok' || tone === 'warn' || tone === 'testing') {
    return tone
  }
  return 'idle'
}

function getServiceStatus(tone: HealthTone) {
  if (tone === 'ok') {
    return '已通过'
  }
  if (tone === 'warn') {
    return '需要处理'
  }
  if (tone === 'testing') {
    return '测试中'
  }
  return '未测试'
}

function getEnvHealthCard(envSettings: ComponentProps<typeof EnvSettingsPanel>): SettingsHealthCard {
  const { envStatus } = envSettings
  if (!envStatus) {
    return {
      icon: 'env',
      message: '先检查本机依赖；缺少 Python 时也可以一键安装推荐运行环境。',
      meta: 'Python 3.12 · FFmpeg · genanki · yt-dlp · Anki · AnkiConnect',
      status: '未检查',
      tab: 'env',
      title: '本地环境',
      tone: 'idle',
    }
  }

  const blockingIssue = envStatus.status_items?.find((item) => item.status === 'blocked')
  const actionIssue = envStatus.status_items?.find((item) => item.status === 'action')
  const coreReady = Boolean(envStatus.python && envStatus.ffmpeg && envStatus.genanki)
  const issue = blockingIssue ?? (!coreReady ? actionIssue : undefined)

  if (issue || !coreReady) {
    return {
      icon: 'env',
      message: issue?.fix ?? issue?.detail ?? '生成或导出依赖还没有全部就绪。',
      meta: envStatus.worker ? 'Worker 已定位，继续处理缺失依赖' : '需要重新检查本地运行环境',
      status: '需要处理',
      tab: 'env',
      title: '本地环境',
      tone: 'warn',
    }
  }

  const optionalMissing = [
    !envStatus.yt_dlp ? 'YouTube 导入' : '',
    !envStatus.anki_installed ? 'Anki 桌面端' : '',
    !envStatus.anki_connect ? 'Anki 直连' : '',
  ].filter(Boolean)
  return {
    icon: 'env',
    message: optionalMissing.length ? `${optionalMissing.join('、')}还需要单独确认。` : '生成、切片和 APKG 导出所需依赖已就绪。',
    meta: envStatus.python ? `Python ${envStatus.python}` : '核心依赖已就绪',
    status: optionalMissing.length ? '基本可用' : '已就绪',
    tab: 'env',
    title: '本地环境',
    tone: optionalMissing.length ? 'idle' : 'ok',
  }
}

function getSettingsHealthCards({
  apiSettings,
  envSettings,
  ttsSettings,
}: Pick<SettingsDialogProps, 'apiSettings' | 'envSettings' | 'ttsSettings'>): SettingsHealthCard[] {
  const apiTone = normalizeHealthTone(apiSettings.apiTestTone)
  const ttsTone = ttsSettings.tts.enabled ? normalizeHealthTone(ttsSettings.ttsTestTone) : 'idle'
  return [
    {
      icon: 'api',
      message:
        apiTone === 'ok'
          ? '模型连接可以用于生成卡片。'
          : apiTone === 'warn'
            ? apiSettings.apiTestTitle
            : apiTone === 'testing'
              ? '正在验证服务商、模型和授权。'
              : apiSettings.apiConfig.provider === 'local'
                ? '预览模式只能演示流程，正式抽取学习点和制卡必须配置 API。'
                : '选好服务商后先测试连接。',
      meta: apiSettings.apiTestMeta,
      status: getServiceStatus(apiTone),
      tab: 'api',
      title: '模型 API',
      tone: apiTone,
    },
    {
      icon: 'tts',
      message: !ttsSettings.tts.enabled
        ? '视频卡导出需要整句 TTS 和表达 TTS；请在语音页开启并测试。'
        : ttsTone === 'ok'
          ? 'TTS 可用于整句朗读和表达发音。'
          : ttsTone === 'warn'
            ? ttsSettings.ttsTestTitle
            : ttsTone === 'testing'
              ? '正在验证语音模型和音色。'
              : '开启后建议先测试 TTS。',
      meta: !ttsSettings.tts.enabled ? '关闭时不能导出视频卡' : ttsSettings.ttsTestMeta,
      status: !ttsSettings.tts.enabled ? '已关闭' : getServiceStatus(ttsTone),
      tab: 'tts',
      title: '语音 TTS',
      tone: ttsTone,
    },
    getEnvHealthCard(envSettings),
  ]
}

function SettingsHealthIcon({ icon, tone }: Pick<SettingsHealthCard, 'icon' | 'tone'>) {
  if (tone === 'testing') {
    return <Loader2 className="spin" size={19} />
  }
  if (tone === 'ok') {
    return <CheckCircle2 size={19} />
  }
  if (tone === 'warn') {
    return <CircleAlert size={19} />
  }
  if (icon === 'api') {
    return <Boxes size={19} />
  }
  if (icon === 'tts') {
    return <PlugZap size={19} />
  }
  return <Settings2 size={19} />
}

export function SettingsDialog({
  apiSettings,
  dialogRef,
  envSettings,
  motionDuration,
  open,
  prefersReducedMotion,
  settingsTab,
  ttsSettings,
  onClose,
  onSettingsTabChange,
}: SettingsDialogProps) {
  const healthCards = getSettingsHealthCards({ apiSettings, envSettings, ttsSettings })

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="settings-overlay"
          role="presentation"
          onClick={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: motionDuration }}
        >
          <motion.section
            className="settings-dialog"
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
            initial={{ opacity: 0, x: prefersReducedMotion ? 0 : 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: prefersReducedMotion ? 0 : 24 }}
            transition={{ duration: motionDuration, ease: 'easeOut' }}
          >
            <div className="settings-dialog-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h2 id="settings-title">设置</h2>
              </div>
              <button className="icon-button" type="button" onClick={onClose} aria-label="关闭设置">
                <X size={18} />
              </button>
            </div>
            <div className="settings-health-strip" aria-label="设置状态总览">
              {healthCards.map((card) => (
                <button
                  aria-label={`${card.title}：${card.status}，打开${card.title} 设置`}
                  className={`settings-health-card ${card.tone} ${settingsTab === card.tab ? 'selected' : ''}`}
                  key={card.tab}
                  type="button"
                  onClick={() => onSettingsTabChange(card.tab)}
                >
                  <span className="settings-health-icon" aria-hidden="true">
                    <SettingsHealthIcon icon={card.icon} tone={card.tone} />
                  </span>
                  <span className="settings-health-copy">
                    <span className="settings-health-title">
                      <strong>{card.title}</strong>
                      <em>{card.status}</em>
                    </span>
                    <span>{card.message}</span>
                    <small>{card.meta}</small>
                  </span>
                </button>
              ))}
            </div>
            <div className="settings-tabs" role="tablist" aria-label="设置分类">
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'api'}
                className={settingsTab === 'api' ? 'selected' : ''}
                onClick={() => onSettingsTabChange('api')}
              >
                模型 API
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'tts'}
                className={settingsTab === 'tts' ? 'selected' : ''}
                onClick={() => onSettingsTabChange('tts')}
              >
                语音 TTS
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'env'}
                className={settingsTab === 'env' ? 'selected' : ''}
                onClick={() => onSettingsTabChange('env')}
              >
                本地环境
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={settingsTab === 'about'}
                className={settingsTab === 'about' ? 'selected' : ''}
                onClick={() => onSettingsTabChange('about')}
              >
                关于 / 版权
              </button>
            </div>

            <div className="settings-content">
              {settingsTab === 'env' ? <EnvSettingsPanel {...envSettings} /> : null}
              {settingsTab === 'api' ? <ApiSettingsPanel {...apiSettings} /> : null}
              {settingsTab === 'tts' ? <TtsSettingsPanel {...ttsSettings} /> : null}
              {settingsTab === 'about' ? <AboutSettingsPanel /> : null}
            </div>
          </motion.section>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}
