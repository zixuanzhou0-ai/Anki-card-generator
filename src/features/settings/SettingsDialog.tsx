import type { ComponentProps, RefObject } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Boxes, CheckCircle2, CircleAlert, Layers3, Loader2, PlugZap, RotateCcw, Settings2, X } from 'lucide-react'

import { useModalFocusTrap } from '../../app/useModalFocusTrap'
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
  dirty: boolean
  saving: boolean
  settingsMode: 'simple' | 'advanced'
  settingsTab: SettingsTab
  ttsSettings: ComponentProps<typeof TtsSettingsPanel>
  onApplyWithoutVerification: () => void
  onClose: () => void
  onDiscardChanges: () => void
  onRerunOnboarding: () => void
  onSaveAndVerify: () => void
  onSettingsModeChange: (mode: 'simple' | 'advanced') => void
  onSettingsTabChange: (tab: SettingsTab) => void
}

type HealthTone = 'idle' | 'ok' | 'testing' | 'warn'

type SettingsHealthCard = {
  icon: 'anki' | 'api' | 'env' | 'tts'
  actionLabel?: string
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
      meta: 'Python 3.12 · FFmpeg · genanki · yt-dlp',
      status: '未检查',
      tab: 'env',
      title: '本地环境',
      tone: 'idle',
    }
  }

  const coreReady = Boolean(envStatus.python && envStatus.ffmpeg && envStatus.genanki)
  const issue = !coreReady
    ? envStatus.status_items?.find((item) => item.status === 'blocked' || item.status === 'action')
    : undefined

  if (!coreReady) {
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

  const optionalMissing = [!envStatus.yt_dlp ? 'YouTube 导入' : ''].filter(Boolean)
  return {
    icon: 'env',
    message: optionalMissing.length
      ? `${optionalMissing.join('、')}还需要单独确认。`
      : '生成、切片和 APKG 导出所需依赖已就绪。',
    meta: envStatus.python ? `Python ${envStatus.python}` : '核心依赖已就绪',
    status: optionalMissing.length ? '基本可用' : '已就绪',
    tab: 'env',
    title: '本地环境',
    tone: optionalMissing.length ? 'idle' : 'ok',
  }
}

function getAnkiHealthCard(envSettings: ComponentProps<typeof EnvSettingsPanel>): SettingsHealthCard {
  const { envStatus } = envSettings
  if (envStatus?.anki_connect) {
    return {
      icon: 'anki',
      actionLabel: '导入与核验',
      message: 'AnkiConnect 已连接，可以在导入后继续核验牌组、卡片和媒体。',
      meta: '导入与核验 · 当前连接可用',
      status: 'AnkiConnect 可用',
      tab: 'env',
      title: 'Anki',
      tone: 'ok',
    }
  }
  if (envStatus?.anki_installed === false) {
    return {
      icon: 'anki',
      actionLabel: '导入与核验',
      message: '未检测到 Anki 桌面端；生成 APKG 不受影响，导入前需要先安装。',
      meta: '导入与核验 · 仅导入阶段要求',
      status: '需要安装',
      tab: 'env',
      title: 'Anki',
      tone: 'warn',
    }
  }
  return {
    icon: 'anki',
    actionLabel: '导入与核验',
    message: envStatus?.anki_installed
      ? 'Anki 已安装；点击导入时会检查 AnkiConnect，并给出唯一修复动作。'
      : '尚未检查 Anki；只在导入牌组时检查，不阻塞卡片生成和 APKG 导出。',
    meta: '导入与核验 · 导入时确认',
    status: '导入时检查',
    tab: 'env',
    title: 'Anki',
    tone: 'idle',
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
    getAnkiHealthCard(envSettings),
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
  if (icon === 'anki') {
    return <Layers3 size={19} />
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
  dirty,
  saving,
  settingsMode,
  settingsTab,
  ttsSettings,
  onApplyWithoutVerification,
  onClose,
  onDiscardChanges,
  onRerunOnboarding,
  onSaveAndVerify,
  onSettingsModeChange,
  onSettingsTabChange,
}: SettingsDialogProps) {
  const healthCards = getSettingsHealthCards({ apiSettings, envSettings, ttsSettings })
  const visibleHealthCards =
    settingsMode === 'simple'
      ? healthCards.map((card) =>
          card.icon === 'api' || card.icon === 'tts'
            ? { ...card, meta: card.tone === 'ok' ? '当前方案已验证' : '只显示完成此能力所需的设置' }
            : card,
        )
      : healthCards
  const activeHealthCard = visibleHealthCards.find((card) => card.tab === settingsTab)
  const transactionStatus = dirty ? '更改尚未应用到制卡流程。' : '当前设置已应用。'
  const settingsAnnouncement = saving
    ? '正在验证并保存当前草稿…'
    : activeHealthCard
      ? `${activeHealthCard.title}：${activeHealthCard.status}。${activeHealthCard.message} ${transactionStatus}`
      : transactionStatus
  const actionsDisabled = saving || apiSettings.appBusy || ttsSettings.appBusy
  const requestClose = (nextAction: () => void = onClose) => {
    if (dirty) {
      const discard = window.confirm('设置还有尚未应用的更改。要放弃这些更改吗？')
      if (!discard) return
      onDiscardChanges()
    }
    nextAction()
  }
  useModalFocusTrap({
    active: open,
    containerRef: dialogRef,
    initialFocusRef: dialogRef,
    onEscape: requestClose,
  })

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="settings-overlay"
          role="presentation"
          onClick={() => requestClose()}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: motionDuration }}
        >
          <motion.section
            className={'settings-dialog settings-mode-' + settingsMode}
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
            initial={{ opacity: 0, scale: prefersReducedMotion ? 1 : 0.985 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: prefersReducedMotion ? 1 : 0.985 }}
            transition={{ duration: motionDuration, ease: 'easeOut' }}
          >
            <div className="settings-dialog-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h2 id="settings-title">设置</h2>
              </div>
              <div className="settings-header-actions">
                <div className="settings-mode-switch" role="group" aria-label="设置显示模式">
                  <button
                    type="button"
                    className={settingsMode === 'simple' ? 'selected' : ''}
                    aria-pressed={settingsMode === 'simple'}
                    onClick={() => onSettingsModeChange('simple')}
                  >
                    简单
                  </button>
                  <button
                    type="button"
                    className={settingsMode === 'advanced' ? 'selected' : ''}
                    aria-pressed={settingsMode === 'advanced'}
                    onClick={() => onSettingsModeChange('advanced')}
                  >
                    高级
                  </button>
                </div>
                <button
                  className="ghost-button settings-rerun-button"
                  type="button"
                  onClick={() => requestClose(onRerunOnboarding)}
                >
                  <RotateCcw size={17} />
                  重新运行启动检查
                </button>
                <button className="icon-button" type="button" onClick={() => requestClose()} aria-label="关闭设置">
                  <X size={18} />
                </button>
              </div>
            </div>
            <div className="settings-health-strip" aria-label="设置状态总览">
              {visibleHealthCards.map((card) => (
                <button
                  aria-label={`${card.title}：${card.status}，${card.actionLabel ? `打开${card.actionLabel}区域` : `打开${card.title} 设置`}`}
                  className={`settings-health-card ${card.tone} ${settingsTab === card.tab ? 'selected' : ''}`}
                  key={`${card.tab}-${card.title}`}
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
              {settingsTab === 'env' ? (
                <EnvSettingsPanel {...envSettings} simpleMode={settingsMode === 'simple'} />
              ) : null}
              {settingsTab === 'api' ? (
                <ApiSettingsPanel {...apiSettings} hideSaveAction simpleMode={settingsMode === 'simple'} />
              ) : null}
              {settingsTab === 'tts' ? (
                <TtsSettingsPanel {...ttsSettings} hideSaveAction simpleMode={settingsMode === 'simple'} />
              ) : null}
              {settingsTab === 'about' ? <AboutSettingsPanel /> : null}
            </div>
            <div className="settings-config-actions settings-transaction-actions" aria-label="设置应用操作">
              <span role="status" aria-live="polite" aria-atomic="true">
                {settingsAnnouncement}
              </span>
              <button
                className="secondary-button"
                type="button"
                disabled={actionsDisabled || !dirty}
                onClick={onApplyWithoutVerification}
              >
                应用但稍后验证
              </button>
              <button className="primary-button" type="button" disabled={actionsDisabled} onClick={onSaveAndVerify}>
                {saving ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
                {saving ? '验证中…' : '保存并验证'}
              </button>
            </div>
          </motion.section>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}
