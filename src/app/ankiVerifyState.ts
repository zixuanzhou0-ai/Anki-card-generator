import type { AnkiVerifyResult, ExportResult } from '../domain/types'

export type AnkiVerifyStartPreparation =
  | {
      ok: true
      exportResult: ExportResult
    }
  | {
      ok: false
      statusMessage?: string
    }

export function ankiVerificationPassed(
  result: Pick<AnkiVerifyResult, 'ok' | 'failed_checks'> | null | undefined,
): boolean {
  return result?.ok === true && Array.isArray(result.failed_checks) && result.failed_checks.length === 0
}

export function exportResultForAnkiVerify(fullExport: ExportResult | null, compactExport: ExportResult | null) {
  if (!hasCompleteAnkiWriteEvidence(fullExport) || !hasCompleteAnkiWriteEvidence(compactExport)) {
    return null
  }
  return exportResultsHaveMatchingIdentity(fullExport, compactExport) ? fullExport : null
}

type UnknownRecord = Record<string, unknown>

const SHA256_PATTERN = /^[0-9a-f]{64}$/
const WINDOWS_DEVICE_NAME_PATTERN = /^(?:con|prn|aux|nul|clock\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)/i
const WINDOWS_INVALID_BASENAME_PATTERN = /[<>:"/\\|?*]/
const MEDIA_FIELD_BY_ROLE: Record<string, string> = {
  video: 'Video',
  poster: 'Video',
  original_audio: 'Audio',
  sentence_tts: 'TtsAudio',
  phrase_tts: 'PhraseTtsAudio',
}
const CARD_MEDIA_ROLE_BY_FIELD = {
  video_webm: 'video',
  video_mp4: 'video',
  poster: 'poster',
  original_audio: 'original_audio',
  sentence_tts_audio: 'sentence_tts',
  phrase_tts_audio: 'phrase_tts',
} as const

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function hasInvalidMediaCodePoint(value: string): boolean {
  return [...value].some((character) => {
    const codePoint = character.codePointAt(0)
    return codePoint === undefined || codePoint <= 0x1f || codePoint > 0x7f
  })
}

function isWindowsSafeMediaBasename(value: unknown): value is string {
  if (!isNonEmptyString(value) || value !== value.trim() || value.length > 255) return false
  if (hasInvalidMediaCodePoint(value)) return false
  if (value.normalize('NFC') !== value) return false
  if (value === '.' || value === '..' || value.endsWith('.') || value.endsWith(' ')) return false
  if (WINDOWS_INVALID_BASENAME_PATTERN.test(value) || WINDOWS_DEVICE_NAME_PATTERN.test(value)) return false
  return true
}

function windowsMediaNameKey(value: string): string {
  return value.normalize('NFC').toLocaleLowerCase('en-US')
}

function normalizeExportIdentityPath(value: string): string {
  const withWindowsSeparators = value.trim().replace(/\//g, '\\')
  const isUncPath = withWindowsSeparators.startsWith('\\\\')
  const withoutUncPrefix = isUncPath ? withWindowsSeparators.slice(2) : withWindowsSeparators
  const collapsed = withoutUncPrefix.replace(/\\+/g, '\\')
  const withoutTrailingSeparator = collapsed.length > 3 ? collapsed.replace(/\\+$/, '') : collapsed
  return `${isUncPath ? '\\\\' : ''}${withoutTrailingSeparator}`.toLocaleLowerCase('en-US')
}

function orderedStringsMatch(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function exportResultsHaveMatchingIdentity(full: ExportResult, compact: ExportResult): boolean {
  const scalarFields: Array<keyof ExportResult> = [
    'schema_version',
    'apkg_sha256',
    'apkg_size_bytes',
    'apkg_mtime_ms',
    'source_fingerprint',
    'deck_name',
    'deck_kind',
    'model_name',
    'note_model_id',
    'template_name',
    'template_family',
    'template_schema',
    'template_version',
    'compatibility_contract_version',
    'note_model_contract_digest',
    'anki_tag',
    'cards',
    'segments',
  ]
  if (!scalarFields.every((field) => Object.is(full[field], compact[field]))) return false
  if (normalizeExportIdentityPath(full.apkg_path) !== normalizeExportIdentityPath(compact.apkg_path)) {
    return false
  }
  if (normalizeExportIdentityPath(full.media_dir) !== normalizeExportIdentityPath(compact.media_dir)) {
    return false
  }
  if (!orderedStringsMatch(full.deck_names, compact.deck_names)) return false

  const fullFingerprint = full.note_content_fingerprint
  const compactFingerprint = compact.note_content_fingerprint
  return (
    fullFingerprint.schema_version === compactFingerprint.schema_version &&
    fullFingerprint.algorithm === compactFingerprint.algorithm &&
    fullFingerprint.serialization === compactFingerprint.serialization &&
    fullFingerprint.card_count === compactFingerprint.card_count &&
    orderedStringsMatch(fullFingerprint.field_names, compactFingerprint.field_names) &&
    full.media_summary.media_files === compact.media_summary.media_files &&
    full.media_summary.media_bytes === compact.media_summary.media_bytes &&
    full.media_summary.card_media_ledger_items === compact.media_summary.card_media_ledger_items
  )
}

export function hasCompleteAnkiWriteEvidence(
  result: ExportResult | null | undefined,
): result is ExportResult {
  try {
    if (!isRecord(result)) return false
    const candidate: UnknownRecord = result

    const manifest = candidate.media_manifest
    if (!isRecord(manifest)) return false
    const manifestEntries = Object.entries(manifest)
    const manifestNames = new Set<string>()
    const windowsManifestNames = new Set<string>()
    let manifestBytes = 0
    for (const [name, entry] of manifestEntries) {
      if (!isWindowsSafeMediaBasename(name) || !isRecord(entry)) return false
      const windowsName = windowsMediaNameKey(name)
      if (windowsManifestNames.has(windowsName)) return false
      windowsManifestNames.add(windowsName)
      if (!SHA256_PATTERN.test(String(entry.sha256 ?? ''))) return false
      if (!Number.isSafeInteger(entry.bytes) || Number(entry.bytes) < 0 || Number(entry.bytes) > 256 * 1024 * 1024) {
        return false
      }
      manifestBytes += Number(entry.bytes)
      if (!Number.isSafeInteger(manifestBytes) || manifestBytes > 2 * 1024 * 1024 * 1024) return false
      manifestNames.add(name)
    }

    const mediaLedger = candidate.media_ledger
    if (!Array.isArray(mediaLedger)) return false
    const mediaLedgerNames: string[] = []
    const mediaOwnershipKeys = new Set<string>()
    const mediaOwnershipByFile = new Map<
      string,
      { role: string; segmentId: string; field: string; cardIds: Set<string> }
    >()
    for (const item of mediaLedger) {
      if (
        !isRecord(item) ||
        !isWindowsSafeMediaBasename(item.file) ||
        !isNonEmptyString(item.role) ||
        !isNonEmptyString(item.segment_id) ||
        typeof item.card_id !== 'string' ||
        item.card_id !== item.card_id.trim() ||
        !isNonEmptyString(item.field) ||
        item.field !== MEDIA_FIELD_BY_ROLE[item.role] ||
        (item.role === 'phrase_tts' ? item.card_id.length === 0 : item.card_id.length > 0)
      ) {
        return false
      }
      if (!manifestNames.has(item.file)) return false
      const ownershipKey = [item.file, item.role, item.segment_id, item.card_id].join('\u001f')
      if (mediaOwnershipKeys.has(ownershipKey)) return false
      mediaOwnershipKeys.add(ownershipKey)
      const existingOwnership = mediaOwnershipByFile.get(item.file)
      if (
        existingOwnership &&
        (existingOwnership.role !== item.role ||
          existingOwnership.segmentId !== item.segment_id ||
          existingOwnership.field !== item.field)
      ) {
        return false
      }
      const ownership =
        existingOwnership ??
        {
          role: item.role,
          segmentId: item.segment_id,
          field: item.field,
          cardIds: new Set<string>(),
        }
      ownership.cardIds.add(item.card_id)
      mediaOwnershipByFile.set(item.file, ownership)
      mediaLedgerNames.push(item.file)
    }
    if (new Set(mediaLedgerNames).size !== manifestNames.size) return false
    if (![...manifestNames].every((name) => mediaLedgerNames.includes(name))) return false
    for (const [name, entry] of manifestEntries) {
      if (!isRecord(entry)) return false
      const ownership = mediaOwnershipByFile.get(name)
      if (!ownership) return false
      const manifestCardId = entry.card_id ?? ''
      if (
        entry.role !== ownership.role ||
        entry.segment_id !== ownership.segmentId ||
        entry.field !== ownership.field ||
        typeof manifestCardId !== 'string' ||
        manifestCardId !== manifestCardId.trim() ||
        (ownership.role === 'phrase_tts'
          ? !ownership.cardIds.has(manifestCardId)
          : manifestCardId.length > 0)
      ) {
        return false
      }
    }

    const deckName = candidate.deck_name
    const rawDeckNames = candidate.deck_names
    if (!isNonEmptyString(deckName) || !Array.isArray(rawDeckNames) || rawDeckNames.length === 0) return false
    if (
      !rawDeckNames.every(
        (name): name is string =>
          isNonEmptyString(name) && (name === deckName || name.startsWith(deckName + '::')),
      )
    ) {
      return false
    }
    const deckNames = rawDeckNames as string[]
    if (new Set(deckNames).size !== deckNames.length) return false

    const ledger = candidate.card_media_ledger
    if (!Array.isArray(ledger)) return false
    const ledgerCardIds = new Set<string>()
    const cardMediaFields = [
      'video_webm',
      'video_mp4',
      'poster',
      'original_audio',
      'sentence_tts_audio',
      'phrase_tts_audio',
    ] as const
    for (const item of ledger) {
      if (
        !isRecord(item) ||
        !isNonEmptyString(item.card_id) ||
        !isNonEmptyString(item.segment_id) ||
        !isNonEmptyString(item.deck_name) ||
        !deckNames.includes(item.deck_name) ||
        !Array.isArray(item.note_tags) ||
        item.note_tags.length !== 6 ||
        !item.note_tags.every(
          (tag) => isNonEmptyString(tag) && tag === tag.trim() && !/\s/.test(tag),
        ) ||
        new Set(item.note_tags).size !== item.note_tags.length ||
        !item.note_tags.includes(String(candidate.anki_tag ?? '')) ||
        !SHA256_PATTERN.test(String(item.note_content_sha256 ?? '')) ||
        ledgerCardIds.has(item.card_id)
      ) {
        return false
      }
      ledgerCardIds.add(item.card_id)
      for (const field of cardMediaFields) {
        const mediaName = item[field]
        if (
          mediaName !== undefined &&
          (typeof mediaName !== 'string' ||
            (mediaName.length > 0 &&
              (!isWindowsSafeMediaBasename(mediaName) || !manifestNames.has(mediaName))))
        ) {
          return false
        }
      }
    }
    const expectedOwnershipKeys = new Set<string>()
    for (const item of ledger) {
      for (const [field, role] of Object.entries(CARD_MEDIA_ROLE_BY_FIELD)) {
        const file = item[field]
        if (typeof file === 'string' && file.length > 0) {
          expectedOwnershipKeys.add(
            [file, role, item.segment_id, role === 'phrase_tts' ? item.card_id : ''].join(
              '\u001f',
            ),
          )
        }
      }
    }
    if (
      expectedOwnershipKeys.size !== mediaOwnershipKeys.size ||
      ![...expectedOwnershipKeys].every((key) => mediaOwnershipKeys.has(key))
    ) {
      return false
    }

    const fingerprint = candidate.note_content_fingerprint
    if (!isRecord(fingerprint) || !Array.isArray(fingerprint.field_names)) return false
    const fingerprintFields = fingerprint.field_names
    if (
      fingerprintFields.length === 0 ||
      !fingerprintFields.every((name) => isNonEmptyString(name) && name === name.trim()) ||
      new Set(fingerprintFields).size !== fingerprintFields.length
    ) {
      return false
    }

    const mediaSummary = candidate.media_summary
    if (!isRecord(mediaSummary)) return false

    return Boolean(
      candidate.schema_version === 2 &&
        isNonEmptyString(candidate.apkg_path) &&
        SHA256_PATTERN.test(String(candidate.apkg_sha256 ?? '')) &&
        Number.isSafeInteger(candidate.apkg_size_bytes) &&
        Number(candidate.apkg_size_bytes) >= 0 &&
        Number.isSafeInteger(candidate.apkg_mtime_ms) &&
        Number(candidate.apkg_mtime_ms) >= 0 &&
        isNonEmptyString(candidate.media_dir) &&
        isNonEmptyString(candidate.deck_kind) &&
        isNonEmptyString(candidate.model_name) &&
        Number.isSafeInteger(candidate.note_model_id) &&
        Number(candidate.note_model_id) > 0 &&
        isNonEmptyString(candidate.template_name) &&
        isNonEmptyString(candidate.template_family) &&
        ['V10', 'V12', 'V14', 'V15'].includes(String(candidate.template_schema)) &&
        candidate.template_version === candidate.template_schema &&
        candidate.compatibility_contract_version === 1 &&
        SHA256_PATTERN.test(String(candidate.note_model_contract_digest ?? '')) &&
        isNonEmptyString(candidate.anki_tag) &&
        Number.isSafeInteger(candidate.cards) &&
        Number(candidate.cards) >= 1 &&
        ledger.length === candidate.cards &&
        fingerprint.schema_version === 1 &&
        fingerprint.algorithm === 'sha256' &&
        fingerprint.serialization === 'json-field-pairs-v1' &&
        Number.isSafeInteger(fingerprint.card_count) &&
        Number(fingerprint.card_count) >= 1 &&
        fingerprint.card_count === candidate.cards &&
        fingerprint.card_count === ledger.length &&
        mediaSummary.card_media_ledger_items === ledger.length &&
        mediaSummary.media_files === manifestEntries.length &&
        mediaSummary.media_bytes === manifestBytes
    )
  } catch {
    return false
  }
}

export function prepareAnkiVerifyStart({
  workerBusy,
  exportResult,
  tauriRuntime,
}: {
  workerBusy: boolean
  exportResult: ExportResult | null
  tauriRuntime: boolean
}): AnkiVerifyStartPreparation {
  if (workerBusy) {
    return { ok: false, statusMessage: '已有任务正在运行，请先取消或等待完成。' }
  }
  if (!exportResult?.apkg_path) {
    return { ok: false }
  }
  if (!hasCompleteAnkiWriteEvidence(exportResult)) {
    return {
      ok: false,
      statusMessage: '这个 APKG 来自旧版本或恢复证据不完整，请重新导出后再导入 Anki。',
    }
  }
  if (!tauriRuntime) {
    return { ok: false, statusMessage: '浏览器预览模式不能连接 AnkiConnect。' }
  }
  return { ok: true, exportResult }
}

export function buildAnkiVerifyPayload(exportResult: ExportResult) {
  return {
    export_result: exportResult,
    import_apkg: true,
    wait_for_anki_seconds: 30,
  }
}

export function buildAnkiMediaPreparationPayload(exportResult: ExportResult) {
  return {
    export_result: exportResult,
    import_apkg: false,
    prepare_media_only: true,
    wait_for_anki_seconds: 15,
  }
}

export function ankiVerifyStartingStatusMessage() {
  return '正在通过 AnkiConnect 导入当前 APKG，并核验卡片、媒体和音频取证。'
}

export function ankiVerifyWorkerStartedMessage() {
  return 'Anki 导入与媒体核验已在后台运行。'
}

export function ankiOpenImportStartingStatusMessage() {
  return '正在启动 Anki，并安全预置本次 APKG 的媒体文件。'
}

export function ankiOpenImportRequestedStatusMessage() {
  return '媒体已安全准备，Anki 导入选项已打开；确认导入后可继续点击“导入并核验本次牌组”。'
}
