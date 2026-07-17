# 可靠性与核验

> 状态：PROPOSED 可靠性合同；引用 CURRENT 内核能力
> 日期：2026-07-17
> “生成”“导出”“导入”“核验”是四个不同事实。

## 1. 可靠性的定义

可靠性不是一个布尔值。插件需要分别证明：

| 维度 | 证明什么 |
|---|---|
| source_integrity | 读取的是哪一版来源，覆盖了多少 |
| evidence_alignment | 学习目标和答案能追溯到正确证据 |
| learning_design_checks | 目标可作答、可评分且符合当前学习设计规则 |
| generation_integrity | 卡片正文、字段和用户锁定没有被错误改变 |
| media_integrity | 音视频文件存在、哈希一致、时间和语义匹配 |
| package_integrity | APKG 内 note/card/deck/media 与清单一致 |
| import_integrity | Anki 实际导入了预期对象 |
| runtime_experience | 翻面、滚动、播放和重启后复习正常 |
| factual_confidence | 事实是否由来源/外部证据充分支持 |

CURRENT 的 verified 主要覆盖结构、来源片段、媒体和导入一致性；它不能自动等同于现实世界事实正确。插件 UI 和 API 必须显示具体维度。

## 2. 可靠性阶梯

~~~text
R0 输入已授权
  ↓
R1 来源身份与完整性通过
  ↓
R2 证据与语义单元通过
  ↓
R3 学习目标与候选门禁通过
  ↓
R4 CardPlan 通过
  ↓
R5 卡片与媒体生成通过
  ↓
R6 APKG 生成与包内验证通过
  ↓
R7 用户授权导入
  ↓
R8a Anki 数据完整性核验通过
  ↓
R8b 真实渲染、播放与复习核验通过
~~~

下游不能绕过上游。每一层保存 Artifact 和版本化检查记录；R8a 与 R8b 不能折叠成一个布尔值。

## 3. R0：授权

检查：

- 当前可信连接身份与 Card Service 内部授权记录有效；MCP 不携带授权 bearer。
- audience、intent/task、来源、项目 revision、动作、策略和数量匹配。
- 网络/模型/TTS 数据域已授权。
- 高影响动作具备真实用户确认。

失败不读取或写入任何新资源。

## 4. R1：来源

检查：

- SourceAsset identity 稳定。
- 内容哈希/宿主 revision 可验证。
- 解析前后来源未变化。
- complete/partial/unknown 有明确覆盖。
- 省略项全部列出。
- Evidence locator 可重放。

失败语义：

- SOURCE_CHANGED：停止下游发布。
- SOURCE_PARTIAL：只允许带警告的候选/草稿。
- SOURCE_UNREADABLE：保留其他来源结果，不声称完整。

## 5. R2：证据和语义

语言：

- exact_span 与偏移量重新验证。
- 忽略大小写只能用于查找，不改变原文。
- 多锚点语法结构按顺序存在。
- 时间 cue 与句子/音视频范围一致。

知识：

- claim 的限定、时间、归因和极性保留。
- source_direct/source_derived/external_corroboration/pedagogical_example 明确区分。
- 支持、反证和冲突关系可见。
- 未解决冲突不合并成单一事实。

定位器可重放只证明“该片段存在于该来源修订”，不自动证明它蕴含答案、来源在现实世界为真或卡片有效促进学习。semantic support、source consistency、factual truth 和 learning effect 必须分开记录；模型自报 relation/confidence 不能独立通过。

## 6. R3：学习目标和选择

硬门禁：

- evidence。
- goal relevance。
- novelty。
- scoreability。
- card suitability。
- conflict。
- review value。
- security。

要求：

- 每张卡一个核心评分边界。
- 不值得制卡的内容转 ReferenceNote/PracticeTask。
- deterministic duplicate 为 0。
- PortfolioSelection 显示覆盖和复习债务。
- 用户排除/锁定不能被重新推荐覆盖。

## 7. R4：CardPlan

验证：

- 正面不泄露核心答案。
- 题面上下文足够。
- coreAnswer 与 scoringPoints 一致。
- acceptedVariants 不扩大到错误答案。
- 背面解释不改变评分边界。
- EvidenceAnchor 全覆盖。
- route 与用户目标一致。
- 模板和媒体策略受支持。
- 预计复习时间合理。

状态：

- pass：可生成。
- review：需要用户/专家判断，默认不自动导出。
- fail：禁止生成。

## 8. R5：生成与媒体

逐目标对账：

| 状态 | 含义 |
|---|---|
| verified | 当前生成、证据、字段和媒体门禁通过 |
| needs_review | 有明确降级或不确定，卡片保留但禁用 |
| hard_failed | 未产生有效卡或违反阻塞规则 |

规则：

- 模型输出先经过 schema 和内容验证。
- fallback 卡默认为 needs_review。
- 生成 HTML 不可信；展示标记由 Worker 安全插入。
- 原始文本、TTS 输入和审计文本保持纯文本。
- 用户锁定字段逐字段比对。
- 活动批次失败不抹掉已完成批次。

媒体检查：

- 文件存在、非空、可解码。
- SHA-256 与 ledger 一致。
- 视频切片覆盖证据时间。
- 原声、慢读、表达 TTS 与目标语义匹配。
- 媒体文件名安全且无冲突。

## 9. R6：APKG

导出前重新读取当前 ProjectArtifact，不能信任调用方传入的完整 project JSON。

检查：

- ReliabilityManifest 没有 blocker。
- enabled card 计数与 selected outcomes 对账。
- Note Model、模板、字段和 CardId 稳定。
- note/card/deck 数符合期望。
- media manifest、media ledger、card-media ledger 闭合。
- TTS 语义和音频审计通过。
- APKG SHA-256、大小和时间保存。
- partial 文件不发布。

### CURRENT：精确 Note Model 合同已实现，M0 验收仍在进行

旧 Worker 的 immersive_v11/V14 曾由 `startswith("Anki Card Generator V1")` 宽前缀意外接受，V199 等伪版本也会命中。当前 M0 工作分支已关闭这一 fail-open：

1. template family、template schema、Note Model ID 与 compatibilityContractVersion 分离并进入精确合同注册表。
2. 生产 V14 和明确支持的 V10 兼容模型按精确名称、ID、字段顺序/规格、模板、CSS 与静态模型行为摘要匹配，不再按前缀推断；生成该规范形状的 serializer 固定为 `genanki==0.13.1`。
3. 10 个生产生成变体都用真实 `handle_export` 产物执行整包合同验证，覆盖 V14、V12 与明确支持的 V10 语言/文档路径，而不是只测试手工构造 fixture。
4. 完整 APKG 包合同要求唯一且受限的 ZIP/collection/media 条目、无重复 JSON key、模型/牌组/note/card 关系闭合、CardId 与纯内容 SHA 可重算、media manifest/ledger/card-media ledger 一致，并只允许受控展示 HTML；任一结构或摘要不一致均 fail closed。
5. 导出候选先写入最终目录中的唯一 `.partial`；只有整包合同通过才以 no-replace 语义原子发布最终 APKG，目标路径已存在时拒绝覆盖。校验、发布或最终 stat/SHA 失败会删除/隔离 partial，且不能发出 100%/done。
6. 真实生成的 V14 与 V10 APKG 进入 release smoke；V13、V15、V199、近似名称、非规范 ID/整数和字段/模板/model extras/CSS 篡改进入负向合同测试。release smoke 强制调用生产 `verify_apkg.py`；验证器缺失、合同不唯一或报告失败都会阻断发布，独立 CLI 合同失败时 `ok=false` 且退出码为 1。
7. 生产 `verify_anki_import` 先执行 contract preflight：验证应用内部生成、证据完整的 raw `ExportResult`、payload 覆盖一致性、绝对 APKG/media 路径、实际 SHA-256/大小、整包卡片/牌组/模型/字段/媒体账本和相同精确合同；失败时媒体准备和 `importPackage` 均为 0 次。raw `ExportResult` 只属于内部兼容接口，并未认证来源，因而无法抵抗能同时篡改 APKG 和 `ExportResult` 的同权限本机攻击者。媒体准备后、紧贴 `importPackage` 前再次 stat + SHA 以及 partial 后的 no-replace 原子发布都只缩小、不能从原理上消除路径 TOCTOU。M2 必须以认证 Artifact 注册表、不透明句柄和受控文件句柄替代调用方可构造的 `ExportResult`；在此之前它不能作为公共 MCP 信任根。
8. 标准 Windows Anki profile 的媒体预置是 direct-first：不先调用 AnkiConnect，而是从同一已打开源句柄以 1 MiB 固定块读取并同步计数/SHA-256，写入 `mkstemp` 返回的原句柄，flush/fsync 后复核源、临时文件与目录 identity，再以 same-dir no-replace 语义发布。并发产生同内容目标时幂等成功，并发产生不同内容目标时拒绝覆盖；source、标准媒体目录或受信路径组件含 symlink/junction/reparse 时 fail closed。
9. 前端导入入口要求 full 与 compact 导出结果都通过完整证据检查，并对规范化路径、APKG 哈希/大小/mtime、牌组、模型、模板、合同、标签、卡片/片段、来源与内容指纹及核心媒体摘要做同一产物配对；任一缺失或错配返回空，不再回退到陈旧摘要。
10. 最终自动化回归通过 Vitest 830、正式 `pytest` 581、独立 `unittest discover` 571、Rust 31 项通过与 1 项按设计忽略、UI smoke 3、V14/V10 release smoke、`npm run check:full` 和 `npm run tauri:build`。`pytest` 与 `unittest` 有重叠，不能相加为独立测试总数。
11. 20 卡生产 V14 离线 APKG 通过完整合同：20 notes / 20 cards / 52 个唯一媒体，每卡 6 个引用、共 120 个媒体归属；manifest/ledger 为 52，20/20 字幕对齐且包问题为 0。素材是合成视频与静音 TTS，不是语义、听感或复习证据。
12. 隔离真实 Anki 已完成 E→C 单卡跨盘数据级核验：1 note / 1 card / 6 media；6/6 通过 `direct-first / trusted_atomic_copy` 预置，逐文件大小和 SHA-256 一致，missing/mismatch/inaccessible 为 0，`retrieveMediaFile`/`storeMediaFile` 为 0 次；重复导入跳过且 `duplicates=0`，真实重启后再次通过计数与哈希复核。
13. 同一 20 卡包完成隔离 Anki 数据级核验：首次导入 20 notes / 20 cards / 52 media；52/52 通过 `direct-first / trusted_atomic_copy` 预置，52 个媒体哈希和 120 个 card-media ownership bindings 闭合，媒体传输 API 为 0 次；重复导入跳过且 `duplicates=0`，真实重启后仍为 20/20/52。正式 profile/牌组未触碰，隔离进程已关闭。它不证明 GUI 翻面、播放或连续复习。
14. 非 NFC、Windows 保留设备名（含 `CLOCK$`）、大小写/规范化冲突与 APKG archive 资源上限已经通过。APKG archive/package/verifier 与标准 Windows Anki direct path 均使用有界流式读取；64 MiB direct 样本在禁用整文件读取、Base64 和 AnkiConnect 媒体动作时通过，Python `tracemalloc` 峰值增量低于 32 MiB。
15. 非标准/portable profile 与非 Windows 只保留不超过 8 MiB 原始媒体的 AnkiConnect inline 兼容路径；8 MiB+1 在任何媒体 API 前失败。8 MiB 不是进程峰值，该路径仍会整文件 Base64；retrieve/store/普通 action 和健康检查的响应分别受限。
16. 多文件部分写入用 ownership ledger 区分 created/already-present/failed，并保留 timeout 未知结果、可能孤儿、可能残留与清理错误。媒体准备后和紧贴 `importPackage` 前的最终 barrier 都要求全部 manifest 大小/SHA 闭合、目录 identity 不变且零 recovery failure；导入后补救失败也不能返回 `ok=true`。
17. 在合同未对齐的先前真实尝试中，preflight/final gate fail closed，隔离目标保持 0 note / 0 card / 0 media，证明失败没有产生半写入。

这里的“已实现”只指当前 Worker/APKG、标准 Windows Anki direct-first 媒体路径与隔离 Anki 数据级基线，且 `genanki` 固定不等于全部依赖已做版本+哈希供应链锁定。M0 仍需 Computer Use 桌面视觉/交互验收、真实 GUI 翻面与媒体播放，以及至少 20 张连续复习；当前执行环境没有 Computer Use。独立 runtime verifier、Card Service、MCP、插件安装、raw `ExportResult` 的 M2 认证替代、完整 Win32 目录句柄/私有 staging 与非标准 profile 的全流式兼容均不属于当前完成项，因此 M0 状态仍为进行中。详见 [M0 验证报告](M0_VERIFICATION_REPORT_2026-07-17.md)。

## 10. R7：导入授权

anki.prepare_import 先生成不可变 ImportPlan。用户确认页面显示：

- 项目、PackageArtifact、APKG 哈希与大小。
- 精确 Anki profile/collection 和目标牌组。
- note/card/media 数。
- V1 固定 duplicate policy。
- Note Model、front/back/CSS/JS 与媒体 manifest 哈希。
- RequiredAnkiCheckManifest 的数据/运行时检查、确定性采样策略、RuntimeVerifierBinding（实现/兼容合同/producer trust/protocol）与 RuntimeVerifierIsolationPolicy。
- 媒体预置、失败恢复和手动回退影响。

真实用户确认只写入 Card Service 当前会话的内部 approval ledger，不向 MCP 返回 token/ref。anki.import_and_verify 仅以 importIntentId 定位并原子消费已批准计划，执行前重算全部哈希、文件身份、AnkiConnect key/版本、profile identity、runtime verifier binding 与隔离策略。崩溃恢复不会复用已消费批准：确定未写入时派生新 session 的 recovery intent 并重新确认；已写入且身份匹配时只做 verification-only successor；写边界不明时停在 conflict/interrupted。

## 11. R8：Anki 数据与运行时分层核验

R8a 数据完整性由 AnkiConnect/包复核证明：

- APKG 是否已导入、重复或冲突。
- 目标 deck 存在。
- note/card 数量。
- CardId 和 note 内容指纹。
- Note Model、模板和字段。
- media 名称、大小、SHA-256 与各媒体角色文件证据。

AnkiVerificationContractV1 把 anki-data-runtime-v1 精确冻结为 11 个 data checks、10 个 runtime checks、四个媒体角色映射、normal/narrow 双视口、sample/full 模式、20 张样本下限及全部子证据版本；RequiredAnkiCheckManifest 不得删减。PackageCardIdentitySet、PackageMediaManifest 与 CardMediaRoleInventory 逐卡绑定媒体角色、文件 SHA-256 和 manifest entry。R8a 必须证明导入后的 CardId、note/deck/model/template/字段与 required media live re-hash 等于权威 Artifact，且每个 required data check 恰好一次 passed；空集、子集、未知、重复、遗漏、producer 不受信或合同版本不匹配都 fail closed。只有 R8a 全部通过才设置 ArtifactStage=anki_data_verified。

R8b 运行时体验必须由 ImportPlan 绑定的版本化 trusted Anki add-on 或 GUI protocol 产生 AnkiRuntimeEvidenceArtifact：

- 对 deterministic sample 的正面、背面、翻面、长文本、滚动和 960×720 / 600×720 窗口缩放；每个正反面 proof 同时包含两个视口的 typed render tree 与 PNG。
- 对样本中每张卡实际存在的原声、慢读、表达 TTS 与视频角色逐一播放，并证明事件顺序、时间推进和解析后的媒体 SHA-256。
- 在受信复制的隔离 profile 中真实重启 helper 与 isolated Anki 两类进程，并在新 Anki 实例中重新打开同卡继续复习；不能把“只重启 verifier”冒充 Anki 重启。
- 记录每个 required check/card/media role 的 typed proof、时间和 producer trust；proof facts 由 launch-attested verifier process 使用当前 producer key/epoch 做 domain-separated 签名，Card Service 验签后根据固定 predicate 重算 passed/failed，不采信 payload 自报身份或布尔值。
- 证明 entire-collection scheduling/review history 前后 digest 相等，八类数据库/媒体写入计数全为 0；不得关闭、抢焦点或重启用户已有 Anki。

RequiredAnkiCheckManifest 必须让 eligible CardId 精确等于权威 CardIdentitySet，sample 固定取全部或最多 20 张，并把每个 selected CardId 的权威媒体 binding 投影为唯一 phase/scope/checkId/cardId/mediaRole tuple 集。CardRenderExpectation 由 Service 从 CardPlan、字段投影和模板确定性派生；正面至少 root+非空 cue/content，背面至少 root+非空 answer/content，禁止空集合真空通过。每条 RuntimeObservationRecord 都引用独立 Evidence Artifact；render、interaction、media playback、restart continuity 或 failure proof 必须满足固定 canonical schema 与 pass predicate。记录与 expected set 必须一一相等；额外、遗漏、重复、错 proof kind、缺少归属、Blob/ref/digest/preimage 不一致都不能形成 sample_passed/full_passed。

R8b 准备时先分配 runId/operationBoundary、启动跨进程 audit/environment baseline，再用不含 runBindingDigest 的 PreRunSourceStateSnapshot 制作 source/trusted copy；随后 Card Service 签署 RuntimeVerificationRunBinding，把 task/input/audience/service、plan/manifest、expected tuples/render expectations、目标与隔离身份、source/copy、verifier/policy 组成无环信任根。所有 child evidence 复用同 run/父链，禁止跨运行拼接。Service/copier/verifier 的 revocation snapshot 由 pinned root 签名，以 complete append-only tombstone history 逐 `(keyId,keyEpoch)` 冻结唯一 32-byte Ed25519 publicKeyRef/SHA-256；同版本映射、revoked/disabled tombstone 永不改变，旧公钥 hash 不得跨 keyId/epoch 复用，并有本机单调 anti-rollback floor；prepare、run start、final commit 都重查当前序列和精确公钥版本，旧 key/snapshot 或调用方替换公钥不能回滚。

运行时证据严格分为 target_profile_preview 与 isolated_restart_copy。零写证明必须同时使用 add-on 全连接 hook、collection DB/WAL/SHM 跨进程 storage journal 和 media-tree journal；三个 sensor 都有 service 签名 coverage、稳定资源身份、无 gap/overflow/reset，connection-local hook 不能单独验收。process/window/focus trace 强制 from/to 与可信动作归因；signed append-only run-owned process lifecycle ledger 记录 Service 主进程及所有曾加入 Job Object 的后代/代理、join/exit 历史与独立 cutoff-active 子集，focus 按事件时 joined-not-exited 区间归因，既有 Anki 内 add-on 的每次 focus action 另用 verifier key 签名。focus-steal predicate 对称检查 from 或 to 触及用户 Anki；restart proof 同时绑定 helper 与真实 isolated-Anki 的前后 process、launch attestation 和 window owner 映射。任一外部写后恢复、旧窗口重放、用户 Anki 关闭/重启/抢焦点都失败。

为关闭 R8a→R8b 的 TOCTOU，首次 runtime 前与末次 observation 后各生成 typed data snapshot 并重扫 required media；短时 read barrier 为每次尝试分配新 instance/read-snapshot identity，11 条 typed final-check evidence 必须绑定同 run/boundary/commit descriptor 和 barrier 内采集时间；Typed FinalRuntimeEvidenceInputsManifest 以固定 cardinality/顺序完整列出 observations/proofs、data/profile states、两相位 audits、environment、run-owned lifecycle ledger/process launches、add-on focus attestations 与 final checks，其 JCS digest 与 aggregate 一起进入 barrier signature，并在 FinalReverification/RuntimeEvidence 中逐字节复用。三传感器与环境 observer 在签名截止点后继续 armed，commit 前任何事件都中止私有 write set。barrier attestation、final reverification、runtime evidence 与 VerificationArtifact 以预分配 ID 原子提交后才释放。

普通 AnkiConnect 查询不能证明渲染或播放。结构正确且可信的 required failure proof 形成 status=runtime_failed，ArtifactStage 保持 anki_data_verified；合同、签名、run、proof、TOCTOU、profile/process/environment/copy-lineage 形状不一致返回 ANKI_VERIFY_FAILED，而非伪装成体验失败。只有所有 required observations 通过、两相位零写入、最终 11 项 R8a 通过且最终 Artifact 原子提交，sample/full 才分别形成 sample_passed/full_passed 与 ArtifactStage=anki_verified。runtime verifier 不可用时保持 anki_data_verified，并显式记录 RUNTIME_EXPERIENCE_NOT_ASSESSED。
## 12. 状态词典

| 用户文案 | 所需证据 |
|---|---|
| 已发现学习点 | DiscoveryArtifact 完成 |
| 已生成草稿 | ProjectArtifact 存在 |
| N 张可导出 | 对应 CardPlan/卡片通过门禁 |
| APKG 已生成 | PackageArtifact + hash + 包内验证 |
| 尚未导入 Anki | 没有导入证据 |
| 已导入，尚未核验 | 导入成功但 required data checks 未全部通过 |
| Anki 数据核验通过，实际复习尚未评估 | VerificationArtifact status=data_verified |
| Anki 数据完整，但实际渲染/播放/重启核验失败 | VerificationArtifact status=runtime_failed，ArtifactStage 仍为 anki_data_verified |
| 已在 Anki 中完成运行时核验 | VerificationArtifact status=fully_verified，且 required runtime evidence 通过 |

禁止使用模糊的“完成”“一切就绪”覆盖多阶段。

## 13. 失败、重试与产物保留

每个 TaskFailure 使用 [目标架构](ARCHITECTURE.md) 的结构化合同，并至少包含：

- code 与失败 stage。
- preservedArtifactHandles。
- remoteCostState：none/possible/incurred/unknown。
- retryable 与 retryScope：none/item/batch/phase/whole_task。
- authorizationState：not_required/valid/required/expired/revoked。
- 唯一 requiredAction 与 requiredActionContextRef；人类错误文本不能代替动作枚举。

| 阶段 | 保留 | 重试 |
|---|---|---|
| 来源解析 | 已完成来源和 manifest | 失败来源/页 |
| 发现 | 已验证语义单元和候选 | 未完成工作单元 |
| 规划 | 已通过 CardPlan | 失败目标 |
| 生成 | 已通过批次 | 活动批次整批 |
| 导出 | ProjectArtifact | 仅导出，不重跑模型/TTS |
| Anki 导入/核验 | APKG、ImportPlan、创建媒体清单和可能的导入证据 | 先生成 AnkiRecoveryDecision；未写入则新 intent 重新确认，已写入则仅核验，边界不明则停在冲突 |

### 13.1 重启后的重新授权与 successor task

TaskInputManifestDigest 是一次执行实例的身份，包含当前 session/service 授权和凭据修订；它不能跨重启伪装为仍然有效。project_task 的可复用性另由 WorkReuseDigest 证明：绑定语义输入、Artifact/CardPlan、组件/规则/模板、profile configurationFingerprint、生成与工作分区策略，不绑定会话授权、user gesture、credentialRevision 或检查时间。profile_validation 不适用该排除：credentialRevision 必须进入其 WorkReuseDigest，旧连接测试不可跨密钥修订复用。

- 原授权仍有效且完整 TaskInputManifestDigest 不变：原 task 继续。
- 会话/Service 改变、授权过期或 credentialRevision 变化：取得新验证/授权，创建 successor task 和新的 TaskInputManifest；不修改旧任务。
- 只有 WorkReuseDigest 相同、已完成 Artifact 重新验 hash/parents/gate、稳定 capability 兼容，且新 disclosure/egress 等价或更窄时，successor 才复用已完成 work unit；活动单元整批/整单元重试。
- SuccessorTaskRebase 同时保存 predecessor/successor、复用结果摘要和旧/新授权审计引用；授权本身绝不转移。
- 来源、CardPlan、profile 配置、组件/策略改变或权限范围扩大时，不能 remaining 复用，必须明确 restart_phase/full_refresh。旧产物保留但不作为当前成功结果。
- StableCapabilityBinding 排除 checkedAt、snapshotRevision、暂态 state 和 issue 文本，避免正常复检制造假不一致；当前兼容性仍在恢复时重新判断。

## 14. 取消

- cancel requested 不等于 cancelled。
- 安全取消等待原子产物写入完成。
- 强制结束仅在安全取消超时后出现。
- safe 取消在可证明的原子边界和一致检查点完成时写 cancelled；force 终止或无法证明最后写入边界时写 interrupted。调用方不能指定二者，且 cancelled/interrupted 都不生成 succeeded。force 只终止该 task 独占的 job/process tree；共享服务或其他任务绝不能被连带结束。
- 导出取消清理或忽略 partial APKG。
- Anki 取消/崩溃后必须按 AnkiRecoveryDecision 的 not_written/written_identity_matched/write_boundary_ambiguous 三分支恢复；不允许仅凭旧 importIntent 重试写入。

## 15. 审计证书

VerificationCertificate：

~~~ts
type VerificationCertificate = {
  certificateId: string;
  projectId: string;
  projectRevision: number;
  sourceRefs: string[];
  learningContractRef: string;
  selectedObjectiveRefs: string[];
  cardPlanRefs: string[];
  projectArtifactRef: string;
  packageArtifactRef: string;
  apkgSha256: string;
  checks: {
    sourceIntegrity: "passed" | "partial" | "failed";
    locatorReplay: "passed" | "partial" | "failed";
    attributionCoverage: "passed" | "partial" | "failed";
    semanticSupportAssessment: "passed" | "partial" | "failed";
    sourceConsistency: "passed" | "partial" | "failed";
    factualTruth: "not_assessed" | "source_only" | "externally_corroborated";
    learningDesignChecks: "passed" | "partial" | "failed";
    learningEffect: "not_assessed" | "experimental" | "measured";
    generationIntegrity: "passed" | "partial" | "failed";
    mediaIntegrity: "passed" | "partial" | "failed";
    packageIntegrity: "passed" | "partial" | "failed";
    ankiDataIntegrity: "not_assessed" | "passed" | "partial" | "failed";
    ankiRuntimeExperience: "not_assessed" | "sample_passed" | "full_passed" | "failed";
    ankiVerificationArtifactRef?: string;
    ankiRuntimeEvidenceRef?: string;
  };
  knownLimitations: string[];
  createdAt: string;
  producerVersions: Record<string, string>;
};
~~~

证书本身有哈希并引用不可变产物。它不声称来源在现实世界必然为真、卡片已产生学习效果或学习者已经掌握内容。Anki 数据与运行时维度必须分开：runtime_failed 不能把 ankiDataIntegrity 从 passed 降级或抹去，也不能升级为 fully verified。每个状态必须由版本化、类型化检查记录的 producer/method/evidence 支撑，不能直接采用模型自报值。

## 16. 指标与阈值

发布硬指标：

- 对声明为 source-supported 的已验证卡，claim-level evidence mapping = 100%。
- 这些卡中 unsupported/unattributed factual statement = 0；现实世界 factual truth 另以 not_assessed/source_only/externally_corroborated 标示，不作越界承诺。
- unresolved blocking conflict in fact cards = 0。
- deterministic duplicate = 0。
- user locked field overwritten = 0。
- stale objective generated = 0。
- silent partial source omission = 0。
- false verified terminal state = 0。
- APKG/media hash mismatch accepted = 0。

运营指标：

- needs_review 比例。
- 高置信错误率。
- 平均恢复重复调用数。
- 每 100 张导入冲突。
- 用户编辑、删除、暂停比例。
- 单位复习时间的学习增益。

## 17. 验收证据

每次发布保存：

- 自动测试清单与版本。
- golden corpus 摘要。
- 单卡和 20+ 批量 Anki 数据完整性报告，以及独立的真实渲染/播放/重启复习 runtime evidence 报告。
- 50/100 张任务、取消和恢复报告。
- E 盘输出到 C 盘 Anki 的跨磁盘报告。
- 安全 canary 和注入测试。
- 当前已知限制。

测试计划见 [基准与评估](BENCHMARK_AND_EVALUATION.md)。
