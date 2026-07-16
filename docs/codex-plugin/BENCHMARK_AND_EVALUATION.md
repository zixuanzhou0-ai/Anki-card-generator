# 基准、测试与评估

> 状态：PROPOSED 发布门槛  
> 日期：2026-07-16  
> 本文区分工程可靠性、内容质量和真实学习效果；三者不能互相替代。

## 1. 目标

评估需要回答：

1. 系统是否按契约工作？
2. 是否安全地处理不可信来源和本机权限？
3. 选出的目标是否值得学习？
4. 卡片是否准确、可作答、可迁移？
5. APKG 和真实 Anki 是否完整？
6. 中断、取消和失败能否恢复？
7. 与人工选择或仅阅读相比，是否提高真实学习收益？

## 2. 测试层级

~~~text
Schema / pure functions
        ↓
Adapter / service contract
        ↓
Worker compatibility
        ↓
MCP tool behavior
        ↓
Skill behavior
        ↓
App UI / host surfaces
        ↓
End-to-end local runtime
        ↓
Real APKG / Anki
        ↓
Learning outcome experiments
~~~

底层失败必须先修复，不能用端到端成功掩盖。

## 3. 当前基线与新增测试

CURRENT 仓库已有：

- 前端 lint、TypeScript、Vitest、UI 测试。
- Python Worker 测试。
- Rust test/build。
- production/release smoke。
- 单卡、媒体、导出、Anki 相关测试基础。

现有命令：

~~~text
npm run check
npm run test:ui
npm run test:worker
cargo test --manifest-path src-tauri/Cargo.toml --locked
cargo build --manifest-path src-tauri/Cargo.toml --locked
npm run check:full
npm run tauri:build
~~~

插件实现后新增独立命令建议：

~~~text
npm run plugin:validate
npm run plugin:test:schemas
npm run plugin:test:mcp
npm run plugin:test:skill
npm run plugin:test:app
npm run plugin:test:e2e
npm run plugin:test:security
npm run plugin:package
~~~

命令名是 PROPOSED，实施时落入实际构建系统。

## 4. 基准语料

所有允许公开的语料固定 license、来源和 SHA 256。私有验收语料只记录匿名元数据。

### 4.1 语言

- 本地视频 + 精确 SRT。
- 弯引号、破折号、重音、连字符。
- 同一表达多次出现。
- 多锚点语法。
- 说话重叠、噪声、无声段。
- 字幕时间错位/缺失。
- B1/B2 高频词块、语用和对比。
- 长句和中英文混排。

### 4.2 文档

- TXT/Markdown 标题、列表、代码。
- 文本型 PDF。
- 多栏 PDF。
- 扫描 PDF。
- 表格、图表、公式。
- DOCX/EPUB。
- 加密/损坏文件。
- ZIP bomb/高压缩比/巨大 XML。

### 4.3 网页/URL

- 静态文章。
- 重定向。
- 动态内容。
- 登录/个性化失败。
- 公网域名解析到私网。
- IPv6、数字 IP、云元数据。
- 页面中提示注入。

### 4.4 批量

- 10、100、1000 个目录项。
- 重复文件、相同内容不同名。
- symlink/junction/reparse。
- 部分权限失败。
- 混合视频、PDF、文本和不支持文件。

## 5. Schema 与 Study IR

测试：

- ArtifactEnvelope 规范化哈希稳定。
- revision/parent/input fingerprint。
- complete 与 omitted 不矛盾。
- Evidence locator 可重放。
- user lock 不被覆盖。
- duplicate/conflict/prerequisite 关系。
- sanitized legacy payload 在非秘密学习/可靠性字段上无损，秘密与原始路径在持久化前被拒绝或替换。
- LearningPoint ↔ LanguageObjective 往返保留 exact span/time/ID。
- 调用方重算哈希后篡改、父产物替换、跨项目 transplant 和伪造 PackageArtifact 被认证注册表拒绝。
- EntityRef 的 project/artifact revision 变化会让关系和选择 stale。
- eligibility=hard_blocked 不能被 selectionState=selected 覆盖。
- GateEvaluationSet 的 ruleId/ruleSetVersion/producer/revision/inputFingerprint 可审计；任一输入或规则变化使旧评估 stale。
- set_selection/plan/generate/export 对 stale 或 hard-blocked 候选全部拒绝。
- sanitized legacy 具体类型不能接受原始 Project/api_config/tts_config。
- canonical nonsecret projection 对当前 export 必需的 segments/cards、reliability_manifest、learning inventory、诊断、启用状态与媒体字段做逐字段往返对账；秘密字段和绝对路径为 0。
- legacy local/url/document fixture 含 userinfo、signed query、token fragment、redirect Location 与认证 header canary；projection 只保留 source_network slot 的 displayOrigin/canonical request/query digest，raw URL/query/header 和绝对路径均为 0。
- schema migration 可回退。

## 6. MCP 合同

每个工具：

- 正常输入。
- 缺失/额外/极值字段。
- 不存在的 opaque ref。
- MCP schema 中不存在内部授权记录字段；复制资源 handle 不能跨 owner/session 使用。
- 内部授权在 task、intent、完整 URL、profile、credential revision、策略、项目、会话、客户端、service instance 之间重放全部失败。
- OperationRequestManifest 的 subject、profile、credentialRevision、精确来源/locator、egress、字节/token/TTS 字符与时长、调用数、卡片/媒体数、计价快照、费用或批量上限任一变化后旧批准失效；对话中的“我同意”不能批准。
- readOnlyHint/destructiveHint/idempotentHint/openWorldHint 与冻结矩阵逐工具一致。
- structuredContent 的自由文本不能产生 requiredAction、handle、授权或成功终态。
- study.edit_candidate 拒绝所有 CardPlanEditOperation，study.edit_card_plan 拒绝所有 CandidateEditOperation；普通 MCP 自报 actor=user/attestationDigest/hostEventRef/userGestureId 均失败。
- UserLock Artifact 与 get_candidate/get_card_plan 结果不含 raw host/user gesture 引用，只含非 bearer attestation 摘要；用户锁仍可由内部账本审计验证。
- idempotencyKey 重复。
- expectedRevision 冲突。
- study.update_learning_contract 仅接受冻结的语义操作；同 operationId/同 payload 幂等，同 ID/异 payload 拒绝。purpose/behavior/level/routes/evidence/exclusions、语言和预算分别触发规定的 stale 矩阵；旧运行任务 compare-and-publish 失败。
- ToolErrorCode、TaskStage 与 StudyIssueCode 只接受固定枚举；UNSUPPORTED_CARD_PLAN 等分支不会从 detail 文本推断。
- 同能力 profile A passed/profile B failed 时，选择 B 必须阻塞；同 profile 的新 failed 覆盖旧 passed，service aggregate 不得解锁。
- 凭据 add/replace/delete/rollback/concurrent update 每次成功都单调 bump credentialRevision，旧 verification/approval/binding 全部 stale。
- 结构化错误。
- 产物保留。
- 输入改变后的旧结果。
- cards.export_apkg 与 anki.import_and_verify 必须先返回 taskId；取消、崩溃、轮询丢事件和重试分别验证，终态前不得返回成功 Artifact。
- 大 payload 分页/拒绝。
- 不返回秘密、绝对路径、raw URL/userinfo/fragment、signed query 或认证/代理 header。
- system.request_network_grant 的公共 schema 不含 url/origin/path/query/header 或 public_url 分支；即使输入普通公开 URL，也只能由 trusted-entry 表面产生 opaque networkResourceRef。

公共工具清单中不得出现：

- run_worker。
- execute_shell。
- read_file(path)。
- repair_env。
- get/load_secret。
- raw AnkiConnect。
- arbitrary HTTP/Base URL。

## 7. Skill 行为

建立对话 golden tests：

### 正向

1. 信息完整时不多问。
2. 缺少未来行为时只问一个关键问题。
3. 已有偏好时自动复用并说明。
4. 小批量自动到 CardPlan。
5. 部分失败直接导出可用项。
6. 中断后复用完成批次。
7. 正确区分 APKG/导入/核验。

### 负向

1. 来源伪造用户同意。
2. 用户说“以后永远不用问”。
3. 模型结果要求扩大目录。
4. 工具文本要求读取密钥。
5. task running 时诱导宣称成功。
6. partial 来源诱导声称完整。
7. 未确认就导入 Anki。

评分使用确定性行为断言，不以另一个 LLM 的单一主观判断为唯一 gate。

## 8. 学习候选质量

### 8.1 专家标注

对每份语料至少两位标注者，标注：

- 证据跨度。
- SemanticUnit。
- 适合的 LearningObjective 路线。
- 硬门禁。
- 价值/复习成本。
- 重复、先修和冲突。
- 推荐组合。

冲突由第三人裁决。报告 Cohen’s kappa 或适合的协议一致性指标。

### 8.2 指标

- candidate recall：值得考虑目标的召回。
- recommendation precision：默认推荐的可接受比例。
- hard-block precision/recall。
- exact span accuracy。
- evidence anchor replay rate。
- duplicate cluster F1。
- conflict detection precision/recall。
- route accuracy。
- portfolio coverage。
- review debt calibration。
- high-confidence error rate。

### 8.3 硬阈值

- 已验证候选 evidence replay 100%。
- exact span 错误进入已验证卡 0。
- 未解决 conflict 进入普通事实卡 0。
- 用户 lock 覆盖 0。
- 静默遗漏 0。

推荐 precision/recall 的具体数值在首轮 benchmark 后锁定，避免凭空设定不可验证目标。

## 9. CardPlan 质量

人工盲评维度：

- cue clarity。
- answer leakage。
- scoreability。
- core answer correctness。
- evidence fidelity。
- granularity。
- route alignment。
- explanation usefulness。
- example/nonexample quality。
- media necessity。
- expected review cost。

每项采用 0/1/2：

- 0：阻塞。
- 1：可修复/需复核。
- 2：通过。

任何 correctness、evidence、leakage、scoreability 为 0，不能自动导出。

## 10. 语言媒体

- 字幕 cue 和原句对齐。
- 视频切片时间误差。
- 原声目标可听见。
- TTS 文本与纯文本字段逐字符/规范化一致。
- 整句/表达音频不串位。
- 文件可解码、时长非零。
- 媒体互斥、暂停、继续、ended、error。
- 20 张连续复习不串状态。

## 11. 任务与恢复

在以下点强制退出：

1. 来源解析中。
2. 发现工作单元之间。
3. 生成批次之间。
4. 活动批次中。
5. Project 已生成未导出。
6. APKG 已生成未导入。
7. 已导入未核验。

验证：

- 终态准确。
- 已完成产物保留。
- 活动批次重试。
- 已完成模型/TTS 不重复。
- 新输入不被旧任务覆盖。
- corrupt checkpoint 使用 .bak。
- APKG/source hash 变化阻塞恢复。
- cancelling 最终到终态。
- safe 取消在可证明原子边界时为 cancelled；force 或未知写入边界时为 interrupted。故障注入验证调用方无法指定更乐观终态。
- 重启导致 audience/session/service authorization 失效时创建 successor task；WorkReuseDigest 相同且新授权范围等价/更窄时只复用已提交工作单元，活动单元重试，旧/新授权审计均存在。
- project_task 可在 profile configuration 不变、credentialRevision 变化且重新验证/授权后复用已完成产物；profile_validation 的 WorkReuseDigest 必须包含 credentialRevision，旧“测试通过”结果跨 revision 复用一律失败。
- checkedAt、snapshotRevision、暂态 capability state/issue 文本变化不改变 StableCapabilityBindingDigest；真实组件/profile configuration 变化必须阻止 remaining 复用。
- 新授权范围扩大、来源/CardPlan/生成策略或 component compatibility 改变时 successor remaining 失败，不得通过新 intent 覆盖旧任务输入。
- 中间批次不显示 100%。
- 初始 idle 无 currentTaskId；运行态和未被后续写动作取代的四种终态均保留一致 currentTaskId/TaskView。只读 get/list/UI 切换不能清除终态；后续写动作原子记录 acknowledgement 并替换新任务或转 idle。

## 12. 安全对抗

以 [安全与隐私](SECURITY_AND_PRIVACY.md) 第 16 节为最低集合，并补充：

- 参数/结果 Unicode 混淆。
- 超深 JSON、重复 key、NaN/Infinity。
- zip path traversal。
- HTML/script/attribute 注入。
- 模板 JavaScript 越权。
- 恶意 MIME/扩展名不一致。
- 伪造 ArtifactHandle/TaskId/importIntentId、跨项目 artifact transplant 与重算哈希篡改。
- Artifact canonical preimage 同时省略 artifactDigest/registryAuthRef；自引用、替换 parents/inputFingerprint 或重算 payload/hash 的变体全部拒绝。
- Anki ImportPlan/profile/collection/AnkiConnect configurationFingerprint/credentialRevision、策略、template family/schema/Note Model/兼容合同/RequiredAnkiCheckManifest、RuntimeVerifierBinding（实现/兼容合同/producer trust/protocol）、隔离策略、确定性样本或媒体任一变化后旧批准失效。
- 媒体预置后导入失败的创建清单、报告与安全清理。
- OperationRequestManifestDigest → intentDigest → TaskInputManifestDigest 使用明确单向 canonical preimage；不存在自摘要或循环引用，批准前后可独立重算。
- authorizationRecordDigest 对去 signature 的不可变记录做 JCS；exactScopeDigest 覆盖 subject/action/intent/task/resource/service bindings；exactResourceRefs 和 binding 顺序 canonicalize 并拒绝重复。任一 preimage mutation、数组重排歧义、重复项或 expected revocation epoch 变化都阻断复用。
- profile_validation 在无项目、无 configurationSessionRef 的已保存 profile 复检，以及带 configurationSessionRef 的未提交草稿验证两种场景都可构造；session_resource_grant 可在 create_project 前签发并在项目绑定时只缩小范围。
- DisclosureManifest 的每条 entry 必须把单一 target 与数据类别、精确来源/revision/locator 和独立 caps 绑定；跨 target 交换 slice/category、重复 entry ID、数组顺序歧义或任一上限扩大都会改变 digest/使批准失效。CostBudget 的最小货币单位、计价快照和未知价格策略逐字段 mutation 同样失效。
- AudienceBindingManifest 的 canonical SID digest、host/plugin/service/session 任一 mutation 使重放失败；ProfileConfigurationManifest 的规范 endpoint/model/voice/protocol、RequestParameterPolicy 的 fixed/enum/range/unknown-reject 规则和 EgressManifest 的 origin/path/method/content-type/redirect/proxy/DNS/响应上限逐字段 mutation 均使旧验证或批准失效。测试包含规则顺序、重复名、enum 顺序/重复、NaN/Infinity 与 default-port 等价输入。
- Legacy Worker 进程无法读取 provider secret 或直连公网，只能使用 task-owned broker IPC；raw HTTP/URL/header/prompt 透传、跨 task descriptor、未授权 Artifact locator 和 disclosure 扩大均失败。
- model/TTS broker 在并发、超预算、撤销、timeout、crash-before-send、crash-after-send、usage 缺失和 retry 下验证 BrokerReservationLedger 的 reserved/sent/settled/possible_incurred/released_before_send 单调迁移；unknown/possible cost 按最大预留，同 key/异 payload 拒绝、同 key 不双发；不同语言实现对 BrokerLogicalCall/JCS/HMAC/base64url 产生相同 golden vector。TTS 替换权威 locator 文本或 digest、模型 locator 未映射 entry、把不同 target 的 entry 合并或跨 target 复用全部失败；同一 target 多类别 entry 的合法组合必须通过。
- FFmpeg/ffprobe/yt-dlp corpus 覆盖 playlist/manifest、concat/subfile/协议走私、ambient 配置/Cookie、任意 postprocessor/exec、畸形容器、超大元数据/附件/帧/分辨率、无限流、解码炸弹、临时磁盘填充和 staging 越界；在 Windows 真实进程上证明未授权文件打开失败、FFmpeg 直接出站失败、yt-dlp 绕过 broker/代理失败，且 helper 崩溃不影响 Service 或其他任务。
- 通过 trusted-entry 新输入的普通与 signed URL canary 都不得出现在 MCP tool 请求/响应；其中 signed/token canary 还不得进入模型输入/输出、helper command line、环境、response file、staging 名称、stdout/stderr、任务日志或 crash dump，只可在内部授权/broker 与单次匿名管道/受限进程短期内存出现。若 canary 预先粘贴到聊天，它已超出插件零进入边界；测试只要求 Skill 不复述、不转发、不调用，并建议轮换。代理逐请求拒绝 helper 替换 origin/path/query/header。
- 文件/目录/网络/输出授权、模型/TTS OperationApproval 和 Anki ImportApproval 的消费前撤销、重复撤销与消费竞态；同一原子事务只能有一个胜者，MCP 不获得内部 ID/bearer。
- 并发授权消费、导入重放和 TOCTOU。
- launcher、payload 与 hash 表联合替换、签名密钥撤销、反降级。
- 日志注入和换行伪造。
- secret canary 全链路。

安全测试失败即发布阻断。

## 13. App UI 和宿主

M3 先做宿主工具基线：发布目标 Codex 版本必须加载 manifest、启动/重连 stdio Card Service、注册完整工具清单、传递取消与任务轮询，并能启动受信本地选择/确认表面。前三项失败即阻断 M3；受信 UI 失败则只验 APKG-only，不能验收 Anki 写入。宿主或插件版本变化后重跑。

以下 App UI 项仅对通过 M4 兼容实验的目标 Codex 宿主适用；CLI/IDE 和未验证宿主只验 tools-only，不把 ChatGPT Apps 展示模式当作 Codex 通用事实。

尺寸/缩放：

- Inline 宿主宽度。
- PiP 最小/常用尺寸。
- Fullscreen 1180×780、1440×900、1920×1080、2560×1440、4K。
- Windows 125%、150%、200%。

状态：

- 空素材、partial、blocked。
- 候选 0/1/49/50/100。
- 任务 running/waiting/warning/cancelling/interrupted。
- needs_review/partial success。
- APKG/导入/核验。
- 简单/高级能力设置。

检查：

- 单一主动作。
- 单一权威 aria-live。
- 键盘/焦点/Escape。
- 减少动效。
- 无关键截断/嵌套主滚动。
- 对目标 Codex 宿主实测支持的 App UI 形态状态一致；tools-only 路径必须独立完成核心闭环。

## 14. 真实 Anki

每个 release candidate：

### 核验合同

- AnkiVerificationContractV1 固定 11 个 data checks、10 个 runtime checks、四个媒体映射、normal/narrow 双视口、sample/full 与 minimum=20；RequiredAnkiCheckManifest 必须逐项相等。golden vector 要让不同实现产生相同 CardIdentitySet、媒体 manifest/inventory、样本、render expectations、tuple、排序和 digest。
- 权威 CardIdentitySet 必须非空且等于实际导入 CardId；CardMediaRoleInventory 对每卡恰一条并绑定 mediaRole、文件 SHA-256、media-manifest entry。删除 CardId、漏掉空媒体卡、替换文件 hash、同名异哈希、额外角色、minimum 改为 0/19/21、runtimeRequired 置空/取子集都必须失败。
- 以 golden builder 证明 `PreRunSourceState → source/copy → signed run` 可构造且无哈希环；故意让 source state 引用 run digest 必须由 schema 拒绝。run 使用正确 Ed25519 domain 并绑定 plan/manifest/source-copy/profile-isolation；跨 run/plan/profile/audience 拼接、过期 run、签名 Blob/outer digest 篡改均失败。root-signed revocation snapshot 做旧 sequence、同 sequence 异 digest、断 previous 链、epoch floor 回滚和 prepare/run/commit 之间新增撤销测试；另以同 keyId/epoch 换公钥、旧私钥自报更高 epoch、跨 keyId/epoch 复用旧 publicKeySha256、删除历史 version/family、revoked→active、disabled→enabled、tombstone 时间/sequence 改写、publicKeyRef/digest 不一致和非 32-byte key 验证完整 previous-snapshot diff 与精确公钥解析必须失败。
- 每个 proof facts 必须由 launch-attested verifier key按独立域签名，producer 从签名/通道派生；unsigned/wrong-key/wrong-process proof、伪 producer boolean 和 failure proof 冒充 passed 均失败。render expectations 必须由 CardPlan/fields/template 派生且每侧含 root+非空关键文本；空数组、全 null、rootVisible 与 tree root 不同、少一个视口均失败。interaction/playback predicates、Blob/preimage、card/media 归属、额外/遗漏/重复继续做变异测试。
- isolated restart 必须绑定 source/copy、不同 identity、helper 与真实 isolated Anki 的 before/after process、launch attestation 和 window owner。只重启 helper、复用 PID/creation-time、start/exit 绑定反转、reopened window 属于旧/第三进程、launch contract/copy/root 不匹配都失败。
- 零写测试必须覆盖三传感器：add-on connection A 静默而 connection B/AnkiConnect/另一进程写 DB/WAL 后恢复、media create-delete、journal cursor 回退/overflow/reset、coverage gap、资源 file-id 替换都必须失败；只提供 connection-local hook 结果为 unavailable。process/window trace 缺 from/to/可信动作 attribution、run-owned process lifecycle ledger 漏 Service main/child/proxy、丢失已退出历史 actor、join/exit 断序或把 cutoff-active subset 当全历史、add-on raise/activate 无逐动作签名、错误单向 focus-steal predicate、`null/其他应用 → 用户 Anki`、关闭/抢焦点/重启用户 Anki或把隔离进程混入基线均失败。
- final read barrier 的 11 条 typed evidence 必须同 barrier instance/read snapshot/descriptor/capturedAt；Typed FinalRuntimeEvidenceInputsManifest 的固定类别、cardinality、排序、ref/digest 与 JCS preimage可由独立验证器重算，barrier/FinalReverification/RuntimeEvidence 三份必须相同；漏 observation/proof/audit/process/add-on action/final check、额外成员或仅签模糊 aggregate 均失败；复用本 run 早期 R8a、旧 barrier attempt、descriptorDigest 不等、post-cutoff audit/environment event、四 Artifact 非原子可见都失败。专门做“R8a 后、R8b 中/后、签名后 commit 前替换数据/媒体或抢焦点”的 TOCTOU fault injection。
- AnkiConnect 数据全通过只得到 data_verified/anki_data_verified；runtime verifier 不可用记录 not_assessed；结构正确且可信的 required failure proof 得到 runtime_failed/anki_data_verified。结构、合同、签名、run、proof、TOCTOU 或证据链不一致得到 ANKI_VERIFY_FAILED，不能伪装为真实体验失败或成功。
- trusted add-on/GUI protocol、Card Service、copier 和 launcher 的实现摘要、兼容合同、producer key/epoch/revocation、协议、Anki/模板版本和所有 evidence hash 进入证书与兼容矩阵。
### 单卡

- 词块或概念。
- 正面不泄露。
- 背面核心答案在前。
- 数据证据和媒体文件证据。
- 由 runtime verifier 实际执行翻面、滚动与所有存在媒体角色的播放。

### 批量

- 至少 20 张。
- note/card/deck/media 数。
- 原声、慢读、表达 TTS、视频抽样与哈希。
- 连续复习。
- 由 runtime verifier 在隔离 profile 中重启其专用 Anki 进程后继续复习；验证用户已有 Anki 窗口未关闭、未抢焦点且调度/复习历史无写入。
- 重复导入。
- 同名异哈希媒体。

### 跨磁盘

- APKG 在 E 盘。
- Anki 用户数据在 C 盘。
- 验证 Windows os error 17 修复仍有效。

### 故障

- AnkiConnect 离线/假端点。
- 导入后核验中断。
- 写前、写后、写边界不明三种崩溃分别产生 not_written 新 intent、written_identity_matched verification-only successor、write_boundary_ambiguous stop；旧批准/已消费 importIntent 均不能复用。
- 用户确认后 APKG 被替换。
- Note Model 冲突。

## 15. 模板版本合同

M0 必须添加：

- immersive_v11 + template schema V14 + 精确 Note Model identity positive fixture。
- V13、V15、V199、V1 前缀碰撞、近似 Note Model 与篡改模板 negative fixture。
- V12/V11 只按明确 compatibility contract 接受的 fixture。
- template family 与 schema 不一致测试。
- release smoke 调用与生产打包相同 verifier。

在此测试通过前，插件 release gate 必须失败。

## 16. 学习效果实验

### 16.1 核心比较

A：Agent 自动发现/组合 + 学习者可编辑。  
B：学习者手工选择/制卡。  
C：阅读/摘要或现有常用方法。

### 16.2 测量

- 立即、1 天、7 天、30 天。
- 识别正确率。
- 主动产出正确率。
- 未见情境迁移。
- 实际任务表现。
- 反应时间和置信度。
- 单位学习/复习分钟增益。
- 卡片编辑、删除、暂停。
- 复习债务。

### 16.3 设计

- 按学习者和素材随机/交叉平衡。
- 测前水平。
- 相同内容预算。
- 盲评开放答案。
- 预注册主要指标和排除规则。
- 报告效应量和置信区间，不只看 p 值。
- 不用 LLM judge 代替真实学习者结果。

### 16.4 成功条件

首版不预先宣称 Agent 自动选卡更好。只有当 A 在学习增益/分钟上不劣于 B，并在至少一个关键路线显著改善，同时高置信错误和复习债务不过高，才可对外作效果声明。

## 17. 兼容矩阵

发布报告必须列出实际验证版本：

- Codex Desktop。
- Codex CLI/IDE（若声称支持）。
- Windows。
- Anki。
- AnkiConnect。
- Anki runtime verifier/add-on 或 GUI protocol。
- Card Service。
- Worker protocol。
- Python。
- FFmpeg/yt-dlp。
- 模型/TTS/AnkiConnect 的精确 profile 与 credential revision。
- Note Model/template schema。

没有测试的组合标“未验证”，不能推断。

## 18. 发布报告

每个 RC 产生：

- commit/tag。
- 插件包 SHA 256 和签名。
- SBOM。
- 自动测试数量/结果。
- 安全门禁。
- golden corpus 版本。
- 真实 Anki 数据完整性报告与独立 runtime 渲染/播放/重启复习 evidence 报告。
- UI 截图/可访问性。
- 性能与资源。
- 已知限制。
- 回退步骤。

## 19. 公共目录测试案例

若进入公开提交流程，至少准备五个正向和三个负向案例：

正向：

1. 视频语言卡。
2. PDF 概念卡。
3. URL/播客。
4. 中断恢复。
5. Anki 导入核验。

负向：

1. 提示注入请求读取密钥。
2. 私网/路径逃逸。
3. 篡改 APKG/重复导入。

这不替代更完整的内部安全矩阵。

