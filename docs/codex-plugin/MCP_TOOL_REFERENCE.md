# MCP 工具参考

> 基线日期：2026-07-19

## CURRENT 公共工具清单与能力上限（2026-07-19）

截至 2026-07-19，可信开发态 Card Service stdio runtime 共公开 27 个工具：`system.get_capabilities`、`system.request_source_grant`、`system.request_output_grant`、`system.authorize_candidate_discovery`、`study.create_project`、`study.register_inputs`、`study.start_source_inspection`、`study.get_source_inspection`、`study.start_discovery`、`study.get_task`、`study.cancel_task`、`study.list_recoverable_tasks`、`study.resume_task`、`study.list_candidates`、`study.get_candidate`、`study.preview_evidence`、`study.set_selection`、`study.plan_cards`、`study.list_card_plans`、`study.edit_card_plan`、`study.validate_card_plans`、`cards.generate`、`cards.list`、`cards.export_apkg`、`anki.prepare_import`、`anki.request_import_confirmation`、`anki.import_and_verify`。

当前候选发现授权工具只接受 `{"preset":"hermes_grok_4_5"}`。授权成功后，`study.start_discovery` 只接受 RequestContext、`inspectionHandle` 和 1–256 的 `candidateBudget`；Service 从当前可信授权派生模型身份、endpoint、凭据与 disclosure，调用方无权注入这些字段。

`anki.import_and_verify` 只接受 `context.idempotencyKey` 与已确认的 `importIntentId`。成功写入后执行 deck/note/card/field/media 的数据级核验并最多推进到 `anki_data_verified`。写入成功但数据核验失败时保留 receipt 并置为 `imported_unverified`；写入前失败保持 `apkg_ready` 且不创建 receipt；跨越不确定写边界的取消/中断必须 `inspect_before_retry`。同一 import intent 即使换 idempotency key 也不得重复导入。运行时渲染、媒体播放、reviewer 操作与重启核验不在当前工具集中。

下文总表同时保留 PROPOSED V1 工具设计；只有本节列出的 25 个名字可被当前 Skill 命令式调用。

> 状态：CURRENT 25 工具开发态 runtime + PROPOSED 扩展工具契约；正式签名插件尚未发布
> 日期：2026-07-19
> 工具名和 schema 在实现前仍可调整；一旦 V1 发布即按版本策略维护。

## 1. 设计目标

MCP 工具服务于用户意图，而不是暴露内部 Worker。工具层必须：

- 足够少，让 Agent 能可靠选择。
- 足够类型化，让错误在执行前被发现。
- 副作用、权限和确认一目了然。
- 长任务返回 taskId，不阻塞对话。
- 使用不透明引用，不返回秘密或任意本地路径。
- 可由 App UI 和对话共享。

官方工具设计参考：[Describe tools](https://developers.openai.com/apps-sdk/build/mcp-server#step-2--describe-tools)。

当前桥实现协议握手、动态工具发现、零参数只读能力快照，以及可信会话中的本地 source/output opaque grant、幂等项目/素材登记、有界确定性素材检查、现有认证 Discovery 的候选列表/详情/证据预览、本地组合选择、受限确定性 CardPlan 创建/分页复核/Agent 编辑/独立重验，以及文本卡片的确定性生成与分页审阅。`cards.generate` 只接受当前 planSetHandle，要求全部八项门禁为 passed，发布不可变 CardArtifact、ReliabilityManifest、空 MediaLedger、SanitizedLegacyProjectArtifact 与 ProjectArtifact；它不调用模型、TTS、媒体、网络或 Anki。`cards.list` 只返回学习者可见题面、答案、解释、例句、评分边界和验证状态。没有原生 launcher audience 时只公开 `system.get_capabilities`；可信 audience 由父 PID、固定 launcher 可执行文件、当前 OS 用户 SID 摘要和每进程随机 nonce 派生，工具参数不能自报。桥仍不接受任意路径、URL、调用方构造的 Artifact 或 OperationIntent，也不公开启动候选发现、候选编辑、Anki 写入、凭据、原始 Worker 或 Shell。CURRENT APKG 导出只接受当前 ProjectArtifact handle 与受信 outputRef，返回可轮询任务；除明确标为 CURRENT 的工具外，下文仍是后续里程碑的目标合同。

## 2. 公共请求约定

~~~ts
type RequestContext = {
  projectId?: string;
  expectedProjectRevision?: number;
  idempotencyKey: string;
  operationIntentId?: string; // 仅定位已冻结操作，不是批准 bearer

  locale?: string;
};

type ToolSuccess<T> = {
  ok: true;
  requestId: string;
  projectRevision?: number;
  structuredContent: T;
  notices: UserNotice[];
};

type ToolFailure = {
  ok: false;
  requestId: string;
  error: ToolError;
};

type ToolErrorCode =
  | "SCHEMA_INVALID"
  | "UNSUPPORTED_COMBINATION"
  | "UNSUPPORTED_CARD_PLAN"
  | "GRANT_REQUIRED"
  | "GRANT_EXPIRED"
  | "AUTHORIZATION_REQUIRED"
  | "CONFIRMATION_REQUIRED"
  | "SOURCE_CHANGED"
  | "SOURCE_PARTIAL"
  | "SOURCE_UNREADABLE"
  | "PRIVATE_NETWORK_BLOCKED"
  | "PATH_ESCAPE"
  | "PROMPT_INJECTION_SUSPECTED"
  | "MODEL_STALE"
  | "TTS_UNAVAILABLE"
  | "FFMPEG_MISSING"
  | "MEDIA_SANDBOX_BLOCKED"
  | "ANKI_OFFLINE"
  | "NO_SCOREABLE_OBJECTIVE"
  | "UNRESOLVED_CONFLICT"
  | "REVIEW_BUDGET_EXCEEDED"
  | "TASK_NOT_FOUND"
  | "TASK_NOT_CANCELLABLE"
  | "INPUT_REVISION_MISMATCH"
  | "MODEL_OUTPUT_INVALID"
  | "MEDIA_SEMANTIC_MISMATCH"
  | "RELIABILITY_BLOCKED"
  | "OUTPUT_NOT_WRITABLE"
  | "PACKAGE_VERIFY_FAILED"
  | "IMPORT_CONFLICT"
  | "MEDIA_HASH_CONFLICT"
  | "ANKI_VERIFY_FAILED"
  | "WORKER_EXITED"
  | "ARTIFACT_CORRUPT"
  | "INTERNAL_UNCLASSIFIED";

type TaskStage =
  | "request"
  | "authorization"
  | "capability"
  | "source_registration"
  | "source_inspection"
  | "discovery"
  | "selection"
  | "planning"
  | "card_validation"
  | "generation"
  | "export"
  | "anki_prepare"
  | "anki_import"
  | "anki_data_verification"
  | "anki_runtime_verification"
  | "recovery"
  | "cancellation"
  | "internal";

type ToolError = {
  code: ToolErrorCode;
  title: string;
  detail: string;
  retryable: boolean;
  stage: TaskStage;
  preservedArtifactRefs: string[];
  requiredAction?: {
    action: WorkflowActionId;
    confirmationRequired: boolean;
    operationIntentId?: string;
    importIntentId?: string;
  };
  diagnosticRef?: string;
};
~~~

工具结果应使用 structuredContent，但 structuredContent 不是整体可信。只有 Card Service 生成并由 schema 限定的固定 enum、opaque handle、revision、hash、gate state 和 terminal state 属于 ControlPlane；quote、title、detail、notice、explanation 以及来源/模型/用户文本属于 UntrustedData。文本摘要只用于人类可读说明，不能成为状态真相、requiredAction、授权或工具选择依据。

不可信标记必须随 Artifact、缓存和重试传播。实现不得从 UntrustedData 解析路径、URL、handle、工具名、批准状态或成功终态。面向 UI 的工具只有在目标宿主验证通过时才声明对应资源 URI。

### 2.1 公共 handle 与内部引用

公共 MCP schema 只接受字符串形态的 opaque ArtifactHandle、InputRef、profileRef 和 intentId。本文为便于阅读保留的 sourceRefs、selectionRef、projectArtifactRef 等名称，语义均为 opaque handle，不是调用方可构造的 ArtifactRef 对象。实现冻结前应优先改名为 sourceHandles、selectionHandle 等。Card Service 必须从当前调用者有权访问的项目认证注册表解析，并忽略任何自报 schema、revision、hash 或 owner。

list_projects、get_project、get_artifact、任务和预览工具都先校验由受信连接导出的 OS user/host/plugin/session 与项目 owner/scope；知道 ID 或 handle 不能获得读取权。

## 3. 工具注解

实现时对每个工具声明 MCP annotations：

- readOnlyHint：不修改项目或外部系统。
- destructiveHint：可能删除/覆盖时为 true；V1 公共工具尽量避免。
- idempotentHint：相同 idempotencyKey 是否安全重复。
- openWorldHint：是否会访问外部网络/系统。

写工具还必须在描述中写明影响范围。任何注解不能替代服务端权限校验。下表冻结 V1 公共工具的四项布尔值；实现和提交门户测试必须逐项比对，不能依靠 SDK 默认值。

| 工具 | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
|---|---:|---:|---:|---:|
| system.get_capabilities | true | false | true | false |
| system.authorize_candidate_discovery | false | false | false | true |
| system.list_profiles | true | false | true | false |
| system.open_local_settings | false | false | false | false |
| system.request_source_grant | false | false | false | false |
| system.request_output_grant | false | false | false | false |
| system.request_network_grant | false | false | false | true |
| system.request_operation_confirmation | false | false | false | false |
| system.revoke_grant | false | true | true | false |
| system.validate_profile | false | false | true | true |
| study.list_projects | true | false | true | false |
| study.get_project | true | false | true | false |
| study.create_project | false | false | true | false |
| study.update_learning_contract | false | false | true | false |
| study.register_inputs | false | false | true | true |
| study.start_source_inspection | false | false | true | true |
| study.get_source_inspection | true | false | true | false |
| study.start_discovery | false | false | true | true |
| study.get_task | true | false | true | false |
| study.list_recoverable_tasks | true | false | true | false |
| study.cancel_task | false | false | true | false |
| study.resume_task | false | false | true | true |
| study.list_candidates | true | false | true | false |
| study.get_candidate | true | false | true | false |
| study.preview_evidence | true | false | true | false |
| study.edit_candidate | false | false | true | false |
| study.set_selection | false | false | true | false |
| study.plan_cards | false | false | true | false |
| study.list_card_plans | true | false | true | false |
| study.edit_card_plan | false | false | true | false |
| study.validate_card_plans | false | false | true | false |
| cards.generate | false | false | true | false |
| cards.list | true | false | true | false |
| cards.export_apkg | false | false | true | false |
| anki.prepare_import | false | false | true | true |
| anki.request_import_confirmation | false | false | false | false |
| anki.import_and_verify | false | true | true | true |
| study.get_artifact | true | false | true | false |
| study.get_audit | true | false | true | false |

destructiveHint 表示工具可能终止任务、撤销授权或持久修改外部系统，不等于“允许破坏”。anki.import_and_verify 即使 V1 采用 detect_and_report，仍会写入 Anki，必须按高影响工具处理。

## 4. 工具总表

| 工具 | 作用 | 副作用 | 确认 |
|---|---|---|---|
| system.get_capabilities | 读取环境、模型、TTS 与 Anki 能力快照 | 只读 | 无 |
| system.authorize_candidate_discovery | CURRENT：打开固定 Hermes Grok 4.5 候选发现授权窗口 | 本地授权状态 | 必须用户动作 |
| system.list_profiles | 读取脱敏后的模型/TTS/AnkiConnect profile | 只读 | 无 |
| system.open_local_settings | 打开受信本地配置窗口 | 启动本地 UI，不提交秘密给模型 | 必须用户动作 |
| system.request_source_grant | 打开受信文件/目录选择器并签发受限输入引用 | 本地授权状态 | 必须用户动作 |
| system.request_output_grant | 打开受信目录选择器并签发输出引用 | 本地授权状态 | 必须用户动作 |
| system.request_network_grant | 打开受信本地 URL 输入表面；MCP 参数不接收任何 raw URL/origin/query | 本地授权状态 | 每次新网络资源必须用户动作 |
| system.request_operation_confirmation | 在受信本地 UI 批准冻结的模型/TTS/成本/批量 OperationIntent | 本地授权状态 | 必须用户动作 |
| system.revoke_grant | 打开受信授权管理器并撤销所选资源/模型/TTS/Anki 授权或待执行批准 | 本地授权状态 | 必须用户动作 |
| system.validate_profile | 验证已有 profile | 可能访问远程服务 | 首次新服务时 |
| study.list_projects | 分页读取项目摘要 | 只读 | 无 |
| study.get_project | 读取项目和权威工作流快照 | 只读 | 无 |
| study.create_project | 创建学习项目和合同草稿 | 本地写入 | 无 |
| study.update_learning_contract | 用版本化语义操作更新学习目标、路线、预算、语言、证据策略或排除项 | 本地写入并使受影响下游 stale | 无 |
| study.register_inputs | 注册授权来源并建立快照 | 读取来源、本地写入 | 新目录/新网络域需确认 |
| study.start_source_inspection | 创建来源检查任务/产物 | 本地写入，可能解析文件 | 无 |
| study.get_source_inspection | 读取已有来源检查产物 | 只读 | 无 |
| study.start_discovery | 发现语义单元和学习候选 | 模型调用、本地写入 | 超出已批准成本/数量时 |
| study.get_task | 查询权威任务 | 只读 | 无 |
| study.list_recoverable_tasks | CURRENT：列出可安全恢复的候选发现任务 | 只读 | 无 |
| study.cancel_task | 请求安全取消 | 终止本地任务 | 明确用户动作，但无需二次确认 |
| study.resume_task | CURRENT：为候选发现创建或复用认证后继任务 | 模型调用、本地写入 | 必须存在当前固定模型授权 |
| study.list_candidates | 分页读取候选 | 只读 | 无 |
| study.get_candidate | 候选、证据和关系详情 | 只读 | 无 |
| study.preview_evidence | 预览受控证据片段 | 读取认证本地快照 | 无 |
| study.edit_candidate | 语义编辑、拆分等；锁定需受信用户事件 | 本地写入 | lock/unlock 必须真实用户动作 |
| study.set_selection | 保存候选组合 | 本地写入 | 无 |
| study.plan_cards | 生成 CardPlan | 模型可选、本地写入 | 超出预算时 |
| study.list_card_plans | 分页读取卡片计划 | 只读 | 无 |
| study.edit_card_plan | 语义修改卡片计划；不创建或清除用户锁 | 本地写入 | 无 |
| study.validate_card_plans | 执行门禁 | 本地写 CardPlanValidationArtifact | 无 |
| cards.generate | CURRENT：将全门禁通过的文本 CardPlan 确定性投影为 CardArtifact/ProjectArtifact | 本地认证 Artifact 写入；不调用模型/TTS/媒体/网络/Anki | 无 |
| cards.list | 分页审阅当前 ProjectArtifact 中的已验证卡片 | 只读 | 无 |
| cards.export_apkg | CURRENT：从当前认证 ProjectArtifact 异步生成、独立复验并投递 APKG | 只在受信 outputRef 下创建版本化文件，不覆盖 | 新目录授权由受信选择器取得 |
| anki.prepare_import | CURRENT：重验当前 PackageArtifact、只读检查固定本机 AnkiConnect 并冻结 ImportPlan | 本地写认证 ImportPlan，不写 Anki | Anki 必须已打开 |
| anki.request_import_confirmation | 打开受信本地确认窗口并写入会话绑定的批准状态 | 本地授权状态 | 必须用户动作 |
| anki.import_and_verify | 按已批准的 importIntentId 导入并验证 | 修改 Anki | 服务端批准状态必须有效 |
| study.get_artifact | 读取小型结构化产物或受可信会话约束的 opaque resource handle | 只读 | 无 |
| study.get_audit | 获取审计/验证证书 | 只读 | 无 |


## 4.0 CURRENT APKG 异步工具合同

`cards.export_apkg` 只接受封闭 `RequestContext`、当前 `projectArtifactHandle` 和由受信本地选择器签发的精确 `outputRef`。它不接受路径、文件名、replace、媒体目录、Worker 参数或调用方 ArtifactRef；立即返回 `taskId`，由 `study.get_task` 轮询，`study.cancel_task` 请求安全取消。

成功必须同时满足：Worker 只在 task workspace 写入；Card Service 独立重验完整 APKG 合同、SQLite note/card、模板与 CSS 摘要；APKG 字节进入内容寻址 Blob；目标目录使用同目录 `.partial`、flush/fsync 与 no-replace 版本化发布；PackageArtifact、CardIdentitySet、PackageMediaManifest、CardMediaRoleInventory 和 APKG file Artifact 已认证发布；项目已单调提交到 `apkg_ready` 或更后阶段。任一提交窗口未闭合时不得公开 `succeeded`。重复同一幂等请求不会重新调用 Worker，也不会覆盖或重复创建最终文件。

当前这条公开路线只承诺已经实现的文本、零媒体 CardArtifact 投影；模型/TTS/媒体生成仍按现有门禁失败关闭。APKG 成功不等于已导入 Anki；CURRENT `anki.prepare_import` 创建认证计划，`anki.request_import_confirmation` 建立当前 session 的一次性批准，`anki.import_and_verify` 才执行幂等写入与数据核验。即使数据核验通过，`runtimeVerification` 仍为 `not_assessed`。
## 4.1 系统与本地配置

### system.get_capabilities

返回统一 SystemCapabilitySnapshot，但严格分两层：fixedCapabilities 表达宿主、stdio MCP、本地 Runtime、Worker、FFmpeg、来源适配器、Anki 安装和 runtime verifier；serviceProfiles 按 (model|tts|anki_connect, profileRef, configurationFingerprint, credentialRevision) 逐项表达状态与 latestVerification。serviceAggregates 只提供 none/some/all ready 的展示计数，不能驱动 gate。

host 部分至少分别报告：pluginManifestLoaded、stdioServiceLaunch、toolRegistration、trustedLocalUiLaunch、attachmentBridge、mcpAppResources。M3 只要求前四项中的 manifest/stdio/tool 可用；attachmentBridge 可由受信本地选择器替代，mcpAppResources 在 M4 前保持 not_checked/optional。trustedLocalUiLaunch 不可用时，来源/输出可用已有稳定授权继续，但新的高影响授权和 Anki 写入 fail closed，产品降为 APKG-only。

只读检查不能自动安装、修改配置或发起模型/TTS 网络请求。历史验证不等于当前 ready；宿主版本或插件安装实例变化后 host capability 记录立即 stale。

工作流只能读取当前 action 明确选择的 profile 条目；latestVerification 必须匹配同一 capability/profileRef/fingerprint/credentialRevision，且按单调 sequence 取最新。最新 failed 覆盖旧 passed，其他 profile 的 ready 或 aggregate some_ready 不能替它解锁。

### system.authorize_candidate_discovery

> CURRENT：固定 Hermes Grok 4.5 的受信候选发现授权。

输入必须精确为：

~~~json
{"preset":"hermes_grok_4_5"}
~~~

工具不接受 URL、Provider、model、credential、prompt、source body、authorization token 或调用方预算。Card Service 固定使用 `model.hermes-grok-4.5`、字面 loopback `http://127.0.0.1:8645/v1` 与 `grok-4.5`，并在 digest-pinned 本地窗口取得真实用户决定。用户批准后，Service 会先复核 Hermes xAI OAuth 并在需要时以固定 host/port/provider 参数启动本地代理；只有本地 `/health` 同时报告 xAI/Grok upstream 与 authenticated 才返回 `capabilityAvailable=true`。这项本地预检不等于 xAI 公网推理已经成功；上游连接失败仍会在 discovery task 中以可重试的 `MODEL_STALE` 失败关闭。

输出只包含 `approved/declined/cancelled/failed/timed_out` 状态、`capabilityAvailable` 与非秘密授权摘要；不返回凭据、内部 intent、文件路径或可转移 bearer。只有 `approved` 且 capability available 才能继续 `study.start_discovery`。

### system.list_profiles

只返回脱敏的 modelProfileRef、ttsProfileRef 和 AnkiConnect profileRef：provider、model/voice/目标、能力标签，以及与该 profile 当前 fingerprint/credentialRevision 精确匹配的 latest verification。多个 profile 各占一条；不得用“任意 profile ready”覆盖当前选择的失败。不得返回 API Key、OAuth Token、Cookie、认证头或包含秘密的 URL。卡片模板与生成策略由当前 Learning Contract、CardPlan 和服务端版本化规则确定，不要求调用方取得额外 generationProfileRef。

### system.open_local_settings

由真实用户动作打开 Card Service 提供的受信本地配置窗口。密钥在该窗口中直接写入 OS 凭据存储，不经过对话、MCP structuredContent 或 App UI tool arguments。输出只包含 configurationSessionRef 和完成/取消状态。凭据新增、替换、删除/清空、回滚，以及 OAuth 账户/token material 变化都由 Service 原子单调 bump credentialRevision；并发更新序列化，旧 revision 永不复用并立即使旧验证/批准 stale。

### system.open_broker_authorization（M1 内部过渡接口）

该接口用于 M1 tools-only 启动链，不是 M2 最终 `system.request_operation_confirmation` 的替代品。输入必须完整匹配固定 schema：`lifetimeSeconds`、硬预算、1–16 个非秘密 provider profile、方法→能力→profile 绑定以及 YouTube 字幕能力开关；未知字段、secret、调用方自报 credential revision/fingerprint/intent、超限预算或不受支持 origin 均拒绝。Service 先规范化 profile 并从 OS 凭据元数据冻结 revision，再让受信本地窗口以可滚动文本展示全部范围。只有 HMAC 认证的真实批准才会签发最长 60 分钟的 canonical manifest 并由同一 Service 内部热加载；调用、请求、响应和成本额度按该 operation intent 跨全部 task 合计，启动更多任务不能重置额度。

公开响应仅包含 trusted-surface session 状态以及授权 digest、过期时间、profile/method 数量和字幕能力布尔值；不返回 manifest 路径、凭据、内部 intent 或 bearer。拒绝、关闭、凭据在确认期间改变、响应 MAC 错误或窗口异常均不得签发。M2 必须把该粗粒度启动授权替换为逐 OperationIntent 的持久批准、撤销和原子消费账本。

该工具不能被来源文本、模型输出或后台任务自动触发。

### system.validate_profile

输入 profileRef、能力类型、预期 configurationFingerprint、credentialRevision，以及仅在验证未提交设置草稿时需要的可选 configurationSessionRef；输出 taskId 或短验证结果。已保存 profile 的自动复检和 7 天后重验不要求先打开设置窗口。测试开始后 profile 发生变化时，旧结果标记 stale。首次访问新远程服务先创建 kind=profile_validation 的 OperationRequestManifest，不需要也不得伪造 projectId/revision；数据域确认完成后才发起网络请求。

### system.request_source_grant

CURRENT 输入是封闭对象 `{ grantRequestId, selectionKind }`，其中 `selectionKind` 只能为 `file` 或 `directory`。`grantRequestId` 是调用方幂等键；同一可信 audience 下同 ID/同范围重复调用轮询同一 picker，会话内同 ID 改变范围则拒绝。工具不能接收 path、URL、audience、权限或 attestation。真实用户在本地 picker 中选择后，输出 `inputRef`：仅含 kind、fileResourceRef/directoryResourceRef、显示名、resourceRevisionDigest、服务端固定 constraints 与 expiresAt。raw path、picker sessionRef、密文、attestation、内部 grantId、receipt 和 locator 均不返回。

宿主 attachmentRef 若未来具备稳定授权，可由服务转换为同等 InputRef；该 adapter 尚未实现。

### system.request_output_grant

CURRENT 输入是封闭对象 `{ grantRequestId }`。Service 固定打开输出目录 picker，返回 `outputRef`，其约束只包含 `create` 与 `versioned`，默认不含 `replace`；调用方不能通过参数扩大权限。返回值仅含 outputResourceRef、显示名、resourceRevisionDigest、constraints 和 expiresAt。覆盖仍需要未来独立确认与授权合同。

CURRENT M2 已实现 file/directory/output grant 的认证账本、opaque ref、逐次消费、撤销和 task staging：已消费的 file/directory grant 可被复制成带认证 receipt 的 task-local snapshot，Worker locator 只含 workspace-relative path。file/directory ref 已可通过可信 `study.register_inputs` 绑定到 StudyTask、稳定 Blob/目录 manifest、`study.source-asset` 与项目 `sources_ready` 阶段；output ref 已通过 `cards.export_apkg` 绑定到版本化 no-replace APKG 发布。

两个工具都只在可信 stdio audience 中注册；无 audience 时调用得到 Unknown tool。picker 等待超时会返回 `awaiting_user`，使用相同 `grantRequestId` 可继续轮询。`cancelled` 与 `failed` 是显式终态；公开失败只返回固定错误码，不回显路径或私有异常。


### system.request_network_grant

输入固定为判别值 kind=trusted_entry，并包含 sourceKind=public_video/web/podcast/other；不接受 url、origin、path、query、header 或调用方自报的公开/敏感分类。工具只打开 Card Service 的受信本地 URL 输入表面；用户在该表面直接录入 raw URL，Service 在字符串进入 MCP 之前完成 userinfo/秘密模式扫描、规范化、DNS/重定向/公网策略检查和确认。MCP 只收到 networkResourceRef、脱敏 displayOrigin、adapter 类型和 canonical policy 摘要；后续 register_inputs 只接受 networkResourceRef。

如果用户已把 URL 粘贴到对话，Skill 不得把该值复制进工具参数。疑似 signed/token/auth/query 凭据时应说明对话记录可能已经暴露、建议撤销或轮换，然后要求在受信表面输入新值。此设计为所有 URL 增加一次本地输入动作，以换取“raw URL 从不进入 MCP request”的可验证边界。

CURRENT M2 已实现该工具之后的内部 network grant/consume/redirect/revoke/fetch 合同与 33 项定向测试，但没有实现本 public MCP 工具或生产受信 URL 输入窗口。内部 registry 不能被 Agent 直接调用来绕过真实用户动作；Service 重启后因 raw URL 不落盘，旧 ref 返回 `reauthorization_required`。

### system.request_operation_confirmation

> CURRENT 内部状态：model/TTS OperationIntent/Approval/InternalAuthorization 账本内核已实现摘要、受众、一次性批准消费、task 绑定、共享调用预算与撤销 epoch；受信窗口 attestation 生产适配器和本 MCP 工具尚未接线，默认 verifier 缺失时批准失败关闭。

当 system.validate_profile、study.start_discovery、study.plan_cards、cards.generate 或需要重新授权的 study.resume_task 将首次向新服务发送数据，或超过 Learning Contract 已批准的模型/TTS 调用、卡片数量、媒体数量、费用/时间上限时，Service 必须先创建 OperationRequestManifestV1，再由其摘要创建不可变 OperationIntent，并返回 CONFIRMATION_REQUIRED + operationIntentId；此时不得启动远程调用。

OperationRequestManifest 的 subject 是 project_task 或 profile_validation。前者绑定项目/学习合同/输入 Artifact/来源修订；后者始终绑定 profileRef、configurationFingerprint 与 credentialRevision，只有验证未提交设置草稿时才额外绑定 configurationSessionRef，不要求项目。每条 DisclosureEntryV1 把一个 capability/profile/origin/model-or-voice 目标与一个数据类别、精确来源修订/locator 集和该目标自己的请求字节、输入/输出 token、TTS 字符/秒数上限绑定；不能跨 target 交换片段。ProfileConfigurationManifest/EgressManifest 与 AudienceBindingManifest 都使用固定 JCS preimage。CostBudgetV1 绑定整数最小货币单位、计价快照版本、调用/卡片/媒体上限；价格未知时明确显示 unknown，并以硬资源上限约束。

该工具只能由真实用户动作打开受信本地确认窗口。确认后 Service 写入内部 call_model/call_tts 授权记录；只返回 operationIntentId 与 approved/declined/expired/revoked 状态，不返回授权字符串。调用方随后以相同 idempotencyKey 和 operationIntentId 重试原工具；Service 重建并比对 OperationRequestManifestDigest 与 intentDigest，完全一致后才创建单向绑定 intentDigest 的 TaskInputManifest。任何 subject、来源/locator、profile、凭据、egress、字节/token/字符/时长、数量、计价或批量变化都会使批准失效并要求新 intent。

### system.revoke_grant

只能由真实用户动作打开受信本地授权管理器。MCP 可传可选 project/resource/operation/import 公共引用作为显示筛选，但不能提交 authorizationId、ledger key 或撤销 bearer。受信 UI 从 Card Service 直接列出脱敏的文件/目录/网络授权、模型/TTS OperationApproval、Anki ImportApproval 及其范围/过期/消费状态；用户选择后由 Service 在内部账本写 revoked。

输出只包含 revoked/already_consumed/not_found、受影响任务数和脱敏摘要，不返回内部授权 ID。撤销在消费前立即阻止调用；运行中任务在安全点停止。已经完成的远程调用或 Anki 写入不会被伪装成已回滚，已产生 Artifact 保留并记录授权撤销。相同 UI revocation operation 重试幂等。

### 授权生命周期

~~~text
prepare request
→ host/native trusted UI 显示精确资源和影响
→ 真实 user gesture
→ Service 保存仅内部可见的 authorization/approval record
→ MCP 只携带资源 handle 或 intentId；服务按可信连接身份解析
→ 调用时校验客户端、会话、任务、资源、revision、策略、数量和有效期
→ 服务端账本原子消费使用次数
→ expire 或 revoke
~~~

资源 handle 只用于定位已授权对象，不单独构成授权。它必须与由受信握手导出的 OS 用户、host/plugin/service instance、session 和服务端 authorization ledger 同时匹配；复制 handle 到另一会话不能获得权限。若目标宿主无法提供或启动受信确认表面，写操作必须 fail closed。

## 5. 项目工具

### 5.1 study.create_project

> CURRENT：本工具已在可信 stdio audience 下注册，使用封闭 RequestContext/Learning Contract schema 调用认证 Project Registry；相同 idempotencyKey 精确幂等，冲突失败关闭，无可信 audience 时工具不可见。当前 learningContractRef 是项目 scope 内的版本化 contract identity，独立 Learning Contract Artifact/handle 尚未发布。

输入：

~~~ts
{
  context: RequestContext;
  title?: string;
  learningContract: {
    purpose: string;
    targetBehavior: string;
    learnerLevel?: string;
    routes?: LearningRoute[];
    maxNewCards?: number;
    targetDailyReviewMinutes?: number;
    promptLanguage?: string;
    answerLanguage?: string;
    exclusions?: string[];
  };
}
~~~

输出：

~~~ts
{
  projectId: string;
  projectRevision: number;
  learningContractRef: string;
  inferredDefaults: { field: string; value: unknown; reason: string }[];
}
~~~

语义：

- 缺省值必须记录来源。
- 不创建模型或 TTS 请求。
- 相同 idempotencyKey 返回同一项目。

### 5.2 study.update_learning_contract

> CURRENT 内部状态：固定语义操作、双 revision CAS、operationId 精确幂等和最小失效矩阵已有服务端存储实现与回归测试；公共 MCP schema、canonical learningContractRef 发布和跨 Artifact/Task 原子提交仍未实现。

输入 projectId、expectedProjectRevision、expectedContractRevision、operationId 和非空 operations。operations 只允许 StudyIR 冻结的语义联合：set_purpose、set_target_behavior、set_learner_level、replace_routes、set_budget、set_languages、set_evidence_policy、add_exclusion、remove_exclusion；不接受 JSON Patch、任意字段路径或模型生成的对象合并。

Service 先对整个 ChangeSet 做 schema/长度/预算/路线约束校验，再以 compare-and-publish 原子提交。相同 operationId 与相同 payload 幂等返回同一 revision；同 ID 不同 payload 拒绝。输出新 projectRevision、contractRevision、canonical learningContractRef，以及 invalidatedStages 和 preservedArtifactRefs。

失效矩阵固定为：purpose、targetBehavior、routes、evidencePolicy 或 exclusions 变化使 discovery 与全部下游 stale；prompt/answer language 变化使 CardPlan 与全部下游 stale；budget 变化使 selection、planning 与全部下游 stale；learnerLevel 变化使 discovery 与全部下游 stale。运行中旧 revision 任务可以完成私有中间结果，但 compare-and-publish 失败，不能覆盖当前项目。修改本身不调用模型/TTS，也不自动重跑。

### 5.3 study.list_projects

分页返回项目 ID、标题、revision、Learning Contract 摘要、ArtifactStage、最后任务状态、更新时间和是否可恢复。不得返回完整来源正文或本地绝对路径。

### 5.4 study.get_project

返回项目元数据和唯一 WorkflowSnapshot：当前产品步骤、ArtifactStage、OperationState、能力阻塞、主动作、currentTaskId 和最新 Artifact refs。currentTaskId 在 queued/running/cancelling 时指向活动任务，在 succeeded/failed/cancelled/interrupted 时指向尚未被后续写动作取代的最近终态任务；初始 idle 或终态被一个不创建异步任务的写动作确认后才为空。读取项目、切换页面或仅展示结果不算确认。任一后续写动作被接受时，Service 必须原子记录 lastAcknowledgedTaskId/terminalOutcomeAcknowledgedAt；若该动作创建新任务，则在同一事务把 currentTaskId 换成新 taskId，否则转为 idle。对话、Inline、PiP 与 Fullscreen 都以此快照为状态真相。

### 5.5 study.register_inputs

CURRENT 输入是封闭对象：`context` 只接受 projectId、expectedRevision、idempotencyKey 和 locale；`inputs` 接受 1–64 个 kind=file|directory 的 opaque InputRef；`snapshotPolicy` 接受 require_stable|allow_conditional|draft_only。schema 不含 path、URL、audience、自定义权限、receipt 或 Worker locator。授权不会作为模型可提交的 bearer 传入；Card Service 使用当前可信连接身份和内部授权账本校验每个 InputRef。

Service 为本次登记创建可恢复 StudyTask，将来源绑定到任务指纹，复制到任务专属 staging，并把文件流式写入内容寻址 Blob；目录逐文件写入 Blob，再发布 canonical directory manifest。随后发布认证 `study.source-asset`，并以 expectedRevision 把项目原子推进到 `sources_ready`。精确重试会重新签发当前会话 handle；若崩溃发生在 Artifact 发布后、项目提交前，恢复会复用认证 Artifact 并完成项目提交。

CURRENT 公开结果仅返回项目/任务状态、SourceAsset opaque handle、内容摘要、大小、支持级别和警告；不得包含 source path、InputRef、私有 receipt、resolution proof、registry ref、stagingRef、worker locator 或绝对 task path。单文件当前硬限制为 2 GiB，超限时在发布 SourceAsset 前显式失败，不产生半成品成功状态。

snapshotPolicy：

- require_stable：无法稳定快照则失败。
- allow_conditional：允许 B 级来源，但必须返回警告。
- draft_only：model_relayed 内容只生成草稿。

登记只证明“获得了稳定字节快照”，不证明内容已经解析、完整或适合制卡。文件/目录在 source inspection 完成前固定为 B 级 conditional；未知类型为 C 级 unsupported。当前调用同步等待登记完成，公共任务轮询/取消仍待统一任务工具开放。

禁止：

- 接受通配绝对路径作为永久权限。
- 递归读取未在目录授权范围中的兄弟目录。
- 跟随逃出授权根的 symlink/reparse point。

### 5.6 study.start_source_inspection

CURRENT 输入为封闭对象：`context` 只接受 projectId、expectedProjectRevision、idempotencyKey 和可选 locale；`sourceHandles` 接受 1–64 个当前项目的认证 SourceAsset handle。schema 不接受路径、URL、source text、audience、解析器参数、模型 profile 或网络能力。

Card Service 创建可恢复 StudyTask，逐来源验证认证 Blob，再发布 `study.source-representation`、`study.source-inspection` 与汇总 `study.inspection`。纯文本、Markdown、代码、HTML 和 SRT/VTT/ASS/SSA 走无模型、无网络的确定性解析；HTML 的 script/style/noscript/template 内容不会进入可见文本，字幕保留 cue 时间。受限目录只解析 manifest 中已快照且受支持的成员。PDF、Office、图片、音视频等尚无本安全解析器的来源显式返回 C 级 `SOURCE_PARSER_NOT_AVAILABLE`，超过同步上限的来源返回 `SOURCE_ASYNC_INSPECTION_REQUIRED`，不会无限同步读取或伪造成功。

公开结果仅返回项目 revision、taskId、inspectionHandle、每个来源的 identity 摘要、支持级别、覆盖计数、推荐路线和 issue code；不返回来源正文、BlobRef、SourceAsset 内部 ref、原始路径、目录成员名、InputRef、staging receipt 或私有任务记录。至少一个来源形成可用表示时项目保持 `sources_ready` 并把主动作推进为 `discover_candidates`；全部阻塞时主动作是 `resolve_issue`。当前工具为有界同步调用，公共 task poll/cancel 与大型异步解析器仍待统一任务工具开放。

### 5.7 study.get_source_inspection

CURRENT 输入只接受一个认证 `inspectionHandle`。工具只读取已经存在的 `study.inspection` 及其来源检查 Artifact，返回与 start 相同的脱敏结果；readOnlyHint=true，不启动解析、不调用模型或网络，也不能借 handle 越过 project/audience/session scope。

## 6. 发现任务

### 6.1 study.start_discovery

> CURRENT：已注册的异步候选发现入口。

调用前必须先通过 `system.authorize_candidate_discovery` 取得当前固定 Hermes 授权。输入是封闭对象：

~~~ts
{
  context: {
    projectId: string;
    expectedProjectRevision: number;
    idempotencyKey: string;
  };
  inspectionHandle: string;
  candidateBudget: {
    target: number;   // 1..256
    maximum: number;  // target..256
  };
}
~~~

Service 从当前可信授权、audience、项目 revision、inspection 与候选预算派生模型 profile/configuration、credential revision、disclosure、egress、OperationIntent、exact scope 与成本摘要。调用方不能提交 Provider、Base URL、model、credential、prompt、source body、authorization token 或这些 Service-owned 字段。

工具立即返回 `intent=discover_candidates` 的任务快照；状态为 queued/running/cancelling/succeeded/failed/cancelled/interrupted，`resumability=resume_remaining`。用 `study.get_task` 轮询。模型只能读取认证 inspection 中完成本次任务所需的有界证据；候选 eligibility 与门禁由 Service 派生，模型不能自报。

### 6.2 study.get_task

> CURRENT：输入精确为 `{"taskId": "..."}`。

返回公开任务快照：`schemaVersion`、`taskId`、`intent`、`state`、`cancellable`、`resumability`、`progress`、`nextAction`，以及终态时可选的 `result` 或 `error`。公开结果不包含 Worker 输出、路径、credential、内部 ArtifactRef 或 input fingerprint。

### 6.3 study.list_recoverable_tasks

> CURRENT：输入只能为空对象或 `{"limit": 1..100}`。返回当前 audience 下公开恢复运行时真正支持的 failed/cancelled/interrupted 候选发现任务；导出与 Anki import 不会出现在列表中。

输出包含 `schemaVersion`、公开任务快照数组、`returnedTasks` 与 `nextAction`。任务仍经公开投影，不返回授权、路径、ArtifactRef、Provider、input fingerprint 或 Worker 状态。

### 6.4 study.cancel_task

> CURRENT：输入精确为 `{"taskId": "..."}`。

请求当前任务安全取消并返回任务快照。重复请求幂等；取消必须保留最后可靠 Artifact 阶段。调用方不能选择 force mode 或伪造终态。

### 6.5 study.resume_task

> CURRENT：输入精确为 `{"taskId":"...","idempotencyKey":"..."}`。仅接受 `study.list_recoverable_tasks` 返回的候选发现任务。Service 重新验证项目 revision、原 inspection、预算、能力与当前固定 Hermes 授权，再创建或复用绑定 predecessor/rebase 的认证 successor；相同幂等键不会重复模型调用。

导出和 Anki import 明确返回 `TASK_RESUME_UNSUPPORTED`。调用方不能提交 Provider、URL、模型、凭据、授权、预算、scope、input fingerprint 或 successor 身份。

## 7. 候选工具

### 7.1 study.list_candidates

CURRENT 输入：

~~~ts
{
  discoveryHandle: string;
  filter?: {
    eligibility?: LearningCandidate["eligibility"][];
    route?: LearningRoute[];
    sourceHandles?: string[];
    selectionState?: ("selected" | "unselected")[];
    query?: string;
  };
  sort?: "recommended" | "source_order" | "review_cost";
  cursor?: string;
  limit?: number;
}
~~~

`discoveryHandle`、`sourceHandles` 和返回的 `candidateHandle` 都是 audience/session 绑定的不透明句柄，不是内部 ArtifactRef。LearningCandidate 与 LearningRoute 引用 [Study IR](STUDY_IR_REFERENCE.md) 的固定枚举；未知值由闭合 schema 拒绝。

输出分页摘要，不返回完整原文或所有诊断：

- candidateId、目标摘要和不含路径的来源摘要。
- eligibility、selectionState、推荐理由、风险和预计复习成本。
- 服务端门禁 pass/review/fail 计数、证据数量和是否安全抑制。
- 下一页不透明 cursor；服务端上限为 100 项。

CURRENT cursor 由 Card Service 认证并同时绑定 service instance、Discovery 摘要、规范化筛选条件、排序和末项 candidateId；篡改、跨查询复用、跨服务复用或候选集合变化都会拒绝。`selectionState` 由同一项目当前最新且仍绑定该 Discovery 的认证 SelectionArtifact 派生；候选预算或上游输入使项目退回 `candidates_ready` 后，旧 SelectionArtifact 不再投影为 selected。

### 7.2 study.get_candidate

CURRENT 输入：

~~~ts
{
  discoveryHandle: string;
  candidateHandle: string;
}
~~~

Service 先验证 Discovery 是项目当前最新发现，再验证 candidateHandle 确实属于该 Discovery。返回单一候选的：

- Objective、服务端派生的 eligibility、GateResult 和分项评分。
- EvidenceAnchor 摘要和 quote digest，但不返回证据正文。
- duplicate/conflict/prerequisite 关系、支持路线、风险和安全抑制状态。
- 当前用户编辑历史与锁定投影；CURRENT 尚未实现编辑/锁定，因此分别为空和 false。

响应不包含内部 ArtifactRef、RegistryAuthRef、BlobRef、InputFingerprint、模型提示词、授权记录或本机路径。

### 7.3 study.preview_evidence

CURRENT 输入：

~~~ts
{
  discoveryHandle: string;
  candidateHandle: string;
  evidenceId: string;
  contextCharacters?: number; // 0..480，默认 160
}
~~~

Service 从认证内容寻址的本地 SourceRepresentation 快照重放 evidenceId，重新校验 node bounds 与 quote SHA-256，只返回目标 quote、同一 node 内有界前后文、无路径来源摘要和文本/字幕定位器。即使上游发现已经执行披露过滤，预览仍独立对完整 node 重跑密钥、本机路径和敏感 URL 检查；命中时返回 `EVIDENCE_PREVIEW_REDACTED`，不返回局部安全片段。

CURRENT 实现不会重新打开远程来源，固定返回 `snapshotBacked=true`、`networkAccessed=false`，所以 `openWorldHint=false`。将来若增加远程回源，必须另建显式 open-world 工具或升级合同，并在读取前重验 networkResourceRef、重定向策略、撤销状态和 source revision。
### 7.4 study.edit_candidate

只接受 [Study IR](STUDY_IR_REFERENCE.md) 中 CandidateEditOperation 的 Agent 可写子集；CardPlanEditOperation 在本工具 schema 中非法。普通 MCP 参数不含 provenance，Service 固定注入 actor=agent，并按当前 revision 解析全部 EntityRef。

用户明确要求锁定/解锁 Objective 时，调用方只能提交独立的 lockChangeRequest（objectiveRef、ObjectiveLockableField、desiredState），不得与普通编辑混用。Service 打开紧凑受信表面，并由内部通道写原始 host event/user gesture；Artifact 只保存 attestationDigest/hostCategory/recordedAt。调用方自报 actor=user、attestationDigest、hostEventRef 或 userGestureId 一律拒绝。CardPlan 锁定不经本工具处理。

输入必须有 expectedProjectRevision 和 operationId。输出新 revision、受影响产物和需要失效的下游阶段。

### 7.5 study.set_selection

CURRENT 输入：

~~~ts
{
  context: {
    projectId: string;
    expectedProjectRevision: number;
    idempotencyKey: string;
    locale?: string;
  };
  discoveryHandle: string;
  operation: "add" | "remove" | "accept_recommended";
  candidateHandles?: string[];
  budget?: {
    maxNewCards?: number;
    targetDailyReviewMinutes?: number;
  };
}
~~~

`add` 和 `remove` 必须提交至少一个 candidateHandle；`accept_recommended` 禁止同时提交 candidateHandles。所有 handle 都必须属于同一 audience/session、当前项目最新 Discovery 和精确候选集合；重复 handle、两个别名解析到同一候选、跨 Discovery、过期项目 revision 或失效选择一律拒绝。公共 schema 不接受 ArtifactRef、路径、Provider、模型、授权、凭据、OperationIntent 或 Worker 参数。

显式 `add` 可以纳入 `needs_review` 候选，但必须返回 `SELECTION_NEEDS_REVIEW_INCLUDED`；`hard_blocked`、`excluded`、`duplicate` 以及 evidence/conflict/security hard gate 失败永远不能被 selectionState 覆盖。`accept_recommended` 只考虑 recommended 候选，并用 `portfolio-coverage-v1` 的确定性覆盖优先算法综合迁移价值、路线覆盖、来源覆盖、饱和度、语义重复与预计回答成本；它不是简单 Top-N，稳定 candidateId 仅作最终平局裁决。

输出 audience/session 绑定的 selectionHandle、selectedCount、实际预算、逐路线 selected/available 覆盖摘要、结构化警告和 `review-debt-conservative-v1` 的低置信度复习债务估算。超过 `targetDailyReviewMinutes` 只产生 `SELECTION_REVIEW_BUDGET_RISK`，不会静默删卡；超过 Learning Contract 的 maxNewCards 则失败关闭。每次 add/remove/自动组合都会发布新的认证 `study.portfolio-selection`，把当前 Discovery 和仍有效的前一选择作为父项，并把项目推进或保持在 `selection_ready`。

选择阶段只写本地认证状态和一个快速可重放 StudyTask，不创建 OperationIntent，也不发起模型、TTS、网络或 Anki 调用。重复的相同 idempotencyKey/输入返回原结果；相同 key 携带不同操作摘要必须拒绝。真正的批量、成本和数据出域确认统一延迟到 `study.plan_cards` 或 `cards.generate`。

## 8. 卡片计划

### 8.1 study.plan_cards

> CURRENT：本工具已在可信 stdio audience 下注册。输入是封闭对象 `{ context, selectionHandle }`；context 只接受 projectId、expectedProjectRevision、idempotencyKey 和可选 locale。调用方不能提交 route preferences、media policy、model profile、ArtifactRef、路径、授权或网络字段。Card Service 从当前认证 SelectionArtifact 再验证候选图，最多同步处理 100 项，仅为 `production`、`chunk_collocation`、`reading_recognition` 发布认证 plan/set/validation，并执行八类确定性检查。显式翻译、语用/语法推断或媒体需求返回 `UNSUPPORTED_CARD_PLAN`。能力快照分别报告 `publicCardPlanPlanning=true`、`publicCardPlanQueries=true`、`publicCardPlanEditing=true`、`publicCardPlanValidation=true`。

CURRENT 输入只包含当前 selectionHandle；route preferences、media policy 和 model profile 是未来需要模型/媒体规划时的 PROPOSED 扩展，而且必须由服务端已批准 profile 与 OperationIntent 派生，不能作为普通 MCP 注入字段。服务按当前 project/artifact revision 重新验证候选资格，不能只相信保存选择时的状态。

输出 taskId 与同步 CardPlan set/validation opaque handles。CURRENT 只允许最多 100 项的小型确定性映射；超过时返回 `CARD_PLAN_ASYNC_REQUIRED`，不阻塞 stdio。需模型重写或更大批次时必须先实现任务化公共 planner。

不支持的 objective/route/template 组合返回 UNSUPPORTED_CARD_PLAN，不静默换成别的卡型。

### 8.2 study.list_card_plans

> CURRENT：本工具已注册为只读、closed-world 查询。输入只接受当前 planSetHandle、可选认证 cursor 和 1–100 的 limit；cursor 绑定 service instance、精确 PlanSet digest 与上一项 cardPlanId，篡改、跨集合或失效集合均拒绝。输出只含学习者可见题面、核心答案、解释、证据数量、媒体策略、预计复习时间、八项 check 状态和 opaque cardPlanHandle，不含内部 ArtifactRef、来源路径、正文快照、授权、模型资料或 input fingerprint。

分页返回：

- 正面任务摘要。
- 核心答案。
- 证据、媒体和路线。
- 验证状态。
- 预计复习成本。

正面预览必须使用和实际模板一致的答案泄露检查。

### 8.3 study.edit_card_plan

> CURRENT：可信 stdio 已开放本工具。输入严格限定为 `{ context, planSetHandle, cardPlanHandle, operation }`；operation 只允许 `edit_card_cue`、`edit_card_answer`、`edit_card_feedback` 与 `edit_media_policy` 四种 CardPlanEditOperation，CandidateEditOperation、provenance、EvidenceRef、UserLock、路径、模型或授权字段均非法。Service 固定记录 `actor=agent` 与权威 taskId，不允许调用方伪装用户动作；原 evidenceRefs 与 userLocks 强制保留，编辑后以同一 Artifact identity 发布新 revision，再发布新 PlanSet/Validation revision，并以 expectedProjectRevision 原子推进项目。

编辑不是绕过可靠性门禁：核心答案或 scoring point 偏离冻结 Objective 会使 `scoring_boundary=failed`；新解释、例句或非例句无法由当前确定性证据规则证明时为 `evidence_coverage=needs_review`；启用当前尚无生成器的媒体会使 `media_generatability=failed`。这些计划可保存和查看，但不能进入生成。旧 PlanSet、旧 CardPlan 和后续 revision 之前的幂等结果不会被复活。

用户明确要求锁定/解锁 CardPlan 时，仍必须走未来受信 App/native UI 内部通道；普通 MCP 不创建、延长或清除 UserLock。原始 hostEventRef/userGestureId 不进入 MCP、Artifact 或读取结果。Objective 锁定不经本工具处理。

### 8.4 study.validate_card_plans

> CURRENT：本工具接收封闭 RequestContext 与当前 planSetHandle，不接收调用方自报 check、producer、evidence、ruleSetVersion 或 inputFingerprint。服务重新解析当前认证 Selection/Candidate/Plan 图，重放全部八项确定性检查，发布新 PlanSet 与 CardPlanValidation revision，并保持 `plans_ready`；该动作不访问模型、TTS、网络或 Anki。若图 stale、损坏、跨 audience 或项目 revision 已变化则失败关闭。任务在 Artifact 已写入但提交前中断时，可按同一输入精确恢复；opaque handle 比较按 Artifact identity 而非字符串。

执行：

- 证据覆盖。
- 评分边界。
- 答案泄露。
- 重复。
- 冲突。
- 模板兼容。
- 媒体可生成性。
- 用户锁定。

输出带 CardPlanCheckId、ruleSetVersion、producer、evidence 和 inputFingerprint 的 CardPlanValidationArtifact。fail 项不能进入 cards.generate；规则集或输入 revision 变化后旧结果 stale。

## 9. 生成与导出

### 9.1 cards.generate

> CURRENT：可信 stdio 已开放受限确定性实现。输入严格限定为 `{ context, planSetHandle }`；`context` 只含 projectId、expectedProjectRevision、idempotencyKey 和可选 locale。调用方不能提交 CardPlanRef、模型/TTS profile、批次策略、路径、媒体、授权或任意 ArtifactRef。

服务重新解析精确当前 PlanSet → Validation → CardPlan → Candidate → Representation → SourceAsset 认证图，要求集合中每一项均 eligible，八项门禁均为 `passed`，题面/答案均为文本且四类媒体策略全关。任一 needs_review/failed、stale、跨 audience、父图缺失、媒体请求或不支持路线都失败关闭；不会把未验证计划静默降级成卡片。

成功时为每个计划发布不可变 `study.card`，并发布逐卡对账的 `study.reliability-manifest`、空 `study.media-ledger`、经 sanitizer 处理的 Legacy Worker 兼容投影，以及唯一 `study.project-artifact`。项目从 `plans_ready` 原子推进到 `cards_ready`；任务在 work unit 完成、task success 或项目提交边界中断时，可以按同一输入恢复而不重复发布卡片。当前返回：

~~~ts
{
  schemaVersion: 1;
  projectId: string;
  projectRevision: number;
  artifactStage: "cards_ready";
  taskId: string;
  projectArtifactHandle: string;
  generatedCards: number;
  verifiedCards: number;
  needsReviewCards: 0;
  hardFailedCards: 0;
  mediaCount: 0;
  generationMode: "deterministic_projection";
  nextAction: "export_apkg";
}
~~~

当前实现不调用模型、TTS、媒体、网络或 Anki；需要新语义生成、翻译、媒体或 TTS 的计划仍由 CardPlan 门禁阻塞。`cards.generate` 成功只表示 ProjectArtifact 已达到 `cards_ready`；必须由独立的 `cards.export_apkg` 任务成功后才是 `apkg_ready`，仍不等于已导入 Anki。

### 9.1.1 cards.list

> CURRENT：输入为当前 `projectArtifactHandle`、可选 service 认证 cursor 与 1–100 的 limit。服务再次验证当前项目阶段、ProjectArtifact 父图、cardIds 对账与 sanitized legacy projection，只返回题面、核心答案、解释、例句/非例句、评分点、可接受变体、媒体角色和验证状态。内部 ArtifactRef、EvidenceRef、路径、来源文件名、授权、模型数据与 input fingerprint 不进入公共结果。cursor 绑定 service instance、audience、ProjectArtifact 身份与 offset；解码后必须重编码为逐字符相同的 canonical Base64URL，等价非规范编码、签名篡改、跨 session 或跨项目复用均拒绝。

PROPOSED 扩展：当 Broker、OperationIntent、TTS/媒体生成与细粒度异步任务全部接线后，`cards.generate` 可在同一封闭合同下支持模型与媒体；扩展不得放宽当前的 PlanSet/Validation 当前性和 fail-closed 规则。
### 9.2 cards.export_apkg

> CURRENT：输入只允许封闭 RequestContext、当前 `projectArtifactHandle` 与受信选择器签发的完整 `outputRef`。不接受 enabled IDs、raw path、文件名策略、overwritePolicy、Worker 参数、媒体目录或调用方 ArtifactRef。

服务先解析当前 ProjectArtifact，重新核对 `cards_ready` 阶段、project revision、CardArtifact/ReliabilityManifest/MediaLedger 父图和 output grant。工具立即返回 `taskId`；`study.get_task` 提供单调进度，`study.cancel_task` 请求安全取消。Worker 只写 task-owned workspace，不能直接写用户目录。

Service 不采信 raw `ExportResult` 作为公共信任根，而是重新计算 APKG SHA/size，执行完整包合同与 archive 限额，检查 `collection.anki2` 的 note/card、正反模板和 CSS 摘要，验证 Worker package card ID 与 ProjectArtifact source card ID 的映射，并重建媒体 manifest 与逐卡角色 inventory。成功后发布认证 `study.apkg-file`、`study.card-identity-set`、`study.package-media-manifest`、`study.card-media-role-inventory` 和 `study.package-artifact`。

目标文件名由项目标题和 APKG SHA 确定；写入目标目录中的同盘 `.partial`，flush/fsync 后以 hard-link no-replace 发布。存在同名文件时仅当 SHA 和大小完全相同才视为已有相同结果，否则失败，不覆盖。跨磁盘场景因此不会对 Worker 临时文件执行 rename。取消或失败不能公开 partial 或 `apkg_ready`。

终态 `succeeded` 的公开 result 只含 PackageArtifact handle、阶段/revision、APKG SHA/size、安全文件名、deckNames、note/card/media 数、deliveryState 和 `prepare_anki_import` 下一动作；不返回路径、BlobRef、内部 ArtifactRef、媒体目录、raw ExportResult 或 input fingerprint。PackageArtifact 已发布但项目 commit 中断时，精确重试只补项目提交，不重跑 Worker；项目后来推进到 Anki 阶段时原导出任务仍保持成功。

CURRENT 仍只覆盖确定性文本/零媒体 ProjectArtifact；通用模型扩写、TTS 与媒体路线未开放。Anki 数据写入与核验已由受信 import intent 闭合，但 runtime 渲染、播放、reviewer 和重启证据未开放。M0 的真实 GUI 证据不能外推为通用插件 runtime verifier。
## 10. Anki

### 10.1 anki.prepare_import

CURRENT 输入是封闭 `context { projectId, expectedProjectRevision, idempotencyKey }` 与 audience/session 绑定的 `packageArtifactHandle`。调用方不能传路径、Anki 地址、profile 名、目标目录、manifest、duplicate policy 或检查子集。Service 重新解析当前 PackageArtifact 与其 APKG file 父产物，流式复核内容寻址 Blob 的 SHA/size，并确认项目至少处于 `apkg_ready`。

目标检查固定为禁用环境代理的显式 IPv4 loopback AnkiConnect endpoint；开发态 launcher 默认 `http://127.0.0.1:8765`，也可通过受控启动参数 `--anki-connect-url http://127.0.0.1:<port>` 指定其他本机端口。该参数拒绝 hostname、IPv6、userinfo、query、fragment、非 HTTP 和非 loopback 地址，不能由 MCP 调用方提交。Windows 把 8765 纳入排除端口范围时，可把隔离 AnkiConnect 与 Card Service 一起配置为 8785 等未占用端口，不能要求 APKG 位于 Anki 数据目录或同一磁盘。探测只调用 `version`、`getActiveProfile`、`getMediaDirPath` 和 `deckNames`。原始 profile、媒体目录和 deck 名不会进入公共结果；持久计划只保留 profileRef、配置/collection/deck 摘要、AnkiConnect 版本和计数。随后服务发布认证 `study.anki-verification-contract` 与 `study.anki-import-plan`，固定 11 项数据检查、`detect_and_report` 重复策略、`explicit-confirmation-required` 写策略和 `inspect-before-any-retry` 恢复策略。项目保持 `apkg_ready`，只增加 revision 和当前计划引用。

公开结果只含 `importPlanHandle`、当前 session 的 `importIntentId` 与 pending 状态、APKG SHA/size/安全文件名、deck/note/card/media 计数、脱敏目标摘要、检查数、`runtimeVerification=not_assessed`、`confirmationRequired=true` 和下一动作。精确重试返回首次保存的同一句柄且不重复探测 Anki；跨插件句柄、旧 PackageArtifact、离线/畸形 AnkiConnect 响应均失败关闭。此工具不写 Anki，不代表已经导入、数据核验或真实复习核验。

PROPOSED 扩展会在受信确认之前再冻结 RuntimeVerifierBinding、隔离策略、RequiredAnkiCheckManifest、确定性采样和完整凭据版本绑定；这些尚未实现，不能从 CURRENT ImportPlan 推导。任何已绑定字段变化都必须使旧确认失效。

### 10.2 anki.request_import_confirmation

> CURRENT：已注册；只建立一次性服务端批准，不写入 Anki。

`anki.prepare_import` 现在从当前认证 ImportPlan 派生确定性的 `importIntentId`；它绑定 OS 用户摘要、host/plugin/service instance、当前 session、完整 ImportPlan ArtifactDigest、APKG SHA-256 和脱敏 Anki target digest，默认 30 分钟过期。输入只能是这个 `importIntentId`，不能附带 `approved=true`、token、路径、Anki 地址、profile 或计划覆盖字段。工具打开 digest-pinned 本地窗口，显示当前 Anki 目标、deck、note/card/media 数、APKG/模板/Note Model/媒体清单摘要、重复策略和写边界恢复策略。

受信窗口响应以每会话 HMAC 认证，Service 校验 session/nonce 后才生成仅存在于内存的精确手势 attestation；专用 ImportApproval ledger 再用服务密钥认证持久记录并绑定完整计划。工具只返回 `approvalState`、`importIntentId` 和 `expiresAt`；等待或关闭窗口时分别返回 pending/cancelled，真实点击后返回 approved/declined。任何 attestation、执行 token、ledger ref、session ref 或内部 ArtifactRef 都不进入 MCP。跨 audience/session 查询、篡改记录、过期批准和复制聊天内容全部失败关闭；批准只能由后续写任务原子消费一次。恢复 intent 与受信撤销管理器仍属后续恢复切片。

### 10.3 anki.import_and_verify

> CURRENT：已注册的唯一 Anki 写工具；只执行已确认 import intent 的幂等导入与数据级核验。

输入是封闭对象：

~~~ts
{
  context: {
    idempotencyKey: string;
  };
  importIntentId: string;
}
~~~

调用方不能提交项目、APKG 路径、Anki 地址、profile、deck、媒体目录、duplicate policy、verification checks 或授权字段。Service 解析并原子消费与当前 audience/session、ImportPlan、APKG 和 Anki target 精确绑定的批准；重复同一 import intent（即使更换 idempotency key）返回同一任务/结果，不重复导入。

工具立即返回任务快照，后续以 `study.get_task` 轮询。当前终态规则：

1. 导入或已存在且全部 required data checks 通过：发布 import receipt 与数据验证结果，项目推进到 `anki_data_verified`，`runtimeVerification=not_assessed`。
2. 写入已经发生但数据检查失败或不完整：保留 receipt，项目为 `imported_unverified`。
3. 写入前失败：不创建 receipt，项目保持 `apkg_ready`。
4. 取消/中断可能跨越写边界：任务为 `interrupted`，下一动作 `inspect_before_retry`；不得盲目调用 import 或通用 `study.resume_task`。
5. 不允许未知、缺失、重复的数据检查伪装成成功。

CURRENT 数据验证覆盖服务合同规定的 deck、note、card、字段、模板/模型身份与打包媒体证据，但不运行卡片 reviewer。正背面渲染、翻面、滚动、音视频播放、焦点行为和真实重启持续性均未评估。

R8b 的 RuntimeVerifierBinding、签名 proof、隔离 Anki、跨进程零写审计、运行时采样和 `anki_verified`/fully_verified 状态仍为 PROPOSED。只有未来 trusted runtime verifier 返回经过认证且完整的证据，才可称“已在 Anki 完成运行时核验”。

## 11. 产物与审计

### 11.1 study.get_artifact

只返回允许的小型 payload。大型内容返回：

- artifact metadata。
- 可分页片段。
- 受可信 OS/host/plugin/session、项目 scope、时限和权限约束的 opaque local resource handle；不可作为 bearer URL，也不可跨会话转移。

不提供任意文件下载。

### 11.2 study.get_audit

返回指定阶段的审计证书：

- 输入身份和覆盖。
- 生产者、配置指纹和模型引用。
- 门禁结果。
- 产物哈希和父产物。
- Anki 核验证据。
- 已知限制。

## 12. 错误码

稳定顶级类别：

| 类别 | 示例 |
|---|---|
| INVALID_REQUEST | SCHEMA_INVALID、UNSUPPORTED_COMBINATION |
| AUTHORIZATION | GRANT_REQUIRED、GRANT_EXPIRED、AUTHORIZATION_REQUIRED、CONFIRMATION_REQUIRED |
| SOURCE | SOURCE_CHANGED、SOURCE_PARTIAL、SOURCE_UNREADABLE |
| SECURITY | PRIVATE_NETWORK_BLOCKED、PATH_ESCAPE、PROMPT_INJECTION_SUSPECTED |
| CAPABILITY | MODEL_STALE、TTS_UNAVAILABLE、FFMPEG_MISSING、MEDIA_SANDBOX_BLOCKED、ANKI_OFFLINE |
| LEARNING | NO_SCOREABLE_OBJECTIVE、UNRESOLVED_CONFLICT、REVIEW_BUDGET_EXCEEDED、UNSUPPORTED_CARD_PLAN |
| TASK | TASK_NOT_FOUND、TASK_NOT_CANCELLABLE、INPUT_REVISION_MISMATCH |
| GENERATION | MODEL_OUTPUT_INVALID、MEDIA_SEMANTIC_MISMATCH |
| EXPORT | RELIABILITY_BLOCKED、OUTPUT_NOT_WRITABLE、PACKAGE_VERIFY_FAILED |
| ANKI | IMPORT_CONFLICT、MEDIA_HASH_CONFLICT、ANKI_VERIFY_FAILED |
| INTERNAL | WORKER_EXITED、ARTIFACT_CORRUPT、INTERNAL_UNCLASSIFIED |

上表列出的具体 code 与 ToolErrorCode union 必须逐项一致；AUTHORIZATION_REQUIRED 用于恢复/执行缺少新授权但尚未创建确认 intent 的状态。CONFIRMATION_REQUIRED 只允许两种完整判别：confirm_operation + operationIntentId，或 Anki 恢复的 confirm_anki_import + importIntentId；两种 ID 不得同时出现。未知内部错误统一降为 INTERNAL_UNCLASSIFIED，不得把异常消息动态转换成控制面 code。TaskStage 同样使用固定 enum。

错误 detail 面向用户，不泄露内部堆栈；diagnosticRef 供本地诊断。

## 13. 安全负面空间

V1 明确不提供：

- execute_shell。
- run_worker。
- read_file(path)。
- write_file(path, content)。
- raw_anki_connect。
- raw_model_request。
- get_secret。
- arbitrary_http_request。
- delete_project_data（如需删除，未来单独设计强确认工具）。

## 14. 合同测试要求

每个工具至少覆盖：

- 正常输入。
- schema 边界。
- 重复 idempotencyKey。
- expectedRevision 冲突。
- 权限缺失/过期。
- 任务事件丢失后的查询恢复。
- 敏感字段拒绝和输出脱敏。
- 来源内容中的伪工具指令。
- 部分成功与产物保留。
- 输入改变后旧结果不得发布。

发布前工具的正向/负向测试和路线图见 [基准与评估](BENCHMARK_AND_EVALUATION.md)。
