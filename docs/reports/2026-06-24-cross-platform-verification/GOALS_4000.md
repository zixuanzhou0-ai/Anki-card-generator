# Goals：Anki Card Generator 跨平台验收与下一阶段执行目标

目标是在不混乱当前 Windows 桌面端代码的前提下，完成 Anki Card Generator 的全链路验收、公开说明材料和浏览器端规划，为下一轮 Codex 循环提供可直接执行的任务边界。

## 交付物地址

- 测试协议：`E:\ANKI\docs\reports\2026-06-24-cross-platform-verification\TEST_PROTOCOL.md`
- 项目说明：`E:\ANKI\docs\reports\2026-06-24-cross-platform-verification\ANKI_CARD_GENERATOR_PROJECT_OVERVIEW.md`
- Word 报告：`E:\ANKI\docs\reports\2026-06-24-cross-platform-verification\Anki_Card_Generator_Cross_Platform_Verification.docx`
- PPT 演示：`E:\ANKI\docs\reports\2026-06-24-cross-platform-verification\Anki_Card_Generator_Cross_Platform_Verification.pptx`
- 浏览器端计划目录：`E:\ANKI\docs\web-helper\`

## 必须完成的事情

1. 完成 `v0.9.4-beta` GitHub Release 验收：确认用户能在 GitHub 上明确看到这是 Windows 桌面端，知道下载 NSIS、MSI 或 portable zip，并能看到主界面、设置页、生成结果和 Anki 成品卡截图。

2. 确认 Release 资产可信：从 GitHub 下载安装器和 SHA256SUMS，计算安装器 SHA256，必须匹配 GitHub asset digest 和 SHA256SUMS 文件。下载资产只能放在 `C:\tmp`，不能进入 Git 仓库。

3. 确认本机安装版可用：winget/ARP 必须显示 `Anki Card Generator 0.9.4`，启动路径必须是安装目录，不得把本地 `target/release` 当成用户下载版。若生产 WebView2 不开放 CDP 调试端口，不继续卡住，记录为自动化可观测性限制。

4. 跑完整自动化验收：`check:versions`、`lint`、`build`、`test:unit`、`test:ui`、`test:worker`、`tauri:build`、`smoke:release`。记录通过数量和关键输出。Playwright 必须覆盖最小窗口 compact 模式、素材面板、批量文件夹入口、底部 CTA、无横向溢出。

5. 写清楚功能能力：本地视频 + SRT、视频链接、批量素材、学习点抽取、完整复读、快速复读、TTS、视频/音频媒体、APKG 导出、Anki/APKG verify、安全拦截。不要把浏览器端说成已经完成。

6. 生成三份说明材料：Markdown、Word、PPT。Word 必须使用 documents 技能和设计预设，渲染成 PNG 检查页面；PPT 必须使用 presentations 技能和 `@oai/artifact-tool`，导出预览图检查无重叠、无裁切、截图清晰。

7. 明确下一阶段架构：Windows 桌面端、浏览器端、local helper 必须放在不同目录。浏览器端只做 UI 和本地设置；local helper 负责本地文件、ffmpeg、worker、APKG、AnkiConnect。共享包只放类型、卡片 schema 和 UI token。

8. 做安全扫描：扫描报告目录、`docs\web-helper`、Git diff 和 staged diff。禁止提交 API key、token、secret、`.env`、APKG、视频、音频、`release/smoke`、`test_runs`、`target`、`.venv`、`node_modules`、本机私密路径和临时缓存。

## 最终验收标准

用户打开 GitHub 能明白当前 Windows 版如何下载和使用；打开报告能看到每一步测试怎么做、结果如何、哪些没覆盖；打开 Word 能像读正式产品验收报告；打开 PPT 能直接向别人介绍 Anki Card Generator 的能力、现状和下一阶段；下一个 Codex 可以按这些文档继续实现浏览器端，而不需要重新猜范围。


