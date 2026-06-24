# Goals：Anki Card Generator Windows 桌面端 PR 收口

目标是在 `E:\ANKI` 中完成 Anki Card Generator Windows 桌面端的最终清洗、启动验证、测试验证和 PR 准备。不要再出现 错误项目名的任何拼写。当前项目名只能是 Anki Card Generator / Anki 卡片生成器。

## 参考文档

- 清洗报告：`E:\ANKI\docs\reports\2026-06-24-project-cleanup\CLEANUP_AND_STARTUP_REPORT.md`
- 完整计划：`E:\ANKI\docs\reports\2026-06-24-project-cleanup\FULL_EXECUTION_PLAN.md`
- 跨平台验收：`E:\ANKI\docs\reports\2026-06-24-cross-platform-verification\TEST_PROTOCOL.md`

## 必须完成

1. 全仓库扫描并清理旧项目名。扫描文本、文件名、目录名、Word/PPTX 包内 XML。结果必须无 错误项目名命中。
2. 保持本次 PR 聚焦 Windows 桌面端。本地暂停资料目录只保留在工作区，不提交、不展示、不作为当前路线承诺。
3. 启动脚本必须自动选择可监听的本机开发端口；静态 fallback 使用 `5173`，避免 Windows 保留端口导致 EACCES。
4. 正常启动当前项目：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_desktop_dev.ps1 -TimeoutSeconds 180`。验收标准是 Vite ready、Tauri debug exe 运行、窗口标题为 `Anki 卡片生成器`、startup JSON 显示 `visible=true`。
5. 跑测试：`check:versions`、`test:ui`、`smoke:release`、`build`、`cargo check --manifest-path src-tauri/Cargo.toml`。全部通过才算清洗完成。
6. 做安全扫描：报告目录、Git diff、Office 包内 XML 都不能有真实 API key、token、secret、password。
7. 上传 GitHub 前只能白名单 staging。允许产品源码、启动脚本、公开 Windows 桌面端文档和清洗报告；禁止本地暂停资料目录、APKG、视频、音频、`release/smoke`、`target`、`.venv`、`node_modules`、`test_runs`、本地缓存和 API key。
8. 不提交 `src-tauri\Cargo.toml` 的无内容换行符状态。若要处理，必须先确认真实 diff。

## 最终验收

用户打开项目只能看到 Anki Card Generator。项目能正常启动和测试。GitHub 用户能明确知道当前下载的是 Windows 桌面端；macOS/Linux 用户会看到当前桌面端暂不支持，不会误下载 Windows 安装器。下一轮 Codex 可以按这些文档继续完成 PR 收口，不需要重新猜项目名和边界。

