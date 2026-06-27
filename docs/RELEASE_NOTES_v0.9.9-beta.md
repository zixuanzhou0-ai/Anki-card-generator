# Anki Card Generator v0.9.9-beta Release Notes

`v0.9.9-beta` 是 Windows 桌面端发布前的质量收口版，重点修复“模型生成了内容但不可导出/卡片质量不稳定”的真实问题，并把默认配置对齐 Vertex Gemini 3.5 Flash 与 Vertex Gemini TTS。

## 适用平台

- Windows 10/11 x64。
- 当前没有 macOS/Linux 桌面端安装包。
- Release 资产应包含 NSIS installer、MSI installer、portable zip 和 SHA256SUMS。

## 本版重点

- **严格可导出质量闸**：只有通过质量检查、默认启用、且不含本地草稿/待精修/预览占位/模型保底内容的卡片才计入可导出卡。
- **需复查卡保留但不导出**：模型只生成需复查卡时，任务会正常返回审核区，让用户看到原因；这些卡默认不会进入 APKG。
- **统一学习卡策略**：普通视频制卡继续只生成一种“学习卡”，避免同一学习点拆出多张内容相似的听力/表达/填空卡。
- **Vertex Gemini 3.5 Flash 默认**：文本模型默认使用 Vertex `gemini-3.5-flash`，适合快速批量筛选和生成；Vertex 模式使用本机 `gcloud` OAuth，不需要在应用内保存 Vertex API Key。
- **Vertex Gemini TTS 默认开启**：新项目默认使用 Vertex Gemini TTS 配置，导出前仍要求 TTS 测试通过，避免晚期导出失败。
- **设置页授权文案修正**：模型设置页在 Vertex 模式下显示“Vertex 授权 / 使用本机 gcloud OAuth”，自动化 UI smoke 已覆盖该状态。
- **无终端弹窗保持**：安装版普通启动继续隐藏 Windows console；worker 调用外部工具时也保持隐藏窗口。

## 用户如何使用

1. 下载 Windows installer、MSI 或 portable zip。
2. 安装后打开 `Anki Card Generator`，正常只显示桌面 UI，不应弹出黑色终端窗口。
3. 在 `设置 -> 本地环境` 检查 Python、FFmpeg、Anki、AnkiConnect。
4. 在 `设置 -> 模型 API` 使用 Vertex 时确认本机 `gcloud` 已登录并有 Vertex AI 权限；其它 OpenAI-compatible 服务商按需填写 API Key。
5. 在 `设置 -> 语音 TTS` 测试 TTS。
6. 回到主界面选择本地视频 + 字幕或视频链接，抽取学习点、生成卡片、审核并导出 APKG。

## 验证摘要

本地候选包生成前已完成：

- `npm.cmd run check:versions`：通过，版本为 `v0.9.9-beta`。
- `npm.cmd run lint`：通过。
- `npm.cmd run test:unit`：62 files / 467 tests passed。
- `npm.cmd run test:ui`：3 Playwright smoke tests passed。
- `npm.cmd run test:worker`：441 Python worker tests passed。
- `python -m pytest tests/test_worker_quality.py -q`：351 tests passed。
- `npm.cmd run build`：通过。
- `cargo check --manifest-path src-tauri/Cargo.toml`：通过。
- `npm.cmd run smoke:release`：通过，生成 1 张可导出卡并完成 APKG verify。

## 安全和隐私

- API Key 不应提交到 GitHub，也不应写入 release notes、截图、Word、PPT 或 Markdown 交付文档。
- Vertex 模式使用本机 `gcloud` OAuth；应用不会要求用户粘贴 Vertex API Key。
- 生成媒体、APKG、`release/smoke/`、`test_runs/`、缓存、日志和本地项目素材不进入 Git。

## 已知限制

- 卡片质量依赖模型、字幕质量、TTS 服务和本机环境。
- YouTube/视频链接导入可能受网络、区域、yt-dlp、登录限制或版权策略影响。
- 需复查卡不会自动导出；用户需要重试、更换模型或人工修正后再导出。