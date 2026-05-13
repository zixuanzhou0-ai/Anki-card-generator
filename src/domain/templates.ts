import type { TemplateId } from './types'

export const templateOptions: Array<{ id: TemplateId; label: string; note: string; locked?: boolean }> = [
  { id: 'immersive', label: '沉浸语言 V10', note: '当前主力模板：视频、音频、答案重点优先' },
  { id: 'dictionary', label: '词典解释', note: '下一轮打磨，暂不开放', locked: true },
  { id: 'minimal', label: '极简复习', note: '下一轮打磨，暂不开放', locked: true },
]
