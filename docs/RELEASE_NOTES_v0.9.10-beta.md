# Anki Card Generator v0.9.10-beta Release Notes

发布日期：2026-06-27

## 这版解决什么

`v0.9.10-beta` 是一次面向 Windows 桌面端上市前的卡片质量收口版本。重点不是增加花哨卡型，而是把“抽取学习点 -> 推荐 -> 用户勾选 -> 生成卡片 -> 导出 APKG”这条主链路做得更稳。

## 主要改进

- **Vertex Gemini 3.5 Flash 可用性修复**：继续支持 Vertex `gemini-3.5-flash` 作为快速/低成本模型，但学习点推荐前会做迁移价值检查。
- **弱学习点默认降级**：纯名词块、主题标签、低迁移泛表达、无法在原句定位的答案、疑似坏字幕/ASR 语法片段，不再默认推荐。
- **典型坏例修复**：`age groups` 这类离开原句没有训练动作的名词块会进入候选；`have break` 这类疑似漏词字幕不会默认生成；`sort of` 这类真实语气/话语标记可保留为有效学习点。
- **用户勾选不再静默丢卡**：如果 AI 卡片生成漏掉部分已勾选学习点，系统会对缺失项单独重试一次。
- **基础卡补齐**：模型仍然缺字段时，应用会用原学习点、字幕、时间点和学习动作补成一张基础学习卡，避免出现用户选了学习点但最终 APKG 为 0 张的情况。
- **硬质量闸继续保留**：视频、原声、整句 TTS、表达 TTS、媒体账本和 hash 校验失败仍会阻止导出。
- **学习点总览文案更清楚**：已勾选数量和可批量制卡数量分开显示，避免用户误解“候选数等于卡片数”。

## 实测证据

使用真实 YouTube 流程和 Vertex `gemini-3.5-flash` 做了新用户视角测试：

- 视频：`https://www.youtube.com/watch?v=RP1AL2DU6vQ`
- 素材：约 109 秒英文日常对话视频，下载字幕后进入 worker 流程。
- 学习点抽取：推荐 4 个，候选 6 个，无 hard block。
- 人工抽查：`get out of bed`、`wake up`、`relax for a bit` 可生成；弱名词块和坏字幕不再默认推荐。
- 卡片生成：已勾选 3 个学习点，最终生成 3 张可导出学习卡。
- 结果：`generation_reconciliation_status=ok`，没有再出现“导出没有生成 APKG / 0 张可用卡”的核心失败。

## 用户注意

- 这个版本仍然是 Windows 桌面端 beta。
- Vertex 模式使用本机 `gcloud` OAuth，不需要在应用里填写 Vertex API Key。
- Gemini 3.5 Flash 适合快速试流程和低成本批量；最终高质量卡片仍建议用更强模型复核。
- 生成的 `.apkg` 可能包含第三方视频片段、字幕和 TTS 音频，默认仅供个人学习使用。

## 验证建议

发布前建议至少运行：

```powershell
npm.cmd run check:versions
npm.cmd run lint
npm.cmd run test:unit
npm.cmd run test:worker
npm.cmd run test:ui
npm.cmd run build
cargo check --manifest-path src-tauri/Cargo.toml
npm.cmd run tauri:build
```

安装包发布前还应确认普通启动没有黑色终端弹窗，桌面端最小窗口下左侧流程和学习点面板仍可操作。
