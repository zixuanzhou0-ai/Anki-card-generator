import type { StudyDepth } from './types'

export const studyDepthOptions: Array<{
  id: StudyDepth
  label: string
  note: string
}> = [
  { id: 'deep', label: '深度理解', note: '先理解整段素材，再筛选和撰写卡片' },
  { id: 'standard', label: '快速生成', note: '直接按候选片段生成，速度更快' },
]

export const defaultStudyDepth: StudyDepth = 'deep'

export function normalizeStudyDepth(value: unknown): StudyDepth {
  return value === 'standard' || value === 'deep' ? value : defaultStudyDepth
}
