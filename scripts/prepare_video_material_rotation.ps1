param(
  [Parameter(ValueFromRemainingArguments = $false)]
  [string[]]$Url = @(),
  [string]$RunLabel = "",
  [string]$OutputRoot = "test_runs",
  [int]$MaxHeight = 720,
  [string]$SubLangs = "en,en-US,en-GB",
  [switch]$Download,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputRootPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputRoot))
if (-not $outputRootPath.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputRoot must stay inside the repository: $OutputRoot"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$safeLabel = ($RunLabel -replace "[^A-Za-z0-9_-]+", "_").Trim("_")
$runName = if ($safeLabel) { "video_material_rotation_${timestamp}_${safeLabel}" } else { "video_material_rotation_${timestamp}" }
$runDir = Join-Path $outputRootPath $runName
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$normalizedUrls = @()
foreach ($urlEntry in $Url) {
  foreach ($urlPart in ([string]$urlEntry -split "\s*,\s*")) {
    $trimmedPart = $urlPart.Trim()
    if ($trimmedPart) { $normalizedUrls += $trimmedPart }
  }
}
$Url = $normalizedUrls

function ConvertTo-SafeFileName([string]$Value) {
  $clean = ($Value -replace "[^A-Za-z0-9._-]+", "_").Trim("_")
  if ($clean.Length -gt 48) { return $clean.Substring(0, 48) }
  if ($clean) { return $clean }
  return "material"
}

function Get-Sha256Text([string]$Text) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

function Get-FirstExistingFilePath($Files) {
  $file = $Files | Select-Object -First 1
  if ($file) { return $file.FullName }
  return $null
}

function Get-FirstTextValue($Values, [string]$Fallback) {
  foreach ($value in $Values) {
    $text = [string]$value
    if ($text.Trim()) { return $text }
  }
  return $Fallback
}

function Get-FileEvidence([string]$FilePath) {
  if (-not $FilePath) {
    return [ordered]@{
      bytes = $null
      sha256 = $null
    }
  }
  $item = Get-Item -LiteralPath $FilePath
  $hash = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLowerInvariant()
  return [ordered]@{
    bytes = $item.Length
    sha256 = $hash
  }
}

function Find-ExistingUrlCacheDirs([string]$VideoId) {
  if (-not $VideoId) { return @() }
  $cacheRoot = Join-Path $repoRoot "projects\url_cache"
  if (-not (Test-Path -LiteralPath $cacheRoot)) { return @() }
  $matches = @()
  foreach ($dir in Get-ChildItem -LiteralPath $cacheRoot -Directory -ErrorAction SilentlyContinue) {
    $info = Join-Path $dir.FullName "source.info.json"
    if (-not (Test-Path -LiteralPath $info)) { continue }
    $pattern = '"id"\s*:\s*"' + [System.Text.RegularExpressions.Regex]::Escape($VideoId) + '"'
    if (Select-String -LiteralPath $info -Pattern $pattern -Quiet) {
      $matches += $dir.FullName
    }
  }
  return $matches
}

function Invoke-NativeCapture([string]$ExePath, [string[]]$Arguments) {
  $previousErrorAction = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $output = & $ExePath @Arguments 2>&1 | ForEach-Object { $_.ToString() }
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorAction
  }
  return [ordered]@{
    Output = @($output)
    ExitCode = $exitCode
  }
}

function Read-MetadataSummary([string]$MetadataPath, [string]$UrlValue, [int]$Index) {
  if (-not (Test-Path -LiteralPath $MetadataPath)) {
    $fallbackHash = Get-Sha256Text("${UrlValue}|${Index}")
    return [ordered]@{
      id = ""
      title = "metadata unavailable"
      duration = $null
      channel = ""
      webpage_url = $UrlValue
      fingerprint = "url:$($fallbackHash.Substring(0, 16))"
    }
  }
  $metadata = Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json
  $videoId = Get-FirstTextValue @($metadata.id) ""
  $title = Get-FirstTextValue @($metadata.title, $metadata.fulltitle) "untitled"
  $duration = $metadata.duration
  $channel = Get-FirstTextValue @($metadata.channel, $metadata.uploader) ""
  $webpageUrl = Get-FirstTextValue @($metadata.webpage_url) $UrlValue
  $fingerprintSeed = "${videoId}|${title}|${duration}|${webpageUrl}"
  $fingerprintHash = Get-Sha256Text($fingerprintSeed)
  return [ordered]@{
    id = $videoId
    title = $title
    duration = $duration
    channel = $channel
    webpage_url = $webpageUrl
    fingerprint = "yt:$($fingerprintHash.Substring(0, 16))"
  }
}

$ytDlp = $null
if (-not $DryRun) {
  $ytDlpCommand = Get-Command "yt-dlp" -ErrorAction SilentlyContinue
  if (-not $ytDlpCommand) {
    throw "yt-dlp was not found. Run the app environment check or install yt-dlp before preparing rotation materials."
  }
  $ytDlp = $ytDlpCommand.Source
}

$items = @()
$index = 0
foreach ($urlValue in $Url) {
  $index += 1
  $trimmedUrl = $urlValue.Trim()
  if (-not $trimmedUrl) { continue }

  $itemDir = Join-Path $runDir ("url_{0:00}" -f $index)
  New-Item -ItemType Directory -Force -Path $itemDir | Out-Null
  $metadataPath = Join-Path $itemDir "source.info.json"
  $probeLogPath = Join-Path $itemDir "metadata.log"
  $downloadLogPath = Join-Path $itemDir "download.log"

  if ($DryRun) {
    $dryMetadata = [ordered]@{
      id = ""
      title = "dry run material $index"
      duration = $null
      channel = ""
      webpage_url = $trimmedUrl
      dry_run = $true
    }
    $dryMetadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding utf8
    "Dry run: yt-dlp metadata probe was not executed." | Set-Content -LiteralPath $probeLogPath -Encoding utf8
  } else {
    $metadataArgs = @("--dump-single-json", "--skip-download", "--no-playlist", $trimmedUrl)
    $metadataResult = Invoke-NativeCapture $ytDlp $metadataArgs
    $metadataResult.Output | Set-Content -LiteralPath $probeLogPath -Encoding utf8
    if ($metadataResult.ExitCode -ne 0) {
      throw "yt-dlp metadata probe failed for URL $index. See $probeLogPath"
    }
    $metadataJsonLines = @($metadataResult.Output | Where-Object { $_.TrimStart().StartsWith("{") })
    if (-not $metadataJsonLines.Count) {
      throw "yt-dlp metadata probe returned no JSON for URL $index. See $probeLogPath"
    }
    ($metadataJsonLines -join "`n") | Set-Content -LiteralPath $metadataPath -Encoding utf8
  }

  $summary = Read-MetadataSummary -MetadataPath $metadataPath -UrlValue $trimmedUrl -Index $index
  $cacheDirs = Find-ExistingUrlCacheDirs -VideoId $summary.id

  if ($Download -and -not $DryRun) {
    $format = "bv*[height<=$MaxHeight]+ba/b[height<=$MaxHeight]/best[height<=$MaxHeight]/best"
    $outputTemplate = Join-Path $itemDir "source.%(ext)s"
    $downloadArgs = @(
      "--no-playlist",
      "--write-info-json",
      "--write-subs",
      "--write-auto-subs",
      "--sub-langs",
      $SubLangs,
      "--convert-subs",
      "srt",
      "--merge-output-format",
      "mp4",
      "-f",
      $format,
      "-o",
      $outputTemplate,
      $trimmedUrl
    )
    $downloadResult = Invoke-NativeCapture $ytDlp $downloadArgs
    $downloadResult.Output | Set-Content -LiteralPath $downloadLogPath -Encoding utf8
    if ($downloadResult.ExitCode -ne 0) {
      throw "yt-dlp download failed for URL $index. See $downloadLogPath"
    }
  } elseif ($Download -and $DryRun) {
    "Dry run: download was requested but not executed." | Set-Content -LiteralPath $downloadLogPath -Encoding utf8
  }

  $videoFiles = Get-ChildItem -LiteralPath $itemDir -File -ErrorAction SilentlyContinue |
    Where-Object { @(".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v") -contains $_.Extension.ToLowerInvariant() } |
    Sort-Object Length -Descending
  $subtitleFiles = Get-ChildItem -LiteralPath $itemDir -File -ErrorAction SilentlyContinue |
    Where-Object { @(".srt", ".vtt") -contains $_.Extension.ToLowerInvariant() } |
    Sort-Object Name
  $videoPath = Get-FirstExistingFilePath $videoFiles
  $subtitlePath = Get-FirstExistingFilePath $subtitleFiles
  $videoEvidence = Get-FileEvidence $videoPath
  $subtitleEvidence = Get-FileEvidence $subtitlePath
  $localFingerprint = $summary.fingerprint
  if ($videoEvidence.sha256) {
    $localFingerprint = "file:$($videoEvidence.sha256.Substring(0, 16))"
  }

  $items += [ordered]@{
    index = $index
    kind = "youtube_url"
    url = $trimmedUrl
    title = $summary.title
    duration_seconds = $summary.duration
    channel = $summary.channel
    video_id = $summary.id
    webpage_url = $summary.webpage_url
    item_dir = $itemDir
    metadata_path = $metadataPath
    downloaded_video_path = $videoPath
    subtitle_path = $subtitlePath
    video_bytes = $videoEvidence.bytes
    subtitle_bytes = $subtitleEvidence.bytes
    video_sha256 = $videoEvidence.sha256
    subtitle_sha256 = $subtitleEvidence.sha256
    source_fingerprint = $localFingerprint
    cache_probe = [ordered]@{
      status = if ($cacheDirs.Count) { "possible_existing_cache" } else { "no_existing_url_cache_found" }
      existing_url_cache_dirs = @($cacheDirs)
      note = "Cold-path timing must still disable controllable caches or use this fresh source fingerprint."
    }
  }
}

$manifest = [ordered]@{
  schema_version = 1
  created_at = (Get-Date).ToString("s")
  run_dir = $runDir
  run_label = $RunLabel
  dry_run = [bool]$DryRun
  download_requested = [bool]$Download
  max_height = $MaxHeight
  subtitle_languages = $SubLangs
  cache_policy = [ordered]@{
    old_regression_fixture = "https://www.youtube.com/watch?v=KL89K07KxYc"
    cold_path_rule = "Use new URL/source_fingerprint and disable controllable AI/card caches in payload. Do not delete old caches."
    hot_path_rule = "Repeat the same source/config with cache enabled and report cache hits/misses separately."
  }
  required_matrix = @(
    "old_url_regression_hot",
    "new_youtube_full_cold",
    "new_youtube_fast_cold",
    "new_youtube_hot",
    "youtube_derived_local_full_cold",
    "youtube_derived_local_fast_cold",
    "youtube_derived_local_hot"
  )
  items = $items
}

$manifestPath = Join-Path $runDir "material_manifest.json"
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding utf8

$summaryPath = Join-Path $runDir "summary.md"
$lines = @()
$lines += "# Video Material Rotation Prep"
$lines += ""
$lines += "- Run dir: ``$runDir``"
$lines += "- Dry run: ``$([bool]$DryRun)``"
$lines += "- Download requested: ``$([bool]$Download)``"
$lines += "- Subtitle languages: ``$SubLangs``"
$lines += "- Manifest: ``$manifestPath``"
$lines += ""
$lines += "## Materials"
$lines += ""
if ($items.Count -eq 0) {
  $lines += "No URLs were provided. Re-run with at least two new YouTube URLs."
} else {
  $lines += "| # | Title | Duration s | Video | Subtitle | Bytes | Cache probe | Fingerprint |"
  $lines += "| --- | --- | ---: | --- | --- | ---: | --- | --- |"
  foreach ($item in $items) {
    $totalBytes = [int64]0
    if ($null -ne $item.video_bytes) { $totalBytes += [int64]$item.video_bytes }
    if ($null -ne $item.subtitle_bytes) { $totalBytes += [int64]$item.subtitle_bytes }
    $lines += "| $($item.index) | $($item.title) | $($item.duration_seconds) | ``$($item.downloaded_video_path)`` | ``$($item.subtitle_path)`` | $totalBytes | $($item.cache_probe.status) | ``$($item.source_fingerprint)`` |"
  }
}
$lines += ""
$lines += "## Next"
$lines += ""
$lines += "1. Use old KL89K07KxYc only as a regression/hot fixture."
$lines += "2. For cold timing, run new URL materials with controllable caches disabled in payload."
$lines += "3. Use one downloaded ``source.*`` pair as the local video + subtitle fixture."
$lines += "4. Report cache hits/misses separately from cold-path timing."
$lines | Set-Content -LiteralPath $summaryPath -Encoding utf8

Write-Host "Material rotation manifest: $manifestPath"
Write-Host "Summary: $summaryPath"
