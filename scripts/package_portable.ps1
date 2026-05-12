param(
  [string]$ReleaseExe,
  [string]$OutputDir = "release",
  [string]$Version = "0.9.2-beta"
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
Copy-Item (Join-Path $Root "scripts") (Join-Path $PortableRoot "scripts") -Recurse
Copy-Item (Join-Path $Root "docs") (Join-Path $PortableRoot "docs") -Recurse

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
