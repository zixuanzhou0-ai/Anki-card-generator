# Anki Card Generator v0.9.7-beta Release Notes

发布日期：2026-06-27

## 本版定位

`v0.9.7-beta` 是 Windows 桌面端的质量修复版，重点解决两类真实使用问题：

- 普通项目导出 APKG 时，不再误触发 release 验收证据目录保护。
- Vertex AI / Gemini 3.5 Flash 生成不完整时，系统保底卡会留在审核区提示“需修复”，但不会再被计入可导出正式卡。

## 关键修复

### APKG 导出路径

旧版在某些情况下会沿用 Windows 文件夹选择器记住的 `test_runs` release 验收目录。普通项目如果选择到了形似 release evidence 的 APKG 目录，会被误判成“正式验收 APKG”，从而拒绝覆盖旧证据并显示没有生成 APKG。

本版修复后：

- 只有真正带 release case 身份的项目才会启用 release APKG 目录保护。
- 普通视频、URL、字幕项目不会再触发 release case canonical path guard。
- URL 项目和无本地素材项目会优先使用应用本地数据目录作为保存目录兜底，减少串到历史测试目录的概率。

### 卡片质量与 Gemini 3.5 Flash

Gemini 3.5 Flash 是 Vertex AI 中可用的快速模型，但更适合长字幕快速筛选和低成本批量，不建议作为最终高质量制卡的首选模型。旧版在模型未完整返回时会用学习点生成“保底卡”，并错误地把这些卡计入可导出正式卡。

本版修复后：

- 保底卡仍会显示在审核区，方便用户知道哪些学习点没有被模型完整处理。
- 保底卡会标记为“需修复”，默认不可勾选导出。
- APKG 导出前会自动移除这类不可导出的卡；如果没有剩余正式卡，会提示重新生成或手动修复。
- Vertex 模型列表中将 `Gemini 3.5 Flash` 标注为“快速批量”，并把高质量模型放在更靠前位置。

## 建议使用方式

- 高质量制卡优先使用：MIMO V2.5 Pro、DeepSeek V4 Pro、Gemini 3.1 Pro Preview 或 Gemini 2.5 Pro。
- Gemini 3.5 Flash 建议用于：快速浏览、低成本批量初筛、长字幕候选学习点粗处理。
- 正式导出前请在审核区查看“需修复”标记；只有可导出卡片会进入 APKG。

## 验证结果

本版本地验证通过：

- `npm.cmd run test:worker`：441 tests passed
- `npm.cmd run test:unit`：466 tests passed
- `npm.cmd run test:ui`：3 Playwright smoke tests passed
- `npm.cmd run build`：通过
- `npm.cmd run check:versions`：通过，版本为 `v0.9.7-beta`
- `cargo check --manifest-path src-tauri/Cargo.toml`：通过
- `npm.cmd run smoke:release`：通过并生成 APKG

## 安全边界

- 不包含 API key。
- 不提交 APKG、视频、音频、缓存和本地测试原始证据。
- 用户配置、Credential Manager 和 AppData 不会被安装包主动清理。