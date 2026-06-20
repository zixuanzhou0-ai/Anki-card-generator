# Anki Card Generator v0.9.3-beta

这是视频制卡主线完成 production-grade hardening 后的 Windows beta 版本。它面向普通用户的公开流程只保留两条路径：`本地视频 + 字幕` 和 `视频链接`。

## 下载哪个文件

| 文件 | 适合谁 |
| --- | --- |
| `AnkiCardGenerator-v0.9.3-beta-windows-portable.zip` | 推荐。解压后运行，便于测试和迁移。 |
| `Anki Card Generator_0.9.3_x64-setup.exe` | Windows NSIS 安装器。 |
| `Anki Card Generator_0.9.3_x64_en-US.msi` | Windows MSI 安装器。 |
| `SHA256SUMS-v0.9.3-beta.txt` | 校验下载文件。 |

## 主要更新

- 普通开发启动默认隐藏 Tauri/npm 调试终端；只显示桌面 UI，日志继续写入 `.tauri-dev-current.*` / `.vite-dev-current.*`。
- 新增 `npm.cmd run desktop:dev:debug`，需要排查时可显式显示调试终端。
- 视频制卡 release matrix 已完成 8/8 真实验收：YouTube、本地视频 + SRT、完整复读、快速复读、cold/hot cache、100+ 张一次点击压力包。
- 100+ 张压力包证明用户只需一次点击；内部可分批执行，但不改变用户操作模型。
- Anki 端真实验证覆盖 202 张目标卡、112 张预览检查，并实际点击视频、原声、整句 TTS、表达 TTS。
- `public_video` source provenance 已纳入 release evidence，公开视频下载后的本地 mp4/SRT 也会参与来源证明。
- README、用户指南、故障排查、架构和发布清单已更新到当前视频制卡主线。
- `.gitignore` 补强，默认排除 `.env*`、secret/token/credential 文件、生成媒体、APKG、test runs、日志、内部 handoff/goal 文档。

## 当前能力

- 本地视频 + SRT/VTT 制卡。
- 视频链接下载视频和字幕后制卡。
- AI 精筛学习点，用户勾选后生成完整卡片。
- 完整复读与快速复读两种 V11 卡片模式。
- 每张卡可包含视频片段、原声、整句 TTS、表达 TTS、语境义和学习提示。
- 导出 `.apkg` 并通过 AnkiConnect 核验 note/card/media。
- 设置页支持模型 API、TTS、本地环境检测和一键修复。

## 已验证

```powershell
npm.cmd run check
cargo check --manifest-path src-tauri/Cargo.toml
npm.cmd run tauri:build
```

Release-hardening matrix:

- 8/8 cases passed。
- 202 target cards。
- 112 Anki preview inspections。
- `release_ready=true`。
- `failed_checks=[]`。

## 已知限制

- 当前仍是 beta，不承诺第三方模型、TTS、YouTube、yt-dlp 或网络环境永远稳定。
- YouTube 可能遇到 429、字幕缺失、区域限制或 challenge 变化。
- 未内置真实 ASR/forced alignment；没有字幕的视频建议先转写成 SRT。
- 使用第三方模型或 TTS 会发送所选文本给对应服务商，并可能产生费用。
- 生成卡包可能包含第三方视频片段、字幕和合成音频，默认仅供个人学习。

## 安全提醒

Release 不包含任何真实 API key。不要把 API key 放进 issue、截图、日志、release notes 或公开仓库。
