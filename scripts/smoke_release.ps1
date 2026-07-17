param(
  [string]$WorkerPath = "",
  [string]$OutputDir = "",
  [switch]$IncludeDocumentSmoke
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $WorkerPath) {
  $WorkerPath = Join-Path $Root "workers\anki_worker.py"
}
if (-not $OutputDir) {
  $OutputDir = Join-Path $Root "release\smoke"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$SmokeInput = Join-Path $OutputDir "input"
$SmokeOut = Join-Path $OutputDir "out"
New-Item -ItemType Directory -Force -Path $SmokeInput | Out-Null
New-Item -ItemType Directory -Force -Path $SmokeOut | Out-Null
$SmokeTemp = Join-Path $OutputDir "tmp"
New-Item -ItemType Directory -Force -Path $SmokeTemp | Out-Null
$env:TEMP = $SmokeTemp
$env:TMP = $SmokeTemp
$env:TMPDIR = $SmokeTemp

$Video = Join-Path $SmokeInput "smoke-video.mp4"
$Srt = Join-Path $SmokeInput "smoke-video.srt"
$GenerateJson = Join-Path $OutputDir "generate.json"
$ExportJson = Join-Path $OutputDir "export.json"
$VerifyJson = Join-Path $OutputDir "verify_apkg.json"
$VerifyOut = Join-Path $OutputDir "verify_import"
$LegacySmokeOut = Join-Path $OutputDir "legacy-out"
$LegacyExportJson = Join-Path $OutputDir "legacy_v10_export.json"
$LegacyVerifyJson = Join-Path $OutputDir "legacy_v10_verify_apkg.json"
$LegacyVerifyOut = Join-Path $OutputDir "legacy_v10_verify_import"
$Document = Join-Path $SmokeInput "study-notes.md"
$DocumentGenerateJson = Join-Path $OutputDir "document_generate.json"
$DocumentExportJson = Join-Path $OutputDir "document_export.json"
$DocumentVerifyJson = Join-Path $OutputDir "document_verify_apkg.json"
$DocumentVerifyOut = Join-Path $OutputDir "document_verify_import"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

function Enable-SmokeTtsConfig {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Project
  )

  if (-not $Project.PSObject.Properties["api_config"] -or $null -eq $Project.api_config) {
    $Project | Add-Member -NotePropertyName "api_config" -NotePropertyValue ([pscustomobject]@{}) -Force
  }
  if (-not $Project.api_config.PSObject.Properties["tts_config"] -or $null -eq $Project.api_config.tts_config) {
    $Project.api_config | Add-Member -NotePropertyName "tts_config" -NotePropertyValue ([pscustomobject]@{}) -Force
  }

  $Tts = $Project.api_config.tts_config
  $Tts | Add-Member -NotePropertyName "enabled" -NotePropertyValue $true -Force
  $Tts | Add-Member -NotePropertyName "provider" -NotePropertyValue "openai-compatible" -Force
  $Tts | Add-Member -NotePropertyName "api_key" -NotePropertyValue "smoke-test-key" -Force
  $Tts | Add-Member -NotePropertyName "base_url" -NotePropertyValue "https://example.invalid/v1" -Force
  $Tts | Add-Member -NotePropertyName "model" -NotePropertyValue "tts-smoke" -Force
  $Tts | Add-Member -NotePropertyName "voice" -NotePropertyValue "smoke" -Force
  $Tts | Add-Member -NotePropertyName "format" -NotePropertyValue "mp3" -Force
  $Tts | Add-Member -NotePropertyName "speed" -NotePropertyValue 1 -Force
  $Tts | Add-Member -NotePropertyName "sample_rate" -NotePropertyValue 24000 -Force
}

function Initialize-SmokeTtsCache {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Project,
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot
  )

  $WorkerRoot = Join-Path $RepoRoot "workers"
  $SeedScript = Join-Path $PSScriptRoot "seed_smoke_tts_cache.py"

  $ProjectJson = $Project | ConvertTo-Json -Depth 50
  $CacheItemsJson = $ProjectJson | & $PythonExe $SeedScript $WorkerRoot
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to compute smoke TTS cache paths."
  }

  $CacheItems = @($CacheItemsJson | ConvertFrom-Json | ForEach-Object { $_ })
  if ($CacheItems.Count -lt 1) {
    throw "Smoke TTS cache seeding found no TTS tasks."
  }

  foreach ($Item in $CacheItems) {
    $CachePath = [string]$Item.path
    $CacheParent = [System.IO.Path]::GetDirectoryName($CachePath)
    New-Item -ItemType Directory -Force -Path $CacheParent | Out-Null
    if (-not (Test-Path -LiteralPath $CachePath)) {
      $Duration = "1.20"
      ffmpeg -v error -y -f lavfi -i "anullsrc=channel_layout=mono:sample_rate=24000" -t $Duration -acodec libmp3lame -q:a 5 $CachePath | Out-Null
      if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $CachePath)) {
        throw "Failed to create smoke TTS cache file: $CachePath"
      }
    }
  }

  Write-Host "Seeded smoke TTS cache items: $($CacheItems.Count)"
}

if (-not (Test-Path $WorkerPath)) {
  throw "Worker not found: $WorkerPath"
}

@"
1
00:00:00,000 --> 00:00:02,400
Honestly, it's such a nice Monday morning.

2
00:00:02,500 --> 00:00:05,200
I need to figure out what happens next before we decide.

3
00:00:05,300 --> 00:00:08,000
It turns out this small habit can change your life.
"@ | Set-Content -Encoding UTF8 $Srt

@"
# Retrieval practice

Retrieval practice means trying to recall information before checking the answer. It improves long-term memory because the act of recall strengthens access to the idea, not only recognition.

# Interleaving

Interleaving mixes related problem types during practice. It is slower at first, but it helps learners decide which method fits a new problem.
"@ | Set-Content -Encoding UTF8 $Document

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  throw "ffmpeg is required for smoke test."
}

ffmpeg -v error -y -f lavfi -i testsrc=size=1280x720:rate=30 -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -t 8 -shortest -pix_fmt yuv420p $Video | Out-Null

$envResult = '{}' | & $Python $WorkerPath check_env | ConvertFrom-Json
if (-not $envResult.genanki) {
  throw "genanki is not available. Run scripts/setup_runtime.ps1 first."
}

$payload = @{
  source_mode = "local"
  title = "Release Smoke Test"
  video_path = $Video
  subtitle_path = $Srt
  language = "English"
  level = "B1"
  collection_levels = @("A2", "B1", "B2")
  max_segments = 0
  template_id = "immersive_v11"
  content_toggles = @{
    daily = $true
    slang = $true
    sarcasm = $true
    business = $true
    culture = $true
    profanity = $false
    romance = $false
    rare = $false
  }
  card_types = @("listening", "phrase", "cloze")
  api_config = @{
    provider = "local"
    api_key = ""
    base_url = ""
    model = ""
    capabilities = @()
    tts_config = @{
      enabled = $false
      provider = "disabled"
      api_key = ""
      base_url = ""
      model = ""
      voice = ""
      format = "mp3"
      speed = 1
      sample_rate = 24000
    }
  }
} | ConvertTo-Json -Depth 10

$project = $payload | & $Python $WorkerPath generate | ConvertFrom-Json
$project | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $GenerateJson
if (-not $project.segments -or $project.segments.Count -lt 1) {
  throw "Smoke generation produced no segments."
}

$enabledCards = 0
foreach ($segment in $project.segments) {
  foreach ($card in $segment.cards) {
    if ($card.phrase -and $card.phrase -ne "key expression") {
      $card.enabled = $true
      $enabledCards += 1
    }
  }
}
if ($enabledCards -eq 0) {
  $project.segments[0].cards[0].enabled = $true
  $enabledCards = 1
}

Enable-SmokeTtsConfig -Project $project
Initialize-SmokeTtsCache -Project $project -PythonExe $Python -RepoRoot $Root

$exportPayload = @{
  project = $project
  output_dir = $SmokeOut
} | ConvertTo-Json -Depth 30

$export = $exportPayload | & $Python $WorkerPath export | ConvertFrom-Json
$export | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $ExportJson
if (-not (Test-Path $export.apkg_path)) {
  throw "APKG was not created: $($export.apkg_path)"
}
if ($export.template_family -ne "language-immersive-v11") {
  throw "Release smoke template family drifted: $($export.template_family)"
}
if ($export.template_schema -ne "V14" -or $export.template_version -ne "V14") {
  throw "Release smoke template schema is not V14: $($export.template_schema) / $($export.template_version)"
}
if ([int64]$export.note_model_id -ne 3157735470) {
  throw "Release smoke Note Model ID drifted: $($export.note_model_id)"
}
if ([int]$export.compatibility_contract_version -ne 1 -or -not $export.note_model_contract_digest) {
  throw "Release smoke Note Model contract metadata is missing."
}

$VerifyScript = Join-Path (Split-Path $WorkerPath -Parent) "verify_apkg.py"
if (-not (Test-Path -LiteralPath $VerifyScript)) {
  throw "Required APKG verifier is missing: $VerifyScript"
}
$verify = & $Python $VerifyScript $export.apkg_path $VerifyOut | ConvertFrom-Json
$verify | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 $VerifyJson
if (-not $verify.ok) {
  throw "APKG verification failed. See $VerifyJson"
}
if ($verify.failed_checks.Count -ne 0 -or $verify.note_model_contract_issues.Count -ne 0) {
  throw "APKG Note Model contract verification reported failures. See $VerifyJson"
}
if ($verify.note_model_contracts.Count -ne 1 -or [int64]$verify.note_model_contracts[0].noteModelId -ne 3157735470) {
  throw "APKG verifier did not prove the exact V14 Note Model contract. See $VerifyJson"
}

$legacyProject = $project | ConvertTo-Json -Depth 50 | ConvertFrom-Json
$legacyProject.title = "Release Smoke V10 Compatibility"
$legacyProject.template_id = "immersive"
New-Item -ItemType Directory -Force -Path $LegacySmokeOut | Out-Null
$legacyExportPayload = @{
  project = $legacyProject
  output_dir = $LegacySmokeOut
} | ConvertTo-Json -Depth 30
$legacyExport = $legacyExportPayload | & $Python $WorkerPath export | ConvertFrom-Json
$legacyExport | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $LegacyExportJson
if (-not (Test-Path $legacyExport.apkg_path)) {
  throw "Legacy V10 compatibility APKG was not created: $($legacyExport.apkg_path)"
}
if ($legacyExport.template_family -ne "language-immersive" -or $legacyExport.template_schema -ne "V10") {
  throw "Legacy compatibility contract drifted: $($legacyExport.template_family) / $($legacyExport.template_schema)"
}
if ([int64]$legacyExport.note_model_id -ne 3784810093) {
  throw "Legacy V10 Note Model ID drifted: $($legacyExport.note_model_id)"
}
$legacyVerify = & $Python $VerifyScript $legacyExport.apkg_path $LegacyVerifyOut | ConvertFrom-Json
$legacyVerify | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 $LegacyVerifyJson
if (-not $legacyVerify.ok -or $legacyVerify.note_model_contract_issues.Count -ne 0) {
  throw "Legacy V10 compatibility APKG verification failed. See $LegacyVerifyJson"
}
if ($legacyVerify.note_model_contracts.Count -ne 1 -or [int64]$legacyVerify.note_model_contracts[0].noteModelId -ne 3784810093) {
  throw "Legacy V10 compatibility contract was not proven. See $LegacyVerifyJson"
}
if ($IncludeDocumentSmoke) {
  $documentPayload = @{
    source_mode = "document"
    title = "Document Release Smoke Test"
    document_path = $Document
    language = "English"
    level = "B1"
    collection_levels = @("A2", "B1", "B2")
    max_segments = 0
    template_id = "immersive"
    content_toggles = @{}
    language_focus = @("phrases", "listening")
    document_focus = @("concepts", "arguments", "terms")
    document_study_mode = "knowledge"
    document_answer_language = "zh"
    document_depth = "standard"
    document_answer_length = "medium"
    card_types = @("knowledge")
    api_config = @{
      provider = "local"
      api_key = ""
      base_url = ""
      model = ""
      capabilities = @()
      tts_config = @{
        enabled = $false
        provider = "disabled"
        api_key = ""
        base_url = ""
        model = ""
        voice = ""
        format = "mp3"
        speed = 1
        sample_rate = 24000
      }
    }
  } | ConvertTo-Json -Depth 10

  $documentProject = $documentPayload | & $Python $WorkerPath generate | ConvertFrom-Json
  $documentProject | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $DocumentGenerateJson
  if ($documentProject.source_mode -ne "document" -or -not $documentProject.segments -or $documentProject.segments.Count -lt 1) {
    throw "Document smoke generation produced no document segments."
  }

  $documentProject.segments[0].cards[0].enabled = $true
  $documentExportPayload = @{
    project = $documentProject
    output_dir = $SmokeOut
  } | ConvertTo-Json -Depth 30

  $documentExport = $documentExportPayload | & $Python $WorkerPath export | ConvertFrom-Json
  $documentExport | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $DocumentExportJson
  if (-not $documentExport.apkg_path -or -not (Test-Path $documentExport.apkg_path)) {
    throw "Document APKG was not created: $($documentExport.apkg_path)"
  }
  if ($documentExport.deck_kind -ne "document_knowledge") {
    throw "Document APKG deck kind is not source-aware: $($documentExport.deck_kind) / $($documentExport.deck_name)"
  }

  $documentVerify = & $Python $VerifyScript $documentExport.apkg_path $DocumentVerifyOut | ConvertFrom-Json
  $documentVerify | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 $DocumentVerifyJson
  if (-not $documentVerify.ok) {
    throw "Document APKG verification failed. See $DocumentVerifyJson"
  }
}

Write-Host "Smoke test passed." -ForegroundColor Green
Write-Host "Segments: $($project.segments.Count)"
Write-Host "APKG: $($export.apkg_path)"
Write-Host "Verify report: $VerifyJson"
Write-Host "Legacy V10 APKG: $($legacyExport.apkg_path)"
Write-Host "Legacy V10 verify report: $LegacyVerifyJson"
if ($IncludeDocumentSmoke) {
  Write-Host "Document segments: $($documentProject.segments.Count)"
  Write-Host "Document APKG: $($documentExport.apkg_path)"
  Write-Host "Document verify report: $DocumentVerifyJson"
}
