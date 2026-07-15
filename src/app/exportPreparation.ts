import { materializeLearningPointInventory } from '../domain/inventoryDrafts'
import {
  applyUsableCardSelection,
  getExportSelectionStats,
  isUsableCardForExport,
  removeExportBlockedCardSelection,
} from '../domain/quality'
import { buildReliabilityManifest, evaluateProjectReliabilityGate } from '../domain/reliability'
import { stripStaleOrdinaryAsrGate } from '../domain/payloadSanitization'
import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
  type VideoReleaseCaseId,
} from '../domain/releaseEvidenceLayout'
import { publicTemplateIdFor } from '../domain/templates'
import type { ApiConfig, GenerateRequest, Project, TemplateId, TtsConfig, TtsSemanticVerificationConfig } from '../domain/types'

type ExportPreparationBase = {
  project: Project
  materializedDraftCards: number
  removedRepairRequiredCards: number
  selectedExportableCards: number
  statusMessage: string
}

export type ExportPreparationResult =
  | (ExportPreparationBase & {
      status: 'ready'
      autoSelectedUsableCards: number
    })
  | (ExportPreparationBase & {
      status: 'blocked'
      reason: 'no_exportable_cards' | 'selected_cards_all_repair_required' | 'reliability_gate_blocked'
      reliabilityBlockerCodes?: string[]
    })

function removeSupersededRepairDraftSegments(project: Project) {
  const verifiedPointIds = new Set(
    (project.reliability_manifest?.selected_point_outcomes ?? [])
      .filter((outcome) => outcome.status === 'verified')
      .map((outcome) => outcome.learning_point_id)
      .filter(Boolean),
  )
  if (verifiedPointIds.size === 0) return { project, removedCards: 0 }

  const pointIdsWithUsableCards = new Set<string>()
  project.segments.forEach((segment) => {
    segment.cards.forEach((card) => {
      const pointId = String(card.learning_point_id || segment.learning_point_id || '')
      if (pointId && verifiedPointIds.has(pointId) && isUsableCardForExport(segment, card)) {
        pointIdsWithUsableCards.add(pointId)
      }
    })
  })
  if (pointIdsWithUsableCards.size === 0) return { project, removedCards: 0 }

  let removedCards = 0
  const segments = project.segments.filter((segment) => {
    const pointIds = new Set(
      [segment.learning_point_id, ...segment.cards.map((card) => card.learning_point_id)]
        .map((value) => String(value || ''))
        .filter(Boolean),
    )
    const isSupersededRepairOnlySegment =
      pointIds.size > 0 &&
      [...pointIds].every((pointId) => pointIdsWithUsableCards.has(pointId)) &&
      segment.cards.length > 0 &&
      segment.cards.every((card) => !isUsableCardForExport(segment, card))
    if (isSupersededRepairOnlySegment) removedCards += segment.cards.length
    return !isSupersededRepairOnlySegment
  })
  return removedCards > 0 ? { project: { ...project, segments }, removedCards } : { project, removedCards: 0 }
}

function exportScopedReliabilityManifest(project: Project) {
  const manifest = project.reliability_manifest
  if (!manifest) return undefined

  const selectedPointIds = new Set<string>()
  let selectedCardsWithoutPointId = 0
  project.segments.forEach((segment) => {
    segment.cards.forEach((card) => {
      if (!card.enabled || !isUsableCardForExport(segment, card)) return
      const pointId = String(card.learning_point_id || segment.learning_point_id || '').trim()
      if (pointId) selectedPointIds.add(pointId)
      else selectedCardsWithoutPointId += 1
    })
  })

  return buildReliabilityManifest({
    outcomes: manifest.selected_point_outcomes.filter((outcome) => selectedPointIds.has(outcome.learning_point_id)),
    selectedPointCount: selectedPointIds.size + selectedCardsWithoutPointId,
    sourceFingerprint: manifest.source_fingerprint,
    modelProvider: manifest.model_provider,
    modelName: manifest.model_name,
    verificationProfile: manifest.verification_profile,
    createdAt: manifest.created_at,
  })
}

function evaluateExportSelectionReliability(project: Project) {
  const scopedManifest = exportScopedReliabilityManifest(project)
  return evaluateProjectReliabilityGate({
    ...project,
    ...(scopedManifest ? { reliability_manifest: scopedManifest } : {}),
    // Reliability is an export contract. Disabled repair drafts remain available
    // in the review UI, but must not block the verified subset the user chose.
    segments: project.segments.map((segment) => ({
      ...segment,
      cards: segment.cards.filter((card) => card.enabled),
    })),
  })
}

export function prepareProjectForExport(project: Project): ExportPreparationResult {
  const supersededDraftCleanup = removeSupersededRepairDraftSegments(project)
  let projectForExport = supersededDraftCleanup.project
  const messages: string[] = []
  if (supersededDraftCleanup.removedCards > 0) {
    messages.push(`已清理 ${supersededDraftCleanup.removedCards} 张已被正式卡替代的旧保底草稿。`)
  }
  const materializedForExport = materializeLearningPointInventory(projectForExport)
  if (materializedForExport.added > 0) {
    projectForExport = materializedForExport.project
    messages.push(`已自动把 ${materializedForExport.added} 个合法学习点补成需修复草稿卡；这些草稿默认不导出。`)
  }

  let currentExportStats = getExportSelectionStats(projectForExport)
  let selectedForExport = currentExportStats.selectedExportableCards
  const hadUserSelectedCards = currentExportStats.selectedCards > 0
  const safeSelection = removeExportBlockedCardSelection(projectForExport)
  if (safeSelection.removed > 0) {
    projectForExport = safeSelection.project
    currentExportStats = getExportSelectionStats(projectForExport)
    selectedForExport = currentExportStats.selectedExportableCards
    if (selectedForExport === 0 && hadUserSelectedCards) {
      return {
        status: 'blocked',
        reason: 'selected_cards_all_repair_required',
        project: projectForExport,
        materializedDraftCards: materializedForExport.added,
        removedRepairRequiredCards: supersededDraftCleanup.removedCards + safeSelection.removed,
        selectedExportableCards: 0,
        statusMessage:
          `已移除 ${safeSelection.removed} 张需修复/不可导出的卡片；当前没有剩余可导出的正式卡。` +
          '请重新生成，或手动修正草稿字段后再导出。',
      }
    }
    messages.push(`已移除 ${safeSelection.removed} 张需修复/不可导出的卡片，继续导出剩余 ${selectedForExport} 张。`)
  }

  let autoSelectedUsableCards = 0
  if (selectedForExport === 0) {
    const usableSelection = applyUsableCardSelection(projectForExport)
    if (usableSelection.selected === 0) {
      return {
        status: 'blocked',
        reason: 'no_exportable_cards',
        project: projectForExport,
        materializedDraftCards: materializedForExport.added,
        removedRepairRequiredCards: supersededDraftCleanup.removedCards + safeSelection.removed,
        selectedExportableCards: 0,
        statusMessage: '当前没有可导出的正式卡。请重新生成卡片，或手动修正“需修复”的草稿字段后再导出。',
      }
    }
    projectForExport = usableSelection.project
    selectedForExport = usableSelection.selected
    autoSelectedUsableCards = usableSelection.selected
    messages.push(`已自动启用 ${usableSelection.selected} 张可导出卡，继续导出。`)
  }

  const reliabilityGate = evaluateExportSelectionReliability(projectForExport)
  if (reliabilityGate.decision === 'block') {
    return {
      status: 'blocked',
      reason: 'reliability_gate_blocked',
      project: projectForExport,
      materializedDraftCards: materializedForExport.added,
      removedRepairRequiredCards: supersededDraftCleanup.removedCards + safeSelection.removed,
      selectedExportableCards: selectedForExport,
      reliabilityBlockerCodes: reliabilityGate.blockerCodes,
      statusMessage:
        `可靠性门禁未通过（${reliabilityGate.blockerCodes.join('、')}）。` +
        '实际导出的学习点必须全部完成验证；未选中的保底草稿和待修复卡不会进入 APKG。',
    }
  }

  return {
    status: 'ready',
    project: projectForExport,
    materializedDraftCards: materializedForExport.added,
    removedRepairRequiredCards: supersededDraftCleanup.removedCards + safeSelection.removed,
    selectedExportableCards: selectedForExport,
    autoSelectedUsableCards,
    statusMessage: messages.join(' '),
  }
}

export type BuildProjectExportPayloadOptions = {
  project: Project
  templateId: TemplateId
  apiConfig: ApiConfig
  ttsConfig: TtsConfig
  ttsSemanticVerification?: TtsSemanticVerificationConfig
  disableMediaCacheRead?: boolean
}

export const APKG_EXPORT_DIRECTORY_DIALOG_TITLE = '选择 APKG 保存目录'

const VIDEO_RELEASE_CASE_IDS = new Set<string>(VIDEO_RELEASE_CASES.map((releaseCase) => releaseCase.id))

export type ReleaseCaseProjectIdentity = {
  title?: string | null
  source_info?: unknown
  release_case_id?: unknown
  case_id?: unknown
  release_run_dir?: unknown
  release_run_segment?: unknown
}

export type ReleaseApkgTarget = {
  caseId: VideoReleaseCaseId
  runSegment: string
  outputDir: string
  canonicalApkgPath: string
}

export type ReleaseApkgOutputGuardResult =
  | {
      status: 'ready'
      releaseCaseId: VideoReleaseCaseId | null
      releaseTarget: ReleaseApkgTarget | null
      canonicalApkgPath: string | null
    }
  | {
      status: 'blocked'
      reason: 'release_case_apkg_dir_required' | 'release_case_apkg_case_mismatch' | 'release_case_apkg_run_mismatch'
      releaseCaseId: VideoReleaseCaseId
      releaseTarget: ReleaseApkgTarget | null
      selectedOutputDir: string
      expectedDirectoryPattern: string
      statusMessage: string
    }

function isVideoReleaseCaseId(value: unknown): value is VideoReleaseCaseId {
  return typeof value === 'string' && VIDEO_RELEASE_CASE_IDS.has(value)
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

export function releaseCaseIdForProject(project: ReleaseCaseProjectIdentity | null | undefined): VideoReleaseCaseId | null {
  const record = recordValue(project)
  if (!record) return null
  const sourceInfo = recordValue(record.source_info)
  const candidates = [
    record.release_case_id,
    record.case_id,
    sourceInfo?.release_case_id,
    sourceInfo?.case_id,
    record.title,
  ]
  return candidates.find(isVideoReleaseCaseId) ?? null
}

export function releaseTargetRequiresColdMediaCacheReadsDisabled(target: ReleaseApkgTarget | null | undefined) {
  if (!target) return false
  return VIDEO_RELEASE_CASES.find((releaseCase) => releaseCase.id === target.caseId)?.cacheState === 'cold'
}

function releaseRunSegmentFromValue(value: unknown): string | null {
  const text = typeof value === 'string' ? value.trim().replace(/[/\\]+$/, '') : ''
  if (!text) return null
  const segment = text.split(/[/\\]+/).at(-1) ?? ''
  if (
    segment.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX) &&
    VIDEO_RELEASE_RUN_STAMP_PATTERN.test(segment.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
  ) {
    return segment
  }
  return null
}

export function releaseRunSegmentForProject(project: ReleaseCaseProjectIdentity | null | undefined): string | null {
  const record = recordValue(project)
  if (!record) return null
  const sourceInfo = recordValue(record.source_info)
  const candidates = [
    record.release_run_segment,
    record.release_run_dir,
    sourceInfo?.release_run_segment,
    sourceInfo?.release_run_dir,
  ]
  for (const candidate of candidates) {
    const segment = releaseRunSegmentFromValue(candidate)
    if (segment) return segment
  }
  return null
}

export function parentDirectoryFromFilePath(filePath?: string | null): string | null {
  const trimmed = typeof filePath === 'string' ? filePath.trim() : ''
  if (!trimmed) return null
  const normalized = trimmed.replace(/[/\\]+$/, '')
  const lastSlash = Math.max(normalized.lastIndexOf('\\'), normalized.lastIndexOf('/'))
  if (lastSlash <= 0) return null
  return normalized.slice(0, lastSlash)
}

export function defaultExportDirectoryForRequest(
  request: Pick<GenerateRequest, 'source_mode' | 'video_path' | 'subtitle_path'>,
): string | null {
  if (request.source_mode !== 'local') return null
  return parentDirectoryFromFilePath(request.video_path) ?? parentDirectoryFromFilePath(request.subtitle_path)
}

export function defaultExportDirectoryForProject(
  project: Pick<Project, 'source_mode' | 'video_path' | 'subtitle_path' | 'source_info'>,
): string | null {
  if (project.source_mode !== 'local') return null
  const sourceInfo = project.source_info && typeof project.source_info === 'object' ? project.source_info : null
  const sourceInfoVideoPath = sourceInfo && 'video_path' in sourceInfo && typeof sourceInfo.video_path === 'string'
    ? sourceInfo.video_path
    : null
  const sourceInfoSubtitlePath =
    sourceInfo && 'subtitle_path' in sourceInfo && typeof sourceInfo.subtitle_path === 'string'
      ? sourceInfo.subtitle_path
      : null
  return (
    parentDirectoryFromFilePath(project.video_path) ??
    parentDirectoryFromFilePath(project.subtitle_path) ??
    parentDirectoryFromFilePath(sourceInfoVideoPath) ??
    parentDirectoryFromFilePath(sourceInfoSubtitlePath)
  )
}

export function canonicalReleaseApkgPathForOutputDirectory(outputDir: string | null | undefined): string | null {
  return releaseApkgTargetForOutputDirectory(outputDir)?.canonicalApkgPath ?? null
}

export function releaseApkgTargetForOutputDirectory(outputDir: string | null | undefined): ReleaseApkgTarget | null {
  const trimmed = typeof outputDir === 'string' ? outputDir.trim().replace(/[/\\]+$/, '') : ''
  if (!trimmed) return null
  const parts = trimmed.split(/[/\\]+/)
  if (parts.length < 4) return null
  const apkgSegment = parts.at(-1)
  const caseId = parts.at(-2)
  const casesSegment = parts.at(-3)
  const runSegment = parts.at(-4)
  if (apkgSegment !== 'apkg' || casesSegment !== 'cases') return null
  if (!isVideoReleaseCaseId(caseId)) return null
  if (
    !runSegment ||
    !runSegment.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX) ||
    !VIDEO_RELEASE_RUN_STAMP_PATTERN.test(runSegment.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
  ) {
    return null
  }
  const separator = trimmed.includes('\\') ? '\\' : '/'
  return {
    caseId,
    runSegment,
    outputDir: trimmed,
    canonicalApkgPath: `${trimmed}${separator}${caseId}.apkg`,
  }
}

function releaseApkgDirectoryPattern(caseId: VideoReleaseCaseId, runSegment?: string | null): string {
  return `...\\${runSegment || `${VIDEO_RELEASE_RUN_DIR_PREFIX}YYYYMMDD_HHMMSS`}\\cases\\${caseId}\\apkg`
}

function releaseApkgTargetGuardMessage({
  caseId,
  target,
  expectedRunSegment,
}: {
  caseId: VideoReleaseCaseId
  target: ReleaseApkgTarget | null
  expectedRunSegment?: string | null
}) {
  const expected = releaseApkgDirectoryPattern(caseId, expectedRunSegment)
  if (target && target.caseId !== caseId) {
    return `已取消导出：当前是 release case 验收（${caseId}），保存目录必须是 ${expected}；不能写入 ${target.caseId} 的 APKG 目录。`
  }
  if (target && expectedRunSegment && target.runSegment !== expectedRunSegment) {
    return `已取消导出：当前是 release case 验收（${caseId}），保存目录必须属于本次 run：${expected}；不能写入 ${target.runSegment}。`
  }
  return `已取消导出：当前是 release case 验收（${caseId}），保存目录必须是 ${expected}；不能选择 Documents、素材目录或 case 下的其他目录。`
}

export function releaseApkgOutputGuardForProject(
  project: ReleaseCaseProjectIdentity | null | undefined,
  outputDir: string | null | undefined,
): ReleaseApkgOutputGuardResult {
  const releaseCaseId = releaseCaseIdForProject(project)
  const expectedRunSegment = releaseRunSegmentForProject(project)
  const releaseTarget = releaseApkgTargetForOutputDirectory(outputDir)
  if (!releaseCaseId) {
    return {
      status: 'ready',
      releaseCaseId: null,
      releaseTarget: null,
      canonicalApkgPath: null,
    }
  }
  const selectedOutputDir = typeof outputDir === 'string' ? outputDir : ''
  if (!releaseTarget) {
    return {
      status: 'blocked',
      reason: 'release_case_apkg_dir_required',
      releaseCaseId,
      releaseTarget,
      selectedOutputDir,
      expectedDirectoryPattern: releaseApkgDirectoryPattern(releaseCaseId, expectedRunSegment),
      statusMessage: releaseApkgTargetGuardMessage({ caseId: releaseCaseId, target: releaseTarget, expectedRunSegment }),
    }
  }
  if (releaseTarget.caseId !== releaseCaseId) {
    return {
      status: 'blocked',
      reason: 'release_case_apkg_case_mismatch',
      releaseCaseId,
      releaseTarget,
      selectedOutputDir,
      expectedDirectoryPattern: releaseApkgDirectoryPattern(releaseCaseId, expectedRunSegment),
      statusMessage: releaseApkgTargetGuardMessage({ caseId: releaseCaseId, target: releaseTarget, expectedRunSegment }),
    }
  }
  if (expectedRunSegment && releaseTarget.runSegment !== expectedRunSegment) {
    return {
      status: 'blocked',
      reason: 'release_case_apkg_run_mismatch',
      releaseCaseId,
      releaseTarget,
      selectedOutputDir,
      expectedDirectoryPattern: releaseApkgDirectoryPattern(releaseCaseId, expectedRunSegment),
      statusMessage: releaseApkgTargetGuardMessage({ caseId: releaseCaseId, target: releaseTarget, expectedRunSegment }),
    }
  }
  return {
    status: 'ready',
    releaseCaseId,
    releaseTarget,
    canonicalApkgPath: releaseTarget.canonicalApkgPath,
  }
}

export function buildProjectExportPayloadProject({
  project,
  templateId,
  apiConfig,
  ttsConfig,
  ttsSemanticVerification,
  disableMediaCacheRead,
}: BuildProjectExportPayloadOptions): Project & {
  api_config: ApiConfig
  tts_config: TtsConfig
  tts_semantic_verification?: TtsSemanticVerificationConfig
} {
  const publicTemplateId = publicTemplateIdFor(templateId, project.source_mode)
  const projectForExport =
    project.source_mode === 'document'
      ? project
      : (stripStaleOrdinaryAsrGate(project as Project & Record<string, unknown>) as Project)
  const scopedReliabilityManifest = exportScopedReliabilityManifest(projectForExport)
  const apiConfigForExport = stripStaleOrdinaryAsrGate(apiConfig as ApiConfig & Record<string, unknown>) as ApiConfig
  const cacheReadPolicy = disableMediaCacheRead
    ? {
        disable_tts_cache_read: true,
        disable_media_cache_read: true,
      }
    : {}

  return {
    ...projectForExport,
    ...(scopedReliabilityManifest ? { reliability_manifest: scopedReliabilityManifest } : {}),
    ...cacheReadPolicy,
    template_id: publicTemplateId,
    api_config: {
      ...apiConfigForExport,
      ...cacheReadPolicy,
      tts_config: ttsConfig,
    },
    // The worker still accepts legacy top-level tts_config and reads it in a few paths.
    // Keep both copies aligned so a stale generated project cannot disable TTS at export.
    tts_config: ttsConfig,
    ...(ttsSemanticVerification ? { tts_semantic_verification: ttsSemanticVerification } : {}),
  }
}

export function videoExportTtsBlockReason(
  project: Pick<Project, 'source_mode'>,
  ttsConfig: TtsConfig,
  validationError: string | null,
) {
  if (project.source_mode === 'document') return null
  if (!ttsConfig.enabled || ttsConfig.provider === 'disabled') {
    return '视频卡必须包含整句 TTS 和表达 TTS。当前 TTS 已关闭，请在设置页开启并测试通过后再导出。'
  }
  if (validationError) {
    return `视频卡必须包含整句 TTS 和表达 TTS。当前 TTS 配置未通过：${validationError} 请在设置页修复并测试通过后再导出。`
  }
  return null
}

export function normalizeProjectForExportWorker(project: Project): Project {
  if (project.source_mode === 'document') return project
  return {
    ...project,
    ...(project.source_mode === 'url' ? { url_import_mode: 'video' as const } : {}),
    skip_video_slicing: false,
  }
}

export function exportStartingStatusMessage({
  sourceMode,
  auto,
  ttsConfigError,
}: {
  sourceMode: Project['source_mode']
  auto?: boolean
  ttsConfigError?: string | null
}) {
  if (ttsConfigError) return `TTS 配置未通过，视频卡必须先修复整句 TTS 和表达 TTS：${ttsConfigError}`
  if (sourceMode === 'document') return '正在打包文档知识卡 apkg。'
  if (auto) return '卡片正文已完成，正在自动生成音频、切片并打包 APKG。'
  return '正在切视频、生成音频并打包 apkg。'
}

export function exportWorkerStartedProgressMessage(auto?: boolean) {
  return auto ? 'APKG 打包任务已在后台运行。' : '导出任务已在后台运行。你可以继续浏览当前卡片。'
}

export function exportWorkerStartedStatusMessage(auto?: boolean) {
  return auto ? '正在生成 APKG。导出期间不能再次生成或导出。' : '导出任务已在后台运行。导出期间不能再次生成或导出。'
}
