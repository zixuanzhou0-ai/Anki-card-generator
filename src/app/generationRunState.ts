import type { AnkiVerifyResult, ExportResult, WorkerFinishedEvent, WorkerOperation } from '../domain/types'
import { ankiVerificationPassed } from './ankiVerifyState'

export type GenerationRunState =
  | 'source_not_ready'
  | 'source_ready'
  | 'learning_points_ready'
  | 'generation_confirming'
  | 'generation_running'
  | 'cards_ready'
  | 'export_running'
  | 'export_failed_retryable'
  | 'export_ready'
  | 'anki_verified'

type BuildGenerationRunStateInput = {
  sourceReady: boolean
  learningPointResult: unknown | null
  generationConfirmOpen: boolean
  workerOperation: Pick<WorkerOperation, 'status' | 'command'> | null
  project: unknown | null
  lastExport: Pick<ExportResult, 'apkg_path'> | null
  lastWorkerError: Pick<WorkerFinishedEvent, 'command' | 'retryable'> | null
  ankiVerifyResult: Pick<AnkiVerifyResult, 'ok' | 'failed_checks'> | null
}

function isGenerationCommand(command: WorkerOperation['command']) {
  return command === 'generate' || command === 'generate_cards_from_learning_points'
}

export function buildGenerationRunState({
  sourceReady,
  learningPointResult,
  generationConfirmOpen,
  workerOperation,
  project,
  lastExport,
  lastWorkerError,
  ankiVerifyResult,
}: BuildGenerationRunStateInput): GenerationRunState {
  if (workerOperation?.status === 'running' || workerOperation?.status === 'cancelling') {
    if (workerOperation.command === 'export') return 'export_running'
    if (isGenerationCommand(workerOperation.command)) return 'generation_running'
  }

  if (lastWorkerError?.command === 'export' && lastWorkerError.retryable !== false) {
    return 'export_failed_retryable'
  }

  if (project && lastExport?.apkg_path && ankiVerificationPassed(ankiVerifyResult)) {
    return 'anki_verified'
  }

  if (project && lastExport?.apkg_path) {
    return 'export_ready'
  }

  if (project) {
    return 'cards_ready'
  }

  if (generationConfirmOpen) {
    return 'generation_confirming'
  }

  if (learningPointResult) {
    return 'learning_points_ready'
  }

  return sourceReady ? 'source_ready' : 'source_not_ready'
}
