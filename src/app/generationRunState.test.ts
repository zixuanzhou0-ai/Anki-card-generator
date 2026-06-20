import { describe, expect, it } from 'vitest'

import { buildGenerationRunState, type GenerationRunState } from './generationRunState'

type GenerationRunStateInput = Parameters<typeof buildGenerationRunState>[0]

const base: GenerationRunStateInput = {
  sourceReady: false,
  learningPointResult: null,
  generationConfirmOpen: false,
  workerOperation: { status: 'idle' },
  project: null,
  lastExport: null,
  lastWorkerError: null,
  ankiVerifyResult: null,
}

const exampleExportPath = 'C:/Example/anki-release/out/deck.apkg'
const exampleOldExportPath = 'C:/Example/anki-release/out/old.apkg'
const exampleStaleExportPath = 'C:/Example/anki-release/out/stale.apkg'

function state(overrides: Partial<GenerationRunStateInput> = {}): GenerationRunState {
  return buildGenerationRunState({ ...base, ...overrides })
}

describe('generationRunState', () => {
  it('names the documented main flow states in order', () => {
    expect(state()).toBe('source_not_ready')
    expect(state({ sourceReady: true })).toBe('source_ready')
    expect(state({ sourceReady: true, learningPointResult: { learning_points: [] } })).toBe('learning_points_ready')
    expect(
      state({
        sourceReady: true,
        learningPointResult: { learning_points: [] },
        generationConfirmOpen: true,
      }),
    ).toBe('generation_confirming')
    expect(
      state({
        sourceReady: true,
        learningPointResult: { learning_points: [] },
        generationConfirmOpen: true,
        workerOperation: { status: 'running', command: 'generate_cards_from_learning_points' },
      }),
    ).toBe('generation_running')
    expect(state({ sourceReady: true, project: { id: 'project-1' } })).toBe('cards_ready')
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        workerOperation: { status: 'running', command: 'export' },
      }),
    ).toBe('export_running')
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastWorkerError: { command: 'export', retryable: true },
      }),
    ).toBe('export_failed_retryable')
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastExport: { apkg_path: exampleExportPath },
      }),
    ).toBe('export_ready')
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastExport: { apkg_path: exampleExportPath },
        ankiVerifyResult: { ok: true, failed_checks: [] },
      }),
    ).toBe('anki_verified')
  })

  it('keeps generation and export running states ahead of stale completed artifacts', () => {
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastExport: { apkg_path: exampleOldExportPath },
        ankiVerifyResult: { ok: true, failed_checks: [] },
        workerOperation: { status: 'running', command: 'generate' },
      }),
    ).toBe('generation_running')

    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastExport: { apkg_path: exampleOldExportPath },
        ankiVerifyResult: { ok: true, failed_checks: [] },
        workerOperation: { status: 'cancelling', command: 'export' },
      }),
    ).toBe('export_running')
  })

  it('keeps retryable export failures ahead of stale clean Anki verification', () => {
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastExport: { apkg_path: exampleOldExportPath },
        lastWorkerError: { command: 'export', retryable: true },
        ankiVerifyResult: { ok: true, failed_checks: [] },
      }),
    ).toBe('export_failed_retryable')
  })

  it('only reports retryable export failure for export errors that can be retried', () => {
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastWorkerError: { command: 'export' },
      }),
    ).toBe('export_failed_retryable')

    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastWorkerError: { command: 'export', retryable: false },
      }),
    ).toBe('cards_ready')

    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastWorkerError: { command: 'generate_cards_from_learning_points', retryable: true },
      }),
    ).toBe('cards_ready')
  })

  it('keeps failed Anki verification at export-ready until verify passes cleanly', () => {
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastExport: { apkg_path: exampleExportPath },
        ankiVerifyResult: { ok: false, failed_checks: ['media_hash_mismatch'] },
      }),
    ).toBe('export_ready')
  })

  it('does not report anki_verified after export state has been cleared', () => {
    expect(
      state({
        sourceReady: true,
        project: { id: 'project-1' },
        lastExport: null,
        ankiVerifyResult: { ok: true, failed_checks: [] },
      }),
    ).toBe('cards_ready')
  })

  it('does not report export-ready terminal states without a current project', () => {
    expect(
      state({
        sourceReady: false,
        project: null,
        lastExport: { apkg_path: exampleStaleExportPath },
      }),
    ).toBe('source_not_ready')

    expect(
      state({
        sourceReady: true,
        project: null,
        lastExport: { apkg_path: exampleStaleExportPath },
      }),
    ).toBe('source_ready')

    expect(
      state({
        sourceReady: true,
        project: null,
        lastExport: { apkg_path: exampleStaleExportPath },
        ankiVerifyResult: { ok: true, failed_checks: [] },
      }),
    ).toBe('source_ready')
  })
})
