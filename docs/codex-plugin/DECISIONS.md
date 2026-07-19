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
- 当前证据：生产 V15、V14 与明确兼容的 V10 由精确合同注册表驱动；V15 使用模型作用域 GUID，历史模型 GUID 不变。最终回归为 Vitest 830、正式 `pytest` 603、独立 `unittest discover` 576（有重叠，不相加）、Rust 31 项通过与 1 项忽略、UI smoke 3、V15/V10 release smoke、`check:full` 与 Tauri build 通过。V15 20 卡离线媒体包为 20/20/52；隔离 Anki 覆盖单卡、20 卡重复/重启和 V14/V15 同字段并存，Computer Use 覆盖真实 GUI 20 张连续复习与媒体交互。
- 信任边界：raw `ExportResult` 只作为内部兼容输入，不认证来源，不能抵抗同时篡改 APKG 与结果的同权限本机攻击者；stat/SHA 与 no-replace 发布只缩小 TOCTOU。M2 必须用认证 Artifact 注册表、不透明引用和受控文件句柄替代。
- 安全边界：非 NFC、`CLOCK$` 等 Windows 保留设备名、大小写/规范化冲突和 APKG archive 资源上限已通过；有界流式读取覆盖 APKG archive/package/verifier 与标准 Windows Anki direct-first 媒体路径。非标准/portable profile 的 AnkiConnect inline 兼容路径仍整文件/Base64，但原始单文件硬限制为 8 MiB；8 MiB 不是进程峰值。
- 剩余出口：M0 已完成；M1 以后继续为 plugin/MCP/Service/Study IR 建立各自版本轴。合成视频和静音 TTS 的结果不得写成真人语义、听感或长期学习效果通过。

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
- CURRENT：精确 V15/V14/V10 合同、V15 模型作用域 GUID、完整 APKG 合同、原子发布、强制 verifier、导入前 preflight、媒体 barrier、最终自动化、V15 20/20/52 包、隔离 Anki 重复/重启/V14-V15 并存，以及 Computer Use 真实 GUI 20 张连续复习均已实现。M1/M2/M3 与 Codex 宿主证据仍是插件发布阻断。

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

## D-029：本机可信复制与兼容网络传输分层

- 状态：Accepted；CURRENT M0 已实现。
- 决策：标准 Windows Anki profile 使用 direct-first 有界流式预置，不先调用 AnkiConnect 媒体 API；只有非标准/portable profile 与非 Windows 使用 AnkiConnect inline 兼容路径，原始单文件上限为 8 MiB。
- 理由：AnkiConnect 的 `data`、`path` 和 `retrieveMediaFile` 都会整文件读入；把 `data` 改成 `path` 只会把峰值转移到 Anki 进程，并不形成流式链路。8 MiB 是兼容协议的原始媒体上限，不是进程峰值。
- 完整性：direct path 使用同一源/临时文件句柄、分块 hash/count、flush/fsync、identity 复核和 no-replace；inline path 使用有界请求/响应、写后大小/SHA 复核。两条路径都进入 ownership ledger 与最终导入 barrier。
- 兼容后果：标准 NTFS profile 支持最大 256 MiB/文件、2 GiB/批、2000 项的流式预置；非标准 profile 的更大媒体 fail closed，并提示改用标准 profile 或手动导入 APKG。
- 残余：完整 Win32 目录句柄固定、私有 ACL staging、同权限攻击者与 `importPackage(path)` 的最终路径 TOCTOU 留到 M2；兼容 inline 路径仍有小文件 Base64 放大。

## D-030：V15 以模型作用域 GUID 与最小 Anki add-on 冻结运行时行为

- 状态：Accepted；CURRENT M0 已实现并验证。
- 决策：新卡使用 V15 Note Model 和 `Note Model ID + 50 个原始字段` 计算的模型作用域 GUID；V10/V12/V14 的历史 GUID 算法与既有卡片保持不变。
- 决策：Space/Enter 媒体路由由最小 Anki add-on 提供，不把全局快捷键抢占逻辑塞入卡片 HTML；add-on 必须精确匹配 Anki point version、Note Model ID、模板摘要、角色、键位与 DOM token runtime contract，否则 fail closed。
- 理由：相同字段的 V14/V15 note 必须并存，且 Anki 26.05 的 review shortcut hook 只能由宿主扩展安全协调；仅靠卡片 JavaScript 无法可靠阻止 Anki 全局 Space 翻面竞争。
- 证据：V14/V15 同字段并存与重启 JSON 无差异；V15 重复导入不增卡；Computer Use 连续复习 20 张，表达/原声/慢读/视频的 Space/Return 暂停与继续、媒体互斥和背景 Space 翻面全部通过。
- 边界：当前 runtime contract 只声明支持 Anki 26.05；其他版本必须新增精确合同和真实 GUI 证据，不能以范围匹配静默放宽。

## D-031：外部本地服务必须做当前进程预检，端口由受控 launcher 固定

- 状态：Accepted；CURRENT 开发态已实现 Hermes 与 AnkiConnect 两条路径。
- Hermes：固定使用 `127.0.0.1:8645`、`provider=xai`、`model=grok-4.5`。受信批准后必须确认 `/health` 的 upstream 与 OAuth；未运行时由 Service 以固定参数启动。初次、异步和恢复 discovery 都重新预检，历史授权不等于当前可用。
- AnkiConnect：默认 `127.0.0.1:8765`，但 Windows 排除端口范围可能使其不可绑定；launcher 可固定其他显式 IPv4 loopback 端口。MCP、项目与任务不能提交 endpoint。
- 理由：端口属于部署环境而不是学习意图；把 8765 硬编码到导入 Worker 既不能解决 Windows 排除端口，也会把正确的跨磁盘导入错误归因于 APKG 目录。
- 失败语义：Hermes 本地健康只证明 OAuth 可解析，不证明 xAI 公网可达。真实上游失败必须作为可恢复模型故障停止，不能发布候选或卡片。Anki 离线/端口错误在任何写入前停止。
- 安全边界：只允许字面 `127.0.0.1`、显式端口、无 userinfo/query/fragment/path；禁用环境代理。该可配置端口不扩大到 LAN、自定义 hostname 或 MCP 参数。
- 证据：2026-07-20 Computer Use 已完成真实 source picker 与 Hermes 授权；8645 健康/OAuth ready 后，真实 xAI upstream 仍超时并正确停止为 `MODEL_STALE`。隔离 AnkiConnect 8785 返回 version 6；53 项定向自动化通过。详见 `M1_REAL_SERVICE_RECOVERY_VERIFICATION_2026-07-20.md`。

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
