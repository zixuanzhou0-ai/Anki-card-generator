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
| 学习硬门禁可机器审计 | 已加入 GateEvaluationSet、规则版本、revision 与 stale 语义 | 待实现 |
| Artifact 防篡改与 stale | 已加入 canonical preimage、认证注册表、EntityRef 与攻击测试 | 待实现 |
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
