# Anki Card Generator v0.9.4-beta 全链路验收记录

日期：2026-06-24  
对象：`v0.9.4-beta` Windows 桌面端 Release  
结论：GitHub 用户可见信息、Release 资产、核心自动化测试、发布构建、APKG smoke 验证均已通过。安装版 WebView2 生产进程未开放 CDP 调试端口，因此安装版 UI 自动截图采用兜底证据；这不是功能失败。

## 1. 验收范围

本次验收覆盖四个层面：

1. GitHub 上用户是否能看懂当前产品是什么、下载什么、支持什么。
2. Release 资产是否真实可下载、哈希是否和 GitHub 资产摘要一致。
3. 本地功能链路是否完整：生成、导出、媒体、TTS、APKG 校验、UI 最小窗口可达性。
4. 后续浏览器端和 local helper 规划是否已经形成清晰边界，避免 Windows 端与浏览器端混成一个代码堆。

不覆盖：

- 不重新跑 27 小时全量矩阵。
- 不把 `release/smoke/`、APKG、视频、音频、`test_runs/` 原始证据提交到 GitHub。
- 不在公开文档中暴露 API key、本机用户目录、真实私密素材。

## 2. GitHub 用户可见信息检查

仓库：`zixuanzhou0-ai/Anki-card-generator`  
Release：`v0.9.4-beta`  
Release 地址：`https://github.com/zixuanzhou0-ai/Anki-card-generator/releases/tag/v0.9.4-beta`

### 2.1 About / 简介

检查结果：通过。

GitHub About 已将项目标注为 Windows desktop video-to-Anki generator，描述了本地视频/字幕、视频链接、AI 学习点、TTS、APKG 导出和 Anki 导入核验能力。

### 2.2 Release 资产标注

检查结果：通过。

`v0.9.4-beta` Release 中可见资产：

| 资产 | 用户用途 | 结果 |
|---|---|---|
| `Anki.Card.Generator_0.9.4_x64-setup.exe` | Windows NSIS 安装器 | 通过 |
| `Anki.Card.Generator_0.9.4_x64_en-US.msi` | Windows MSI 安装器 | 通过 |
| `AnkiCardGenerator-v0.9.4-beta-windows-portable.zip` | Windows portable 包 | 通过 |
| `SHA256SUMS-v0.9.4-beta.txt` | 下载完整性校验 | 通过 |

Release body 已明确这些资产是 Windows 版本，避免 macOS/Linux 用户误以为桌面端可直接运行。

### 2.3 README 截图

检查结果：通过。

README 已引用以下用户可见截图：

- `docs/screenshots/desktop-workspace.png`
- `docs/screenshots/workflow-start.png`
- `docs/screenshots/workflow-generated.png`
- `docs/screenshots/settings-model-api.png`
- `docs/screenshots/settings-tts.png`
- `docs/screenshots/settings-environment.png`
- `docs/screenshots/anki-card-stress-start.jpg`
- `docs/screenshots/anki-card-stress-middle.jpg`
- `docs/screenshots/anki-card-stress-end.jpg`

本地截图目录还包含：

- `card-review-panel.png`
- `document-knowledge-review.png`
- `settings-modal.png`

截图覆盖：主界面、素材输入、生成结果、设置、TTS、本地环境、Anki 成品卡。

## 3. Release 下载与安装链路

下载目录：`C:\tmp\anki-card-generator-release-audit-20260624\v0.9.4-beta`  
说明：该目录在 Git 仓库外，不会提交。

### 3.1 安装器哈希

检查结果：通过。

`Anki.Card.Generator_0.9.4_x64-setup.exe`

- 实测 SHA256：`61b44fe794c83a1da6c8516342b9aa9d3164d2b28660745e494309e97a1637db`
- GitHub asset digest：`61b44fe794c83a1da6c8516342b9aa9d3164d2b28660745e494309e97a1637db`
- `SHA256SUMS-v0.9.4-beta.txt`：包含同一哈希

结论：用户从 GitHub 下载到的安装器与 Release 记录一致。

### 3.2 本机安装登记

检查结果：通过。

`winget list --name "Anki Card Generator"` 显示：

- 名称：`Anki Card Generator`
- ID：`ARP\User\X64\Anki Card Generator`
- 版本：`0.9.4`

安装版 exe 位于 `%LOCALAPPDATA%\Anki Card Generator\anki-card-generator.exe`。

### 3.3 安装版启动

检查结果：通过，带一项可观测性限制。

已从安装目录启动安装版进程，进程名为 `anki-card-generator`。生产 WebView2 未开放 `9333/9222/9223` 调试端口，因此无法用 CDP 直接操控安装版窗口截图。

处理方式：

- 不继续阻塞在 CDP 调试端口。
- 安装链路用 GitHub 下载、哈希、winget 登记和安装版进程证明。
- UI 可达性用已通过的 Playwright smoke 自动化证明。

## 4. 自动化测试结果

### 4.1 版本一致性

命令：`npm.cmd run check:versions`  
结果：通过。  
输出摘要：版本检查通过，当前版本为 `v0.9.4-beta`。

### 4.2 ESLint

命令：`npm.cmd run lint`  
结果：通过。

### 4.3 前端生产构建

命令：`npm.cmd run build`  
结果：通过。

Vite 构建成功，存在一个非阻塞警告：主 JS chunk 大于 500 kB。该警告不影响本次发布可用性，但后续可以通过 code splitting 优化。

### 4.4 Unit tests

命令：`npm.cmd run test:unit`  
结果：通过。

- Test files：62 passed
- Tests：462 passed

### 4.5 Playwright UI smoke

命令：`npm.cmd run test:ui`  
结果：通过。

通过用例：

1. public source selector exposes only video paths from current dev app
2. compact inspector keeps source and batch controls reachable at minimum desktop size
3. desktop workflow shell supports simplified settings, video URL mode, and generation

关键覆盖：

- `1180x780` 进入 compact 模式。
- 左侧控制列在 compact 模式下收为“素材面板”。
- “批量 / 文件夹”可点击。
- “选择视频文件夹批量添加”可滚动到且无遮挡。
- 底部 CTA 可达。
- 无横向溢出。

### 4.6 Worker tests

命令：`npm.cmd run test:worker`  
结果：通过。

- Ran：436 tests
- Result：OK

覆盖路径包括：

- 本地视频/SRT 生成。
- 文档知识卡生成。
- APKG 导出。
- Anki verify 模拟。
- TTS 缓存和音频字段。
- URL 私网拦截。
- AnkiConnect 只允许 loopback。
- 本地路径确认。
- ASR 命令安全约束。

### 4.7 Tauri release build

命令：`npm.cmd run tauri:build`  
结果：通过。

产物：

- `src-tauri/target/release/bundle/msi/Anki Card Generator_0.9.4_x64_en-US.msi`
- `src-tauri/target/release/bundle/nsis/Anki Card Generator_0.9.4_x64-setup.exe`

说明：该构建只证明本地打包链路健康；用户安装验证仍以 GitHub Release 下载包为准。

## 5. Release smoke 测试

命令：`npm.cmd run smoke:release`  
结果：通过。

输出摘要：

- `Smoke test passed.`
- Segments：1
- APKG：`release/smoke/out/.../Release_Smoke_Test.apkg`
- Verify report：`release/smoke/verify_apkg.json`

`verify_apkg.json` 关键字段：

| 字段 | 结果 |
|---|---|
| `ok` | `true` |
| `note_count` | `1` |
| `card_count` | `1` |
| `has_video_html_field` | `true` |
| `has_mp4_video_source` | `true` |
| `has_webm_video_source` | `true` |
| `has_poster_html_field` | `true` |
| `has_audio_html_field` | `true` |
| `missing_archive_media` | empty |
| `invalid_archive_media` | empty |
| `missing_referenced_media` | empty |
| `unreferenced_media` | empty |

结论：生成、TTS 缓存、视频切片、APKG 打包、媒体引用、模板字段和 APKG 内部校验均通过。

## 6. 功能矩阵

| 能力 | 验收方式 | 当前结果 |
|---|---|---|
| 本地视频 + SRT | worker tests + smoke release | 通过 |
| 视频链接模式 | Playwright UI smoke | 通过 |
| 学习点抽取 | Playwright UI smoke + worker tests | 通过 |
| 完整复读/快速复读 | UI smoke 检查模式入口 | 通过 |
| TTS 配置与导出音频 | UI smoke + worker tests + smoke release | 通过 |
| 视频 MP4/WebM 媒体 | smoke APKG verify | 通过 |
| APKG 导出 | worker tests + smoke release | 通过 |
| Anki/APKG verify | worker tests + smoke release | 通过 |
| 最小窗口左侧栏可达 | Playwright UI smoke | 通过 |
| 安装版启动无额外终端 | 安装版进程观察 | 通过 |
| 安装版 CDP 自动截图 | 生产 WebView2 未开放端口 | 受限，不判失败 |

## 7. 浏览器端规划状态

本地已存在浏览器端规划资料：

- `docs/web-helper/README.md`
- `docs/web-helper/IMPLEMENTATION_PLAN.md`
- `docs/web-helper/REPOSITORY_BOUNDARIES.md`
- `docs/web-helper/LOCAL_HELPER_API.md`
- `docs/web-helper/ACCEPTANCE_CHECKLIST.md`
- `docs/web-helper/GOALS.md`

当前结论：

- 浏览器端 + local helper 还只是规划，不应在 GitHub Release 中宣传为可下载产品。
- 后续上传到 GitHub 时应增加清晰入口：Windows Desktop 已可用，Browser + Helper 是独立路线。
- 两者必须放入不同目录并明确边界，避免再次变成混杂代码。

## 8. 安全与发布边界

必须继续遵守：

- 不提交 `.env`、`.env.*`、API key、token、secret。
- 不提交 `release/smoke/`、APKG、视频、音频、缓存、`test_runs/`。
- 不提交 `src-tauri/target/`、`.venv/`、`node_modules/`。
- 不把临时下载目录 `C:\tmp\...` 放入 Git。
- 不提交 `src-tauri/Cargo.toml` 的换行符状态。

最终提交前需要做：

1. 对 `docs/reports/2026-06-24-cross-platform-verification/` 做 secret scan。
2. 对 `docs/web-helper/` 做 secret scan。
3. 对 `git diff` 和 `git diff --cached` 做 secret scan。
4. 人工检查截图不包含 API key、本机用户名、私密素材。

## 9. 当前未覆盖与风险

1. 安装版 CDP 自动截图受 WebView2 生产环境限制，未完成。
2. 本次没有重跑 27 小时全量矩阵。
3. 本次 smoke 使用合成小视频和本地模式，不代表所有真实长视频和所有外部模型供应商都已重新验收。
4. Vite chunk size 警告仍存在，属于后续性能优化项。
5. `src-tauri/Cargo.toml` 在工作树显示换行符状态，但无内容 diff；发布时必须避免误提交。

6. Word 渲染视觉 QA 受限：本机没有可用的 `soffice` / LibreOffice 命令，`render_docx.py` 无法导出页面 PNG。已完成 DOCX 结构检查，确认文件生成、段落、表格和 section 存在。
7. PPT 图像查看器受当前 Windows 沙箱限制，不能直接打开 montage；已完成替代 QA：10 张 slide PNG 均生成且尺寸为 `1280x720`，10 个 layout JSON 均生成，layout/inspect 未命中 `overlap`、`clip`、`warning`、`error`。

## 10. 交付文档

本次生成的正式说明材料：

- Markdown 测试协议：`docs/reports/2026-06-24-cross-platform-verification/TEST_PROTOCOL.md`
- Markdown 项目说明：`docs/reports/2026-06-24-cross-platform-verification/ANKI_CARD_GENERATOR_PROJECT_OVERVIEW.md`
- 4000 字以内 goals：`docs/reports/2026-06-24-cross-platform-verification/GOALS_4000.md`
- Word 报告：`docs/reports/2026-06-24-cross-platform-verification/Anki_Card_Generator_Cross_Platform_Verification.docx`
- PowerPoint 演示：`docs/reports/2026-06-24-cross-platform-verification/Anki_Card_Generator_Cross_Platform_Verification.pptx`
- PPT montage QA 图：`docs/reports/2026-06-24-cross-platform-verification/assets/pptx-deck-montage.webp`

## 11. 最终判断

`v0.9.4-beta` 已达到可公开给 Windows 用户下载测试的状态。GitHub 上已清楚标注 Windows 桌面端属性，Release 资产和哈希可验证，README 有足够截图展示产品能力，核心生成/导出/媒体/APKG 验证链路通过。浏览器端还未实现，应作为下一阶段独立产品线推进。



