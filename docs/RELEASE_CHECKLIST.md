# Release Checklist

目标：确认别人拿到 Windows 包后，在没有源码和开发服务的环境里也能完成制卡和导出。

## 构建前

- [ ] `git status` 只包含本次发布相关文件。
- [ ] 没有真实 API Key。
- [ ] `.gitignore` 已排除缓存、媒体、`.apkg`、测试输出。
- [ ] 版本号已更新：`package.json`、`package-lock.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`。
- [ ] `workers/` 已作为 Tauri resources 打包。

## 自动测试

```powershell
python -m py_compile workers\anki_worker.py tests\test_worker_quality.py
python -m unittest discover -s tests -p "test_worker_quality.py"
npm run build
npm run tauri:build
```

## 便携包检查

- [ ] 便携包包含 `Anki Card Generator.exe`。
- [ ] 便携包包含 `workers/`。
- [ ] 便携包包含 `scripts/setup_runtime.ps1`。
- [ ] 便携包包含 `README.md` 和 `docs/`。
- [ ] 从便携包运行 `scripts/smoke_release.ps1` 通过。

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

## GitHub Release 内容

- `AnkiCardGenerator-v0.9.0-beta-windows-portable.zip`
- `AnkiCardGenerator-v0.9.0-beta-source.zip`
- `AnkiCardGenerator-v0.9.0-beta-source.bundle`
- `Anki Card Generator_0.9.0_x64-setup.exe`
- `Anki Card Generator_0.9.0_x64_en-US.msi`
- Release notes: `docs/RELEASE_NOTES_v0.9.0-beta.md`
