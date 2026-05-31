import type { TemplateId } from './types'

export const templateOptions: Array<{ id: TemplateId; label: string; note: string; locked?: boolean }> = [
  { id: 'immersive_v11', label: '沉浸复读 V11', note: '正面跟读训练，背面快速核对表达和语境' },
  { id: 'immersive', label: '沉浸语言 V10', note: '旧版兼容模板：视频、音频、答案重点优先' },
  { id: 'dictionary', label: '词典解释', note: '下一轮打磨，暂不开放', locked: true },
  { id: 'minimal', label: '极简复习', note: '下一轮打磨，暂不开放', locked: true },
]
