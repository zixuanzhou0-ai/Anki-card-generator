#!/usr/bin/env node

import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_RUN_DIR_PREFIX,
  VIDEO_RELEASE_RUN_STAMP_PATTERN,
} from '../src/domain/releaseEvidenceLayout.ts'
import { pathSegments, releaseReportOutputPathChecks } from './release_report_output_guard.mjs'
import { buildVerification } from './verify_video_release_case.mjs'

function usage() {
  return [
    'Usage: node scripts/summarize_video_release_run.mjs --run-dir PATH [--dry-run|--write] [options]',
    '',
    'Builds top-level video-release run reports from canonical per-case verifier evidence.',
    'Default mode is dry-run. Write mode updates only matrix_summary.json, release_risk_report.md, and run_observations.md.',
    'It never creates APKG, source, deck, Anki, audio, timing, cache, screenshot, observation, Computer Use, case-pass, or matrix-pass proof.',
    '',
    'Options:',
    '  --run-dir PATH                    video_release_hardening_* run directory',
    '  --dry-run                         print the planned top-level report updates without writing (default)',
    '  --write                           rewrite top-level reports with the current verified state',
    '  --output PATH                     write the summarizer JSON report; final evidence paths are refused',
    '  --overwrite                       allow replacing an existing --output file',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    runDir: null,
    runDirInput: null,
    write: false,
    dryRunExplicit: false,
    outputPath: null,
    outputPathInput: null,
    overwrite: false,
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--help' || arg === '-h') {
      console.log(usage())
      process.exit(0)
    }
    if (arg === '--write') {
      args.write = true
      continue
    }
    if (arg === '--dry-run') {
      args.dryRunExplicit = true
      continue
    }
    if (arg === '--overwrite') {
      args.overwrite = true
      continue
    }
    if (['--run-dir', '--output'].includes(arg)) {
      const value = argv[index + 1]
      if (!value) {
        throw new Error(`${arg} requires a value`)
      }
      if (arg === '--run-dir') {
        args.runDirInput = value
        args.runDir = path.resolve(value)
      } else {
        args.outputPathInput = value
        args.outputPath = path.resolve(value)
      }
      index += 1
      continue
    }
    throw new Error(`Unknown argument: ${arg}`)
  }

  if (!args.runDir) {
    throw new Error('--run-dir is required')
  }
  if (args.write && args.dryRunExplicit) {
    throw new Error('Use either --write or --dry-run, not both')
  }
  return args
}

function validateRunDirInput(runDir, rawRunDir = runDir) {
  const failedChecks = []
  if (!path.isAbsolute(runDir)) {
    failedChecks.push('run_dir_not_absolute')
  }
  if (pathSegments(rawRunDir).some((segment) => segment === '..')) {
    failedChecks.push('run_dir_path_unsafe')
  }
  const runDirName = pathSegments(runDir).at(-1) ?? ''
  if (
    !runDirName.startsWith(VIDEO_RELEASE_RUN_DIR_PREFIX) ||
    !VIDEO_RELEASE_RUN_STAMP_PATTERN.test(runDirName.slice(VIDEO_RELEASE_RUN_DIR_PREFIX.length))
  ) {
    failedChecks.push('run_dir_not_release_hardening_dir')
  }
  return failedChecks
}

function pathIsInside(childPath, parentPath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(childPath))
  return Boolean(relativePath) && !relativePath.startsWith('..') && !path.isAbsolute(relativePath)
}

function runRelativePath(runDir, filePath) {
  return path.relative(runDir, filePath).split(path.sep).join('/')
}

async function readJsonIfPresent(filePath) {
  try {
    const content = await readFile(filePath, 'utf8')
    return {
      value: JSON.parse(content.replace(/^\uFEFF/, '')),
      missing: false,
      error: null,
    }
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return { value: null, missing: true, error: null }
    }
    return {
      value: null,
      missing: false,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

async function initializedRunChecks(runDir, rawRunDir = runDir) {
  const failedChecks = validateRunDirInput(runDir, rawRunDir)
  try {
    const runStat = await stat(runDir)
    if (!runStat.isDirectory()) {
      failedChecks.push('run_dir_not_directory')
    }
  } catch (error) {
    failedChecks.push(error?.code === 'ENOENT' ? 'run_dir_not_found' : 'run_dir_access_error')
  }

  for (const releaseCase of VIDEO_RELEASE_CASES) {
    const caseDir = path.join(runDir, 'cases', releaseCase.id)
    if (!pathIsInside(caseDir, runDir)) {
      failedChecks.push(`case_${releaseCase.id}_dir_outside_run_dir`)
      continue
    }
    try {
      const caseStat = await stat(caseDir)
      if (!caseStat.isDirectory()) {
        failedChecks.push(`case_${releaseCase.id}_dir_not_directory`)
      }
    } catch (error) {
      failedChecks.push(
        error?.code === 'ENOENT' ? `case_${releaseCase.id}_dir_not_found` : `case_${releaseCase.id}_dir_access_error`,
      )
    }
  }
  return [...new Set(failedChecks)]
}

async function summarizerOutputPathChecks(args) {
  return releaseReportOutputPathChecks({
    prefix: 'summarizer',
    outputPath: args.outputPath,
    outputPathInput: args.outputPathInput,
    overwrite: args.overwrite,
    runDir: args.runDir,
  })
}

function outputPathBlockedReport(args, failedChecks) {
  return {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    status: 'blocked',
    ok: false,
    release_ready: false,
    matrix_pass_created: false,
    matrix_pass_verified: false,
    run_dir: args.runDir,
    write_requested: args.write,
    dry_run: !args.write,
    summarizer: {
      ok: false,
      failed_checks: failedChecks,
      cases_passed: 0,
      cases_blocked: VIDEO_RELEASE_CASES.length,
    },
    planned_writes: [],
    written_files: [],
    notes:
      'Summarizer report output path guard blocked before reading verifier evidence or writing top-level reports. No case-local final artifacts or matrix-pass proof were created.',
  }
}

function manifestSourceSummary(manifest) {
  const sourceCandidate = manifest?.source_candidate && typeof manifest.source_candidate === 'object' ? manifest.source_candidate : null
  if (!sourceCandidate) {
    return null
  }
  return {
    title: sourceCandidate.title ?? null,
    url: sourceCandidate.url ?? null,
    video_id: sourceCandidate.video_id ?? null,
    source_fingerprint: sourceCandidate.source_fingerprint ?? null,
    cache_probe_status: sourceCandidate.cache_probe_status ?? null,
    video_path: sourceCandidate.video_path ?? sourceCandidate.downloaded_video_path ?? null,
    subtitle_path: sourceCandidate.subtitle_path ?? null,
  }
}

function topMissingChecks(failedChecks) {
  return failedChecks.filter((check) => check !== 'case_manifest_not_passed').slice(0, 12)
}

async function summarizeCase(runDir, releaseCase) {
  const caseDir = path.join(runDir, 'cases', releaseCase.id)
  const manifestPath = path.join(caseDir, 'case_manifest.json')
  const preflightPath = path.join(caseDir, 'preflight_start.json')
  const finalizerDiagPath = path.join(caseDir, 'diagnostics', 'finalize_case_slice144_blocked_diag', 'finalizer.dry_run.json')
  const manifest = await readJsonIfPresent(manifestPath)
  const preflight = await readJsonIfPresent(preflightPath)
  const finalizerDiagnostic = await readJsonIfPresent(finalizerDiagPath)
  const verification = await buildVerification({ runDir, caseId: releaseCase.id })
  const failedChecks = verification.verification.failed_checks

  return {
    case_id: releaseCase.id,
    source: releaseCase.source,
    source_kind: releaseCase.sourceKind,
    mode: releaseCase.mode,
    cache_state: releaseCase.cacheState,
    target_card_count: releaseCase.targetCardCount,
    required_preview_cards: releaseCase.requiredPreviewCards,
    manifest_status: manifest.value?.status ?? null,
    verifier_status: verification.status,
    release_case_ready: verification.verification.ok,
    matrix_case_pass_verified: verification.matrix_pass_verified,
    failed_checks: failedChecks,
    missing_or_blocking_checks: topMissingChecks(failedChecks),
    warnings: verification.verification.warnings,
    read_errors: verification.verification.read_errors,
    artifact_summary: verification.artifact_summary,
    source_candidate: manifestSourceSummary(manifest.value),
    preflight: preflight.value
      ? {
          status: preflight.value.status ?? null,
          ok: preflight.value.preflight?.ok ?? preflight.value.ok ?? null,
          failed_checks: preflight.value.preflight?.failed_checks ?? preflight.value.failed_checks ?? [],
          path: runRelativePath(runDir, preflightPath),
        }
      : null,
    finalizer_diagnostic: finalizerDiagnostic.value
      ? {
          status: finalizerDiagnostic.value.status ?? null,
          ok: finalizerDiagnostic.value.ok ?? null,
          failed_checks: finalizerDiagnostic.value.finalizer?.failed_checks ?? [],
          path: runRelativePath(runDir, finalizerDiagPath),
        }
      : null,
  }
}

function caseStatusLabel(caseSummary) {
  if (caseSummary.release_case_ready) {
    return 'passed'
  }
  if (caseSummary.preflight?.status === 'ready_to_start') {
    return 'ready_to_start_but_missing_final_evidence'
  }
  if (caseSummary.source_candidate) {
    return 'material_promoted_but_not_final'
  }
  return 'not_started_or_missing_material'
}

function buildMatrixSummary({ runDir, generatedAt, caseSummaries }) {
  const passedCases = caseSummaries.filter((item) => item.release_case_ready)
  const blockedCases = caseSummaries.filter((item) => !item.release_case_ready)
  const releaseReady = blockedCases.length === 0 && caseSummaries.length === VIDEO_RELEASE_CASES.length
  return {
    schema_version: 2,
    generated_at: generatedAt,
    run_dir: path.basename(runDir),
    run_dir_absolute: runDir,
    status: releaseReady ? 'passed' : 'blocked',
    release_ready: releaseReady,
    matrix_pass_created: false,
    matrix_pass_verified: releaseReady,
    totals: {
      cases_total: caseSummaries.length,
      cases_passed: passedCases.length,
      cases_blocked: blockedCases.length,
      target_cards_total: caseSummaries.reduce((sum, item) => sum + item.target_card_count, 0),
      required_preview_cards_total: caseSummaries.reduce((sum, item) => sum + item.required_preview_cards, 0),
    },
    cases: caseSummaries.map((item) => ({
      case_id: item.case_id,
      status: caseStatusLabel(item),
      verifier_status: item.verifier_status,
      manifest_status: item.manifest_status,
      release_case_ready: item.release_case_ready,
      matrix_case_pass_verified: item.matrix_case_pass_verified,
      source: item.source,
      source_kind: item.source_kind,
      mode: item.mode,
      cache_state: item.cache_state,
      target_card_count: item.target_card_count,
      required_preview_cards: item.required_preview_cards,
      source_fingerprint: item.source_candidate?.source_fingerprint ?? null,
      failed_checks: item.failed_checks,
      missing_or_blocking_checks: item.missing_or_blocking_checks,
      warnings: item.warnings,
    })),
  }
}

function mdEscape(value) {
  return String(value ?? '').replace(/\|/g, '\\|').replace(/\r?\n/g, ' ')
}

function buildRiskReport({ matrixSummary, caseSummaries }) {
  const lines = [
    '# Video Release Risk Report',
    '',
    `Generated: ${matrixSummary.generated_at}`,
    `Status: ${matrixSummary.release_ready ? 'production-grade evidence complete' : 'internal testing only - not release ready'}`,
    '',
    'This report is generated from canonical per-case verifier evidence. It does not create APKG, Anki, audio, timing, cache, screenshot, observation, Computer Use, case-pass, or matrix-pass proof.',
    '',
    '## Matrix Summary',
    '',
    `- Cases passed: ${matrixSummary.totals.cases_passed}/${matrixSummary.totals.cases_total}`,
    `- Target cards represented by matrix: ${matrixSummary.totals.target_cards_total}`,
    `- Required preview/playback cards: ${matrixSummary.totals.required_preview_cards_total}`,
    `- Matrix pass verified: ${matrixSummary.matrix_pass_verified}`,
    '',
    '## Case Status',
    '',
    '| Case | Status | Source | Target | Blocking Checks |',
    '| --- | --- | --- | ---: | --- |',
  ]

  for (const item of caseSummaries) {
    const blocking = item.release_case_ready ? 'none' : item.missing_or_blocking_checks.join(', ')
    lines.push(
      `| ${mdEscape(item.case_id)} | ${mdEscape(caseStatusLabel(item))} | ${mdEscape(item.source_candidate?.source_fingerprint ?? item.source_kind)} | ${item.target_card_count} | ${mdEscape(blocking)} |`,
    )
  }

  const blockedChecks = [...new Set(caseSummaries.flatMap((item) => item.missing_or_blocking_checks))]
  lines.push(
    '',
    '## Remaining Risks',
    '',
    ...(blockedChecks.length
      ? blockedChecks.map((check) => `- ${check}`)
      : ['- No per-case verifier failures remain; confirm release policy and manual review before publishing.']),
    '',
    '## Release Judgment',
    '',
    matrixSummary.release_ready
      ? 'All matrix cases currently pass the canonical verifier. Review screenshots, observations, and release notes before declaring production-grade.'
      : 'Not production-grade. At least one matrix case is missing canonical case-local final evidence.',
    '',
  )
  return lines.join('\n')
}

function buildRunObservations({ matrixSummary, caseSummaries }) {
  const lines = [
    '# Video Release Run Observations',
    '',
    `Generated: ${matrixSummary.generated_at}`,
    '',
    'This file summarizes observed run state from canonical case manifests and verifier outputs. Manual observations from a future Computer Use pass should remain case-local and referenced by the final observations artifacts.',
    '',
  ]

  for (const item of caseSummaries) {
    lines.push(`## ${item.case_id}`, '')
    lines.push(`- Status: ${caseStatusLabel(item)}`)
    lines.push(`- Manifest status: ${item.manifest_status ?? 'missing'}`)
    lines.push(`- Verifier status: ${item.verifier_status}`)
    lines.push(`- Target cards: ${item.target_card_count}`)
    lines.push(`- Required preview/playback cards: ${item.required_preview_cards}`)
    lines.push(`- Source fingerprint: ${item.source_candidate?.source_fingerprint ?? 'missing'}`)
    if (item.source_candidate?.title) {
      lines.push(`- Source title: ${item.source_candidate.title}`)
    }
    if (item.preflight) {
      lines.push(`- Preflight: ${item.preflight.status} (${item.preflight.path})`)
    }
    if (item.finalizer_diagnostic) {
      lines.push(`- Latest finalizer diagnostic: ${item.finalizer_diagnostic.status} (${item.finalizer_diagnostic.path})`)
    }
    lines.push(
      `- Blocking checks: ${item.release_case_ready ? 'none' : item.missing_or_blocking_checks.join(', ') || 'unknown'}`,
    )
    lines.push('')
  }
  return lines.join('\n')
}

function writeSummary(kind, relativePath, content, runDir) {
  return {
    kind,
    relative_path: relativePath,
    absolute_path: path.join(runDir, relativePath),
    write_mode: 'top_level_report_rewrite',
    bytes: Buffer.byteLength(content, 'utf8'),
    content,
  }
}

async function writeReport(outputPath, result, overwrite) {
  if (!outputPath) {
    return
  }
  await mkdir(path.dirname(outputPath), { recursive: true })
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, {
    encoding: 'utf8',
    flag: overwrite ? 'w' : 'wx',
  })
}

async function summarizeRun(args) {
  const runChecks = await initializedRunChecks(args.runDir, args.runDirInput ?? args.runDir)
  if (runChecks.length > 0) {
    return {
      schema_version: 1,
      generated_at: new Date().toISOString(),
      status: 'blocked',
      ok: false,
      release_ready: false,
      matrix_pass_created: false,
      matrix_pass_verified: false,
      run_dir: args.runDir,
      summarizer: {
        ok: false,
        failed_checks: runChecks,
      },
      planned_writes: [],
      written_files: [],
    }
  }

  const generatedAt = new Date().toISOString()
  const caseSummaries = []
  for (const releaseCase of VIDEO_RELEASE_CASES) {
    caseSummaries.push(await summarizeCase(args.runDir, releaseCase))
  }
  const matrixSummary = buildMatrixSummary({ runDir: args.runDir, generatedAt, caseSummaries })
  const riskReport = buildRiskReport({ matrixSummary, caseSummaries })
  const runObservations = buildRunObservations({ matrixSummary, caseSummaries })
  const writes = [
    writeSummary('matrix_summary', 'matrix_summary.json', `${JSON.stringify(matrixSummary, null, 2)}\n`, args.runDir),
    writeSummary('release_risk_report', 'release_risk_report.md', `${riskReport}\n`, args.runDir),
    writeSummary('run_observations', 'run_observations.md', `${runObservations}\n`, args.runDir),
  ]

  const plannedWrites = writes.map(({ content, ...write }) => write)
  const writtenFiles = []
  if (args.write) {
    for (const write of writes) {
      await writeFile(write.absolute_path, write.content, { encoding: 'utf8', flag: 'w' })
      const { content, ...written } = write
      writtenFiles.push(written)
    }
  }

  return {
    schema_version: 1,
    generated_at: generatedAt,
    status: matrixSummary.release_ready ? 'passed' : 'blocked',
    ok: matrixSummary.release_ready,
    release_ready: matrixSummary.release_ready,
    matrix_pass_created: false,
    matrix_pass_verified: matrixSummary.matrix_pass_verified,
    run_dir: args.runDir,
    write_requested: args.write,
    dry_run: !args.write,
    summarizer: {
      ok: matrixSummary.release_ready,
      failed_checks: matrixSummary.release_ready ? [] : ['matrix_cases_not_all_passed'],
      cases_passed: matrixSummary.totals.cases_passed,
      cases_blocked: matrixSummary.totals.cases_blocked,
    },
    planned_writes: plannedWrites,
    written_files: writtenFiles,
    matrix_summary: matrixSummary,
    notes:
      'Top-level report summarizer only. It reads canonical per-case verifier evidence and never creates case-local final artifacts or matrix-pass proof.',
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const args = parseArgs(process.argv.slice(2))
    const outputPathChecks = await summarizerOutputPathChecks(args)
    const result = outputPathChecks.length > 0 ? outputPathBlockedReport(args, outputPathChecks) : await summarizeRun(args)
    if (outputPathChecks.length === 0) {
      await writeReport(args.outputPath, result, args.overwrite)
    }
    console.log(JSON.stringify(result, null, 2))
    process.exit(result.ok ? 0 : 2)
  } catch (error) {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  }
}
