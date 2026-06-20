export type ReleaseSourceFileEvidence = {
  absolute_path: string
  sha256: string
  size_bytes: number
  mtime_ms: number
}

export type ReleaseSourceFilePreflightResult = {
  ok: boolean
  enforced: boolean
  failedChecks: string[]
  declaredSourceFiles: Record<string, ReleaseSourceFileEvidence>
  inputSourceFiles: Record<string, ReleaseSourceFileEvidence>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function unique(values: string[]) {
  return [...new Set(values)]
}

function stringValue(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : null
}

function sha256Value(value: unknown): string {
  const text = stringValue(value).toLowerCase()
  return /^[a-f0-9]{64}$/.test(text) ? text : ''
}

function normalizePath(value: string): string {
  return value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

export function normalizeReleaseSourceFileEvidence(value: unknown): ReleaseSourceFileEvidence | null {
  if (!isRecord(value)) return null
  const absolutePath = stringValue(value.absolute_path)
  const sha256 = sha256Value(value.sha256)
  const sizeBytes = numberValue(value.size_bytes)
  const mtimeMs = numberValue(value.mtime_ms)
  if (!absolutePath || !sha256 || sizeBytes === null || mtimeMs === null) return null
  return {
    absolute_path: absolutePath,
    sha256,
    size_bytes: sizeBytes,
    mtime_ms: mtimeMs,
  }
}

export function sourceFileMapFromObservedAdapterDiagnostics(
  rawObserved: unknown,
  singularSourceFileKey?: string,
): Record<string, ReleaseSourceFileEvidence> {
  if (!isRecord(rawObserved)) return {}
  const adapterDiagnostics = rawObserved.adapter_diagnostics
  if (!isRecord(adapterDiagnostics)) return {}
  const sourceFiles = adapterDiagnostics.source_files
  const normalized: Record<string, ReleaseSourceFileEvidence> = isRecord(sourceFiles)
    ? Object.fromEntries(
        Object.entries(sourceFiles)
          .map(([key, value]) => [key, normalizeReleaseSourceFileEvidence(value)] as const)
          .filter((entry): entry is [string, ReleaseSourceFileEvidence] => Boolean(entry[1])),
      )
    : {}
  const singularSourceFile = normalizeReleaseSourceFileEvidence(adapterDiagnostics.source_file)
  const normalizedSingularKey = stringValue(singularSourceFileKey)
  if (normalizedSingularKey && singularSourceFile && !normalized[normalizedSingularKey]) {
    normalized[normalizedSingularKey] = singularSourceFile
  }
  return normalized
}

export function hasObservedAdapterSourceFiles(rawObserved: unknown, singularSourceFileKey?: string): boolean {
  if (!isRecord(rawObserved)) return false
  const adapterDiagnostics = rawObserved.adapter_diagnostics
  if (!isRecord(adapterDiagnostics)) return false
  if (isRecord(adapterDiagnostics.source_files)) return true
  return Boolean(stringValue(singularSourceFileKey) && isRecord(adapterDiagnostics.source_file))
}

function sourceFileMapForPreflight({
  rawObserved,
  singularSourceFileKey,
}: {
  rawObserved: unknown
  singularSourceFileKey?: string
}) {
  return Object.fromEntries(
    Object.entries(sourceFileMapFromObservedAdapterDiagnostics(rawObserved, singularSourceFileKey))
      .map(([key, value]) => [key, normalizeReleaseSourceFileEvidence(value)] as const)
      .filter((entry): entry is [string, ReleaseSourceFileEvidence] => Boolean(entry[1])),
  )
}

export function buildReleaseSourceFilePreflight({
  rawObserved,
  actualSourceFiles,
  requiredKeys,
  singularSourceFileKey,
  enforce = hasObservedAdapterSourceFiles(rawObserved, singularSourceFileKey),
}: {
  rawObserved: unknown
  actualSourceFiles: Record<string, ReleaseSourceFileEvidence | null | undefined>
  requiredKeys: string[]
  singularSourceFileKey?: string
  enforce?: boolean
}): ReleaseSourceFilePreflightResult {
  const declaredSourceFiles = sourceFileMapForPreflight({ rawObserved, singularSourceFileKey })
  const normalizedActual = Object.fromEntries(
    Object.entries(actualSourceFiles)
      .map(([key, value]) => [key, normalizeReleaseSourceFileEvidence(value)] as const)
      .filter((entry): entry is [string, ReleaseSourceFileEvidence] => Boolean(entry[1])),
  )
  const failedChecks: string[] = []

  if (enforce && Object.keys(declaredSourceFiles).length === 0) {
    failedChecks.push('observed_source_files_missing')
  }

  if (enforce) {
    for (const key of unique(requiredKeys)) {
      const declared = declaredSourceFiles[key]
      const actual = normalizedActual[key]
      if (!declared) {
        failedChecks.push('observed_source_file_identity_missing')
        failedChecks.push(`observed_source_file_${key}_identity_missing`)
        continue
      }
      if (!actual) {
        failedChecks.push('writer_source_file_identity_missing')
        failedChecks.push(`writer_source_file_${key}_identity_missing`)
        continue
      }
      if (normalizePath(actual.absolute_path) !== normalizePath(declared.absolute_path)) {
        failedChecks.push('observed_source_file_absolute_path_mismatch')
        failedChecks.push(`observed_source_file_${key}_absolute_path_mismatch`)
      }
      if (actual.sha256 !== declared.sha256) {
        failedChecks.push('observed_source_file_sha256_mismatch')
        failedChecks.push(`observed_source_file_${key}_sha256_mismatch`)
      }
      if (actual.size_bytes !== declared.size_bytes) {
        failedChecks.push('observed_source_file_size_mismatch')
        failedChecks.push(`observed_source_file_${key}_size_mismatch`)
      }
      if (actual.mtime_ms !== declared.mtime_ms) {
        failedChecks.push('observed_source_file_mtime_mismatch')
        failedChecks.push(`observed_source_file_${key}_mtime_mismatch`)
      }
    }
  }

  const uniqueFailedChecks = unique(failedChecks)
  return {
    ok: uniqueFailedChecks.length === 0,
    enforced: enforce,
    failedChecks: uniqueFailedChecks,
    declaredSourceFiles,
    inputSourceFiles: normalizedActual,
  }
}
