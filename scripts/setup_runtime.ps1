param(
  [switch]$InstallWithWinget
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Requirements = Join-Path $Root "workers\requirements.txt"

function Test-Command($Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "== Anki Card Generator runtime setup ==" -ForegroundColor Cyan

if (-not (Test-Command "python")) {
  Write-Host "Python not found." -ForegroundColor Yellow
  if ($InstallWithWinget -and (Test-Command "winget")) {
    winget install --id Python.Python.3.12 -e
  } else {
    Write-Host "Install Python 3.11+ first: https://www.python.org/downloads/windows/" -ForegroundColor Yellow
  }
} else {
  python --version
}

if (Test-Command "python") {
  python -m pip install --upgrade pip
  python -m pip install -r $Requirements
}

if (-not (Test-Command "deno") -and -not (Test-Command "node")) {
  Write-Host "No JavaScript runtime found. YouTube downloads may need Deno or Node for yt-dlp EJS challenge solving." -ForegroundColor Yellow
  if ($InstallWithWinget -and (Test-Command "winget")) {
    winget install --id DenoLand.Deno -e
  } else {
    Write-Host "Install Deno 2.0+ or Node.js 20+ and add it to PATH." -ForegroundColor Yellow
    Write-Host "Deno: https://deno.com/ | Node.js: https://nodejs.org/" -ForegroundColor Yellow
  }
} elseif (Test-Command "deno") {
  deno --version | Select-Object -First 1
} else {
  node --version
}

if (-not (Test-Command "ffmpeg")) {
  Write-Host "FFmpeg not found." -ForegroundColor Yellow
  if ($InstallWithWinget -and (Test-Command "winget")) {
    winget install --id Gyan.FFmpeg -e
  } else {
    Write-Host "Install FFmpeg and add it to PATH: https://www.gyan.dev/ffmpeg/builds/" -ForegroundColor Yellow
  }
} else {
  ffmpeg -version | Select-Object -First 1
}

if (-not (Test-Command "anki")) {
  Write-Host "Anki command not found. This is OK if Anki is installed in its normal Program Files path." -ForegroundColor Yellow
  Write-Host "Download Anki: https://apps.ankiweb.net/" -ForegroundColor Yellow
}

Write-Host "Runtime setup finished. Open the app and run Settings > Check environment." -ForegroundColor Green
