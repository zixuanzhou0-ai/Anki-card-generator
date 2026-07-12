# Acceptance Checklist

This checklist defines when the browser app + local helper work can be considered complete enough for a public beta.

## Repository Clarity

- [ ] Existing Windows desktop code is clearly identified as the Windows Desktop App.
- [ ] Browser app code lives under `apps/web-static/`.
- [ ] Helper code lives under `apps/local-helper/`.
- [ ] Shared code lives under `packages/`.
- [ ] Each product folder has a README.
- [ ] Root README explains which folder and release asset belongs to which product.

## Browser App

- [ ] Browser app can run without helper.
- [ ] Browser-only mode is labeled clearly.
- [ ] Helper mode is labeled clearly.
- [ ] Settings page can store model/TTS configuration locally.
- [ ] UI never promises local system capabilities when helper is absent.
- [ ] Web build produces static assets.

## Local Helper

- [ ] Helper binds only to `127.0.0.1`.
- [ ] `/health` returns version, platform, and capabilities.
- [ ] Pairing/token flow protects privileged endpoints.
- [ ] Origin allowlist is enforced.
- [ ] File/folder operations require user intent.
- [ ] No arbitrary command endpoint exists.
- [ ] Logs redact secrets.

## End-To-End Flow

- [ ] Browser connects to helper.
- [ ] User selects one local video and one subtitle.
- [ ] Learning points are extracted.
- [ ] Cards are reviewed.
- [ ] APKG is generated.
- [ ] APKG downloads successfully.
- [ ] APKG imports into Anki manually.
- [ ] Optional Anki verify works when Anki is available.

## GitHub Release Clarity

- [ ] Release notes have a "Which file should I download?" section.
- [ ] Windows desktop installer is labeled as desktop app.
- [ ] Helper installers are labeled as browser helper.
- [ ] Browser static build is labeled as web app artifact, if published.
- [ ] SHA256SUMS exists.
- [ ] No APKG, videos, logs, raw test evidence, or API keys are committed.

## Regression

- [ ] Windows desktop app still passes its smoke tests.
- [ ] Browser app passes browser-only smoke.
- [ ] Helper mode passes at least Windows helper smoke.
- [ ] Shared contracts pass tests.
- [ ] Secret scan passes on staged diff and release assets.

