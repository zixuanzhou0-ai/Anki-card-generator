# Anki Card Generator v0.9.6-beta 统一卡片质量、版权设置与发布交付完整计划

## 0. 文档目的

本计划用于指导 Codex 完成下一轮 Anki Card Generator 收口：先解决“推荐卡片质量与卡片形态过于花哨/重复”的核心产品问题，再补充设置页版权声明与 GitHub 仓库入口，最后更新 GitHub 文档、安装包、桌面交付文件夹、截图和验收材料。

本计划只针对 Anki Card Generator，不包含 其他项目，不包含浏览器端 / Local Helper，不把 `docs/web-helper/` 纳入发布。

## 1. 当前已知状态

- 仓库：`https://github.com/zixuanzhou0-ai/Anki-card-generator`
- 当前本地版本基线：`v0.9.5-beta` 后续改动。
- 已有但尚未发布的新改动：
  - 抽取学习点进度页布局修正：右侧进度工作台靠上，左侧运行卡不再被拉成长空白块。
  - Vertex AI 新增 Gemini 3.5 Flash：官方模型 ID `gemini-3.5-flash`，并支持 `gemini-3.5` / `gemini-3.5-flash-latest` 别名归一化。
- 仍存在的核心产品问题：推荐卡片和卡片类型过多，听力/表达/填空/难点等卡片内容容易大同小异，用户背诵负担偏大。
- 本次目标版本建议：`v0.9.6-beta`。

## 2. 产品决策

### 2.1 保留内部学习点分类

继续保留 `candidate_kind` / `phrase_type` 等内部标签：

- `expression`
- `contextual_vocab`
- `grammar_pattern`
- `listening_feature`
- `pragmatic_risk`

这些分类仍用于召回、AI 精筛、评分、解释和界面标签。

### 2.2 导出的 Anki 卡片统一成一种主卡

默认策略改为：**一个 selected learning point 只生成一张统一学习卡**。

不再默认把一个学习点拆成：

- phrase 卡
- listening 卡
- cloze 卡

听力、表达、语法、词汇、语气风险只作为统一卡里的“小标签 / 学习角度”，而不是不同卡型。

### 2.3 完整复读 / 快速复读继续保留

`review_density = full | fast` 是内容密度，不是卡片类型。继续保留：

- 完整复读：解释更完整，适合深度学习。
- 快速复读：字段更短，适合批量复习。

## 3. 代码修改计划

### 3.1 统一制卡策略

重点文件：

- `workers/acg/card_planning.py`
- `workers/acg/commands/generate_cards_from_learning_points.py`
- `workers/acg/legacy_worker.py`
- `tests/test_card_planning_boundaries.py`
- `tests/test_worker_quality.py`

要求：

1. `requested_card_types()` 默认返回 `['phrase']` 或新的统一内部类型，例如 `['learning_point']`。
2. `plan_card_types()` 不再追加 optional listening/cloze 变体。
3. `card_type_for_learning_point()` 对所有学习点默认返回统一主卡类型。
4. `generate_cards_from_learning_points` 每个 selected learning point 只生成一个 segment / one card。
5. 保留旧字段兼容，避免 APKG 模板、媒体、TTS、verify 直接断裂。
6. 如果模板仍需要 `card_type` 字段，统一写入稳定值，例如 `phrase` 或 `learning_point`；优先选择风险更低的兼容值。

验收：同一个 learning point 不得生成多张 phrase/listening/cloze 变体卡。

### 3.2 优化推荐卡片质量

重点文件：

- `workers/acg/pipeline/learning_point_pipeline.py`
- `workers/acg/scoring/learning_value.py`
- `workers/acg/recall/local_learning_points.py`
- `workers/acg/pipeline/learning_point_pipeline.py` 中 AI review prompt
- `src/features/learningPoints/LearningPointOverview.tsx`

目标：推荐卡片宁可少一点，也要更值得背。

新增或强化评分维度：

1. 单一卡片目标是否明确。
2. answer_core 是否在原句中可定位。
3. 是否有迁移价值，避免只适合当前剧情的一次性解释。
4. 是否过泛，例如 `talk about`、`do something`、`good thing`。
5. 是否和已有推荐重复。
6. 是否适合当前用户等级。
7. 是否能形成清楚的 Anki 回忆问题。

建议阈值：

- `recommended`：价值高、可定位、可迁移、难度匹配、非重复。
- `candidate_only`：合法但价值一般、偏基础、偏场景化或不够清晰。
- `hidden_duplicate`：训练动作重复。
- `hard_blocked`：字段缺失、answer_core 非法、无法定位或明显不适合制卡。

推荐结果应在 UI 中更清楚地区分：

- 默认推荐：真正建议生成。
- 候选：可手动加入，但默认不打扰。
- 重复/阻断：只作为诊断，不进入主队列。

### 3.3 设置页新增“关于 / 版权”

重点文件：

- `src/features/settings/SettingsDialog.tsx`
- `src/features/settings/ApiSettingsPanel.tsx` 或新增 `AboutSettingsPanel.tsx`
- `src/app.css`
- `package.json` 或版本读取文件

功能要求：

1. 设置页新增 Tab：`关于 / 版权`。
2. 显示产品名称：`Anki 卡片生成器`。
3. 显示版本：从 `package.json` 或现有版本常量读取，避免手写漂移。
4. 显示版权声明：
   - `版权所有 © 2026 Zixuan Zhou。保留所有权利。`
   - `Anki Card Generator is an independent desktop application for generating Anki study cards from user-provided learning materials.`
5. 显示 Anki 独立声明：
   - `本软件与 Anki、AnkiWeb 或其开发团队无官方隶属关系。`
6. 增加 GitHub 图标按钮：
   - 优先使用 `lucide-react`。当前包没有 GitHub 品牌图标时，使用 `GitBranch` + `ExternalLink` 组成明确的仓库入口。
   - 文案：`GitHub 仓库` / `查看源码`。
   - 点击后打开：`https://github.com/zixuanzhou0-ai/Anki-card-generator`
7. 不展示任何 API key、本机路径或用户隐私信息。

### 3.4 保留当前已完成改动

本轮最终 PR / Release 必须包含并验证：

- 抽取学习点布局修正。
- Vertex AI `Gemini 3.5 Flash Vertex`。
- worker / 前端模型别名归一化。

## 4. 文档与交付更新计划

### 4.1 GitHub 文档

更新：

- `README.md`
- `docs/USER_GUIDE.md`
- `docs/TROUBLESHOOTING.md`
- `docs/RELEASE_CHECKLIST.md`
- 新增 `docs/RELEASE_NOTES_v0.9.6-beta.md`

重点说明：

1. 当前版本是 Windows 桌面端。
2. 默认生成统一学习卡，不再默认生成多种重复卡型。
3. 如何配置模型 API，包括 Vertex Gemini 3.5 Flash。
4. 设置页包含版权声明和 GitHub 入口。
5. 下载哪个安装包、如何校验 SHA256。
6. 不承诺浏览器端 / Local Helper 已完成。

### 4.2 截图更新

更新或新增公开截图：

- 主界面。
- 抽取学习点进度页修正版。
- 学习点推荐列表。
- 统一学习卡审核页。
- 设置页模型配置：含 Gemini 3.5 Flash。
- 设置页关于 / 版权页：含 GitHub 图标。
- Anki 成品卡正反面。

截图要求：

- 无 API key。
- 无真实私密路径。
- 无私人字幕内容。
- 不包含临时测试文件名、APKG 原始路径或用户隐私。

### 4.3 桌面交付文件夹

更新桌面目录：

`C:\Users\Administrator\Desktop\Anki卡片生成器_v0.9.6-beta`

建议结构：

- `安装包\`
  - `Anki.Card.Generator_0.9.6_x64-setup.exe`
  - `Anki.Card.Generator_0.9.6_x64_en-US.msi`
  - `Anki卡片生成器-v0.9.6-beta-Windows便携版.zip`
  - `SHA256SUMS-v0.9.6-beta.txt`
- `说明文档\`
  - `Anki卡片生成器使用手册_v0.9.6-beta.md`
  - `Anki卡片生成器使用手册_v0.9.6-beta.docx`
  - `Anki卡片生成器产品介绍_v0.9.6-beta.pptx`
- `截图\`
  - 安全脱敏后的产品截图和 Anki 成品卡截图。

文档命名尽可能中文化。

## 5. 测试计划

### 5.1 自动化测试

必须运行：

- `npm.cmd run check:versions`
- `npm.cmd run lint`
- `npm.cmd run test:unit`
- `npm.cmd run test:ui`
- `npm.cmd run test:worker`
- `npm.cmd run build`
- `cargo check --manifest-path src-tauri/Cargo.toml`
- `npm.cmd run tauri:build`

建议运行：

- `npm.cmd run smoke:release`

### 5.2 卡片质量专项验收

至少准备 2-3 个小型真实素材：

1. 本地视频 + SRT。
2. 视频链接。
3. 含明显表达/听力/语法混合点的字幕。

验收标准：

- 推荐卡片数量不过度膨胀。
- 一个 learning point 只生成一张卡。
- 默认推荐项中，大多数能清楚回答“为什么值得背”。
- 成品卡不再出现听力/表达/填空多卡重复。
- APKG 内 note/card count 与选中学习点数量一致或接近一致，并能解释差异。
- TTS、媒体切片、poster、音频引用和 verify 通过。

### 5.3 设置页版权验收

- 设置页能打开 `关于 / 版权`。
- 显示产品名、版本、版权声明、独立声明。
- GitHub 图标按钮可点击并打开仓库。
- 无 API key 或本机隐私泄露。
- 小窗口下文字不溢出、不重叠。

### 5.4 安装包验收

- 卸载旧候选程序本体，保留用户配置/API key。
- 安装 `0.9.6` NSIS setup。
- 启动无黑色终端弹窗。
- 设置页版权可见。
- Vertex Gemini 3.5 Flash 可选。
- 完成一次端到端：素材输入、抽取、推荐、生成统一卡、导出 APKG、Anki verify。

## 6. 安全与仓库边界

提交前必须扫描：

- Git diff。
- staged diff。
- 新文档。
- 截图目录。
- 桌面交付文件夹。
- DOCX/PPTX 解包内容。

禁止提交：

- API key / token / Authorization header。
- `.env`、本地配置、Credential 内容。
- `test_runs/`、`release/smoke/`、`src-tauri/target/`。
- APKG、视频、音频原始测试素材。
- `docs/web-helper/`。
- 旧跨项目材料。

必须白名单 stage，不使用 `git add .`。

## 7. GitHub 发布流程

1. 创建或使用分支：`codex/v0.9.6-beta-unified-cards-copyright`。
2. 完成代码、文档、测试。
3. 白名单 stage。
4. 提交：`release: v0.9.6-beta unified cards and copyright settings`。
5. 推送分支。
6. 创建 PR 到 `main`。
7. 等 CI 通过。
8. 合并后在 main 创建 tag：`v0.9.6-beta`。
9. 创建 GitHub Release。
10. 上传 NSIS、MSI、portable zip、SHA256SUMS。
11. Release body 使用 `docs/RELEASE_NOTES_v0.9.6-beta.md`。
12. 不上传本地私密证据或原始测试素材。

## 8. 最终验收标准

本轮完成后必须满足：

- 推荐卡片不再以多卡型重复为默认体验。
- 每个选中学习点默认只生成一张统一学习卡。
- 设置页有版权声明和 GitHub 仓库入口。
- Vertex AI 可选 Gemini 3.5 Flash。
- 抽取学习点进度页布局正常。
- Windows 安装包可安装、可启动、无终端弹窗。
- 端到端制卡和 APKG/Anki verify 通过。
- GitHub README、Release、截图、桌面交付文件夹全部更新。
- Word / PPT / Markdown 使用说明中文命名、中文为主、排版检查通过。
- 无 API key、私密路径、APKG、视频、音频、缓存或测试垃圾进入 GitHub。