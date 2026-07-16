# 设计评审记录

> 状态：CURRENT 文档评审记录；不表示插件已经实现  
> 日期：2026-07-16  
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
- V14 与发布 verifier 的精确兼容合同是必须先处理的 M0 阻断；最终本地审计进一步确认当前 V1 + startswith 判定会同时接受 V14 和 V199，属于 fail-open。

## 4. 关键分歧与裁决

Gemini 的结论是 `implementation-ready-after-m0`，置信度 0.90：设计在解决 V14 发布阻断后即可进入 M1。

Hermes 本地封装席的结论是 `needs-contract-hardening`，置信度 0.74：方向正确，但还应在开工前冻结少量机器合同。

主持裁决采用更保守的后者，但不扩大产品范围。外部顾问的七项核心意见处理如下：

| 意见 | 文档处理 | 代码状态 |
|---|---|---|
| verifier 精确接受 V14、拒绝 V1xx 伪版本 | 已列为 M0 P0 和 release gate | 未修改；本轮禁止改代码 |
| M3 tools-only 工具合同 | 已冻结 37 个工具、schema、注解、错误、幂等和任务语义（新增版本化 study.update_learning_contract） | 待实现 |
| 目标 Codex 宿主/stdio 预检 | 已加入 host capability、M3 阻断与 APKG-only 降级 | 待实测 |
| Anki 确认不可旁路 | 已改为 ImportPlan → 模型外批准 → importIntentId | 待实现 |
| 学习硬门禁可机器审计 | 已加入 GateEvaluationSet、规则版本、revision 与 stale 语义 | 待实现 |
| Artifact 防篡改与 stale | 已加入 canonical preimage、认证注册表、EntityRef 与攻击测试 | 待实现 |
| M3 来源范围冻结 | 已固定本地视频/字幕与安全公开视频 URL；其他来源后移 | 待实现 |

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

最终核心架构席与安全红队分别对当前磁盘做了只读复审，结论均为 **PASS（未发现设计文档层面的 P0/P1）**。这个 PASS 只表示文档合同在已审攻击路径下闭合，不表示 runtime verifier、插件或 Anki 隔离核验已经实现，也不解除下一节的真实代码与设备测试门槛。

顾问评审后进行的仓库核对也把 V14 问题从“未显式列入允许版本”修正为更准确的“V1 宽前缀 fail-open”：当前 verifier 会同时接受合法 V14 和伪造 V199。外部顾问结论只用于设计反证，代码事实以本地逐行核验与真实测试为准。
## 5. 仍未消除的不确定性

- M0 的 verifier fail-open 仍真实存在；文档不能替代精确版本判定、V14 正例与 V13/V15/V199/近似前缀负例 APKG smoke。
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
4. verifier 的 V1 宽前缀 fail-open 被明确保留为未解决 P0，不能把当前导出链写成 production-ready。

进入 M3 之前还必须完成：

1. verifier 精确版本合同修复、V14 正例与 V1xx 伪版本负例发布 smoke。
2. 目标 Codex 宿主 manifest/stdio/tool registration spike。
3. Audience/InternalAuthorization/Disclosure/ProfileConfiguration/Egress、Artifact/Task/Gate、逐 profile verification、BrokerRequest/ReservationLedger，以及 AnkiVerificationContract/CardIdentitySet/MediaInventory、TrustRevocationSnapshotHistory、RuntimeVerificationRunBinding/ProofAuthentication、ObservationEvidence/ProfileState、三传感器 WriteAudit、RunOwnedProcessLifecycleLedger/TrustedAddonFocusAction、FinalRuntimeEvidenceInputsManifest/ReadBarrier、Environment/TrustedCopy/RequiredChecks/RuntimeEvidence/ImportPlan/Recovery 合同测试。
4. Windows 真实 helper 沙箱、普通/敏感 URL 的 MCP 零进入 canary、secret canary 与 model/TTS broker 跨目标/文本替换/预算绕过测试。
5. tools-only 完成 1 张与 20 张 Anki 数据核验，并由版本化隔离 runtime verifier 证明固定检查集、权威 CardId/媒体文件、每条渲染/交互/播放/重启 Evidence Artifact、canonical 调度/历史快照、write audit、受信 copy lineage 与用户进程/窗口零干扰。

## 7. 评审证据边界

顾问输出是设计意见，不是外部事实来源。官方能力事实仍以 OpenAI 官方文档为准；当前实现事实仍以仓库代码和真实测试为准。模型提出但无法映射到既有证据、合同或验收门禁的建议没有进入规范。
