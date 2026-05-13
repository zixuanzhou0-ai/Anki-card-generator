import type { CardKind, ContentToggles } from './types'

export const contentOptions: Array<{ key: keyof ContentToggles; label: string; defaultOn: boolean }> = [
  { key: 'daily', label: '日常表达', defaultOn: true },
  { key: 'slang', label: '俚语', defaultOn: true },
  { key: 'sarcasm', label: '吐槽 / 讽刺', defaultOn: true },
  { key: 'business', label: '职场表达', defaultOn: true },
  { key: 'culture', label: '文化梗', defaultOn: true },
  { key: 'profanity', label: '脏话 / 粗口', defaultOn: false },
  { key: 'romance', label: '暧昧 / 恋爱表达', defaultOn: false },
  { key: 'rare', label: '低频生僻表达', defaultOn: false },
]

export const cardOptions: Array<{ id: CardKind; label: string; note: string }> = [
  { id: 'listening', label: '听力卡', note: '先听原声，不显示字幕' },
  { id: 'phrase', label: '词伙卡', note: '释义、搭配、语境、中文感' },
  { id: 'cloze', label: '填空卡', note: '翻面后核对关键表达' },
]
