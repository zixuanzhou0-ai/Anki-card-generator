# Local Helper API And Security Plan

The local helper gives the static browser app controlled access to local system capabilities. It is not a public backend. It is a user-owned local service.

## Host And Port

Default listener:

```text
http://127.0.0.1:17321
```

The helper must only bind to loopback:

- `127.0.0.1`
- optionally `::1`

It must not listen on `0.0.0.0` or LAN addresses.

## Core Endpoints

```text
GET  /health
GET  /capabilities
POST /auth/pair
POST /auth/refresh
POST /files/pick
POST /folders/pick
POST /source/analyze
POST /learning-points/extract
POST /cards/generate
POST /export/apkg
POST /anki/verify
GET  /jobs/:id
GET  /jobs/:id/events
POST /jobs/:id/cancel
GET  /logs/recent
```

## Health Response

`GET /health` returns:

```json
{
  "ok": true,
  "name": "Anki Card Generator Helper",
  "version": "0.1.0",
  "platform": "windows",
  "apiVersion": "2026-06-23",
  "capabilities": [
    "file-picker",
    "folder-picker",
    "ffmpeg",
    "python-worker",
    "apkg-export",
    "anki-verify"
  ]
}
```

## Pairing

The browser app must not be able to control the helper just because it can reach localhost.

Required pairing flow:

1. Browser calls `GET /health`.
2. Helper reports `paired: false` or `paired: true`.
3. If unpaired, browser calls `POST /auth/pair`.
4. Helper displays a local confirmation prompt or tray notification.
5. User approves.
6. Helper returns a short-lived session token.
7. Browser stores token locally.

All privileged requests must include:

```text
Authorization: Bearer <local-session-token>
```

The token must be scoped to the browser origin and expire.

## Origin Allowlist

The helper must check the `Origin` header.

Allowed origins for development:

```text
http://localhost:5173
http://127.0.0.1:5173
```

Allowed origins for production must be explicit, for example:

```text
https://app.ankicardgenerator.com
```

Do not allow wildcard origins in production.

## File Access

The helper must not accept arbitrary filesystem paths from the browser and operate on them silently.

Preferred flow:

1. Browser requests `POST /files/pick` or `POST /folders/pick`.
2. Helper opens a native picker.
3. User chooses files/folders.
4. Helper returns opaque file refs, not unrestricted path access.

Example:

```json
{
  "fileRef": "local-file:8d848f33",
  "name": "lesson.srt",
  "kind": "subtitle",
  "size": 38291
}
```

The helper internally maps file refs to paths for the active session.

## Job Model

Long-running tasks must return a job ID:

```json
{
  "jobId": "job_20260623_001",
  "status": "queued"
}
```

The browser tracks progress with:

```text
GET /jobs/:id
GET /jobs/:id/events
```

Status values:

```text
queued
running
needs_user_action
succeeded
failed
cancelled
```

Events should be Server-Sent Events first, because they work well from static web apps.

## No Arbitrary Command Execution

The helper must never expose:

```text
POST /run
POST /exec
POST /shell
```

All operations must be typed and validated. FFmpeg, Python worker, and Anki operations must be invoked through fixed internal routines.

## Logging And Redaction

Helper logs are local only.

Logs must redact:

- API keys.
- Bearer tokens.
- Local session tokens.
- Full model authorization headers.
- User private paths in exported public diagnostics.

The helper may keep private local logs, but "copy diagnostics" must produce a sanitized bundle.

## Browser Runtime Contract

The web app should call a runtime abstraction instead of directly coupling UI to helper endpoints:

```ts
interface Runtime {
  kind: 'browser-only' | 'local-helper'
  getCapabilities(): Promise<Capabilities>
  pickVideo(): Promise<FileRef>
  pickSubtitle(): Promise<FileRef>
  pickFolder(): Promise<FolderRef>
  extractLearningPoints(input: ExtractInput): Promise<JobRef>
  generateCards(input: GenerateInput): Promise<JobRef>
  exportApkg(input: ExportInput): Promise<JobRef>
  verifyAnki(input: VerifyInput): Promise<VerifyResult>
}
```

This keeps the UI consistent while preserving a clean boundary between browser-only and helper mode.

