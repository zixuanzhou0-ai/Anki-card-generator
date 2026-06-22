param(
  [string]$Version = "0.9.4-beta"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseDir = Join-Path $repoRoot "release"
$tauriTarget = Join-Path $repoRoot "src-tauri\target\release\bundle"
$previousRustFlags = $env:RUSTFLAGS
$cacheBackupRoot = Join-Path $releaseDir (".build-cache-backup-" + [guid]::NewGuid().ToString("N"))
$movedCacheDirs = @()

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList
  )

  & $FilePath @ArgumentList
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath $($ArgumentList -join ' ') failed with exit code $LASTEXITCODE."
  }
}

function Convert-ToRustFlagValue {
  param([string]$Value)

  if ($Value -match "\s") {
    return '"' + ($Value -replace '"', '\"') + '"'
  }

  return $Value
}

function Add-RemapFlag {
  param(
    [string[]]$Flags,
    [string]$Source,
    [string]$Target
  )

  if ([string]::IsNullOrWhiteSpace($Source)) {
    return $Flags
  }

  $resolved = $Source
  if (Test-Path -LiteralPath $Source) {
    $resolved = (Resolve-Path -LiteralPath $Source).Path
  }

  return $Flags + "--remap-path-prefix=$resolved=$Target"
}

function Get-RelativePath {
  param(
    [string]$BasePath,
    [string]$Path
  )

  $baseUri = [System.Uri]((Join-Path (Resolve-Path -LiteralPath $BasePath).Path "."))
  $pathUri = [System.Uri](Resolve-Path -LiteralPath $Path).Path
  return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($pathUri).ToString()).Replace("/", "\")
}

function Hide-PythonBytecodeCaches {
  $workerRoot = Join-Path $repoRoot "workers"
  if (-not (Test-Path -LiteralPath $workerRoot)) {
    return
  }

  $cacheDirs = Get-ChildItem -LiteralPath $workerRoot -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue
  foreach ($cacheDir in $cacheDirs) {
    $relativePath = Get-RelativePath -BasePath $repoRoot -Path $cacheDir.FullName
    $backupPath = Join-Path $cacheBackupRoot $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
    Move-Item -LiteralPath $cacheDir.FullName -Destination $backupPath
    $script:movedCacheDirs += [pscustomobject]@{
      Original = $cacheDir.FullName
      Backup = $backupPath
    }
  }
}

function Restore-PythonBytecodeCaches {
  $entries = @($script:movedCacheDirs)
  [array]::Reverse($entries)

  foreach ($entry in $entries) {
    if (-not (Test-Path -LiteralPath $entry.Backup)) {
      continue
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $entry.Original) | Out-Null
    if (Test-Path -LiteralPath $entry.Original) {
      Get-ChildItem -LiteralPath $entry.Backup -Force | Move-Item -Destination $entry.Original -Force
      Remove-Item -LiteralPath $entry.Backup -Force
    } else {
      Move-Item -LiteralPath $entry.Backup -Destination $entry.Original
    }
  }
}

function Invoke-ManualWixLink {
  param([string]$MsiOutput)

  $wixDir = Join-Path $repoRoot "src-tauri\target\release\wix\x64"
  $wixObj = Join-Path $wixDir "main.wixobj"
  $locale = Join-Path $wixDir "locale.wxl"
  $light = Join-Path $env:LOCALAPPDATA "tauri\WixTools314\light.exe"

  if (-not (Test-Path -LiteralPath $wixObj)) {
    throw "WiX object was not produced: $wixObj"
  }

  if (-not (Test-Path -LiteralPath $locale)) {
    throw "WiX locale file was not produced: $locale"
  }

  if (-not (Test-Path -LiteralPath $light)) {
    throw "WiX light.exe was not found: $light"
  }

  $env:WIX_TEMP = Join-Path $releaseDir "wix-temp"
  New-Item -ItemType Directory -Force -Path $env:WIX_TEMP | Out-Null
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $MsiOutput) | Out-Null

  Invoke-Checked -FilePath $light -ArgumentList @(
    "-nologo",
    "-sval",
    "-spdb",
    "-ext",
    "WixUIExtension",
    "-cultures:en-US",
    "-loc",
    $locale,
    "-out",
    $MsiOutput,
    $wixObj
  )
}

try {
  $flags = @("-Cstrip=symbols")
  $flags = Add-RemapFlag -Flags $flags -Source $repoRoot -Target "repo"

  if ($env:USERPROFILE) {
    $flags = Add-RemapFlag -Flags $flags -Source $env:USERPROFILE -Target "user-home"
  }

  $cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } elseif ($env:USERPROFILE) { Join-Path $env:USERPROFILE ".cargo" } else { "" }
  $rustupHome = if ($env:RUSTUP_HOME) { $env:RUSTUP_HOME } elseif ($env:USERPROFILE) { Join-Path $env:USERPROFILE ".rustup" } else { "" }

  $flags = Add-RemapFlag -Flags $flags -Source $cargoHome -Target "cargo-home"
  $flags = Add-RemapFlag -Flags $flags -Source $rustupHome -Target "rustup-home"

  $env:RUSTFLAGS = ((@($previousRustFlags) + $flags | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { Convert-ToRustFlagValue $_ }) -join " ")

  Push-Location $repoRoot
  try {
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    Hide-PythonBytecodeCaches

    $buildStartedAt = Get-Date
    Invoke-Checked -FilePath "npm.cmd" -ArgumentList @("exec", "tauri", "--", "build", "--bundles", "nsis")

    $msiBuildStartedAt = Get-Date
    & npm.cmd exec tauri -- build --bundles msi
    $msiExitCode = $LASTEXITCODE
    if ($msiExitCode -ne 0) {
      Write-Warning "Tauri MSI bundling exited with $msiExitCode. Re-linking MSI with WiX -sval for environments where Windows Installer ICE validation is unavailable."

      $tauriConfig = Get-Content -LiteralPath (Join-Path $repoRoot "src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json
      $msiName = "$($tauriConfig.productName)_$($tauriConfig.version)_x64_en-US.msi"
      $manualMsiOutput = Join-Path (Join-Path $tauriTarget "msi") $msiName
      Invoke-ManualWixLink -MsiOutput $manualMsiOutput
    }

    $setup = Get-ChildItem -LiteralPath (Join-Path $tauriTarget "nsis") -Filter "*_x64-setup.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $msi = Get-ChildItem -LiteralPath (Join-Path $tauriTarget "msi") -Filter "*_x64_en-US.msi" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

    if (-not $setup) {
      throw "NSIS setup executable was not produced."
    }

    if (-not $msi) {
      throw "MSI installer was not produced."
    }

    if ($setup.LastWriteTime -lt $buildStartedAt.AddSeconds(-5)) {
      throw "NSIS setup executable was not rebuilt in this run: $($setup.FullName)"
    }

    if ($msi.LastWriteTime -lt $msiBuildStartedAt.AddSeconds(-5)) {
      throw "MSI installer was not rebuilt in this run: $($msi.FullName)"
    }

    Copy-Item -LiteralPath $setup.FullName -Destination $releaseDir -Force
    Copy-Item -LiteralPath $msi.FullName -Destination $releaseDir -Force

    & (Join-Path $repoRoot "scripts\package_portable.ps1") -Version $Version

    $assetNames = @(
      "AnkiCardGenerator-v$Version-windows-portable.zip",
      $setup.Name,
      $msi.Name
    )

    $assetPaths = $assetNames | ForEach-Object { Join-Path $releaseDir $_ }
    $shaPath = Join-Path $releaseDir "SHA256SUMS-v$Version.txt"

    Get-FileHash -Algorithm SHA256 -LiteralPath $assetPaths |
      ForEach-Object { "$($_.Hash)  $(Split-Path -Leaf $_.Path)" } |
      Set-Content -LiteralPath $shaPath -Encoding ascii

    Get-Content -LiteralPath $shaPath
  } finally {
    Restore-PythonBytecodeCaches
    Pop-Location
  }
} finally {
  $env:RUSTFLAGS = $previousRustFlags
}
