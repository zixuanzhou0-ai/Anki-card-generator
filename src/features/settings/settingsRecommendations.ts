import type { ApiConfig, ApiPreset, SavedApiProfile, SavedTtsProfile, TtsPreset } from '../../domain/types'

export type CatalogFilter = 'all' | 'quality' | 'speed' | 'value' | 'custom' | 'saved'
export type CatalogTone = Exclude<CatalogFilter, 'all'> | 'voice'

export const catalogFilters: Array<{ id: CatalogFilter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'quality', label: '质量' },
  { id: 'speed', label: '速度' },
  { id: 'value', label: '性价比' },
  { id: 'custom', label: '自定义' },
  { id: 'saved', label: '我的方案' },
]

export function normalizeCatalogSearch(value: string) {
  return value.trim().toLocaleLowerCase()
}

export function matchesCatalogSearch(search: string, values: Array<string | undefined>) {
  const normalized = normalizeCatalogSearch(search)
  if (!normalized) return true
  return values.some((value) => value?.toLocaleLowerCase().includes(normalized))
}

export function getApiPresetTone(preset: ApiPreset): CatalogTone {
  if (preset.id === 'custom-compatible' || preset.provider === 'local') return 'custom'
  if (
    preset.id.includes('flash') ||
    preset.id.includes('plus') ||
    preset.model.includes('flash') ||
    preset.capabilities.includes('cheap_batch')
  ) {
    return 'speed'
  }
  if (
    preset.id.includes('qwen') ||
    preset.id.includes('token-plan') ||
    preset.id.includes('kimi') ||
    preset.id.includes('openrouter')
  ) {
    return 'value'
  }
  return 'quality'
}

export function getTtsPresetTone(preset: TtsPreset): CatalogTone {
  if (preset.provider === 'disabled' || preset.provider === 'openai-compatible') return 'custom'
  if (preset.provider === 'qwen' || preset.model.includes('flash')) return 'speed'
  if (preset.provider === 'mimo') return 'value'
  return 'voice'
}

export function filterApiPreset(preset: ApiPreset, filter: CatalogFilter, search: string) {
  if (filter === 'saved') return false
  const tone = getApiPresetTone(preset)
  const filterMatches = filter === 'all' || filter === tone
  return (
    filterMatches &&
    matchesCatalogSearch(search, [
      preset.label,
      preset.provider,
      preset.base_url,
      preset.model,
      preset.note,
      preset.key_hint,
      preset.capabilities.join(' '),
    ])
  )
}

export function filterTtsPreset(preset: TtsPreset, filter: CatalogFilter, search: string) {
  if (filter === 'saved') return false
  const tone = getTtsPresetTone(preset)
  const filterMatches = filter === 'all' || filter === tone || (filter === 'quality' && tone === 'voice')
  return (
    filterMatches &&
    matchesCatalogSearch(search, [preset.label, preset.provider, preset.base_url, preset.model, preset.voice, preset.note, preset.key_hint])
  )
}

export function filterSavedApiProfile(profile: SavedApiProfile, filter: CatalogFilter, search: string) {
  if (filter !== 'all' && filter !== 'saved') return false
  return matchesCatalogSearch(search, [profile.label, profile.provider, profile.base_url, profile.model])
}

export function filterSavedTtsProfile(profile: SavedTtsProfile, filter: CatalogFilter, search: string) {
  if (filter !== 'all' && filter !== 'saved') return false
  return matchesCatalogSearch(search, [profile.label, profile.provider, profile.base_url, profile.model, profile.voice])
}

export function canReuseTtsKey(apiConfig: ApiConfig, provider: TtsPreset['provider']) {
  if (provider === 'mimo') return apiConfig.provider === 'mimo'
  if (provider === 'qwen') return apiConfig.provider === 'openai-compatible' && apiConfig.base_url.includes('dashscope')
  if (provider === 'gemini') return apiConfig.provider === 'gemini'
  if (provider === 'gemini-vertex') return apiConfig.provider === 'gemini-vertex'
  return false
}
