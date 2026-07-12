# Goals：Anki Card Generator v0.9.6-beta 发布收口

目标：完成 Anki Card Generator Windows 桌面端 v0.9.6-beta 的产品、文档、安装包、桌面交付与发布前验收。核心方向是把默认卡片从多种相似卡收口为一种“学习卡”，提升推荐质量，并补齐设置页版权声明和 GitHub 仓库入口。

计划地址：`E:\ANKI\docs\reports\2026-06-27-card-quality-copyright-release\FULL_IMPLEMENTATION_PLAN.md`

测试记录地址：`E:\ANKI\docs\reports\2026-06-27-card-quality-copyright-release\TEST_PROTOCOL.md`

桌面交付目录：`C:\Users\Administrator\Desktop\Anki卡片生成器_v0.9.6-beta`

## 1. 范围

只做 Anki Card Generator Windows 桌面端。网页端 / Local Helper 暂停，不提交 `docs/web-helper/`。保留用户本机配置、AppData、API key、历史项目，不做破坏性清理。交付目录和安装包不提交进 Git。

## 2. 功能目标

卡片策略：默认一个 selected learning point 只生成一张统一 `学习卡`。内部仍可保留表达、语境词义、语法、听力特征、语气风险等标签，但它们只作为召回、评分、解释和展示维度，不再默认拆成听力卡、表达卡、填空卡等多张相似卡。完整复读 / 快速复读继续保留，因为它们是解释密度，不是卡片类型。

推荐逻辑：默认推荐宁少勿滥。推荐项必须目标明确、answer_core 可在原句定位、有迁移价值、适合当前等级、非重复、能形成清楚回忆题。低迁移泛表达、一次性剧情解释、过长答案、缺少学习动作、不可定位或重复项降为候选、待审或阻断。

设置页：新增 `关于 / 版权`。显示产品名、版本、版权声明、Anki 独立声明、隐私与密钥边界，并提供 GitHub 仓库按钮：`https://github.com/zixuanzhou0-ai/Anki-card-generator`。普通页面不得展示 API key、本机私密路径或测试素材。

模型配置：Vertex AI 模型目录加入 `gemini-3.5-flash`，并保持 Vertex 通过本机 `gcloud` OAuth 鉴权。保留已支持服务商和 OpenAI-compatible 配置。

启动体验：保持普通安装版启动无黑色终端弹窗。开发调试入口可以显示控制台，但默认用户路径、worker 子进程、ffmpeg/ffprobe/ebook-convert 等外部工具调用必须隐藏窗口。

## 3. 文档与交付目标

更新公开文档：`README.md`、`docs/USER_GUIDE.md`、`docs/TROUBLESHOOTING.md`、`docs/BETA_LIMITATIONS.md`、`docs/RELEASE_CHECKLIST.md`、`docs/RELEASE_NOTES_v0.9.6-beta.md`。

桌面交付文件夹包含：

- `安装包`：安装程序 exe、MSI、便携 zip、SHA256 校验值。
- `说明文档`：中文 Markdown、中文 Word、中文 PPT。
- `截图`：主流程、设置、学习点、审核导出等脱敏截图。

说明文档必须讲清：安装方式、环境检测、模型 API、Vertex Gemini 3.5 Flash、TTS、视频/SRT 制卡、链接制卡、统一学习卡、导出 APKG、Anki verify、隐私、版权和常见问题。

## 4. 验收命令

必须通过：`npm.cmd run check:versions`、`npm.cmd run lint`、`npm.cmd run test:unit`、`npm.cmd run test:ui`、`npm.cmd run test:worker`、`cargo check --manifest-path src-tauri/Cargo.toml`、`npm.cmd run build`、`npm.cmd run tauri:build`、`npm.cmd run smoke:release`。

安装验收建议由用户最终执行：用桌面安装程序安装，确认无黑色终端弹窗；配置模型和 TTS；用小视频 + SRT 完成素材输入、抽取学习点、生成统一学习卡、导出 APKG；如 Anki/AnkiConnect 可用，执行导入/verify。

## 5. 安全与发布标准

提交前扫描 Git diff、staged diff、文档、截图、DOCX/PPTX 解包内容和交付目录。不得出现 API key、token、Authorization header、本机私密路径、APKG、视频、音频、缓存、`release/smoke/`、`test_runs/`、`src-tauri/target/`、`.venv/`、`node_modules/`。

使用白名单 staging，绝不 `git add .`。允许提交源码、测试、公开文档、release notes 和必要配置。禁止提交桌面交付文件夹、安装包和本地 QA 中间产物。

## 6. GitHub 流程

建议分支：`codex/v0.9.6-beta-unified-cards-copyright`。提交信息：`release: v0.9.6-beta unified cards and copyright settings`。PR 到 `main`，CI 通过后再合并并创建 `v0.9.6-beta` Release。Release 上传 NSIS、MSI、portable zip 和 SHA256SUMS，正文以 `docs/RELEASE_NOTES_v0.9.6-beta.md` 为准。

完成标准：统一学习卡跑通、推荐质量改善、版权/GitHub 设置可见、安装包和 SHA256 可用、中文 Markdown/Word/PPT 已生成、桌面交付文件夹完整、自动化与 smoke 通过、敏感信息扫描通过、GitHub 发布边界清楚。