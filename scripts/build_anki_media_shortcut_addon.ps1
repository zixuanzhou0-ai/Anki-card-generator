param(
  [string]$OutputDirectory = "dist/anki-addon"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$SourceDirectory = Join-Path $RepositoryRoot "anki-addon/anki_card_generator_media_shortcut_bridge"
$ResolvedOutput = Join-Path $RepositoryRoot $OutputDirectory
$PackageName = "anki_card_generator_media_shortcut_bridge-1.0.0-m0.ankiaddon"
$FinalPath = Join-Path $ResolvedOutput $PackageName

$RequiredFiles = @(
  "__init__.py",
  "bridge.py",
  "manifest.json",
  "runtime-contract.v1.json"
)
foreach ($Name in $RequiredFiles) {
  $Path = Join-Path $SourceDirectory $Name
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Missing required add-on file: $Name"
  }
}

New-Item -ItemType Directory -Path $ResolvedOutput -Force | Out-Null
if (Test-Path -LiteralPath $FinalPath) {
  throw "Refusing to overwrite existing add-on package: $FinalPath"
}

$TemporaryZip = Join-Path $ResolvedOutput ("." + [guid]::NewGuid().ToString("N") + ".zip")
try {
  Compress-Archive -LiteralPath ($RequiredFiles | ForEach-Object {
    Join-Path $SourceDirectory $_
  }) -DestinationPath $TemporaryZip -CompressionLevel Optimal
  Move-Item -LiteralPath $TemporaryZip -Destination $FinalPath
} finally {
  if (Test-Path -LiteralPath $TemporaryZip) {
    Remove-Item -LiteralPath $TemporaryZip -Force
  }
}

$Digest = (Get-FileHash -LiteralPath $FinalPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "Package: $FinalPath"
Write-Output "SHA256: $Digest"
