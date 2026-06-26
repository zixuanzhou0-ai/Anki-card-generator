# Release Checklist

当前发布目标：`v0.9.6-beta`（package version `0.9.6`）。

## 版本与仓库边界

- [ ] `package.json`、`package-lock.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml` 版本一致。
- [ ] `README.md`、`PRIVACY.md`、`SECURITY.md`、`docs/BETA_LIMITATIONS.md` 都写明当前 Windows 桌面端发布状态。
- [ ] `.gitignore` 明确排除 `.env*`、key/token/credential 本地文件、生成媒体、APKG、test runs、缓存、日志和内部 handoff/goal 文档。
- [ ] 使用白名单 staging；不要运行 `git add .`。
- [ ] `git diff --cached` 人工检查无 API key、私有路径、APKG、视频、音频、`test_runs/` 或内部工作文档。

## 产品文档

- [ ] README 说明当前公开主流程只包含 `本地视频 + 字幕` 和 `视频链接`。
- [ ] README 说明统一学习卡、推荐质量规则、完整复读、快速复读、TTS、APKG 导出、Anki 导入核验、缓存/耗时诊断。
- [ ] `docs/USER_GUIDE.md` 可按普通用户流程完成从设置到导出，并说明关于 / 版权页与 GitHub 入口。
- [ ] `docs/TROUBLESHOOTING.md` 覆盖 Python、FFmpeg、yt-dlp、Anki、AnkiConnect、TTS、API key 常见问题。
- [ ] `docs/screenshots/` 只保留可公开截图；截图不含 API key、本机用户名、私有路径或私人素材。
- [ ] GitHub Release body 使用 `docs/RELEASE_NOTES_v0.9.6-beta.md`。

## 自动验证

```powershell
npm.cmd run check
cargo check --manifest-path src-tauri/Cargo.toml
```

发布包前再跑：

```powershell
npm.cmd run tauri:build
```

如果环境允许，也跑：

```powershell
npm.cmd run check:full
```

## 桌面端验证

- [ ] `npm.cmd run desktop:dev` 只显示桌面 UI，不额外弹出 Tauri/npm 终端窗口。
- [ ] `.tauri-dev-current.out/.err` 和 `.vite-dev-current.out/.err` 仍写入日志。
- [ ] `npm.cmd run desktop:dev:debug` 会显示调试终端，方便开发排查。
- [ ] release 安装包或 portable exe 启动时不显示终端窗口；worker 调用 `ebook-convert`、`ffprobe` 等外部工具时也不弹出黑色 console。
- [ ] `设置 -> 关于 / 版权` 显示版本、版权、Anki 独立声明和 GitHub 仓库入口。

## 视频制卡 Smoke

至少跑一个小样本，确认本次终端隐藏和版本发布没有影响核心路径：

- [ ] 本地视频 + 字幕或视频链接可抽取学习点。
- [ ] 用户可勾选学习点并生成统一学习卡；每个选中学习点默认只生成 1 张卡。
- [ ] 可导出 `.apkg`。
- [ ] Anki 导入核验通过，`failed_checks=[]`。
- [ ] 抽查卡片里的视频、原声、整句 TTS、表达 TTS 可播放。

完整 release-hardening 证据已在本地 2026-06-20 矩阵完成：8/8 cases passed、202 target cards、112 Anki preview inspections。该证据不直接提交到 GitHub。

## GitHub Release

- [ ] 从 release 分支开 PR 到 `main`。
- [ ] PR CI 通过后合并。
- [ ] 在 `main` 合并 commit 上创建 tag `v0.9.6-beta`。
- [ ] 创建 GitHub Release 并上传 Windows installer、MSI、portable zip、SHA256SUMS。
- [ ] Release note 明确这是 beta：第三方模型/TTS/视频下载可能受服务商、网络、费用和版权限制影响。
- [ ] Release note 明确 v0.9.6-beta 的核心变化：统一学习卡、推荐质量收紧、版权页/GitHub入口、Vertex Gemini 3.5 Flash、无终端弹窗保持。
