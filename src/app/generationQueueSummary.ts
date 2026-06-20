import type { GenerateRequest } from '../domain/types'
import type { GenerationQueueSummary, LearningPointItem } from '../domain/learningPoints'
import { learningPointGenerationBatchSize } from '../domain/learningPoints'
import type { GenerationBatchProgress } from './generationBatch'
import { sourceUrlLooksPrivate } from './controllerHelpers'

export const LARGE_GENERATION_QUEUE_THRESHOLD = 50

export function buildGenerationQueueSummary({
  generationQueuePoints,
  generationBatchProgress,
  request,
}: {
  generationQueuePoints: LearningPointItem[]
  generationBatchProgress: GenerationBatchProgress | null
  request: GenerateRequest
}): GenerationQueueSummary {
  const count = generationQueuePoints.length
  const isDocument = request.source_mode === 'document'
  const includesVideo = !isDocument
  const ttsEnabled =
    !isDocument &&
    Boolean(request.api_config.tts_config.enabled) &&
    request.api_config.tts_config.provider !== 'disabled'
  const textWeight = generationQueuePoints.reduce((total, point) => {
    const text = `${point.source_sentence || ''} ${point.answer_core || point.exact_span || ''} ${point.learning_action || ''}`
    return total + Math.max(1, Math.ceil(text.length / 520))
  }, 0)
  const estimatedModelBatches = count > 0 ? Math.max(1, Math.ceil(textWeight / 10)) : 0
  const estimatedMediaTasks = count * (includesVideo ? 4 : 0) + count * (ttsEnabled ? 2 : 0)
  const highRiskShortExpressionCount = ttsEnabled
    ? generationQueuePoints.filter((point) => {
        const expression = (point.answer_core || point.normalized_answer || point.exact_span || '').trim()
        if (!expression) return false
        const wordCount = expression.split(/\s+/).filter(Boolean).length
        return wordCount <= 2
      }).length
    : 0
  const estimatedTtsSemanticChecks = count * (ttsEnabled ? 2 : 0)
  const securityWarnings = [
    request.source_mode === 'url' && sourceUrlLooksPrivate(request.source_url)
      ? request.allow_private_network_url
        ? '已允许本机/内网 URL'
        : '本机/内网 URL 默认会被阻止'
      : '',
    request.source_mode === 'url' && request.allow_ytdlp_remote_components ? '已允许 yt-dlp remote components' : '',
    request.source_mode !== 'url' && (request.video_path || request.subtitle_path || request.document_path)
      ? '本地文件路径将在本轮确认后读取'
      : '',
  ].filter(Boolean)
  const activeBatchProgress = generationBatchProgress?.active ? generationBatchProgress : null
  const batchSize = learningPointGenerationBatchSize(count)
  const batchCount = count > 0 ? Math.ceil(count / batchSize) : 0
  return {
    count,
    batchSize,
    batchCount,
    batchMode: count > batchSize,
    completedBatches: activeBatchProgress?.completedBatches ?? 0,
    completedCount: activeBatchProgress?.completedCount ?? 0,
    generatedCount: activeBatchProgress?.generatedCount ?? 0,
    missingCount: activeBatchProgress?.missingCount ?? 0,
    exportableCount: activeBatchProgress?.exportableCount ?? 0,
    modeLabel: isDocument
      ? request.document_study_mode === 'language_reading'
        ? '文档精读'
        : '知识问答'
      : request.review_density === 'fast'
        ? '快速复读'
        : '完整复读',
    sourceLabel:
      request.source_mode === 'document'
        ? '上传文档'
        : request.source_mode === 'url'
          ? '视频链接'
          : '本地视频 + SRT',
    includesVideo,
    includesOriginalAudio: includesVideo,
    includesSentenceTts: ttsEnabled,
    includesPhraseTts: ttsEnabled,
    estimatedModelBatches,
    estimatedMediaTasks,
    estimatedTtsSemanticChecks,
    highRiskShortExpressionCount,
    ttsSemanticPassed: 0,
    ttsSemanticFailed: 0,
    ttsSemanticManualReview: 0,
    securityWarnings,
    highRisk: count >= LARGE_GENERATION_QUEUE_THRESHOLD,
  }
}
