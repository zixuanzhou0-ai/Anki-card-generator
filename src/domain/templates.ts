import type { CardStyleId, SourceMode, TemplateId } from './types'

export const validTemplateIds: TemplateId[] = ['immersive_v11', 'ciba_tianxia_v1', 'immersive', 'dictionary', 'minimal']

export const templateOptions: Array<{ id: TemplateId; label: string; note: string; locked?: boolean }> = [
  { id: 'immersive_v11', label: '沉浸复读', note: '主流程模板：完整复读和快速复读都使用这套稳定正面' },
  {
    id: 'ciba_tianxia_v1',
    label: '词霸天下实验 V1',
    note: '实验模板：按词块、语境义、概念视角、搭配边界和真实听辨生成语言动作卡',
  },
]

export const validCardStyleIds: CardStyleId[] = ['warm_paper', 'minimal_white', 'dark_immersive']
export const defaultCardStyle: CardStyleId = 'warm_paper'

export const cardStyleOptions: Array<{ id: CardStyleId; label: string; note: string; tone: string }> = [
  { id: 'warm_paper', label: '暖色纸感', note: '温暖、像学习笔记，适合深入解析。', tone: 'warm' },
  { id: 'minimal_white', label: '极简白卡', note: '低干扰、快复习，适合高频刷卡。', tone: 'minimal' },
  { id: 'dark_immersive', label: '深色沉浸', note: '视频更突出，适合夜间听力和跟读。', tone: 'dark' },
]

export function normalizeTemplateId(value: unknown): TemplateId {
  return validTemplateIds.includes(value as TemplateId) ? (value as TemplateId) : 'immersive_v11'
}

export function publicTemplateIdFor(value: unknown, sourceMode: SourceMode | undefined): TemplateId {
  const normalized = normalizeTemplateId(value)
  return sourceMode === 'document' ? normalized : 'immersive_v11'
}

export function normalizeCardStyleId(value: unknown): CardStyleId {
  return validCardStyleIds.includes(value as CardStyleId) ? (value as CardStyleId) : defaultCardStyle
}
