# Codex 学习制卡插件：设计文档总览

> 文档状态：设计基线（PROPOSED）  
> 基线日期：2026-07-16  
> 适用对象：项目作者、插件实现者、安全与学习质量评审者  
> 重要说明：本目录描述后续插件，不代表当前桌面端或插件已经实现。

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
13. [可靠性与核验](RELIABILITY_AND_VERIFICATION.md)：从素材到真实 Anki 的逐级证据链。
14. [基准与评估](BENCHMARK_AND_EVALUATION.md)：功能、对抗、学习效果和发布阈值。
15. [路线图](ROADMAP.md)：阶段、出口条件、迁移和发布策略。
16. [决策记录](DECISIONS.md)：已选方案、理由、替代方案和复议触发器。
17. [可追溯矩阵](TRACEABILITY_MATRIX.md)：目标到接口、测试与里程碑的映射。
18. [术语表](GLOSSARY.md)：跨文档统一语义。
19. [设计评审记录](DESIGN_REVIEW_RECORD.md)：内部委员会、Gemini 与 Hermes/Grok 的终审结论、分歧和裁决。

## 6. 当前可复用资产

CURRENT，经本轮仓库检查确认：

- Python Worker 已有环境检查、API/TTS 测试、学习点抽取、卡片生成、导出和 Anki 核验命令。
- 已有学习点精确跨度、候选验证、去重、状态和可靠性清单。
- 已有任务快照、单调进度、取消、结果引用和中断恢复基础。
- 已有安全检查点、输入指纹、APKG 哈希和备份恢复。
- 已有路径授权、私网 URL 阻断、AnkiConnect 回环限制、秘密存储和跨磁盘 Anki 导入修复。
- 已有 APKG、媒体、TTS、卡片字段、AnkiConnect 数据核验与人工真实 Anki 验收基础；插件所需版本化 runtime verifier 仍是 PROPOSED。

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

