import type { TtsPreset } from './types'
import { MIMO_OPENAI_BASE_URL, MIMO_TOKEN_PLAN_SGP_BASE_URL } from './providers'

export const mimoTtsModels = [
  { value: 'mimo-v2.5-tts', label: 'MiMo-V2.5-TTS' },
  { value: 'mimo-v2.5-tts-voicedesign', label: 'MiMo-V2.5-TTS-VoiceDesign' },
  { value: 'mimo-v2.5-tts-voiceclone', label: 'MiMo-V2.5-TTS-VoiceClone' },
  { value: 'mimo-v2-tts', label: 'MiMo-V2-TTS' },
]

export const mimoTtsVoices = [
  'Mia',
  'Chloe',
  'Milo',
  'Dean',
  'mimo_default',
  '冰糖',
  '茉莉',
  '苏打',
  '白桦',
  'default_en',
  'default_zh',
]

export const ttsPresets: TtsPreset[] = [
  {
    id: 'disabled',
    label: '关闭 TTS',
    provider: 'disabled',
    base_url: '',
    model: '',
    voice: '',
    note: '只使用视频原声音频，不额外生成 AI 朗读。',
    key_hint: '不需要填写',
  },
  {
    id: 'mimo-token-plan-sgp-tts',
    label: 'MIMO SGP TTS',
    provider: 'mimo',
    base_url: MIMO_TOKEN_PLAN_SGP_BASE_URL,
    model: 'mimo-v2.5-tts',
    voice: 'Mia',
    note: '新加坡 Token Plan 专属 TTS；走 /chat/completions + audio，不是 /audio/speech。',
    key_hint: 'Token Plan 专属 API Key，通常是 tp-...',
  },
  {
    id: 'mimo-v25-tts',
    label: 'MIMO V2.5 TTS',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5-tts',
    voice: 'Mia',
    note: '小米 MiMo V2.5 基础语音合成；支持 Mia、Chloe、Milo、Dean 等内置声音。',
    key_hint: '公共平台 Key，通常是 sk-...；tp- Key 请选 SGP TTS。',
  },
  {
    id: 'mimo-v25-voice-design',
    label: 'MIMO VoiceDesign',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5-tts-voicedesign',
    voice: 'A warm, clear English teacher voice with natural pacing.',
    note: 'MiMo V2.5 声音设计模型；Voice 栏填写声音描述，不填内置 voice_id。',
    key_hint: 'MiMo API Key',
  },
  {
    id: 'mimo-v25-voice-clone',
    label: 'MIMO VoiceClone',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2.5-tts-voiceclone',
    voice: 'mimo_default',
    note: 'MiMo V2.5 声音克隆模型；当前先保留模型入口，参考平台要求填 voice。',
    key_hint: 'MiMo API Key',
  },
  {
    id: 'mimo-v2-tts',
    label: 'MIMO V2 TTS',
    provider: 'mimo',
    base_url: MIMO_OPENAI_BASE_URL,
    model: 'mimo-v2-tts',
    voice: 'default_en',
    note: 'MiMo V2 语音合成模型，适合旧套餐；常用 default_en、default_zh、mimo_default。',
    key_hint: 'MiMo API Key',
  },
  {
    id: 'grok',
    label: 'Grok / xAI TTS',
    provider: 'grok',
    base_url: 'https://api.x.ai/v1',
    model: '',
    voice: 'eve',
    note: '单独填写 xAI API Key；Grok TTS 使用 voice_id，例如 eve、ara、leo、rex、sal。',
    key_hint: 'xAI API Key',
  },
  {
    id: 'gemini-tts',
    label: 'Gemini TTS',
    provider: 'gemini',
    base_url: '',
    model: 'gemini-2.5-flash-preview-tts',
    voice: 'Kore',
    note: '单独填写 Gemini API Key；模型和声音按 Google AI Studio 后台调整。',
    key_hint: 'Gemini API Key',
  },
  {
    id: 'openai-speech',
    label: 'OpenAI-compatible Speech',
    provider: 'openai-compatible',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini-tts',
    voice: 'alloy',
    note: '适配 /audio/speech 兼容接口；也可填 Groq 等服务商的 speech Base URL。',
    key_hint: 'Speech API Key',
  },
]

export const featuredTtsPresetIds = new Set(['disabled', 'mimo-token-plan-sgp-tts', 'grok', 'gemini-tts'])

export const featuredTtsPresets = ttsPresets.filter((preset) => featuredTtsPresetIds.has(preset.id))
export const advancedTtsPresets = ttsPresets.filter((preset) => !featuredTtsPresetIds.has(preset.id))
