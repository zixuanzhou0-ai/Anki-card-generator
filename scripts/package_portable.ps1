param(
  [string]$ReleaseExe,
  [string]$OutputDir = "release",
  [string]$Version = "0.9.3-beta"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$OutRoot = Join-Path $Root $OutputDir
$PortableRoot = Join-Path $OutRoot "AnkiCardGenerator-v$Version-windows-portable"
$ZipPath = Join-Path $OutRoot "AnkiCardGenerator-v$Version-windows-portable.zip"

if (-not $ReleaseExe) {
  $ReleaseExe = Join-Path $Root "src-tauri\target\release\anki-card-generator.exe"
}

if (-not (Test-Path $ReleaseExe)) {
  throw "Release executable not found: $ReleaseExe. Run npm run tauri:build first or pass -ReleaseExe."
}

if (Test-Path $PortableRoot) {
  Remove-Item -Recurse -Force $PortableRoot
}
New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null

Copy-Item $ReleaseExe (Join-Path $PortableRoot "Anki Card Generator.exe")
Copy-Item (Join-Path $Root "README.md") $PortableRoot
Copy-Item (Join-Path $Root "PRIVACY.md") $PortableRoot -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "SECURITY.md") $PortableRoot -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "workers") (Join-Path $PortableRoot "workers") -Recurse

$portableScripts = Join-Path $PortableRoot "scripts"
New-Item -ItemType Directory -Force -Path $portableScripts | Out-Null
Copy-Item (Join-Path $Root "scripts\setup_runtime.ps1") $portableScripts -ErrorAction SilentlyContinue

$portableDocs = Join-Path $PortableRoot "docs"
$portableScreenshots = Join-Path $portableDocs "screenshots"
New-Item -ItemType Directory -Force -Path $portableScreenshots | Out-Null

$publicDocs = @(
  "ARCHITECTURE.md",
  "BETA_LIMITATIONS.md",
  "RELEASE_CHECKLIST.md",
  "RELEASE_NOTES_v$Version.md",
  "TROUBLESHOOTING.md",
  "USER_GUIDE.md"
)

foreach ($docName in $publicDocs) {
  Copy-Item (Join-Path $Root "docs\$docName") $portableDocs -ErrorAction SilentlyContinue
}

$publicScreenshots = @(
  "desktop-workspace.png",
  "workflow-start.png",
  "workflow-generated.png",
  "settings-model-api.png",
  "settings-tts.png",
  "settings-environment.png",
  "anki-card-stress-start.jpg",
  "anki-card-stress-middle.jpg",
  "anki-card-stress-end.jpg"
)

foreach ($screenshotName in $publicScreenshots) {
  Copy-Item (Join-Path $Root "docs\screenshots\$screenshotName") $portableScreenshots -ErrorAction SilentlyContinue
}

$internalDocPatterns = @(
  "GOAL*.md",
  "NEXT*.md",
  "HANDOFF*.md",
  "CURRENT_PROJECT_STATE_*.md",
  "RC_TEST_REPORT_*.md",
  "VIDEO_MATERIAL_ROTATION_GATE.md",
  "CLEANUP_BOUNDARIES_*.md"
)
foreach ($pattern in $internalDocPatterns) {
  Get-ChildItem -LiteralPath $portableDocs -Filter $pattern -File -ErrorAction SilentlyContinue |
    Remove-Item -Force
}

Get-ChildItem -LiteralPath (Join-Path $PortableRoot "workers") -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath (Join-Path $PortableRoot "workers") -File -Recurse -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
  Remove-Item -Force

$Manifest = [ordered]@{
  version = $Version
  created_at = (Get-Date).ToUniversalTime().ToString("o")
  files = Get-ChildItem -Recurse -File $PortableRoot | ForEach-Object {
    $_.FullName.Substring($PortableRoot.Length + 1).Replace("\", "/")
  }
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $PortableRoot "portable-manifest.json")

if (Test-Path $ZipPath) {
  Remove-Item -Force $ZipPath
}
Compress-Archive -Path (Join-Path $PortableRoot "*") -DestinationPath $ZipPath

Write-Host "Portable package created:" -ForegroundColor Green
Write-Host $ZipPath
