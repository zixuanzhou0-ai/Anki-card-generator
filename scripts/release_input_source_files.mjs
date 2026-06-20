import { createHash } from 'node:crypto'
import { readFile, stat } from 'node:fs/promises'

import {
  buildReleaseSourceFilePreflight,
  sourceFileMapFromObservedAdapterDiagnostics,
} from '../src/app/releaseEvidenceSourceFilePreflight.ts'

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export async function sourceFileEvidence(filePath) {
  const content = await readFile(filePath)
  const fileStat = await stat(filePath)
  return {
    absolute_path: filePath,
    sha256: createHash('sha256').update(content).digest('hex'),
    size_bytes: fileStat.size,
    mtime_ms: Math.round(fileStat.mtimeMs),
  }
}

export async function readJsonWithSourceFile(filePath, missingCheck, invalidCheck) {
  try {
    const content = await readFile(filePath)
    const fileStat = await stat(filePath)
    const sourceFile = {
      absolute_path: filePath,
      sha256: createHash('sha256').update(content).digest('hex'),
      size_bytes: fileStat.size,
      mtime_ms: Math.round(fileStat.mtimeMs),
    }
    try {
      return {
        value: JSON.parse(content.toString('utf8').replace(/^\uFEFF/, '')),
        failedChecks: [],
        error: null,
        sourceFile,
      }
    } catch (error) {
      return {
        value: null,
        failedChecks: [invalidCheck],
        error: error instanceof Error ? error.message : String(error),
        sourceFile,
      }
    }
  } catch (error) {
    return {
      value: null,
      failedChecks: [error?.code === 'ENOENT' ? missingCheck : invalidCheck],
      error: error instanceof Error ? error.message : String(error),
      sourceFile: null,
    }
  }
}

async function declaredSourceEvidence(declaredSourceFiles, requiredKeys) {
  const sourceFiles = {}
  const readErrors = {}
  const failedChecks = []
  for (const key of requiredKeys) {
    const declared = isRecord(declaredSourceFiles) ? declaredSourceFiles[key] : null
    const absolutePath = isRecord(declared) && typeof declared.absolute_path === 'string' ? declared.absolute_path : ''
    if (!absolutePath) continue
    try {
      sourceFiles[key] = await sourceFileEvidence(absolutePath)
    } catch (error) {
      failedChecks.push('writer_source_file_read_error')
      failedChecks.push(`writer_source_file_${key}_read_error`)
      readErrors[`source_file_${key}`] = error instanceof Error ? error.message : String(error)
    }
  }
  return { sourceFiles, failedChecks, readErrors }
}

export async function buildWriterInputSourceFilePreflight({
  rawObserved,
  actualSourceFiles,
  requiredKeys,
  singularSourceFileKey,
  enforce,
}) {
  const declaredSourceFiles = sourceFileMapFromObservedAdapterDiagnostics(rawObserved, singularSourceFileKey)
  const rehashed = await declaredSourceEvidence(declaredSourceFiles, requiredKeys)
  const preflight = buildReleaseSourceFilePreflight({
    rawObserved,
    actualSourceFiles: {
      ...rehashed.sourceFiles,
      ...actualSourceFiles,
    },
    requiredKeys,
    singularSourceFileKey,
    enforce,
  })
  return {
    ...preflight,
    failedChecks: [...rehashed.failedChecks, ...preflight.failedChecks],
    readErrors: rehashed.readErrors,
  }
}
