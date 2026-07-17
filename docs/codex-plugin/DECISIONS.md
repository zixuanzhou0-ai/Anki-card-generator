# 架构与产品决策记录

> 状态：PROPOSED 设计阶段 ADR 汇总
> 日期：2026-07-17
> Accepted 表示后续实现默认遵守；不表示已经实现。

## D-001：Codex Plugin 是未来主入口

- 状态：Accepted。
- 决策：首版服务项目作者和高级 GitHub 用户；Codex 对话/插件是主入口。
- 理由：Agent 能直接理解素材与学习意图，并减少用户管理桌面流水线。
- 后果：新功能优先设计为可调用领域能力，不继续把 React/Tauri UI 当唯一业务入口。
- 桌面端：继续作为兼容 fallback、调试和真实桌面验证场。
- 复议：若 Codex 宿主无法提供稳定本地 MCP/附件/授权能力。

## D-002：不通过 Computer Use 控制桌面端

- 状态：Accepted。
- 决策：插件调用共享本地 Runtime，不模拟点击 Tauri。
- 理由：界面自动化脆弱、不可恢复、无法形成类型化证据。
- 例外：Computer Use 仅用于真实桌面/Anki 视觉验收。

## D-003：Plugin 核心 = Skill + typed MCP；App UI 为条件适配

- 状态：Accepted。
- Skill：意图、询问策略、工具编排和解释。
- MCP：类型化能力、任务、权限和状态真相。
- App UI：仅在 M4 目标 Codex 宿主兼容实验通过后，承载候选、进度、证据和批量交互；否则 tools-only。
- 可靠性算法：留在本地 Runtime/Worker，不能只写进提示词。

## D-004：V1 使用本地 stdio MCP

- 状态：Accepted。
- 理由：来源、媒体、FFmpeg、秘密和 Anki 都在本机；stdio 减少网络暴露。
- 后果：Codex 退出可能结束进程，必须持久任务。
- DEFERRED：公共目录所需的生产 HTTP MCP/本地执行器配对。

## D-005：不承诺固定右侧栏

- 状态：Accepted。
- 依据：Apps SDK 为 ChatGPT Apps 定义 Inline、Fullscreen、PiP；尚未据此证明目标 Codex 宿主支持。
- 决策：M3 以 tools-only 为核心；M4 以真实 Codex 宿主兼容测试为进入门槛，再让 WorkRailViewModel 适配可用模式并预留未来窄侧栏。
- 禁止：DOM 注入、私有接口和宿主窗口黑客。
- 复议：官方发布稳定侧栏 API。

## D-006：共享 Card Service，不复制安全逻辑

- 状态：Accepted。
- 决策：Tauri 与插件最终调用同一任务、路径、秘密、Worker 和 Anki 服务。
- 理由：两套实现会产生状态、取消、修复和安全分叉。
- 迁移：先 Headless Runtime，再逐步让桌面端接入。

## D-007：Study IR 位于来源与卡片之间

- 状态：Accepted。
- 决策：SourceAsset → ContentNode/EvidenceAnchor → SemanticUnit → LearningObjective → Candidate → CardPlan。
- 理由：文件格式不应直接决定卡片；语言模型不足以表达通用知识。
- 风险：过度设计。
- 缓解：先净化 legacy payload，再用 ArtifactEnvelope 包裹并逐层迁移；禁止把 api_config/tts_config 秘密写入 Artifact。

## D-008：一张卡一个可评分提取目标

- 状态：Accepted。
- 决策：不是机械“一词一卡”，而是一个统一评分边界。
- 后果：复杂技能转 PracticeTask/ReferenceNote；过大目标拆分。
- 依据：见 [学习设计](LEARNING_DESIGN.md)。

## D-009：重要性由学习合同决定

- 状态：Accepted。
- 决策：选择目标面向未来行为、学习者水平和预算，不按来源中心性简单排序。
- 后果：每个项目需要轻量 Learning Contract。
- EXPERIMENT：自动组合是否优于手工选择必须实测。

## D-010：证据先于生成

- 状态：Accepted。
- 决策：正式候选和已验证卡必须有可重放 EvidenceAnchor。
- 后果：Codex 仅上下文转述的附件默认 draft_only。
- 不接受：模型自报置信度替代证据。

## D-011：支持“任何文件”采用分级承诺

- 状态：Accepted。
- Tier A：稳定、完整、可重放。
- Tier B：条件处理和审核。
- Tier C：阻塞/参考。
- 理由：避免“能读一段”冒充“可靠覆盖全部”。

## D-012：高度自治由 InternalAuthorizationRecord 约束

- 状态：Accepted。
- 自动：已授权读取、分析、选择、可恢复生成和版本化输出。
- 确认：新目录/远程服务/私网/超预算/覆盖/Anki；V1 不提供运行期安装能力。
- InternalAuthorizationRecord 只存在 Service 内部，绑定可信会话、intent/task、精确资源/策略/profile/凭据修订，不进入 MCP。
- 永不公开：通用 Shell、任意路径、秘密回读、raw AnkiConnect。
- 理由：用户的“最大权限”应转换为明确可审计范围，不是永久 root 权限。

## D-013：Anki 导入始终需要真实用户动作

- 状态：Accepted。
- 接口：prepare_import 生成不可变 ImportPlan；模型外受信 UI 批准；import_and_verify 只接收 importIntentId，并由 Service 查询/原子消费当前会话的内部批准状态。
- 理由：APKG 可持久修改 Note Model、模板和媒体。
- 后果：对话中的历史同意不代替当前确认。

## D-014：状态分为页面、产物、任务和能力

- 状态：Accepted。
- 决策：不从自由文本或下一动作推断当前状态。
- 后果：对话/UI 只转述 Card Service 的结构化快照。
- 关键区分：草稿、APKG、已导入、已核验。

## D-015：长任务检查点恢复，不承诺后台常驻

- 状态：Accepted。
- V1：宿主退出后进程可能停止；下次标 interrupted 并恢复安全工作单元。
- 不承诺：在模型响应或媒体编码字节中间续跑。
- DEFERRED：守护进程/托盘服务。

## D-016：公共 MCP 不暴露 WorkerCommand

- 状态：Accepted。
- 决策：工具对应用户意图，内部命令由 Service 适配。
- 禁止：run_worker、repair_env、raw model、raw AnkiConnect。
- 理由：Agent 调用方不可信，通用执行器破坏最小权限。

## D-017：Windows-first

- 状态：Accepted。
- 理由：当前 Tauri、Anki、凭据和跨磁盘修复均已在 Windows 投资。
- 后果：V1 明确声明 Windows；其他平台按真实验证后开放。

## D-018：Git/个人 Marketplace 先于公共目录

- 状态：Accepted。
- 理由：首版面向高级用户，本地 stdio 最符合隐私和执行需求。
- 公共目录：需要生产 MCP、域名/法务/测试，后续单独设计。

## D-019：冻结 Web Helper 的“Universal UI”定位

- 状态：Accepted。
- 决策：docs/web helper 保留为历史设计资料；file ref、job、回环安全等概念吸收进 Card Service。
- 禁止：同时发展独立 Helper Runtime，造成两套状态/安全实现。
- 复议：需要独立浏览器产品且共享 Runtime 已成熟。

## D-020：版本轴分离

- 状态：Accepted；CURRENT Worker/APKG M0 子项已实现，插件协议部分仍为 PROPOSED。
- 分开 plugin、MCP、Study IR、Service、Worker protocol、template family、template schema、Anki Note Model。
- 理由：历史 immersive_v11 family、V14 schema 与 V1 `startswith` verifier 的 fail-open 暴露了版本轴混用。
- 当前证据：生产 V14 与明确兼容的 V10 由精确合同注册表驱动；完整 APKG 合同覆盖 10 个生产生成变体，导出只在唯一 `.partial` 校验通过后 no-replace 原子发布。最终回归为 Vitest 830、正式 `pytest` 561、独立 `unittest discover` 551（有重叠，不相加）、Rust 31 项通过与 1 项忽略、UI smoke 3、V14/V10 release smoke、`check:full` 与 Tauri build 通过。20 卡离线媒体包为 20/20/52、每卡 6 引用与 120 个归属；隔离 Anki 数据级验证覆盖 E→C 单卡 1/1/6 和 20 卡 20/20/52 的首次导入、重复跳过及重启哈希。
- 信任边界：raw `ExportResult` 只作为内部兼容输入，不认证来源，不能抵抗同时篡改 APKG 与结果的同权限本机攻击者；stat/SHA 与 no-replace 发布只缩小 TOCTOU。M2 必须用认证 Artifact 注册表、不透明引用和受控文件句柄替代。
- 安全边界：非 NFC、`CLOCK$` 等 Windows 保留设备名、大小写/规范化冲突和 APKG archive 资源上限已通过；有界流式读取只覆盖 APKG archive/package/verifier。AnkiConnect 整文件/base64 媒体恢复仍有最多 256 MiB 单文件的峰值内存放大。
- 剩余出口：Computer Use 当前不可用，真实 GUI 翻面、播放和至少 20 张连续复习尚未完成；M1 以后继续为 plugin/MCP/Service/Study IR 建立各自版本轴。合成视频和静音 TTS 的数据级结果不得写成语义、听感或学习体验通过。

## D-021：用户编辑是语义操作

- 状态：Accepted。
- 决策：lock/exclude/split/merge/change_route 等，而非任意 JSON Patch。
- 理由：可审计、可失效下游、可做并发合并。
- 后果：用户锁定优先于 Agent 重算。

## D-022：Agent-generated, learner owned

- 状态：Accepted 作为产品原则。
- 决策：Agent 发现、排序和生成；学习者拥有目标、组合和最终编辑。
- EXPERIMENT：首次复习前的主动尝试、自动组合和个性化效果需要 A/B 验证。

## D-023：事实可靠性与结构可靠性分开

- 状态：Accepted。
- 决策：verified 必须列具体维度，不能把来源一致性写成现实世界真理。
- 后果：关键外部事实可要求多源/时效核验；首版不承诺通用事实查证。

## D-024：发布以证据而非功能清单为准

- 状态：Accepted。
- 决策：每个来源/路线必须有 schema、golden corpus、安全门禁和真实 Anki 报告。
- CURRENT：精确 V14/V10 合同、完整 APKG 合同、10 个生产变体、`.partial` 后 no-replace 原子发布、V1xx 伪版本负例、强制 release verifier、Anki 写入前 preflight、最终自动化、20 卡 20/20/52 离线媒体合同，以及隔离 Anki 单卡与 20 卡数据级导入/重复/重启证据已实现。Computer Use、真实 GUI 播放与连续复习、AnkiConnect base64 内存改造、M1/M2/M3 与宿主证据仍是发布阻断。

## D-025：能力验证按精确 profile 决策

- 状态：Accepted。
- 决策：model/TTS/AnkiConnect 只有 (capability, profileRef, configurationFingerprint, credentialRevision) 的最新验证记录可驱动 gate；聚合状态只展示。
- 后果：最新失败覆盖旧成功，其他 profile 不能代替当前选择；凭据每次改变都 bump revision。

## D-026：Worker 不直接持有模型/TTS 凭据或公网

- 状态：Accepted。
- 决策：所有上游调用经 Card Service model/TTS broker，以结构化、task/work-unit 绑定的 BrokerModelRequest/BrokerTtsRequest、逐目标 DisclosureEntry、权威文本 locator 和原子 reserve/sent/settle 账本执行。
- 后果：需要 broker metering/retry 审计，但消除 raw HTTP、秘密和预算绕过路径。

## D-027：敏感 URL 只走受信输入表面

- 状态：Accepted。
- 决策：所有 raw URL 都只在 trusted_entry 受信本地表面录入；公共 MCP 不接收 url/origin/query，也不保留 public_url 旁路。
- 后果：MCP、模型、Artifact、日志与 helper 参数都不能含 raw sensitive URL；粘贴到对话的 URL 视为可能泄露并建议轮换。

## D-028：Anki 数据核验与运行时核验分层

- 状态：Accepted。
- 决策：AnkiConnect 最多产生 data_verified/anki_data_verified；运行时明确失败形成 runtime_failed 且保持 anki_data_verified；anki_verified 必须由 ImportPlan 绑定、只读隔离的版本化 trusted add-on 或 GUI protocol 提供真实渲染、播放与重启复习证据。
- 后果：没有 runtime verifier 时产品仍可诚实交付数据已核验牌组，但不能宣称完整用户体验通过。

## 待决事项

以下到对应里程碑再定，不阻塞当前设计：

1. 插件最终名称和仓库目录。
2. 开源许可证。
3. 生产隐私/条款/支持 URL。
4. 受管 Python/FFmpeg 的具体打包方案。
5. 公共目录是否值得引入托管控制面。
6. macOS/Linux 时间表。
7. Anki 复习历史读取的最小权限和隐私策略。
8. ReviewDebtEstimate 初始校准参数。
