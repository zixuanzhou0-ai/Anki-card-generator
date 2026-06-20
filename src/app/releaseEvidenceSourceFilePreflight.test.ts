import { describe, expect, it } from 'vitest'

import {
  buildReleaseSourceFilePreflight,
  hasObservedAdapterSourceFiles,
  sourceFileMapFromObservedAdapterDiagnostics,
  type ReleaseSourceFileEvidence,
} from './releaseEvidenceSourceFilePreflight'

const exampleRunRoot = 'C:\\Example\\anki-release\\test_runs\\video_release_hardening_20260620_033203'
const exampleRunRootPosix = 'C:/Example/anki-release/test_runs/video_release_hardening_20260620_033203'

const caseManifestFile: ReleaseSourceFileEvidence = {
  absolute_path: `${exampleRunRoot}\\cases\\local_srt_full1_cold\\case_manifest.json`,
  sha256: 'a'.repeat(64),
  size_bytes: 1200,
  mtime_ms: 181000,
}

const projectFile: ReleaseSourceFileEvidence = {
  absolute_path: `${exampleRunRoot}\\cases\\local_srt_full1_cold\\diagnostics\\project.raw.json`,
  sha256: 'b'.repeat(64),
  size_bytes: 3400,
  mtime_ms: 182000,
}

function observedWithSourceFiles(sourceFiles: Record<string, ReleaseSourceFileEvidence | Record<string, unknown>>) {
  return {
    case_id: 'local_srt_full1_cold',
    adapter_diagnostics: {
      source_files: sourceFiles,
    },
  }
}

describe('releaseEvidenceSourceFilePreflight', () => {
  it('accepts matching source-file identity for captured writer inputs', () => {
    const rawObserved = observedWithSourceFiles({
      case_manifest: caseManifestFile,
      project: projectFile,
    })

    const preflight = buildReleaseSourceFilePreflight({
      rawObserved,
      actualSourceFiles: {
        case_manifest: caseManifestFile,
        project: projectFile,
      },
      requiredKeys: ['case_manifest', 'project'],
    })

    expect(preflight.ok).toBe(true)
    expect(preflight.enforced).toBe(true)
    expect(preflight.failedChecks).toEqual([])
    expect(preflight.inputSourceFiles.project).toEqual(projectFile)
    expect(sourceFileMapFromObservedAdapterDiagnostics(rawObserved).case_manifest).toEqual(caseManifestFile)
    expect(hasObservedAdapterSourceFiles(rawObserved)).toBe(true)
  })

  it('blocks captured handoffs when a required source-file key is missing', () => {
    const preflight = buildReleaseSourceFilePreflight({
      rawObserved: observedWithSourceFiles({ case_manifest: caseManifestFile }),
      actualSourceFiles: { case_manifest: caseManifestFile },
      requiredKeys: ['case_manifest', 'project'],
    })

    expect(preflight.ok).toBe(false)
    expect(preflight.failedChecks).toContain('observed_source_file_identity_missing')
    expect(preflight.failedChecks).toContain('observed_source_file_project_identity_missing')
  })

  it('blocks captured handoffs when the writer rehash does not match captured identity', () => {
    const preflight = buildReleaseSourceFilePreflight({
      rawObserved: observedWithSourceFiles({
        case_manifest: caseManifestFile,
      }),
      actualSourceFiles: {
        case_manifest: {
          absolute_path: `${exampleRunRootPosix}/cases/local_srt_full1_cold/case_manifest.json`,
          sha256: 'c'.repeat(64),
          size_bytes: caseManifestFile.size_bytes + 1,
          mtime_ms: caseManifestFile.mtime_ms + 1,
        },
      },
      requiredKeys: ['case_manifest'],
    })

    expect(preflight.ok).toBe(false)
    expect(preflight.failedChecks).not.toContain('observed_source_file_case_manifest_absolute_path_mismatch')
    expect(preflight.failedChecks).toContain('observed_source_file_sha256_mismatch')
    expect(preflight.failedChecks).toContain('observed_source_file_case_manifest_sha256_mismatch')
    expect(preflight.failedChecks).toContain('observed_source_file_size_mismatch')
    expect(preflight.failedChecks).toContain('observed_source_file_mtime_mismatch')
  })

  it('blocks captured handoffs when the writer rehash reads a different file path', () => {
    const preflight = buildReleaseSourceFilePreflight({
      rawObserved: observedWithSourceFiles({ project: projectFile }),
      actualSourceFiles: {
        project: {
          ...projectFile,
          absolute_path: `${exampleRunRoot}\\cases\\local_srt_full1_cold\\diagnostics\\other_project.raw.json`,
        },
      },
      requiredKeys: ['project'],
    })

    expect(preflight.ok).toBe(false)
    expect(preflight.failedChecks).toContain('observed_source_file_absolute_path_mismatch')
    expect(preflight.failedChecks).toContain('observed_source_file_project_absolute_path_mismatch')
  })

  it('accepts singular sidecar source-file identity when a writer supplies the required key', () => {
    const rawObserved = {
      case_id: 'local_srt_full1_cold',
      screenshots: [],
      adapter_diagnostics: {
        source_file: projectFile,
      },
    }

    const preflight = buildReleaseSourceFilePreflight({
      rawObserved,
      actualSourceFiles: {
        screenshots: projectFile,
      },
      requiredKeys: ['screenshots'],
      singularSourceFileKey: 'screenshots',
    })

    expect(preflight.ok).toBe(true)
    expect(preflight.enforced).toBe(true)
    expect(preflight.failedChecks).toEqual([])
    expect(preflight.declaredSourceFiles.screenshots).toEqual(projectFile)
    expect(sourceFileMapFromObservedAdapterDiagnostics(rawObserved, 'screenshots').screenshots).toEqual(projectFile)
    expect(hasObservedAdapterSourceFiles(rawObserved, 'screenshots')).toBe(true)
  })

  it('does not force legacy direct raw observed inputs to carry adapter diagnostics', () => {
    const preflight = buildReleaseSourceFilePreflight({
      rawObserved: { case_id: 'local_srt_full1_cold', project: {} },
      actualSourceFiles: {
        case_manifest: caseManifestFile,
      },
      requiredKeys: ['case_manifest', 'project'],
    })

    expect(preflight.ok).toBe(true)
    expect(preflight.enforced).toBe(false)
    expect(preflight.failedChecks).toEqual([])
    expect(hasObservedAdapterSourceFiles({ case_id: 'local_srt_full1_cold' })).toBe(false)
  })

  it('requires captured source-file identities when final writers enforce input provenance', () => {
    const preflight = buildReleaseSourceFilePreflight({
      rawObserved: { case_id: 'local_srt_full1_cold', project: {} },
      actualSourceFiles: {
        case_manifest: caseManifestFile,
        project: projectFile,
      },
      requiredKeys: ['case_manifest', 'project'],
      enforce: true,
    })

    expect(preflight.ok).toBe(false)
    expect(preflight.enforced).toBe(true)
    expect(preflight.failedChecks).toContain('observed_source_files_missing')
    expect(preflight.failedChecks).toContain('observed_source_file_case_manifest_identity_missing')
    expect(preflight.failedChecks).toContain('observed_source_file_project_identity_missing')
  })

  it('reports malformed adapter source files as missing required identity', () => {
    const preflight = buildReleaseSourceFilePreflight({
      rawObserved: observedWithSourceFiles({
        case_manifest: { absolute_path: caseManifestFile.absolute_path, sha256: 'not-a-sha' },
      }),
      actualSourceFiles: {
        case_manifest: caseManifestFile,
      },
      requiredKeys: ['case_manifest'],
    })

    expect(preflight.ok).toBe(false)
    expect(preflight.failedChecks).toContain('observed_source_file_case_manifest_identity_missing')
  })
})
