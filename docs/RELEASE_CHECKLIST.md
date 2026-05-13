# Release Checklist

目标：确认别人拿到 Windows 包后，在没有源码和开发服务的环境里也能完成制卡和导出。

## 构建前

- [ ] `git status` 只包含本次发布相关文件。
- [ ] 没有真实 API Key。
- [ ] `.gitignore` 已排除缓存、媒体、`.apkg`、测试输出和 `.venv/`。
- [ ] 版本号已更新：`package.json`、`package-lock.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`。
- [ ] `workers/` 已作为 Tauri resources 打包。
- [ ] README、`PRIVACY.md`、`SECURITY.md` 和 `docs/BETA_LIMITATIONS.md` 与本次发布一致。
- [ ] Release note 明确说明 YouTube、第三方模型、TTS 费用和版权限制。

## 自动测试

```powershell
python -m py_compile workers\anki_worker.py workers\verify_apkg.py tests\test_worker_quality.py
npm run check
npm run test:ui
cargo build --manifest-path src-tauri/Cargo.toml --locked
npm run tauri:build
npm run smoke:release
```

GitHub Actions 必须是绿色；如果 CI 因外部服务故障失败，release note 需要写明原因和人工复核结果。

## 便携包检查

- [ ] 便携包包含 `Anki Card Generator.exe`。
- [ ] 便携包包含 `workers/`。
- [ ] 便携包包含 `scripts/setup_runtime.ps1`。
- [ ] 便携包包含 `README.md`、`PRIVACY.md`、`SECURITY.md` 和 `docs/`。
- [ ] 从便携包运行 `scripts/setup_runtime.ps1` 会创建项目本地 `.venv`。
- [ ] `runtime_diagnostic.json` 已生成，且不包含 API Key。
- [ ] 从便携包运行 `scripts/smoke_release.ps1` 通过，并生成 `verify_apkg.json`。
- [ ] 可选：`scripts/smoke_portable.ps1 -PortableZip <zip>` 能从 zip 解压后跑完整 smoke。

## 干净机器验证

建议用 Windows Sandbox / 虚拟机 / 另一台电脑。

1. 只复制 release zip，不复制源码。
2. 解压。
3. 运行 `scripts/setup_runtime.ps1`。
4. 打开软件，点击“检查环境”。
5. 填 MIMO Key。
6. 用短视频或 YouTube URL 生成卡片。
7. 导出 `.apkg`。
8. 导入 Anki。
9. 检查视频、原声、TTS、词伙 TTS 是否正常。
10. 删除测试缓存和 `.apkg`，确认没有 API Key 或私人素材进入 release 目录。

## GitHub Release 内容

- `AnkiCardGenerator-v0.9.2-beta-windows-portable.zip`
- `AnkiCardGenerator-v0.9.2-beta-source.zip`
- `AnkiCardGenerator-v0.9.2-beta-source.bundle`
- `Anki Card Generator_0.9.2_x64-setup.exe`
- `Anki Card Generator_0.9.2_x64_en-US.msi`
- Release notes: `docs/RELEASE_NOTES_v0.9.2-beta.md`
