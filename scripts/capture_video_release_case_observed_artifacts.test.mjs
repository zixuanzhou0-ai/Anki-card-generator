import { describe, expect, it } from 'vitest'

import {
  buildAnkiVerifyWrite,
  existingAnkiVerifyArtifactIdentityChecks,
  releaseSourceFingerprintFromManifest,
} from './capture_video_release_case_observed_artifacts.mjs'

describe('capture observed Anki verify writer identity', () => {
  it('stamps release case identity while preserving worker source fingerprints as trace metadata', () => {
    const write = buildAnkiVerifyWrite({
      runDir: 'C:\\Example\\anki-release\\test_runs\\video_release_hardening_20260620_120000',
      caseId: 'local_srt_full1_cold',
      manifest: {
        source_candidate: {
          source_fingerprint: 'file:cff7c10a1bda8f7f',
        },
      },
      observed: {
        export_result: {
          source_fingerprint: '55e5a7a525539d5396270e02d8bfbd28',
          source_identity: {
            source_fingerprint: '55e5a7a525539d5396270e02d8bfbd28',
            source_mode: 'local',
          },
        },
        anki_verify_result: {
          ok: true,
          failed_checks: [],
          source_fingerprint: '55e5a7a525539d5396270e02d8bfbd28',
          source_identity: {
            source_fingerprint: '55e5a7a525539d5396270e02d8bfbd28',
            source_mode: 'local',
          },
        },
      },
      apkgEvidence: {
        absolutePath:
          'C:\\Example\\anki-release\\test_runs\\video_release_hardening_20260620_120000\\cases\\local_srt_full1_cold\\apkg\\local_srt_full1_cold.apkg',
        relativePath: 'cases/local_srt_full1_cold/apkg/local_srt_full1_cold.apkg',
        sha256: 'a'.repeat(64),
        sizeBytes: 12345,
        mtimeMs: 1781921359665,
      },
    })

    const payload = JSON.parse(write.content)

    expect(payload.case_id).toBe('local_srt_full1_cold')
    expect(payload.source_fingerprint).toBe('file:cff7c10a1bda8f7f')
    expect(payload.export_source_fingerprint).toBe('55e5a7a525539d5396270e02d8bfbd28')
    expect(payload.worker_source_fingerprint).toBe('55e5a7a525539d5396270e02d8bfbd28')
    expect(payload.source_identity.source_fingerprint).toBe('55e5a7a525539d5396270e02d8bfbd28')
    expect(payload.apkg_relative_path).toBe('cases/local_srt_full1_cold/apkg/local_srt_full1_cold.apkg')
  })

  it('reads the release source fingerprint only from the case manifest source candidate', () => {
    expect(
      releaseSourceFingerprintFromManifest({
        source_candidate: {
          source_fingerprint: 'file:cff7c10a1bda8f7f',
        },
      }),
    ).toBe('file:cff7c10a1bda8f7f')
    expect(releaseSourceFingerprintFromManifest({})).toBe('')
  })

  it('diagnoses preserved pre-fix Anki verify artifacts without treating them as writable', () => {
    expect(
      existingAnkiVerifyArtifactIdentityChecks({
        artifact: {
          ok: true,
          failed_checks: [],
          source_fingerprint: '55e5a7a525539d5396270e02d8bfbd28',
        },
        caseId: 'local_srt_full1_cold',
        releaseSourceFingerprint: 'file:cff7c10a1bda8f7f',
      }),
    ).toEqual([
      'existing_anki_verify_stdout_case_id_mismatch',
      'existing_anki_verify_stdout_source_fingerprint_mismatch',
    ])
  })

  it('accepts existing Anki verify identity when it already matches the release layer', () => {
    expect(
      existingAnkiVerifyArtifactIdentityChecks({
        artifact: {
          case_id: 'local_srt_full1_cold',
          source_fingerprint: 'file:cff7c10a1bda8f7f',
        },
        caseId: 'local_srt_full1_cold',
        releaseSourceFingerprint: 'file:cff7c10a1bda8f7f',
      }),
    ).toEqual([])
  })

  it('diagnoses existing Anki verify artifacts that are missing release source identity', () => {
    expect(
      existingAnkiVerifyArtifactIdentityChecks({
        artifact: {
          case_id: 'local_srt_full1_cold',
        },
        caseId: 'local_srt_full1_cold',
        releaseSourceFingerprint: 'file:cff7c10a1bda8f7f',
      }),
    ).toEqual(['existing_anki_verify_stdout_source_fingerprint_missing'])
  })
})
