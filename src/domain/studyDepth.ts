import type { StudyDepth } from './types'

export const studyDepthOptions: Array<{
  id: StudyDepth
  label: string
  note: string
}> = [
  { id: 'deep', label: '深入解析', note: '先理解整段素材，再筛选和撰写卡片' },
  { id: 'standard', label: '快速提取', note: '跳过深度上下文，优先提取候选' },
]

export const defaultStudyDepth: StudyDepth = 'deep'

export function normalizeStudyDepth(value: unknown): StudyDepth {
  return value === 'standard' || value === 'deep' ? value : defaultStudyDepth
}
