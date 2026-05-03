# Smoke Test Report: v0.9.0-beta

Date: 2026-05-03

## Build

Commands passed:

```powershell
python -m py_compile workers\anki_worker.py tests\test_worker_quality.py
python -m unittest discover -s tests -p "test_worker_quality.py"
npm run build
npm run tauri:build
```

Results:

- Python quality tests: 46 passed.
- Frontend build: passed.
- Tauri Windows build: passed.

## Release Artifacts

Release file hashes are generated after the final source commit because the portable zip includes these docs. Put the final SHA256 values in the GitHub Release description.

## Portable Smoke

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "release\AnkiCardGenerator-v0.9.0-beta-windows-portable\scripts\smoke_release.ps1"
```

Result:

- Passed.
- Generated 3 subtitle segments.
- Exported 2 Anki cards.
- Created `.apkg`.

## Installer Smoke

Command:

```powershell
Start-Process "release\Anki Card Generator_0.9.0_x64-setup.exe" -ArgumentList "/S" -Wait
```

Result:

- Installer exit code: 0.
- Installed app found at `%LOCALAPPDATA%\Anki Card Generator\anki-card-generator.exe`.
- Installed worker found at `%LOCALAPPDATA%\Anki Card Generator\workers\anki_worker.py`.
- Installed worker smoke test passed and exported `.apkg`.
- Installed GUI process started and stayed alive for 5 seconds.

## Remaining Manual Verification

These require a clean Windows machine or Windows Sandbox:

- Run `scripts/setup_runtime.ps1` from a fresh unzip.
- Fill a real MIMO API Key.
- Generate from one real YouTube vlog.
- Generate from one real YouTube explainer.
- Import the exported `.apkg` into Anki and check video, original audio, sentence TTS, and phrase TTS.
