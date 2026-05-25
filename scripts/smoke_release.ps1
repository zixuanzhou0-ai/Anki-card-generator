param(
  [string]$WorkerPath = "",
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
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

$Video = Join-Path $SmokeInput "smoke-video.mp4"
$Srt = Join-Path $SmokeInput "smoke-video.srt"
$GenerateJson = Join-Path $OutputDir "generate.json"
$ExportJson = Join-Path $OutputDir "export.json"
$VerifyJson = Join-Path $OutputDir "verify_apkg.json"
$VerifyOut = Join-Path $OutputDir "verify_import"
$Document = Join-Path $SmokeInput "study-notes.md"
$DocumentGenerateJson = Join-Path $OutputDir "document_generate.json"
$DocumentExportJson = Join-Path $OutputDir "document_export.json"
$DocumentVerifyJson = Join-Path $OutputDir "document_verify_apkg.json"
$DocumentVerifyOut = Join-Path $OutputDir "document_verify_import"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

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
  template_id = "immersive"
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

$exportPayload = @{
  project = $project
  output_dir = $SmokeOut
} | ConvertTo-Json -Depth 30

$export = $exportPayload | & $Python $WorkerPath export | ConvertFrom-Json
$export | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $ExportJson
if (-not (Test-Path $export.apkg_path)) {
  throw "APKG was not created: $($export.apkg_path)"
}

$VerifyScript = Join-Path (Split-Path $WorkerPath -Parent) "verify_apkg.py"
if (Test-Path $VerifyScript) {
  $verify = & $Python $VerifyScript $export.apkg_path $VerifyOut | ConvertFrom-Json
  $verify | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 $VerifyJson
  if (-not $verify.ok) {
    throw "APKG verification failed. See $VerifyJson"
  }
}

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
if (-not (Test-Path $documentExport.apkg_path)) {
  throw "Document APKG was not created: $($documentExport.apkg_path)"
}
if ($documentExport.deck_kind -ne "document_knowledge") {
  throw "Document APKG deck kind is not source-aware: $($documentExport.deck_kind) / $($documentExport.deck_name)"
}

if (Test-Path $VerifyScript) {
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
Write-Host "Document segments: $($documentProject.segments.Count)"
Write-Host "Document APKG: $($documentExport.apkg_path)"
Write-Host "Document verify report: $DocumentVerifyJson"
