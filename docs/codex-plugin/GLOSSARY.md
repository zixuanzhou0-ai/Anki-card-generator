# 术语表

> 日期：2026-07-16  
> 除明确标注 CURRENT 外，本表术语均为 PROPOSED。
> 这些定义是本目录的规范语义。

## A

### Anki data verified

RequiredAnkiCheckManifest 中全部数据检查均恰好一次通过，证明目标 deck、note、card、字段、模板和媒体数据完整；不证明界面实际渲染、播放或重启复习。

### Anki runtime verifier

受信、版本化的 Anki add-on 或 GUI protocol，按 ImportPlan 绑定的实现/兼容合同/producer trust/protocol 和只读隔离策略，实际执行正背面渲染、翻面、滚动、缩放、媒体播放与隔离重启复习。它不得评分、写调度/复习历史、触发同步或关闭用户已有 Anki。普通 AnkiConnect 查询不属于 runtime verifier。

### Anki runtime evidence

运行时核验的不可变 Artifact，绑定精确验签公钥版本的 anti-rollback trust set、无环 signed run、权威 identity/media、Service-derived expectations、verifier-signed typed proofs、signed run-owned process lifecycle ledger/add-on focus actions、三传感器跨进程写审计、对称 typed focus/process/window、真实 isolated-Anki 重启、Typed FinalRuntimeEvidenceInputsManifest 及 barrier-bound final 11-check aggregate。

### Anki verification contract

把特定 verificationContractVersion 唯一映射到不可删减的数据/运行时检查、媒体角色映射、抽样模式、证据版本和隔离证据版本的不可变 Artifact。V1 固定 11 个数据检查、10 个运行时检查和 20 张 sample；RequiredAnkiCheckManifest 必须逐项相等。

### Anki recovery decision

Anki 写边界中断后的三分支判定：not_written 以新 session intent 重新确认；written_identity_matched 只做 verification-only successor；write_boundary_ambiguous 停止并解决冲突。旧批准和已消费 import intent 不复用。

### Anki verified

不是“APKG 已生成”或“AnkiConnect 返回成功”，而是先通过 Anki data verified，再由 runtime verifier 完成 RequiredAnkiCheckManifest 规定的 sample/full checks。

### App UI

拟议的 MCP App 界面；Inline、Fullscreen、PiP 来自 ChatGPT Apps SDK，目标 Codex 宿主支持需在 M4 实测。

### AudienceBindingManifest

由受信启动链路派生的 canonical OS SID digest、host、plugin、service 和 session 绑定；audienceDigest 是其 JCS 的 SHA-256。任一实例/会话变化都会阻止批准重放。

### Artifact

可持久、版本化、有哈希和血缘的流程产物。

### ArtifactHandle

MCP 可见的不透明字符串，只用于让 Service 定位当前项目中已授权的 Artifact；它不是授权 bearer，也不允许调用方自报 schema/revision/hash。

### ArtifactEnvelope

Service 内部包裹 payload 的认证元数据：schema、版本、ID、revision、hash、parents、producer、completeness 和 issues。MCP 默认只见 ArtifactHandle。

### ArtifactStage

项目最远已取得的可靠产物阶段，不表示用户正在看的页面或任务正在做什么；anki_data_verified 与 anki_verified 是两个不同阶段。

### AuthorizationBindingManifest

一次执行对当前 audience/session/service、不可变授权记录、精确 scope 和 expected revocation epoch 的 canonical 绑定。authorization record、scope 和 bindings 均有冻结 preimage、稳定排序与重复项拒绝规则；摘要不替代原子账本复核。

## B

### BlobRef

大型文本、原始字节或媒体的内容引用；MCP 不直接返回大型 payload。

## C

### CapabilityState

固定宿主/运行时/来源能力，以及每个精确 model/TTS/AnkiConnect profile 的当前状态：not_checked、unknown、checking、ready、stale、action_required、blocked、disabled 或 optional。service aggregate 只用于展示，不能代替具体 profile gate。

### Card media role inventory

PackageArtifact 绑定的逐卡媒体权威清单；每个 CardId 恰有一条记录，并把每个 mediaRole 绑定到实际文件 SHA-256 和 media-manifest entry digest。空媒体卡也必须以空数组出现，防止漏卡或漏角色后真空通过。

### InternalAuthorizationRecord

只存在于 Card Service 内部的不可变授权声明，绑定 OS/host/plugin/service/session、intent/task、精确资源与修订、策略、profile、凭据修订、时限和最大使用次数；消费/撤销状态存于原子账本。它不进入 MCP 或模型上下文。

### CardPlan

生成 Anki 字段前的学习设计：线索、预期回答、评分点、反馈、证据、媒体和验证结果。

### Card Service

插件本地权威服务，负责权限、Study IR、任务、产物、Worker、秘密和 Anki。

### Completeness

来源处理覆盖：complete、partial_declared、unknown 或 blocked。它独立于模型置信度。

### ConflictSet

表达多个语义单元在值、范围、时间、归因或极性上的冲突。

### CURRENT

已在当前仓库代码中静态核验存在；仍不代表本次发布测试已经运行。

## D

### DEFERRED

明确延期，不能作为首版能力或验收依据。

### Discovery

从证据化语义单元建立 LearningObjective 和 LearningCandidate 的过程。

### draft_only

来源身份或证据不足，只允许生成待审核草稿，不能标记已验证。

## E

### EgressManifest

从已保存 profile 派生的出域边界，规范绑定目标 endpoint、method/content-type、redirect/proxy/DNS 策略和响应上限；其摘要变化会使旧批准失效。

### EvidenceAnchor

连接语义/目标与特定来源修订中可重放位置的证据对象。

### Evidence replay

在相同 SourceAsset revision 上按 locator 重新定位并核对 quote/hash。

### EXPERIMENT

需要真实数据验证的产品或学习假设。

## F

### fail closed

无法证明安全或可靠时停止并解释，而不是静默降低门槛。

### factual confidence

事实是否被来源/外部证据充分支持；不同于字段/媒体结构一致。

### fileResourceRef/directoryResourceRef

Card Service 生成的不透明本地资源引用，不是原始绝对路径。

## G

### Final data reverification

全部运行时 observation 结束后，在签名 read barrier 中重新执行固定 11 项 Anki 数据检查并重哈希 required media 的 Artifact。它与 barrier attestation、RuntimeEvidence 和最终 VerificationArtifact 原子提交，用于关闭 R8a 与 R8b 之间的数据/媒体 TOCTOU。

### Final runtime evidence inputs manifest

read barrier 签名前的唯一 runtime 输入聚合 preimage。它用类型固定的 cardinality、顺序、Artifact ref/digest 和 JCS SHA-256 完整列出 observations/proofs、data/profile states、两相位 audits、environment、run-owned lifecycle ledger/process launches、add-on focus actions 与 11 条 final checks；barrier、FinalReverification 和 RuntimeEvidence 必须逐字节复用，不能以模糊 aggregate 代替。

### Gate

候选或卡片必须通过的硬条件，如证据、可评分、冲突和安全。

### generation integrity

卡片字段、用户锁定和媒体生成与 CardPlan 一致。

## H

### hard_failed / hard_blocked

违反不可绕过条件，不能自动生成或导出。

### host attachment

Codex 宿主提供的附件引用。只有稳定修订/快照后才能升级为可靠 SourceAsset。

## I

### idempotencyKey

标识一次用户意图。重复调用返回同一结果或安全合并，避免重复副作用。

### importIntentId

专用于 Anki 导入的幂等意图 ID。

### Inline

Apps SDK 定义的拟议展示模式，用于紧凑状态和主动作；Codex 支持需实测。

### InputRef

宿主附件、本地文件、目录或 URL 的受控输入引用。

### Issue

结构化问题：code、severity、stage、detail、recoverability 和 action。

## L

### Learner-owned

Agent 可以生成和推荐，但学习者拥有目标、选择、锁定、暂停与最终决定。

### LearningCandidate

经过门禁、评分和关系分析的可选学习目标。

### Learning Contract

项目对学习目的、未来行为、水平、路线、预算、语言、证据和排除项的轻量约定。

### LearningObjective

对未来需要回忆或执行的行为的结构化定义；独立于来源格式和最终卡片模板。

### legacy payload

当前 LearningPoint、Project、ExportResult 等结构，在迁移初期先经递归秘密/路径净化，再由 ArtifactEnvelope 引用。

## M

### MCP

Model Context Protocol。插件通过类型化工具和 App 资源连接 Codex 与 Card Service。

### Model/TTS broker

Card Service 内唯一可解析服务 SecretRef 并出站的受控代理。Worker 只通过 task-owned IPC 发送 BrokerModelRequest/BrokerTtsRequest；请求绑定 audience、intent/authorization、profile、逐目标 DisclosureEntry、egress、预算、权威文本 locator、payload digest 和服务端幂等键。BrokerReservationLedger 以 reserved/sent/settled/possible_incurred/released_before_send 记录真实副作用边界，拒绝 raw HTTP、任意 URL/header/prompt/text 透传。

### model_relayed

只有模型上下文转述、无法证明完整来源修订的内容身份等级。

## N

### needs_review

产物被保留，但存在明确不确定或降级，默认禁用/排除，需用户或专家处理。

### Note Model

Anki 中字段和模板的模型身份。它与产品 template family、template schema 版本不同。

## O

### opaque ref

调用者不能从中推断路径/秘密的服务引用。

### AuthorizationSubject

内部授权的判别主体：项目任务、无项目的 profile 验证、项目创建前的会话资源授权或 Anki 导入。它使授权绑定真实对象，而不是为无项目操作伪造 projectId。

### DisclosureManifest

模型/TTS 出域清单，由逐条 DisclosureEntry 构成。每条将一个 capability/profile/origin/model-or-voice 目标与一个数据类别、精确 Artifact/revision/locator 和该目标独立的字节/token/TTS 上限绑在一起；全局 cap 只是附加上限，不能跨 entry 或跨 target 交换数据。

### CostBudget

远程操作的机器可验证预算：已知价格时绑定 ISO 货币、整数最小货币单位和版本化计价快照；价格未知时明确标记 unknown，并依靠调用、卡片、媒体与数据量硬上限。

### OperationRequestManifest

批准前构造的不可变操作请求，绑定 subject、服务配置、DisclosureManifest、CostBudget 与批次策略。它先产生摘要，再生成 OperationIntent；批准后 TaskInputManifest 单向绑定 intentDigest，避免循环摘要。

### OperationIntent

Card Service 为模型/TTS 数据出域、费用和批量上限冻结的不可变操作计划。operationIntentId 只定位服务端计划和批准账本，不是授权 bearer。

### OperationState

当前操作状态：idle、queued、running、cancelling、succeeded、failed、cancelled 或 interrupted。

## P

### PackageArtifact

经过包内验证、具有 SHA-256、清单和账本的 APKG 产物。

### Package card identity set

PackageArtifact 绑定的非空、排序、去重 CardId 权威集合。运行时抽样的 eligibleCardIds 和 Anki 数据核验后的实际 CardId 必须精确等于它，不能用 UI 数量或模型输出推断。

### Pre-run source state snapshot

在 signed run 形成前、同一 provisional runId/operationBoundary 内采集的目标 Anki 状态 Artifact；绑定刚通过的 R8a、collection read snapshot、CardIdentitySet 与媒体清单，但不含 runBindingDigest。它使 source/copy 能被后续 signed run 引用而不形成哈希环。
### ProfileConfigurationManifest

model、TTS 或 AnkiConnect 的非秘密 canonical 配置。endpoint 在摘要前规范化，禁止 query/userinfo/fragment；configurationFingerprint 是该判别联合的 JCS SHA-256，credentialRevision 另行绑定。

### Profile state snapshot

按版本化投影合同对完整 Anki collection 的 cards 调度字段与 revlog 历史行进行 canonical 编码、排序、计数和哈希的 Artifact。before/after snapshot 必须绑定同一操作边界、profile/collection 与受信 SQLite read snapshot；零写入还需独立 write-audit trace。



### PiP

Apps SDK 定义的拟议 Picture-in-Picture 展示模式；适合持续任务监控，Codex 支持需实测。

### PortfolioSelection

在预算内兼顾目标/路线/来源覆盖、重复和复习债务的候选组合。

### PracticeTask

需要开放操作或多步骤反馈、比简单 Anki 问答更合适的练习任务。

### ProductStep

用户正在浏览的产品步骤，不表示产物或任务状态。

### PROPOSED

设计契约，尚未实现。

## R

### RequestParameterPolicyManifest

模型或 TTS profile 允许发出的非秘密请求参数合同，只允许 fixed、enum 和 range 规则，未知参数一律拒绝。规则和值有固定规范化、排序、去重与 JCS SHA-256 preimage；其摘要进入 ProfileConfigurationManifest，因此采样参数、温度、输出限制等策略变化会使旧验证和批准失效。

### Runtime proof authentication

Runtime Verifier 对 proof facts 的 domain-separated Ed25519 签名，绑定当前 run、launch-attested verifier process、producer key/epoch，以及 root-signed snapshot 中该精确 `(keyId,keyEpoch)` 的 raw publicKeyRef/SHA-256。Card Service 从签名/认证通道派生 producer，并独立执行 pass predicate；payload 自报身份或 passed 无效。
### Runtime expected observation set

由固定 Anki verification contract、权威 CardIdentitySet、确定性样本和逐卡媒体 inventory 生成的唯一 phase/scope/checkId/cardId/mediaRole tuple 集。Verifier records 必须与其一一相等，不能多、少、重复或省略归属。

### Runtime observation evidence

每个运行时 tuple 独立引用的受认证 Artifact；把 observation、结果、时间、profile/collection、verifier binding 与 render、interaction、playback 或 restart continuity proof 绑定。其 JCS digest、BlobRef 和权威媒体文件 SHA-256 都必须可重算。

### Runtime verification run binding

Card Service 在任何 R8b 动作前签署的一次性信任根；把 task/input/audience/service、ImportPlan、required checks、期望 tuple/渲染、目标与隔离身份、source/trusted copy、verifier/isolation policy 绑定到随机 runId 和 operationBoundary。所有运行时子证据必须复用它，不能跨 run、plan 或 profile 拼接。

### Run-owned process lifecycle ledger

由 Card Service 签名的 append-only 运行进程历史：包含 signed run 中的 Service 主进程、同一 no-breakaway OS Job Object 内曾加入的全部 child/proxy、runtime verifier 与 isolated Anki，以及每个 join/exit 事件和独立 cutoff-active 子集。focus 按事件时 joined-not-exited 区间归因；重启前已退出进程仍保留历史身份。漏成员、额外代理、事件断序或 launch/job 证据不完整时运行时核验不可用。

### ReferenceNote

用于背景、详细材料或不适合提取练习的信息，不作为评分卡。

### ReliabilityManifest

所选学习目标与生成卡片逐项对账、阻塞导出的可靠性清单。

### Review debt

新增卡片在未来产生的理解、作答和复习时间成本。

### revision

项目或产物的单调版本。写操作使用 expectedRevision 防止覆盖并发修改。

## S

### scoreability

是否能定义并应用明确评分边界。

### SemanticUnit

来源表达的语言形式或知识主张；它描述“素材说了什么”，不等于“用户该学什么”。

### Skill

Codex 的 Agent 行为说明，负责意图、询问、工具编排和解释，不负责本地权限和可靠性算法。

### SourceAsset

具有来源身份、修订、表示、完整性、来源链和支持级别的正式素材产物。

### SourceLocator

文本 span、PDF 页/区域、字幕时间、HTML selector、表格单元格、代码行等可重放位置。

### Study IR

素材到学习目标、候选和 CardPlan 的通用中间表示。

### StudyTask

项目级长任务，包含工作单元、输入/输出 Artifact 和恢复语义；可映射到当前 Worker task。

## T

### Trust revocation snapshot

由发布物内不可变绑定 root keyId/epoch/raw-public-key/SHA-256 的 pinned trust anchor 签名、带严格单调 sequence/previous digest 链的完整 append-only key-family/version tombstone history；每个 `(keyId,keyEpoch)` 永久绑定唯一 32-byte Ed25519 publicKeyRef 与 SHA-256，撤销/禁用不可逆，公钥 hash 不得跨 keyId/epoch 复用。Card Service 为每个 authority 保存不可降低的本机 anti-rollback floor；prepare、run start 与 final commit 必须使用当前最高序列并精确解析公钥，旧 snapshot、同名换钥或旧私钥自报新 epoch 都不能复活。

### Trusted add-on focus action attestation

trusted add-on 在既有用户 Anki 进程内执行 raise/activate/set-foreground 前生成的逐动作签名，绑定 run/boundary、host process、连续 action sequence 与 from/to window。它使插件动作和用户自己的 Anki 操作可区分；无法可靠归因时必须标记 runtime verifier unavailable。

### Trusted copier attestation

受信复制器对 source snapshot、隔离 profile/collection identity、复制后 collection/media 摘要和 isolation policy 形成的签名 Artifact。它与 isolated-copy manifest 共同建立 copy lineage；producer key、subject 或 digest 不匹配时不得进行重启核验。
### ServiceProfileVerificationRecord

某个精确 capability/profileRef/configurationFingerprint/credentialRevision 的版本化验证记录。sequence 最大者是当前真相，最新 failed 覆盖旧 passed；其他 profile 或聚合 ready 不能解锁它。

### StableCapabilityBinding

任务实际依赖能力的稳定投影：fixed 分支绑定 CapabilityId/实现/兼容版本，service_profile 分支绑定 capability/profileRef/configurationFingerprint/credentialRevision；排除 checkedAt、snapshotRevision、暂态状态和人类错误文本，用于恢复时做兼容判断。

### SuccessorTaskRebase

旧任务因会话/授权失效不能原地继续时，由新 taskId 记录的安全继任关系。它绑定同一 WorkReuseDigest、复用工作单元结果和旧/新授权审计；旧授权不转移。

### TaskInputManifestDigest

TaskInputManifestV1 经 JCS 后的 SHA-256，描述一次具体执行实例，绑定语义输入、组件/规则/模板、profile、credentialRevision、当前授权/egress、成本/批量和可选 successor rebase；新会话授权会产生新摘要。

### WorkReuseDigest

与执行授权分离的语义工作单元摘要。project_task 绑定来源、Artifact/CardPlan、组件、profile configuration 与生成/分区策略，但排除 session/service authorization、user gesture、credentialRevision 和检查时间；profile_validation 是例外，credentialRevision 属于被验证输入，必须进入摘要。只在语义完全相同且新授权范围等价或更窄时允许 successor 复用已完成工作。

### StudyTaskSnapshot

任务权威快照，包括状态、输入指纹、阶段/总体进度、结果引用和错误。WorkflowSnapshot.currentTaskId 指向活动任务或尚未被后续写动作取代的最近终态任务。

### template family

产品层卡片家族名，例如 immersive_v11。

### template schema

某卡片家族的当前字段/模板实现版本，例如 V15。

### Tier A/B/C

素材可靠支持分级：自动可靠、有条件、阻塞/参考。

## U

### user lock

学习者锁定字段，Agent 重算不能静默覆盖。

## V

### VerificationArtifact

某个核验阶段的结构化结果。Anki VerificationArtifact 使用 not_imported/conflict/imported_unverified/data_verified/runtime_failed/fully_verified 判别状态；runtime_failed 明确表示数据完整但运行时体验失败，ArtifactStage 仍是 anki_data_verified。各分支不能由独立布尔值拼出矛盾组合。

### VerificationCertificate

汇总来源、目标、CardPlan、APKG 和 Anki 各层证据与已知限制的签名/哈希审计产物。

### verified

只表示明确列出的可靠性维度通过。不能脱离上下文等同于“事实绝对正确”或“学习者已掌握”。

## W

### Write audit（cross-process）

Anki runtime 核验的三传感器零写证明：add-on 覆盖自身所有 SQLite connections，Card Service 以受信 storage journal 覆盖 collection DB/WAL/SHM 和 media tree。每个 sensor 有签名 coverage、稳定资源身份/cursor，gap/overflow/reset 必须为 0；connection-local hook 不能单独验收。
### Work Rail

插件权威控制台组件，展示任务、候选、风险、交付和恢复。它不等于一个固定宿主位置。

### WorkRailViewModel

与宿主形态无关的 UI 状态模型，可映射到 Inline、PiP、Fullscreen 及未来侧栏。
