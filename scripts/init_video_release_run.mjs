#!/usr/bin/env node

import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { buildVideoReleaseRunInitializerPlan } from '../src/domain/releaseEvidenceLayout.ts'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function currentLocalStamp(now = new Date()) {
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(
    now.getSeconds(),
  )}`
}

function usage() {
  return [
    'Usage: node scripts/init_video_release_run.mjs [--stamp YYYYMMDD_HHMMSS] [--output-root PATH] [--dry-run]',
    '',
    'Creates a not-started video_release_hardening_* evidence skeleton.',
    'It never creates verification/audio/timing proof artifacts; those must come from the real desktop + Anki run.',
  ].join('\n')
}

function parseArgs(argv) {
  const args = {
    stamp: currentLocalStamp(),
    outputRoot: path.join(repoRoot, 'test_runs'),
    dryRun: false,
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--help' || arg === '-h') {
      console.log(usage())
      process.exit(0)
    }
    if (arg === '--dry-run') {
      args.dryRun = true
      continue
    }
    if (arg === '--stamp') {
      const value = argv[index + 1]
      if (!value) {
        throw new Error('--stamp requires a value')
      }
      args.stamp = value
      index += 1
      continue
    }
    if (arg === '--output-root') {
      const value = argv[index + 1]
      if (!value) {
        throw new Error('--output-root requires a value')
      }
      args.outputRoot = path.resolve(value)
      index += 1
      continue
    }
    throw new Error(`Unknown argument: ${arg}`)
  }

  return args
}

async function createRun({ stamp, outputRoot, dryRun }) {
  const plan = buildVideoReleaseRunInitializerPlan(stamp)
  const runDir = path.join(outputRoot, plan.runDirName)
  const directories = plan.directories.map((directory) => path.join(runDir, directory))
  const seedFiles = plan.seedFiles.map((file) => ({
    ...file,
    absolutePath: path.join(runDir, file.relativePath),
  }))

  if (!dryRun) {
    await mkdir(outputRoot, { recursive: true })
    await mkdir(runDir, { recursive: false })
    for (const directory of directories) {
      await mkdir(directory, { recursive: true })
    }
    for (const file of seedFiles) {
      await mkdir(path.dirname(file.absolutePath), { recursive: true })
      await writeFile(file.absolutePath, file.content, { encoding: 'utf8', flag: 'wx' })
    }
  }

  return {
    status: dryRun ? 'dry_run_not_written' : 'initialized_not_started',
    run_dir: runDir,
    cases: plan.cases.length,
    directories: directories.length,
    seed_files: seedFiles.length,
    release_ready: false,
  }
}

try {
  const args = parseArgs(process.argv.slice(2))
  const result = await createRun(args)
  console.log(JSON.stringify(result, null, 2))
} catch (error) {
  console.error(error instanceof Error ? error.message : error)
  process.exit(1)
}
