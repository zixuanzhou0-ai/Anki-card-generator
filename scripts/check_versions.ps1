param(
  [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"

function Read-JsonVersion($Path) {
  $content = Get-Content -LiteralPath $Path -Raw
  $match = [regex]::Match($content, '"version"\s*:\s*"([^"]+)"')
  if (-not $match.Success) {
    throw "Could not find JSON version in $Path"
  }
  $match.Groups[1].Value
}

function Assert-Contains($Path, $Pattern, $Description) {
  $content = Get-Content -LiteralPath $Path -Raw
  if ($content -notmatch $Pattern) {
    throw "$Description missing from $Path"
  }
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $root
try {
  $packageVersion = Read-JsonVersion "package.json"
  $packageLockVersion = Read-JsonVersion "package-lock.json"
  $tauriVersion = Read-JsonVersion "src-tauri/tauri.conf.json"

  $cargoText = Get-Content -LiteralPath "src-tauri/Cargo.toml" -Raw
  $cargoVersionMatch = [regex]::Match($cargoText, '(?m)^version\s*=\s*"([^"]+)"')
  if (-not $cargoVersionMatch.Success) {
    throw "Could not find Cargo package version"
  }

  $version = if ($ExpectedVersion) { $ExpectedVersion } else { [string]$packageVersion }
  $betaVersion = "v$version-beta"

  $checks = @(
    @{ Name = "package.json"; Value = [string]$packageVersion },
    @{ Name = "package-lock.json"; Value = [string]$packageLockVersion },
    @{ Name = "src-tauri/tauri.conf.json"; Value = [string]$tauriVersion },
    @{ Name = "src-tauri/Cargo.toml"; Value = [string]$cargoVersionMatch.Groups[1].Value }
  )

  foreach ($check in $checks) {
    if ($check.Value -ne $version) {
      throw "$($check.Name) version is $($check.Value), expected $version"
    }
  }

  Assert-Contains "README.md" ([regex]::Escape($betaVersion)) "README version"
  Assert-Contains "PRIVACY.md" ([regex]::Escape($betaVersion)) "Privacy version"
  Assert-Contains "SECURITY.md" ([regex]::Escape($betaVersion)) "Security version"
  Assert-Contains "docs/BETA_LIMITATIONS.md" ([regex]::Escape($betaVersion)) "Beta limitations version"
  Assert-Contains "docs/RELEASE_CHECKLIST.md" ([regex]::Escape($betaVersion)) "Release checklist beta version"
  Assert-Contains "docs/RELEASE_CHECKLIST.md" ([regex]::Escape($version)) "Release checklist package version"
  Assert-Contains "src-tauri/tauri.conf.json" '"\.\./workers/acg"\s*:\s*"workers/acg"' "Tauri bundled worker package resource"

  Write-Host "Version check passed: $betaVersion"
}
finally {
  Pop-Location
}
