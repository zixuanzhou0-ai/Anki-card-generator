param(
  [Parameter(Mandatory = $true)]
  [string]$PortableZip,
  [string]$OutputDir = "",
  [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not (Test-Path $PortableZip)) {
  throw "Portable zip not found: $PortableZip"
}

if (-not $OutputDir) {
  $OutputDir = Join-Path $Root "release\portable-smoke"
}

$OutputDir = [string](New-Item -ItemType Directory -Force -Path $OutputDir).FullName
$ExtractDir = Join-Path $OutputDir "app"
if (Test-Path $ExtractDir) {
  Remove-Item -LiteralPath $ExtractDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null

Expand-Archive -Path $PortableZip -DestinationPath $ExtractDir -Force

$Setup = Get-ChildItem -Path $ExtractDir -Recurse -Filter setup_runtime.ps1 | Select-Object -First 1
if (-not $Setup) {
  throw "setup_runtime.ps1 was not found inside the portable zip."
}

if (-not $SkipSetup) {
  powershell -NoProfile -ExecutionPolicy Bypass -File $Setup.FullName
}

$Worker = Get-ChildItem -Path $ExtractDir -Recurse -Filter anki_worker.py | Select-Object -First 1
if (-not $Worker) {
  throw "workers/anki_worker.py was not found inside the portable zip."
}

$SmokeOut = Join-Path $OutputDir "smoke-output"
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\smoke_release.ps1") `
  -WorkerPath $Worker.FullName `
  -OutputDir $SmokeOut

$Report = [ordered]@{
  portable_zip = (Resolve-Path $PortableZip).Path
  extracted_to = $ExtractDir
  worker = $Worker.FullName
  setup_script = $Setup.FullName
  smoke_output = $SmokeOut
  generated_at = (Get-Date).ToString("o")
}

$ReportPath = Join-Path $OutputDir "portable_smoke_report.json"
$Report | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding UTF8
Write-Host "Portable smoke passed. Report: $ReportPath" -ForegroundColor Green
