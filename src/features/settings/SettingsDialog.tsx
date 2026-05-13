import type { ComponentProps, RefObject } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'

import type { SettingsTab } from '../../domain/types'
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
            </div>

            <div className="settings-content">
              {settingsTab === 'env' ? <EnvSettingsPanel {...envSettings} /> : null}
              {settingsTab === 'api' ? <ApiSettingsPanel {...apiSettings} /> : null}
              {settingsTab === 'tts' ? <TtsSettingsPanel {...ttsSettings} /> : null}
            </div>
          </motion.section>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}
