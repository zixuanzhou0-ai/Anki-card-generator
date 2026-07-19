# 设计评审记录

> 状态：CURRENT 文档评审记录；不表示插件已经实现
> 日期：2026-07-17
> 范围：`docs/codex-plugin/` 的产品、学习、架构、安全、工具、交付与路线图契约

## 1. 评审目标

本轮只回答三个问题：

1. 设计是否足够聚焦，可以进入 M0/M1，而不是继续无边界发散。
2. 学习点筛选、卡片可靠性和 Anki 写入是否有可机器验证的合同。
3. 是否把 ChatGPT Apps、Codex 宿主或模型意见误写成已经验证的产品事实。

评审不修改产品代码，不把模型共识当作事实证据，也不解除真实测试门槛。

## 2. 评审席与独立性

| 评审席 | 实际能力 | 重点 | 结果 |
|---|---|---|---|
| Codex 主持 | 本地仓库与官方 OpenAI 文档核对 | 范围、事实、跨文档一致性 | 完成 |
| 打包/分发评审 | 独立子代理 | manifest、MCP/App 边界、分发 | 完成 |
| 核心能力评审 | 独立子代理 | Worker、Study IR、任务、迁移 | 完成 |
| 安全红队 | 独立子代理 | bearer、注入、路径、Anki、供应链 | 完成 |
| Gemini 顾问 | `gemini-3.1-pro-preview`，Vertex AI | 产品/学习/架构反证 | 完成 |
| Hermes 本地封装顾问 | `xai-oauth / grok-4.5` 后端 | 安全与实现前合同反证 | 完成 |

Hermes 本地封装向 Grok 4.5 后端的本次请求实际发送 `xhigh`，服务返回 `priority` tier；工具数为 0，`store=false`，会话持久化关闭。Grok MCP 直连因该连接器额度上限不可用，因此不计为额外独立席，也不冒充检索成功。Gemini Search 与 Gemini 顾问同属 Google/Vertex 故障域；Hermes 封装与 Grok 后端同属 xAI 故障域。

发送给外部顾问的是约 7.4 KiB 的脱敏设计摘要、官方能力事实与静态审计结论；不含密钥、个人数据、绝对路径或完整项目文件。用户已明确允许该跨供应商设计评审。

## 3. 共识

所有评审席一致认为：

- 核心方向无需推倒重来。
- M3 应保持 Skill + 本地 stdio MCP + Card Service 的 tools-only 语言视频闭环。
- App UI 必须是 M4 条件适配，不能把 ChatGPT Apps 展示模式外推为所有 Codex 宿主能力。
- 卡片应是一个可重复、可评分的提取事件；学习点必须先过证据、可评分、冲突与安全门禁。
- 高影响授权和 Anki 批准不能成为模型可见 bearer。
- V14 与发布 verifier 的精确兼容合同在评审时是必须先处理的 M0 阻断；当时本地审计确认 V1 + `startswith` 判定会同时接受 V14 和 V199，属于 fail-open。

## 4. 关键分歧与裁决

Gemini 的结论是 `implementation-ready-after-m0`，置信度 0.90：设计在解决 V14 发布阻断后即可进入 M1。

Hermes 本地封装席的结论是 `needs-contract-hardening`，置信度 0.74：方向正确，但还应在开工前冻结少量机器合同。

主持裁决采用更保守的后者，但不扩大产品范围。外部顾问的七项核心意见处理如下：

| 意见 | 文档处理 | 代码状态 |
|---|---|---|
| verifier 精确接受 V14、拒绝 V1xx 伪版本 | 已列为 M0 P0 和 release gate | CURRENT M0 子项已实现；完整里程碑仍在验收 |
| M3 tools-only 工具合同 | 已冻结 37 个工具、schema、注解、错误、幂等和任务语义（新增版本化 study.update_learning_contract） | 待实现 |
| 目标 Codex 宿主/stdio 预检 | 已加入 host capability、M3 阻断与 APKG-only 降级 | 待实测 |
| Anki 确认不可旁路 | 已改为 ImportPlan → 模型外批准 → importIntentId | 待实现 |
| 学习硬门禁可机器审计 | 已加入 GateEvaluationSet、规则版本、revision 与 stale 语义 | CURRENT `candidate-gates-language-v1` 内核、认证 CandidateProposal → GateEvaluation → Discovery 图、角色/schema 分离的提案-复核引擎、冻结模型/授权/成本身份的内部可恢复任务与原子项目提交、任务级 Service Broker/授权摘要派生、公共 list/detail/evidence 投影与认证 coverage-first SelectionArtifact；异步公共 discovery、候选编辑、逐角色检查点与 benchmark 待实现 |
| Artifact 防篡改与 stale | 已加入 canonical preimage、认证注册表、EntityRef 与攻击测试 | CURRENT Registry、证据回放和候选单向图子项；完整跨 Registry 事务与全部领域 Artifact 待实现 |
| M3 来源范围冻结 | 已固定本地视频/字幕与安全公开视频 URL；其他来源后移 | 待实现 |

### 4.1 CURRENT M0 实施更新（2026-07-17）

评审时记录的 V1 宽前缀 P0 已关闭：生产 V15、冻结 V14 与明确兼容的 V10 使用精确 Note Model 合同，release smoke 强制调用 verifier，伪版本/篡改合同测试必须失败。完整 APKG 合同现在验证 ZIP/JSON 唯一性与限额、模型/牌组/note/card、CardId/纯内容 SHA、媒体账本和安全 HTML；10 个生产生成变体都以真实导出产物通过。导出只在唯一 `.partial` 通过整包校验后以 no-replace 语义原子发布最终 APKG；目标已存在时拒绝覆盖，失败不产生新最终包或伪 done。

生产 Anki 写路径在媒体预置前执行内部 raw `ExportResult`/payload/路径/APKG 哈希与完整包 preflight，并在媒体准备后、紧贴 `importPackage` 前再次 stat + SHA。raw `ExportResult` 不认证来源，无法抵抗能同时篡改 APKG 与结果的同权限本机攻击者；partial 后的 no-replace 原子发布和重复 rehash 只缩小、不能消除 TOCTOU。M2 必须用认证 Artifact 注册表、不透明引用和受控文件句柄取代该内部兼容信任边界。

最终自动化回归为 Vitest 830、正式 `pytest` 603、独立 `unittest discover` 576、Rust 31 项通过与 1 项按设计忽略、UI smoke 3、V15/V10 release smoke、`check:full` 和 Tauri build 通过；两套 Python 运行有重叠，不能相加。20 卡生产 V15 离线完整合同为 20 notes / 20 cards / 52 个唯一媒体，manifest、逐媒体哈希、字幕对齐与模型作用域 GUID 闭合。真实隔离 Anki 验证覆盖 E→C 单卡、V15 20 卡重复/重启和 V14/V15 同字段并存；正式 profile/牌组未触碰。此前合同不一致尝试仍作为 fail-closed 0 写入负例保留。

M0 已完成：Computer Use 已在真实 Anki 26.05 中完成翻面、焦点、滚动、四类媒体、Space/Enter 路由和 20 张连续复习；版本化快捷键 add-on 只在精确 runtime contract 下工作。插件安装、目标 Codex 宿主注册、M1 Card Service、stdio MCP 与通用 runtime verifier 仍未实现。20 卡素材是合成视频和静音 TTS，不能证明真人语义、听感或长期学习效果；非标准 AnkiConnect inline 兼容仍有不超过 8 MiB 原始媒体的整文件/Base64 放大，且 8 MiB 不是进程峰值。

顾问评审后，独立核心契约与安全红队又进行了多轮反向审查。为消除“各实现都看似合理但彼此不兼容”的空间，本目录进一步冻结：

- OperationRequestManifest → OperationIntent → TaskInputManifest 单向摘要链，以及 project_task/profile_validation/session_resource_grant 判别主体。
- AuthorizationBindingManifest 的 record/scope canonical preimage、稳定排序、重复项拒绝与 revocation epoch。
- WorkReuseDigest 与一次性执行授权分离；会话变化创建 successor task，绝不回填旧 TaskInputManifest。
- currentTaskId 与 OperationState 的终态保留/后续写动作确认不变量。
- CandidateEditOperation 与 CardPlanEditOperation 互斥，用户锁只从受信通道产生。
- fixed capability 与逐 profile verification 分层；最新失败覆盖旧成功，credentialRevision 原子单调且永不复用。
- Legacy Worker 不持有 provider secret 或公网；模型/TTS 使用正式 BrokerRequest、权威文本 locator、逐目标 DisclosureEntry 与 reserved/sent/settled/possible_incurred 账本。
- 插件摄取的所有 raw URL 统一走 trusted_entry 受信本地表面；公共 MCP 不再含 public_url/url/origin/query 参数。受信表面中新输入的 signed URL 不进入模型、helper 参数或日志；用户预先粘贴到聊天的值超出插件零进入边界，Skill 只警告轮换且不再转发。
- FFmpeg/yt-dlp 的 Windows Job Object + AppContainer/受限 SID + staging DACL + 可执行出站策略，缺失即 fail closed。
- APKG/Anki 数据完整性与真实渲染/播放/重启复习分层；新增 runtime_failed、固定检查合同、权威 CardId/媒体文件清单、逐 observation Evidence Artifact、canonical cards/revlog/write audit、process/window event manifests、受信 copier attestation、target/isolated 分相位 RuntimeEvidence、copy lineage 和写边界恢复三分支。
- 统一撤销管理器、文件/网络/Operation/Import approval 的原子撤销/消费竞态。
- M3 只要求 Skill + tools；App resources 和 Work Rail 为 M4 条件能力。

冻结终审提出的 11 个 P1 已全部落成规范：Learning Contract 更新工具；逐目标 DisclosureEntry；所有 URL trusted-entry-only；runtime_failed；verifier 版本/信任绑定；Anki 一次性批准的跨会话恢复；AudienceBinding canonical preimage；ProfileConfiguration/RequestParameterPolicy/Egress canonical manifest；正式 BrokerModel/TtsRequest；原子 reservation ledger；固定 required set、权威 CardId/媒体文件 hash、逐 observation 证据、canonical profile/process/window/copy Artifact 与精确 tuple/profile/phase/copy-lineage 绑定的只读隔离 RuntimeEvidence。

随后三轮独立机器合同复审又发现并关闭 14 个 P1：proof producer 的 domain-separated 身份认证；Service-derived 非空 render expectations；三传感器跨进程写后恢复检测；11 条 final evidence 与 barrier instance/read snapshot 绑定；root-signed revocation sequence/floor；pre-run/source/signed-run 无环 DAG；registry descriptor digest 等价；typed focus from/to/initiator；restart window owner 映射；`(keyId,keyEpoch)` 精确公钥解析；Typed FinalRuntimeEvidenceInputsManifest 的固定 cardinality/排序/JCS preimage；对称 focus predicate、Service main/child/proxy 与 add-on 动作归因；跨 snapshot append-only tombstone 与公钥 hash 全历史唯一；全运行期 process lifecycle ledger 与独立 cutoff-active subset。

最终核心架构席与安全红队分别对当前磁盘做了只读复审，结论均为 **PASS（未发现设计文档层面的 P0/P1）**。这个 PASS 只表示文档合同在已审攻击路径下闭合，不表示 runtime verifier、插件或完整 Anki GUI/学习体验核验已经实现，也不解除下一节的真实设备测试门槛。

顾问评审后进行的仓库核对也把 V14 问题从“未显式列入允许版本”修正为更准确的“V1 宽前缀 fail-open”：评审当时的 verifier 会同时接受合法 V14 和伪造 V199。该句保留为历史发现；当前实现状态以 4.1 节、本地逐行核验与真实测试为准。

### 4.2 CURRENT 候选模型边界更新（2026-07-19）

内部双角色候选发现已接入现有 Service Broker，但仍保持“模型提案、服务裁决”：proposer/reviewer 的 prompt、输入/输出 schema 和 Broker workUnitId 分离；eligibility、scores、重复判定、GateResult、用户锁与项目状态仍只由确定性 Service 代码产生。任务在冻结模型 identity 后才生成 taskId，再由 provider 为该 task 绑定 handler；身份变化、授权过期、凭据修订变化、撤销、预算不足或非严格 JSON 均失败关闭。

Service Broker 适配器只支持固定的 OpenAI-compatible、Anthropic 与 Gemini JSON 请求形状。调用方和模型都不能提交 Provider、Base URL、model、credentialRevision、OperationIntent、authorizationRecordDigest、scope、egress 或 CostBudget；Card Service 从当前可信短期 Broker 清单、可信 audience、project revision、inspectionHandle 和 candidateBudget 派生这些非秘密摘要。响应只接受一个 JSON 对象，Markdown fence、重复 key、tool block、多 choice/part、超限输入/输出均拒绝。该更新通过 51 项候选/Broker/Issuer 组合测试，正式 Python `tests` 全集为 1388 passed、1 skipped；但它尚未把公共 MCP 写成同步远程调用：必须先实现异步 start/poll/cancel/resume，才开放 `study.start_discovery`。

候选查询评审采用“先证明当前图，再投影最小信息”的边界：`study.list_candidates` 只接收 Discovery opaque handle 和闭合筛选/排序，认证 cursor 同时绑定 service instance、Discovery digest、规范化 query 与末项；`study.get_candidate` 要求 candidateHandle 属于同一最新 Discovery；`study.preview_evidence` 只从内容寻址快照重放，并在返回 quote 前再次复核 node bounds、digest 和整 node 敏感披露策略。列表/详情不会返回来源正文，预览最多返回同一 node 内 480 字符前后文；三个工具均不接受 ArtifactRef、BlobRef、路径、Provider、授权或凭据，且固定 `openWorldHint=false`。
该切片没有为了演示完整流程而同步开放远程发现。`study.start_discovery` 仍等待真正的异步 start/poll/cancel/resume。候选/Artifact/MCP 定向回归共 67 项通过，覆盖游标篡改、跨查询、跨 session、跨 Discovery、旧 Discovery、证据 digest、内部 ref/路径泄漏和纵深敏感上下文阻断；正式 Python `tests` 全集为 1402 passed、1 skipped。

选择切片随后以“用户决定组合，服务证明组合仍合法”为边界开放 `study.set_selection`。工具只能 add/remove 当前 Discovery 的精确 opaque candidate handles，或执行只纳入 recommended 的确定性 `accept_recommended`；算法优先路线/来源覆盖，并对饱和、重复形式和 review cost 扣分，拒绝将简单 Top-N 包装成个性化。所有候选在写入前再次验证 exact ArtifactRef、eligibility 和 evidence/conflict/security hard gates；needs_review 只能显式加入并留下 issue，旧 SelectionArtifact 在上游失效后不会投影。结果进入认证父图和快速幂等 StudyTask，ReviewDebt 超过用户日目标只告警，不擅自删除用户选择。该工具固定 `openWorldHint=false`，不触发模型、TTS、网络、Anki 或 OperationIntent。选择/MCP/文档组合回归 46 项、正式 Python `tests` 全集 1416 passed、1 skipped。

CardPlan 内核评审继续坚持“不支持就阻塞，不把缺失推断伪装成卡片”。内部 `deterministic-language-card-plan-v1` 只处理三条可以直接从冻结 Objective 与 Evidence 恢复题面、核心答案和单一评分边界的路线；非英语翻译、语用/语法变形和媒体语义都返回 typed blocker。每个计划、计划集合和验证记录形成认证父图；八类检查由服务端产生，模型与调用方不能自报 pass。`needs_review`、答案泄露和验证失败保留可追溯计划但阻止进入生成；配置变化后旧幂等调用不能复活失效计划。媒体全关和空用户锁只证明当前受限切片，不可宣称媒体可用或锁定编辑已实现。该内部切片 6 项定向测试、31 项 CardPlan/文档组合回归与正式 Python `tests` 全集 1422 passed、1 skipped 通过。随后公共边界评审只开放 `study.plan_cards` 和 `study.list_card_plans`：输入删除 route/media/model/authorization/path 注入面，输出以认证 PlanSet cursor 和 learner-facing allowlist 投影；首轮 18 项安全合同、真实 stdio 清单/MCP 10 项与正式 Python `tests` 全集 1435 passed、1 skipped 通过。随后 CardPlan revision 评审开放 `study.edit_card_plan` 与 `study.validate_card_plans`，但没有把“可编辑”解释成“可绕过”。公共编辑 schema 只含 cue/answer/feedback/media 四类互斥 Agent operation，禁止调用方自报 provenance、EvidenceRef 或 UserLock；服务强制保留认证证据和锁，记录 `actor=agent`/权威 taskId，发布同 artifact identity 的新 revision，并同步重建 PlanSet 与 Validation。冻结评分边界被修改会 failed，无法由当前确定性证据证明的解释/例句为 needs_review，未接线媒体为 failed。独立重验从当前 Selection/Candidate/Plan 图重放八项检查并发布新 set/validation revision；任务在 Artifact 写完、success 或 project commit 前中断都可精确恢复，恢复比较 Artifact identity 而非每次可能变化的 opaque handle。新增 revision/runtime、恢复与 MCP 合同纳入正式 Python `tests` 全集后为 1448 passed、1 skipped；受信用户锁通道仍保持关闭。随后 CardArtifact 评审只开放一个更窄的确定性文本生成边界：`cards.generate` 不接收模型、TTS、媒体、路径、授权或调用方 ArtifactRef，重新验证当前 PlanSet 和八项门禁后发布认证 CardArtifact/ProjectArtifact 图；`cards.list` 以签名游标返回学习者投影。needs_review/failed、stale、跨 audience 和父图缺失全部失败关闭。任务提交两侧中断恢复、幂等无重复和真实 Worker APKG 兼容导出已验证。首次正式全集进一步捕获 Base64URL 非规范末位可能解码成同一签名字节的问题，修复扩展到 Card/Candidate/CardPlan 三类 cursor；最终正式 Python `tests` 全集为 1469 passed、1 skipped；这不等于公共导出、模型/媒体生成或 Anki 写入已经开放。

## 5. 仍未消除的不确定性

- M0 的 verifier fail-open 已由精确 V15/V14/V10 合同关闭；最终自动化、V15 20/20/52 离线媒体合同、E→C 单卡、V15 重复/重启、V14/V15 并存与 Computer Use 真实 GUI 20 张连续复习已有证据。合成视频和静音 TTS 仍不能提供真人语义、听感或长期学习效果证据。
- 当前内部 raw `ExportResult` 的一致性校验不等于来源认证；能同时改写 APKG 与 `ExportResult` 的同权限本机攻击者仍在信任边界内，须由 M2 认证 Artifact 注册表解决。
- 当前 stat/SHA 重算和同目录 no-replace 原子发布只缩短路径 TOCTOU 窗口，不构成不可变文件句柄证明。
- 非 NFC、Windows 保留设备名（含 `CLOCK$`）、大小写/规范化冲突和 APKG archive 资源上限已通过。流式结论只覆盖 APKG archive/package/verifier；AnkiConnect 媒体恢复仍整文件读入并 base64 编解码，存在峰值内存放大。
- 目标 Codex Desktop 版本能否稳定启动/重连本地 stdio Service，必须在 M3 开发前做最小 spike。
- MCP App resource 与目标 Codex 宿主的连接能力尚未证明；因此 M4 仍是条件里程碑。
- 版本化、只读隔离的 Anki runtime verifier/add-on 或 GUI protocol 尚未实现；只有 AnkiConnect 时最多能声明数据核验，实际运行时失败/通过状态均不能伪造。
- Windows 媒体沙箱与可执行出站隔离必须在真实发布机器证明，不能以文档或低权限 token 代替。
- 学习门禁只能证明设计一致性，不能证明 1/7/30 天学习效果；效果声明要等 M8 实验。
- macOS/Linux、复杂 PDF、OCR、图表、公式和代码证据均不属于 M3 承诺。

## 6. 进入实现的设计门槛

可以开始 M0/M1 的条件是：

1. 本目录内部链接、术语、代码围栏和状态标记通过文档校验。
2. M3/M5/M6/M7 范围不再混写。
3. 公共 MCP 不出现通用 Worker、Shell、原始路径、秘密回读、raw AnkiConnect 或授权 bearer。
4. verifier 的 V1 宽前缀 P0 已有精确合同和负例证据；在 M0 全部出口完成前仍不能把插件或真实 Anki 闭环写成 production-ready。

进入 M3 之前还必须完成：

1. [M0 已完成] verifier 精确 V15/V14/V10 合同、V15/V10 release smoke、V1xx 伪版本/篡改负例、完整 APKG 合同、10 个生产生成变体、`.partial` 后 no-replace 原子发布、生产导入前 preflight、最终自动化、V15 20/20/52 离线媒体合同、隔离真实 Anki 重复/重启/V14-V15 并存，以及 Computer Use 20 张连续复习证据。完整结果见 [M0 验证报告](M0_VERIFICATION_REPORT_2026-07-17.md)。
2. 目标 Codex 宿主 manifest/stdio/tool registration spike。
3. Audience/InternalAuthorization/Disclosure/ProfileConfiguration/Egress、Artifact/Task/Gate、逐 profile verification、BrokerRequest/ReservationLedger，以及 AnkiVerificationContract/CardIdentitySet/MediaInventory、TrustRevocationSnapshotHistory、RuntimeVerificationRunBinding/ProofAuthentication、ObservationEvidence/ProfileState、三传感器 WriteAudit、RunOwnedProcessLifecycleLedger/TrustedAddonFocusAction、FinalRuntimeEvidenceInputsManifest/ReadBarrier、Environment/TrustedCopy/RequiredChecks/RuntimeEvidence/ImportPlan/Recovery 合同测试。
4. Windows 真实 helper 沙箱、普通/敏感 URL 的 MCP 零进入 canary、secret canary 与 model/TTS broker 跨目标/文本替换/预算绕过测试。
5. tools-only 单卡 E→C 1/1/6 和 20 卡 20/20/52 的数据级导入、重复跳过与重启哈希已有 CURRENT 证据；仍须在 Computer Use 可用时完成真实 GUI 翻面、媒体实际播放和至少 20 张连续复习，并由版本化隔离 runtime verifier 证明固定检查集、权威 CardId/媒体文件、每条渲染/交互/播放/重启 Evidence Artifact、canonical 调度/历史快照、write audit、受信 copy lineage 与用户进程/窗口零干扰。

## 7. 评审证据边界

顾问输出是设计意见，不是外部事实来源。官方能力事实仍以 OpenAI 官方文档为准；当前实现事实仍以仓库代码和真实测试为准。模型提出但无法映射到既有证据、合同或验收门禁的建议没有进入规范。

### 4.3 CURRENT APKG 公共边界复审（2026-07-19）

APKG 纵向切片采用“Worker 产出不等于可信包”的结论。`cards.export_apkg` 不能接收 raw path、文件名、replace、raw Project 或 Worker 参数，只能接收当前 ProjectArtifact opaque handle 与受信 outputRef，并立即返回可轮询 StudyTask。Card Service 在发布前独立执行完整 APKG 合同、ZIP/JSON 限额、collection SQLite note/card/模板/CSS 身份、CardId/sourceCardId 映射、媒体清单与文件 SHA；随后把 APKG 字节放入内容寻址 Blob，并发布 APKG file、CardIdentitySet、PackageMediaManifest、CardMediaRoleInventory 与 PackageArtifact 的认证父图。

跨磁盘交付不移动 Worker 临时文件：Service 在用户选择的目标目录创建同盘 `.partial`，完成 flush/fsync 后用 hard-link no-replace 发布确定性版本文件；同名竞态只接受字节完全相同，否则拒绝。任务终态与项目提交有独立可见性闸门：PackageArtifact 未成为当前项目的 latest artifact 时，调用方不能看到 succeeded；Worker 已完成但项目提交中断时，精确重试只补 commit，不重新导出。项目随后进入 imported/verified 阶段时，原导出任务仍保持成功。

该切片的任务、取消、伪造 outputRef、幂等、跨磁盘式目标发布、完整包合同、无头服务、文档和 MCP 注册 83 项定向扩大回归通过；正式 Python `tests` 全集为 1480 passed、1 skipped。它只证明当前受限文本/零媒体路线的可信 APKG 交付，不等于模型/TTS/媒体路线、Anki 导入或运行时体验已经实现。下一复审对象固定为 ImportPlan、真实用户确认与 Anki 写边界恢复。