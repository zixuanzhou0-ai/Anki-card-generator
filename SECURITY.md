# Security Policy

## Supported versions

`v0.9.0-beta` is an internal Windows beta. Security fixes should be made on `main` and included in the next beta release.

## Reporting a vulnerability

Do not publish real API keys, private videos, generated decks with private media, or exploit details in public issues. Report privately to the repository owner first, then publish a sanitized issue after the fix is available.

Please include:

- App version and commit SHA.
- Windows version.
- Whether the issue happens in dev mode, portable zip, installer, or both.
- Minimal reproduction steps using dummy API keys and non-private media.
- Relevant logs with API keys and personal paths redacted.

## Local execution boundary

This app runs a Python worker on the user's machine. The Tauri layer should only call a small whitelist of worker commands and release builds should load the worker from packaged app resources, not arbitrary current working directories.

## Secrets

Never commit real API keys. Do not paste keys into issues, screenshots, release notes, CI logs, or test fixtures. The UI should avoid saving raw keys to browser localStorage; the target design is system keychain / secure storage.

## Third-party services

When users enable model review or TTS, subtitles, document excerpts, card fields, and TTS text may be sent to the selected provider. Keep `PRIVACY.md` current whenever providers or request payloads change.
