import type { ApiConfig, ApiTestResult, SavedApiProfile, TtsConfig, TtsTestResult } from '../domain/types'
import { modelApiTestTitle, ttsApiTestTitle } from './controllerHelpers'

export type SettingsTestTone = 'idle' | 'testing' | 'ok' | 'warn'

export type SettingsTestStatus = {
  tone: SettingsTestTone
  title: string
  message: string
  meta: string
}

export function buildEffectiveApiTestResult({
  result,
  savedProfileTestOk,
  activeProfile,
}: {
  result: ApiTestResult | null
  savedProfileTestOk: boolean
  activeProfile?: Pick<SavedApiProfile, 'provider' | 'model'> | null
}): ApiTestResult | null {
  if (result) {
    return result
  }

  if (!savedProfileTestOk || !activeProfile) {
    return null
  }

  return {
    ok: true,
    provider: activeProfile.provider,
    model: activeProfile.model,
    message: '已保存的模型方案测试通过。配置未改变，无需重复测试。',
  }
}

export function buildApiTestStatus({
  result,
  testing,
  apiConfig,
}: {
  result: ApiTestResult | null
  testing: boolean
  apiConfig: ApiConfig
}): SettingsTestStatus {
  return {
    tone: testing ? 'testing' : result ? (result.ok ? 'ok' : 'warn') : 'idle',
    title: modelApiTestTitle(result, testing),
    message: testing
      ? '正在向当前接口发送一条短测试消息，通常几秒内会返回。'
      : (result?.message ?? '换 Provider、Base URL、模型名或 API Key 后，都建议点一次测试连接。'),
    meta: result
      ? `${result.provider} · ${result.model || '未填模型'}${result.latency_ms ? ` · ${result.latency_ms} ms` : ''}`
      : `${apiConfig.provider} · ${apiConfig.model || '未填模型'}`,
  }
}

export function buildTtsTestStatus({
  result,
  testing,
  tts,
}: {
  result: TtsTestResult | null
  testing: boolean
  tts: TtsConfig
}): SettingsTestStatus {
  return {
    tone: testing ? 'testing' : result ? (result.ok ? 'ok' : 'warn') : 'idle',
    title: ttsApiTestTitle(result, testing, tts.enabled),
    message: testing
      ? '正在生成一小段测试音频，用来确认 Key、语音和接口可用。'
      : (result?.message ??
        (tts.enabled
          ? 'MIMO / Grok / Gemini / Vertex TTS / Speech API 都在这里单独测试，和上面的文本模型测试互不影响。'
          : '关闭时不能导出视频卡；导出前需要开启整句 TTS 和表达 TTS。')),
    meta: result
      ? `${result.provider} · ${result.model || '无模型名'} · ${result.voice || '无 voice'}${
          result.latency_ms ? ` · ${result.latency_ms} ms` : ''
        }${result.bytes ? ` · ${result.bytes} bytes` : ''}`
      : `${tts.provider} · ${tts.model || '无模型名'} · ${tts.voice || '无 voice'}`,
  }
}
