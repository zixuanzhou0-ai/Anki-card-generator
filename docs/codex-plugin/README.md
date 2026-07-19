# Codex 学习制卡插件：设计文档总览

> 基线日期：2026-07-19

## CURRENT 权威实现摘要（2026-07-19）

截至 2026-07-19，可信开发态 Card Service stdio runtime 共公开 27 个工具：`system.get_capabilities`、`system.request_source_grant`、`system.request_output_grant`、`system.authorize_candidate_discovery`、`study.create_project`、`study.register_inputs`、`study.start_source_inspection`、`study.get_source_inspection`、`study.start_discovery`、`study.get_task`、`study.cancel_task`、`study.list_recoverable_tasks`、`study.resume_task`、`study.list_candidates`、`study.get_candidate`、`study.preview_evidence`、`study.set_selection`、`study.plan_cards`、`study.list_card_plans`、`study.edit_card_plan`、`study.validate_card_plans`、`cards.generate`、`cards.list`、`cards.export_apkg`、`anki.prepare_import`、`anki.request_import_confirmation`、`anki.import_and_verify`。

当前候选发现只能通过 `system.authorize_candidate_discovery` 的固定 `hermes_grok_4_5` 预设授权，再由 `study.start_discovery` 启动异步任务；调用方不能选择 Provider、Base URL、模型、凭据、提示词或原始来源正文。当前输入面只支持经本地授权并成功检查的文本、Markdown、代码、HTML、字幕文本及其目录成员；视频/YouTube/PDF/Office/网页抓取/播客与媒体转写仍是路线图，不是当前插件能力。

当前 Anki 闭环已能执行受信确认后的真实导入及数据级核验。最高可信状态是 `anki_data_verified`；真实卡片渲染、音视频播放、复习交互和重启持久性的 runtime verifier 尚未实现，必须报告 `runtimeVerification=not_assessed`。仓库内插件清单仍是被动 Skill 包，不声明 MCP/App；开发态 runtime 可用不等于已有正式签名、可安装、可发布的插件。

下文带日期的 M0/M1 数字和“下一阶段”措辞属于历史实施快照；若与本段冲突，以本段、当前工具清单和代码测试为准。

> 文档状态：CURRENT 开发态 runtime/Skill + PROPOSED 正式插件与扩展能力
> 基线日期：2026-07-19
> 适用对象：项目作者、插件实现者、安全与学习质量评审者
> 重要说明：CURRENT 段落描述当前仓库代码；PROPOSED 与带日期的里程碑快照描述未来或历史。开发态 MCP 可用不等于插件已经正式签名、可安装或可发布。

## 1. 这套文档解决什么问题

本项目下一阶段不是把桌面应用机械地塞进 Codex，而是把已经验证过的制卡可靠性内核，重构成一个由 Agent 驱动、用户可监督、结果可追溯的学习系统。

目标体验是：

1. 用户在对话中交付素材和学习意图。
2. Agent 理解目标、检查素材、发现值得学习的内容。
3. 用户通过对话分页工具，或在目标宿主验证通过后的轻量控制台中，查看任务真相、候选知识点和风险。
4. 本地可靠性服务生成卡片、媒体和 APKG。
5. 用户明确授权后导入 Anki，并获得可核验的导入结果。

一句话产品定义：

> 将 Codex 能被授权读取的素材，转化为有证据、可作答、值得复习、能够在真实 Anki 中验证的学习任务。

## 2. 已确定的关键决策

| 议题 | 决策 |
|---|---|
| 首版用户 | 项目作者本人和高级 GitHub 用户 |
| 主要入口 | Codex 对话 + 插件工作控制台 |
| 桌面端定位 | 可选的兼容入口、调试工具和可靠性验证场，不是首版必需入口 |
| 插件组成 | Skill + 类型化本地 MCP 服务 + 可选 App UI |
| 核心执行 | 复用现有 Python Worker、FFmpeg、TTS、APKG 与 Anki 数据核验；新增受信 runtime verifier 后才宣称真实渲染/播放/复习通过 |
| Agent 自治 | 在用户授予的素材、目录、网络和数量边界内高度自治 |
| 高影响动作 | 开放新目录、上传新远程服务、覆盖/删除、导入 Anki 必须显式确认；V1 不提供运行期安装工具 |
| 固定右侧栏 | 是产品偏好和未来适配目标，不是当前已验证的 Codex 公共扩展接口 |
| App UI 目标形态 | Apps SDK 为 ChatGPT Apps 定义 Inline、Fullscreen、PiP；Codex 各宿主是否支持必须实测，V1 核心按 tools-only 也可完成 |
| 长任务 | 任务化、可取消、可检查点恢复；首版不承诺 Codex 关闭后继续后台运行 |
| 学习点选择 | 目标驱动、证据约束、硬门禁后排序，并按学习组合覆盖而非简单 Top-N |
| 卡片原则 | 一张卡一个可评分的提取目标；背面可以丰富，但核心答案必须独立 |
| “任何文件” | 作为输入愿景成立；只有取得稳定快照和证据定位后才能生成正式已验证卡片 |
| 发布路径 | 首先通过 Git 仓库/个人 Marketplace 分发；公共目录与托管 MCP 属于后续阶段 |

## 3. 官方能力边界

截至 2026-07-16，OpenAI 官方资料明确支持：

- 插件可包含 Skills、MCP-backed App，或二者组合。
- 插件根目录使用 .codex-plugin/plugin.json 描述清单。
- MCP 可使用本地 stdio 或 Streamable HTTP。
- Apps SDK 文档为 ChatGPT Apps 定义 Inline、Fullscreen 和 PiP；这不证明所有 Codex Desktop、CLI 或 IDE 宿主都支持。
- App 与宿主通过标准 MCP Apps 桥接通信。
- Git 仓库和个人 Marketplace 可以承载插件分发。

本次检索没有发现允许第三方插件任意固定占据 Codex 右侧栏的稳定公开接口，也没有据此确认目标 Codex 宿主一定承载三种 Apps SDK 界面。因此设计采用“tools-only 核心 + 条件 App UI 适配器”：

- M3 语言 MVP：对话 + MCP tools 完成核心闭环。
- M4：只有在真实目标 Codex 宿主验证 MCP App resource 可用后，才添加 Inline、Fullscreen、PiP Work Rail。
- 若未来官方开放固定侧栏：只新增宿主适配层，不修改任务、学习或可靠性协议。
- 不注入 Codex DOM，不依赖未公开窗口结构，不使用 Computer Use 作为插件核心控制方式。

官方参考：

- [Plugins overview](https://learn.chatgpt.com/docs/plugins#overview)
- [Build plugins](https://learn.chatgpt.com/docs/build-plugins#plugin-structure)
- [MCP supported features](https://learn.chatgpt.com/docs/extend/mcp#supported-mcp-features)
- [Apps SDK UI display modes](https://developers.openai.com/apps-sdk/concepts/ui-guidelines#display-modes)
- [MCP Apps host bridge](https://developers.openai.com/apps-sdk/mcp-apps-in-chatgpt#host-bridge)

## 4. 状态标记

文档使用下列标记避免把愿景误当成现状：

- CURRENT：已在当前仓库代码中核验存在。
- PROPOSED：插件实现时必须遵守的设计契约。
- DEFERRED：明确延期，不能作为首版验收依据。
- EXPERIMENT：需要用真实学习数据验证的产品假设。

若同一能力同时有当前实现和拟议接口，文档会分别陈述，不把旧接口直接等同于新插件协议。

### 4.1 CURRENT：M0 实施快照（2026-07-17）

当前工作分支已经实现并纳入自动化门禁的基础能力：

- 九个现有 Python Worker 命令有版本化 schema 与 golden exchanges；结果和进度帧的 schema 版本、核心错误码与秘密剥离边界被机器检查。
- APKG 生成与核验不再使用 Note Model 名称前缀猜版本，而是按精确的 family、template schema、Note Model ID、字段/模板/CSS 哈希和兼容合同匹配；Note Model 序列化基线固定为 `genanki==0.13.1`，但这不表示所有依赖都已完成哈希锁定。
- 完整 APKG 包合同已覆盖 ZIP 条目唯一性与限额、collection/media 映射、模型/牌组/note/card 关系、CardId、纯内容摘要、媒体 manifest/ledger、卡片媒体账本及安全展示 HTML；10 个生产生成变体均以真实 `handle_export` 产物通过同一整包验证器。
- 导出先在最终目录写入唯一 `.partial`，整包校验通过后才以 **no-replace** 语义原子发布最终 APKG；目标路径已经存在时拒绝覆盖。校验或发布失败会清理/隔离 partial，不能发出“已完成”状态。
- 生产 V15、V14 与明确保留的 V10 兼容模型使用同一合同注册表；release smoke 继续生成并核验 V14/V10，V15 另由 20 卡生产包、模型作用域 GUID 和完整包合同覆盖。V13、V199、近似名称、非规范 ID/整数、字段/模板/model extras/CSS 篡改、未引用/额外模型、双 collection、重复关键条目和解压限额超限进入负向合同测试。
- 现有 Anki 导入命令只把应用内部生成、证据完整的 raw `ExportResult` 当作兼容输入，并核对 payload 覆盖一致性、绝对 APKG/media 路径、实际哈希/大小、整包内容与精确 Note Model 合同；该阶段失败时媒体准备和 `importPackage` 都不能发生。这个接口不认证 `ExportResult` 的来源，无法抵抗能同时篡改 APKG 与 `ExportResult` 的同权限本机攻击者。媒体准备后、紧贴 `importPackage` 前再次 stat + SHA，只能显著缩窄而不能从原理上消除路径换包 TOCTOU。M2 必须用认证 Artifact 注册表、不透明句柄和受控文件句柄建立真正的信任根；在此之前 raw `ExportResult` 命令不得直接暴露为公共 MCP 写工具。
- 桌面导入入口不会仅凭一个残留状态继续：full 与 compact 两份导出证据必须同时完整，并对同一 APKG 的规范化路径、哈希、大小、mtime、牌组、模型、模板、合同、标签、来源/内容指纹与核心媒体摘要严格配对。标准 Windows Anki profile 的媒体预置 direct-first，以同一源/临时文件句柄、1 MiB 固定块、flush/fsync、identity 复核和 same-dir no-replace 发布；并发同内容幂等，冲突内容绝不覆盖。
- 非标准/portable profile 与非 Windows 只保留原始媒体不超过 8 MiB 的 AnkiConnect inline 兼容路径；8 MiB+1 在任何媒体 API 前停止。8 MiB 是原始媒体协议上限，不是进程峰值；兼容路径仍是整文件 Base64。部分成功、超时未知结果、可能孤儿与清理失败进入 ownership ledger，最终媒体 barrier 未闭合时禁止导入。
- 最终自动化回归已通过：前端 Vitest 830 项；Python 正式 `pytest` 603 项；独立 `unittest discover` 576 项；Rust 31 项通过、1 项按设计忽略；UI smoke 3 项；V15/V10 release smoke、`npm run check:full` 与 `npm run tauri:build` 均通过。`pytest` 与 `unittest` 有重叠，不能相加成独立测试总数。
- 20 卡生产 V15 离线媒体包通过完整 APKG 合同：20 notes / 20 cards / 52 个唯一媒体，manifest、逐媒体哈希、模型作用域 GUID 与字幕对齐全部闭合。素材为 release-smoke 合成视频与 SRT，TTS/原声为静音 fixture，因此只证明包、渲染和媒体状态机，不证明真人语义、听感或长期学习效果。
- 真实隔离 Anki 数据级核验已经完成：单卡 E→C 跨盘导入为 1 note / 1 card / 6 media，最终 V15 20 卡包为 20 notes / 20 cards / 52 media；逐文件大小与 SHA-256 全部闭合，重复导入均跳过，真实重启后计数与哈希仍完整。V14/V15 字段完全相同的 note 在同一集合中保持不同 model、GUID 和 note/card ID，重启前后无差异；正式 profile/牌组未被触碰。
- 非 NFC 名称、Windows 保留设备名（含 `CLOCK$`）、大小写/规范化冲突及 APKG archive 资源上限已经完成 fail-closed 回归；APKG archive/package/verifier 与标准 Windows Anki direct path 均采用有界流式读取。64 MiB direct 样本在整文件读取、Base64 和 AnkiConnect 媒体动作被禁止时通过，Python `tracemalloc` 峰值增量低于 32 MiB；这不等于非标准兼容路径或双进程 RSS 已全部流式化/量化。
- 在合同尚未对齐的先前尝试中，生产 preflight 与最终包门禁按设计 fail closed；隔离目标保持 0 note / 0 card / 0 media。该负例证明失败没有产生半写入，不能被改写成成功测试。

Codex 插件仍未正式交付：仓库已有被动 plugin manifest/Skill、开发态可信 stdio MCP、M1 Headless Card Service、认证 Artifact/opaque handle、固定 launcher、非安装型候选和 finalizer。开发态链已经覆盖候选发现、文本卡片、APKG 和 Anki 数据核验；历史 Codex `0.144.1` 实物探针只证明当时候选可启动。当前 launcher 仍为 `NotSigned`，没有生产发布策略/HSM 签名、正式独立安装验收、App UI 或插件侧 runtime verifier，因此正式安装流程继续失败关闭。详见 [M0 验证报告](M0_VERIFICATION_REPORT_2026-07-17.md) 与 [M1 安装最终化验证报告](M1_INSTALL_FINALIZER_VERIFICATION_2026-07-18.md)。

### 4.2 遗留文档冲突清单（只登记，不回写历史快照）

下列文件仍是有用的历史资料，但不能作为 CURRENT M0 或插件行为的权威来源：

| 位置 | 已发现的冲突或过期内容 | 本轮处理 |
|---|---|---|
| 仓库根 `README.md` | 快速开始仍是十二步桌面流程，并保留“继续导出 N 张”；还包含历史批量发布数字，不能替代当前 M0 合同与隔离 Anki 证据 | 不修改；后续桌面文档专项刷新。CURRENT M0 以本目录和本轮测试证据为准 |
| `docs/USER_GUIDE.md` | 文案称“主界面分为三段”却列出四段，仍有独立“学习设置/确认抽取/审核导出”、顶部抽取/导出入口和旧截图 | 不修改；标记为桌面旧流程指南，待三步流程稳定后统一重写 |
| `docs/ARCHITECTURE.md` | 仍以“素材配置 → 学习设置 → 确认抽取 → 审核导出”和 `source/generate/review` 解释当前桌面层，未反映新的三步体验与插件/Card Service 目标边界 | 不修改；后续把 CURRENT desktop、M0 内核与 PROPOSED plugin 架构分章 |
| `docs/reports/**` | 2026-06-24 至 2026-06-27 的发布、E2E、PPT/DOCX/Markdown 是带日期的归档；其中既有旧“继续导出/学习设置”流程，也有“测试时 AnkiConnect 不可用”等当时事实 | 保持不可变历史证据，不追写新结论；引用时必须同时写明报告日期、版本和适用范围 |

优先级规则：当前代码与本轮机器/真实设备证据 > `docs/codex-plugin/` 明确标为 CURRENT 的段落 > 根 README/用户指南/旧架构 > 历史 reports。这个优先级不删除历史，也不把 PROPOSED 设计伪装成 CURRENT。

## 5. 文档地图

### 先理解产品

1. [产品规格](PRODUCT_SPEC.md)：用户、范围、自治、主流程和验收标准。
2. [用户旅程](USER_JOURNEYS.md)：视频、PDF、网页、播客、批量文件和恢复场景。
3. [学习设计](LEARNING_DESIGN.md)：如何选知识点、为什么值得制卡、卡片的第一性原理。
4. [宿主界面与交互](UX_AND_HOST_SURFACES.md)：对话、控制台和宿主形态如何协作。
5. [限制与已知风险](LIMITATIONS.md)：哪些是现状、规划、条件能力和明确不承诺。

### 再实现系统

6. [目标架构](ARCHITECTURE.md)：组件、边界、数据流、任务和迁移。
7. [插件包参考](PLUGIN_PACKAGE_REFERENCE.md)：目录、清单、分发和兼容策略。
8. [Skill 行为规范](SKILL_BEHAVIOR.md)：询问、自治、工具编排、失败与状态措辞。
9. [Study IR 参考](STUDY_IR_REFERENCE.md)：来源、证据、语义单元、学习目标、候选和卡片计划。
10. [MCP 工具参考](MCP_TOOL_REFERENCE.md)：面向用户意图的类型化工具契约。
11. [素材适配器](SOURCE_ADAPTERS.md)：支持级别、稳定快照、证据定位和降级规则。

### 最后证明它可靠

12. [安全与隐私](SECURITY_AND_PRIVACY.md)：内部授权记录、提示注入、路径、网络、秘密和 Anki 写入。
13. [M0 验证报告](M0_VERIFICATION_REPORT_2026-07-17.md)：最终自动化、V15 20 卡媒体包、隔离 Anki 数据证据、真实 GUI/20 张连续复习和剩余学习效果边界。
14. [M1 安装最终化验证报告](M1_INSTALL_FINALIZER_VERIFICATION_2026-07-18.md)：安装候选、独立签名域、Authenticode、原生预检、实物宿主探针和继续阻断项。
15. [可靠性与核验](RELIABILITY_AND_VERIFICATION.md)：从素材到真实 Anki 的逐级证据链。
16. [基准与评估](BENCHMARK_AND_EVALUATION.md)：功能、对抗、学习效果和发布阈值。
17. [路线图](ROADMAP.md)：阶段、出口条件、迁移和发布策略。
18. [决策记录](DECISIONS.md)：已选方案、理由、替代方案和复议触发器。
19. [可追溯矩阵](TRACEABILITY_MATRIX.md)：目标到接口、测试与里程碑的映射。
20. [术语表](GLOSSARY.md)：跨文档统一语义。
21. [设计评审记录](DESIGN_REVIEW_RECORD.md)：内部委员会、Gemini 与 Hermes/Grok 的终审结论、分歧和裁决。

## 6. 当前可复用资产

CURRENT，经本轮仓库检查确认：

- Python Worker 已有环境检查、API/TTS 测试、学习点抽取、卡片生成、导出和 Anki 核验命令。
- 已有学习点精确跨度、候选验证、去重、状态和可靠性清单。
- 已有任务快照、单调进度、取消、结果引用和中断恢复基础。
- 已有安全检查点、输入指纹、APKG 哈希和备份恢复。
- 已有路径授权、私网 URL 阻断、AnkiConnect 回环限制、秘密存储和跨磁盘 Anki 导入修复。
- Codex 公共链已经达到认证 PackageArtifact、`anki.prepare_import`、受信 `anki.request_import_confirmation` 与 `anki.import_and_verify`：可在模型外真实点击后幂等导入并完成 Anki 数据级核验；runtime 渲染、播放、reviewer 与重启核验仍未开放。
- 已有 APKG、媒体、TTS、卡片字段、AnkiConnect 数据核验与真实 Anki GUI 验收基础；M0 已加入精确 V15/V14/V10 Note Model 合同、V15 模型作用域 GUID、完整 APKG 包合同、partial 校验后 no-replace 原子发布、导入前整包 preflight、隔离真实 Anki 重复/重启/V14-V15 并存证据，以及受版本化 runtime contract 约束的最小媒体快捷键 add-on。Codex 插件侧的通用 runtime verifier 仍是 PROPOSED。

需要重构而不是直接暴露：

- Tauri 控制器是桌面 UI 编排层，不应成为 MCP 公共接口。
- 当前 Worker 命令粒度偏内部，不应提供通用 run_worker 工具。
- 当前文档读取和分块只是实验基础，尚不足以表达复杂 PDF、图表、代码、公式和知识冲突。
- 当前语言学习点结构不能直接承载所有通用知识类型，需要 Study IR。

## 7. 文档治理

任何实现变更都应同时更新：

1. 对应规范文档。
2. [决策记录](DECISIONS.md)。
3. [可追溯矩阵](TRACEABILITY_MATRIX.md)。
4. 对应契约或验收测试。

文档版本规则：

- 破坏性协议变化：增加 schemaVersion 或协议主版本。
- 向后兼容字段：增加次版本并记录默认语义。
- 只改说明、不改行为：记录文档日期即可。
- 未实现字段必须继续标为 PROPOSED，不得通过删标记伪装完成。

## 8. 最终完成的定义

插件不是在能够“生成一段卡片 JSON”时完成，而是在下列闭环成立时完成：

> 授权输入可追溯 → 学习目标明确 → 候选选择可解释 → 卡片可作答 → 内容有证据 → 媒体语义一致 → APKG 完整 → 用户授权导入 → 真实 Anki 可复习 → 失败可恢复且不伪造成功。
