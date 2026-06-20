import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import {
  buildWriterInputSourceFilePreflight,
  sourceFileEvidence,
} from './release_input_source_files.mjs'

const tempRoot = path.join(os.tmpdir(), 'anki-release-input-source-files-')
const tempDirs = []

async function makeTempDir() {
  const dir = await mkdtemp(tempRoot)
  tempDirs.push(dir)
  return dir
}

async function writeJson(filePath, value) {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  return sourceFileEvidence(filePath)
}

afterEach(async () => {
  const dirs = tempDirs.splice(0)
  for (const dir of dirs) {
    const resolved = path.resolve(dir)
    if (!resolved.startsWith(path.resolve(os.tmpdir()))) {
      throw new Error(`Refusing to remove non-temp test directory: ${resolved}`)
    }
    await rm(resolved, { recursive: true, force: true })
  }
})

describe('release input source-file preflight script wrapper', () => {
  it('passes through mandatory enforcement for final writer inputs', async () => {
    const dir = await makeTempDir()
    const caseManifest = await writeJson(path.join(dir, 'case_manifest.json'), {
      case_id: 'local_srt_full1_cold',
    })
    const project = await writeJson(path.join(dir, 'project.raw.json'), {
      id: 'project',
    })

    const preflight = await buildWriterInputSourceFilePreflight({
      rawObserved: { case_id: 'local_srt_full1_cold', project: {} },
      actualSourceFiles: {
        case_manifest: caseManifest,
        project,
      },
      requiredKeys: ['case_manifest', 'project'],
      enforce: true,
    })

    expect(preflight.ok).toBe(false)
    expect(preflight.enforced).toBe(true)
    expect(preflight.failedChecks).toEqual(
      expect.arrayContaining([
        'observed_source_files_missing',
        'observed_source_file_case_manifest_identity_missing',
        'observed_source_file_project_identity_missing',
      ]),
    )
  })

  it('keeps directly read writer source-file evidence authoritative over declared rehashes', async () => {
    const dir = await makeTempDir()
    const canonicalManifest = await writeJson(path.join(dir, 'case_manifest.json'), {
      case_id: 'local_srt_full1_cold',
      source: 'canonical',
    })
    const declaredManifest = await writeJson(path.join(dir, 'declared_manifest.json'), {
      case_id: 'local_srt_full1_cold',
      source: 'declared',
    })
    const project = await writeJson(path.join(dir, 'project.raw.json'), {
      id: 'project',
    })

    const preflight = await buildWriterInputSourceFilePreflight({
      rawObserved: {
        case_id: 'local_srt_full1_cold',
        adapter_diagnostics: {
          source_files: {
            case_manifest: declaredManifest,
            project,
          },
        },
      },
      actualSourceFiles: {
        case_manifest: canonicalManifest,
      },
      requiredKeys: ['case_manifest', 'project'],
      enforce: true,
    })

    expect(preflight.ok).toBe(false)
    expect(preflight.inputSourceFiles.case_manifest).toEqual(canonicalManifest)
    expect(preflight.failedChecks).toEqual(
      expect.arrayContaining([
        'observed_source_file_absolute_path_mismatch',
        'observed_source_file_case_manifest_absolute_path_mismatch',
        'observed_source_file_case_manifest_sha256_mismatch',
      ]),
    )
  })
})
