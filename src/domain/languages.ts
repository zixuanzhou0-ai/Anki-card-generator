import type {
  GenerationBasis,
  LearningLanguageCode,
  PronunciationConfidence,
  PronunciationMeta,
  TtsProvider,
} from './types'

export type PronunciationProfile = {
  code: LearningLanguageCode
  label: string
  accent_profile: string
  notation_system: string
  standard_hint: string
}

export const learningLanguageProfiles: Record<LearningLanguageCode, PronunciationProfile> = {
  en: {
    code: 'en',
    label: 'English',
    accent_profile: 'en-US-general',
    notation_system: 'ipa_en_connected',
    standard_hint: 'IPA',
  },
  fr: {
    code: 'fr',
    label: 'Français',
    accent_profile: 'fr-FR-standard-media',
    notation_system: 'api_ipa_liaison',
    standard_hint: 'API/IPA',
  },
  es: {
    code: 'es',
    label: 'Español',
    accent_profile: 'es-LatAm-general-MX-like',
    notation_system: 'spanish_syllable_stress_optional_ipa',
    standard_hint: '音节+重音',
  },
  ja: {
    code: 'ja',
    label: '日本語',
    accent_profile: 'ja-JP-Tokyo-standard',
    notation_system: 'kana_pitch',
    standard_hint: '假名+音高',
  },
  ru: {
    code: 'ru',
    label: 'Русский',
    accent_profile: 'ru-general-standard',
    notation_system: 'stressed_cyrillic_optional_ipa',
    standard_hint: '重音西里尔',
  },
}

export const learningLanguageOptions = Object.values(learningLanguageProfiles)

const languageAliases: Record<string, LearningLanguageCode> = {
  '': 'en',
  english: 'en',
  'en-us': 'en',
  'en-gb': 'en',
  'us english': 'en',
  'american english': 'en',
  英语: 'en',
  français: 'fr',
  francais: 'fr',
  french: 'fr',
  'fr-fr': 'fr',
  法语: 'fr',
  español: 'es',
  espanol: 'es',
  spanish: 'es',
  'es-mx': 'es',
  'es-419': 'es',
  'es-es': 'es',
  西班牙语: 'es',
  日本語: 'ja',
  japanese: 'ja',
  'ja-jp': 'ja',
  日语: 'ja',
  русский: 'ru',
  russian: 'ru',
  'ru-ru': 'ru',
  俄语: 'ru',
}

export function normalizeLearningLanguage(value: unknown): LearningLanguageCode {
  const raw = String(value ?? '').trim()
  const lower = raw.toLocaleLowerCase()
  if (lower in learningLanguageProfiles) return lower as LearningLanguageCode
  if (lower in languageAliases) return languageAliases[lower]
  if (lower.startsWith('en')) return 'en'
  if (lower.startsWith('fr')) return 'fr'
  if (lower.startsWith('es')) return 'es'
  if (lower.startsWith('ja') || raw.includes('日本')) return 'ja'
  if (lower.startsWith('ru') || raw.includes('Рус') || raw.includes('рус')) return 'ru'
  return 'en'
}

export function learningLanguageLabel(value: unknown): string {
  return learningLanguageProfiles[normalizeLearningLanguage(value)].label
}

export function pronunciationProfileForLanguage(value: unknown): PronunciationProfile {
  return learningLanguageProfiles[normalizeLearningLanguage(value)]
}

export function standardPronunciationHint(value: unknown): string {
  return pronunciationProfileForLanguage(value).standard_hint
}

export function normalizePronunciationMeta(value: unknown, fallbackLanguage: unknown): PronunciationMeta | null {
  let parsed: unknown = value
  if (typeof value === 'string' && value.trim()) {
    try {
      parsed = JSON.parse(value) as unknown
    } catch {
      parsed = null
    }
  }
  if (!parsed || typeof parsed !== 'object') return null
  const raw = parsed as Partial<PronunciationMeta>
  const profile = pronunciationProfileForLanguage(raw.language_code ?? fallbackLanguage)
  const generationBasis: GenerationBasis =
    raw.generation_basis === 'audio_verified' ||
    raw.generation_basis === 'subtitle_inferred' ||
    raw.generation_basis === 'dictionary_only'
      ? raw.generation_basis
      : 'subtitle_inferred'
  return {
    language_code: profile.code,
    accent_profile: String(raw.accent_profile || profile.accent_profile),
    notation_system: String(raw.notation_system || profile.notation_system),
    generation_basis: generationBasis,
    field_confidence: raw.field_confidence && typeof raw.field_confidence === 'object' ? raw.field_confidence : {},
    same_as_standard_reason: raw.same_as_standard_reason ?? null,
    pitch_confidence: raw.pitch_confidence,
    validation_issues: Array.isArray(raw.validation_issues) ? raw.validation_issues : [],
  }
}

export function spokenPronunciationLabel(meta: PronunciationMeta | null): string {
  if (!meta) return '剧中读法'
  if (meta.generation_basis === 'audio_verified') return '剧中读法'
  if (meta.generation_basis === 'dictionary_only') return '按标准读法'
  return '推测口语读法'
}

export function pronunciationBasisHint(meta: PronunciationMeta | null): string {
  if (!meta) return ''
  if (meta.generation_basis === 'audio_verified') return ''
  if (meta.generation_basis === 'dictionary_only') return '未实听，仅提供标准读法'
  return '未实听，按字幕和常见口语规律推测'
}

export function confidenceRank(value: unknown): 0 | 1 | 2 {
  if (value === 'high') return 2
  if (value === 'medium') return 1
  return 0
}

export function lowestPronunciationConfidence(values: unknown[]): PronunciationConfidence {
  return values.reduce<PronunciationConfidence>((lowest, value) => {
    const normalized = value === 'high' || value === 'medium' || value === 'low' ? value : 'low'
    return confidenceRank(normalized) < confidenceRank(lowest) ? normalized : lowest
  }, 'high')
}

const ttsFallbacks: Record<LearningLanguageCode, string[]> = {
  en: ['en-US', 'en-GB'],
  fr: ['fr-FR', 'fr-CA'],
  es: ['es-MX', 'es-419', 'es-US', 'es-ES'],
  ja: ['ja-JP'],
  ru: ['ru-RU'],
}

export function defaultTtsLanguageCode(language: unknown, _provider?: TtsProvider): string {
  return ttsFallbacks[normalizeLearningLanguage(language)][0]
}
