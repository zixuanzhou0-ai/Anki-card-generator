# Anki Card Generator v0.9.8-beta Release Notes

发布日期：2026-06-27

## 本版定位

`v0.9.8-beta` 是 Windows 桌面端的 Vertex 质量与导出稳定性修复版。重点解决三类真实使用问题：

- Vertex Gemini 3.5 Flash 生成不完整时，系统保底卡只保留在审核区，不再默认进入 APKG。
- 视频卡导出依赖 TTS 的规则前移到生成前检查，避免用户跑完整流程后才看到“未生成 APKG”。
- 学习点列表默认只展示可批量制卡项，把字幕拼接不稳、滚动字幕、低置信候选放入“需复查”，减少“不可制卡”给用户造成的误解。

## 关键修复

### 1. 保底卡不再污染成品 APKG

旧版在模型未覆盖某个已选学习点时，会生成一张本地保底卡。这类卡可以帮助用户知道“模型漏掉了什么”，但内容通常只是结构化草稿，不应该作为正式学习卡导出。

本版修复后：

- 保底卡仍显示在审核区，标记为 `需修复` / `needs_review`。
- 保底卡默认 `enabled=false`，不会进入 APKG。
- 成品 APKG 只包含通过质量门槛的推荐卡。
- 生成诊断仍会记录缺失学习点，方便用户重新生成或人工修复。

### 2. TTS 从“导出时报错”改为“生成前硬门槛”

视频卡需要整句 TTS 和表达 TTS。旧版在 TTS 关闭或未测试时，可能等到导出阶段才失败，用户会误以为 APKG 丢失。

本版修复后：

- 本地视频 / 视频链接流程默认视为 `TTS 必需`。
- TTS 关闭时，生成 APKG 前会直接打开语音设置并提示启用。
- TTS 未测试通过时，生成 APKG 前会阻止继续，避免晚失败。
- 已保存且上次测试通过的 TTS 配置仍可复用，不强迫每次重复测试。

### 3. 学习点筛选 UI 更清楚

旧版会把推荐、候选、重复、硬阻断、字幕质量可疑项混在一个默认视图里，容易让用户觉得“很多不可制卡卡片”。

本版修复后：

- 默认筛选改为 `可批量制卡`。
- 新增 `需复查` 视图，专门放字幕拼接、滚动字幕、低置信候选等需要人工判断的学习点。
- “不可制卡”相关文案改为更准确的 `质量拦截`，区分“被质量系统拦住”与“已经生成了坏卡”。

## Vertex 验证结果

本地使用安装版/源码 worker 验证：

- 文本模型：Vertex AI `gemini-3.5-flash`
- TTS 模型：Vertex AI `gemini-3.1-flash-tts-preview`
- TTS 测试：通过，返回有效音频字节。
- 小视频 + SRT E2E：抽取学习点、生成卡片、导出 APKG 成功。
- APKG 离线验证：`ok=true`，2 notes / 2 cards，mp4、webm、poster、原声、整句 TTS、表达 TTS 均引用完整。
- 质量验证：1 张模型漏掉的保底 `needs_review` 卡保留在审核区，但未进入 APKG。

## 建议使用方式

- 追求最终卡片质量时，优先选高质量模型；Gemini 3.5 Flash 更适合快速批量初筛。
- 正式导出前请确认 TTS 设置页显示测试通过。
- 如果看到 `需复查` 或 `质量拦截`，先抽查字幕和卡片内容，再决定是否重新生成或人工修复。


## 回归测试

本地发布前验证通过：

- `npm.cmd run check:versions`：通过，版本为 `v0.9.8-beta`
- `npm.cmd run lint`：通过
- `npm.cmd run test:unit`：62 files / 467 tests passed
- `npm.cmd run test:worker`：441 tests passed
- `npm.cmd run test:ui`：3 Playwright smoke tests passed
- `npm.cmd run build`：通过
- `cargo check --manifest-path src-tauri/Cargo.toml`：通过
- `npm.cmd run smoke:release`：通过并生成 APKG
## 安全边界

- 不包含 API key。
- Vertex 使用本机 gcloud / Vertex AI 授权，不需要在应用内保存 Vertex API Key。
- 不提交 APKG、视频、音频、缓存和本地测试原始证据。
- 安装包不会主动删除用户 AppData、Credential Manager、历史项目或 Anki 数据。