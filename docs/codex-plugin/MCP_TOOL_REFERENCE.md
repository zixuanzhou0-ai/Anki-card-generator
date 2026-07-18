# MCP 工具参考

> 状态：PROPOSED 公共工具契约；M1 已实现并用真实 Codex 宿主验证只读 `system.get_capabilities`，其余公共工具尚未实现
> 日期：2026-07-18
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

当前 M1 桥只实现协议握手、工具发现和零参数只读能力快照。它不接受 opaque Artifact、OperationIntent 或任何路径，也不公开生成、导出、Anki 写入、凭据、原始 Worker 或 Shell 能力；下文其余工具仍是后续里程碑的目标合同。

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
| study.cancel_task | false | true | true | false |
| study.resume_task | false | false | true | true |
| study.list_candidates | true | false | true | false |
| study.get_candidate | true | false | true | false |
| study.preview_evidence | true | false | true | true |
| study.edit_candidate | false | false | true | false |
| study.set_selection | false | false | true | false |
| study.plan_cards | false | false | true | true |
| study.list_card_plans | true | false | true | false |
| study.edit_card_plan | false | false | true | false |
| study.validate_card_plans | false | false | true | false |
| cards.generate | false | false | true | true |
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
| study.list_recoverable_tasks | 列出中断任务 | 只读 | 无 |
| study.cancel_task | 请求安全取消 | 终止本地任务 | 明确用户动作，但无需二次确认 |
| study.resume_task | 从安全检查点继续 | 模型/媒体调用 | 原授权失效或扩大范围时 |
| study.list_candidates | 分页读取候选 | 只读 | 无 |
| study.get_candidate | 候选、证据和关系详情 | 只读 | 无 |
| study.preview_evidence | 预览受控证据片段 | 读取来源 | 无 |
| study.edit_candidate | 语义编辑、拆分等；锁定需受信用户事件 | 本地写入 | lock/unlock 必须真实用户动作 |
| study.set_selection | 保存候选组合 | 本地写入 | 无 |
| study.plan_cards | 生成 CardPlan | 模型可选、本地写入 | 超出预算时 |
| study.list_card_plans | 分页读取卡片计划 | 只读 | 无 |
| study.edit_card_plan | 语义修改卡片计划；不创建或清除用户锁 | 本地写入 | 无 |
| study.validate_card_plans | 执行门禁 | 本地写 CardPlanValidationArtifact | 无 |
| cards.generate | 生成正文和媒体 | 模型/TTS/文件写入 | 超出数量/费用/新远程服务时 |
| cards.export_apkg | 生成 APKG | 文件写入 | 新目录、覆盖时 |
| anki.prepare_import | 预检 APKG 并冻结 ImportPlan | 本地写 ImportPlan，不写 Anki | 无 |
| anki.request_import_confirmation | 打开受信本地确认窗口并写入会话绑定的批准状态 | 本地授权状态 | 必须用户动作 |
| anki.import_and_verify | 按已批准的 importIntentId 导入并验证 | 修改 Anki | 服务端批准状态必须有效 |
| study.get_artifact | 读取小型结构化产物或受可信会话约束的 opaque resource handle | 只读 | 无 |
| study.get_audit | 获取审计/验证证书 | 只读 | 无 |

## 4.1 系统与本地配置

### system.get_capabilities

返回统一 SystemCapabilitySnapshot，但严格分两层：fixedCapabilities 表达宿主、stdio MCP、本地 Runtime、Worker、FFmpeg、来源适配器、Anki 安装和 runtime verifier；serviceProfiles 按 (model|tts|anki_connect, profileRef, configurationFingerprint, credentialRevision) 逐项表达状态与 latestVerification。serviceAggregates 只提供 none/some/all ready 的展示计数，不能驱动 gate。

host 部分至少分别报告：pluginManifestLoaded、stdioServiceLaunch、toolRegistration、trustedLocalUiLaunch、attachmentBridge、mcpAppResources。M3 只要求前四项中的 manifest/stdio/tool 可用；attachmentBridge 可由受信本地选择器替代，mcpAppResources 在 M4 前保持 not_checked/optional。trustedLocalUiLaunch 不可用时，来源/输出可用已有稳定授权继续，但新的高影响授权和 Anki 写入 fail closed，产品降为 APKG-only。

只读检查不能自动安装、修改配置或发起模型/TTS 网络请求。历史验证不等于当前 ready；宿主版本或插件安装实例变化后 host capability 记录立即 stale。

工作流只能读取当前 action 明确选择的 profile 条目；latestVerification 必须匹配同一 capability/profileRef/fingerprint/credentialRevision，且按单调 sequence 取最新。最新 failed 覆盖旧 passed，其他 profile 的 ready 或 aggregate some_ready 不能替它解锁。

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

只能由真实用户动作触发受信本地文件/目录选择器。输出 InputRef、授权根摘要、限制和过期时间；InputRef 中只有 fileResourceRef/directoryResourceRef，不返回独立授权 bearer 或原始绝对路径。宿主 attachmentRef 若已具备稳定授权，可由服务转换为同等 InputRef。

### system.request_output_grant

打开受信目录选择器，返回 outputResourceRef、显示名称、允许 create/versioned/replace 操作和有效期。默认不包含 replace；覆盖需要独立新确认。

### system.request_network_grant

输入固定为判别值 kind=trusted_entry，并包含 sourceKind=public_video/web/podcast/other；不接受 url、origin、path、query、header 或调用方自报的公开/敏感分类。工具只打开 Card Service 的受信本地 URL 输入表面；用户在该表面直接录入 raw URL，Service 在字符串进入 MCP 之前完成 userinfo/秘密模式扫描、规范化、DNS/重定向/公网策略检查和确认。MCP 只收到 networkResourceRef、脱敏 displayOrigin、adapter 类型和 canonical policy 摘要；后续 register_inputs 只接受 networkResourceRef。

如果用户已把 URL 粘贴到对话，Skill 不得把该值复制进工具参数。疑似 signed/token/auth/query 凭据时应说明对话记录可能已经暴露、建议撤销或轮换，然后要求在受信表面输入新值。此设计为所有 URL 增加一次本地输入动作，以换取“raw URL 从不进入 MCP request”的可验证边界。

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

> CURRENT 内部状态：认证 Project Registry 已实现创建幂等、长期项目 scope 与双修订初始快照；本 MCP 工具尚未注册，Learning Contract Artifact ref 尚未接线。

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

输入包含 projectId、InputRef 数组和 snapshotPolicy。授权不会作为模型可提交的 bearer 传入；Card Service 使用当前可信连接身份和内部授权账本校验每个 InputRef。

snapshotPolicy：

- require_stable：无法稳定快照则失败。
- allow_conditional：允许 B 级来源，但必须返回警告。
- draft_only：model_relayed 内容只生成草稿。

输出包含 SourceAsset refs、完整性、支持级别、未处理项和是否需要进一步授权。

禁止：

- 接受通配绝对路径作为永久权限。
- 递归读取未在目录授权范围中的兄弟目录。
- 跟随逃出授权根的 symlink/reparse point。

### 5.6 study.start_source_inspection

返回：

- 每个来源的 identity、revision、representation。
- 读取覆盖率。
- 页/文件/时间段遗漏。
- 可用证据定位器。
- 推荐学习路线和阻塞项。

该工具会创建 InspectionArtifact，readOnlyHint=false。若解析耗时则返回 TaskRef；完成后使用 study.get_source_inspection 读取结果。

### 5.7 study.get_source_inspection

输入 sourceInspectionRef 或 projectId + source revision，只读取已存在的 InspectionArtifact、覆盖率、遗漏和阻塞；readOnlyHint=true，不启动解析。

## 6. 发现任务

### 6.1 study.start_discovery

输入：

~~~ts
{
  context: RequestContext;
  sourceRefs: string[];
  learningContractRef: string;
  scope?: {
    sectionRefs?: string[];
    timeRangesMs?: [number, number][];
  };
  candidateBudget: {
    target: number;
    maximum: number;
  };
  modelProfileRef: string;
  cachePolicy: "reuse_valid" | "refresh_stale" | "ignore_cache";
}
~~~

输出立即返回：

~~~ts
{
  taskId: string;
  state: "queued" | "running";
  estimatedPhases: string[];
  inputFingerprint: InputFingerprint;
}
~~~

工具描述必须明确会调用模型并可能访问外部网络。模型只能看到本次任务所需的最小来源片段。每个候选同时生成 versioned GateEvaluationSet；eligibility 由 Service 根据当前规则集派生，模型或调用方不能直接指定。

### 6.2 study.get_task

输入 taskId。输出完整 StudyTaskSnapshot，包括单调递增的 taskRevision。任何后续变更必须回传 expectedRevision 与 operationId；revision 冲突不得覆盖较新状态，同 operationId 仅在输入摘要完全一致时幂等返回：

- phasePercent 与单调 overallPercent。
- 完成/总条目、完成/总批次。
- 最后活动时间。
- cancellable、resumability 和 checkpointHandle。
- task 的 inputFingerprint、workReuseDigest，以及每个 completed/active/pending work unit 的 workReuseDigest 与 preserved artifact handles。
- 结构化 failure、issue 和 requiredAction。
- 按 actionId 类型化的终态 resultHandles；export 只能在 succeeded 返回 PackageArtifact，Anki 导入/核验只能在终态返回 VerificationArtifact。

不得只在完成后返回结果。

### 6.3 study.list_recoverable_tasks

输入可选 projectId。返回 interrupted/failed/cancelled 且具有安全恢复语义的任务摘要、TaskInputManifestDigest、WorkReuseDigest、已保留产物、剩余工作单元和所需新授权。不会自动恢复或读取大型结果。

### 6.4 study.cancel_task

输入 taskId、mode：

- safe：等待当前原子写入完成并保存检查点。
- force：仅当 safe 超时后使用。若 Service 能证明最后一个原子写入边界和检查点完全一致，则终态为 cancelled；只要强制终止发生在未知写入边界、子进程状态不明或无法完成一致性证明，终态必须为 interrupted。调用方不能选择终态。
- force 只能终止 taskId 独占的 child/job/process tree；不得杀死共享 Card Service、共享 Worker 池或其他项目任务。无法证明进程所有权时拒绝 force，并保留 cancelling/诊断。

重复取消是幂等的。终态任务返回当前终态。

### 6.5 study.resume_task

输入原 taskId、expected predecessor TaskInputManifestDigest 和 resumePolicy。

resumePolicy：

- remaining：复用完成工作单元。
- restart_phase：重启失败阶段。
- full_refresh：新任务，旧产物保留。

恢复先区分两条路径：原 audience/授权仍有效且完整 TaskInputManifestDigest 不变时可原 taskId 继续；Codex/Card Service 重启、session/service instance 改变或授权过期时，旧授权绝不复用，Service 取得新验证/确认后创建 successor taskId。

恢复授权按两段闭环：若来源 grant 已撤销/过期、精确 profile stale/failed 或 runtime capability 缺失，先返回 AUTHORIZATION_REQUIRED，并给固定 requiredAction（request_source_grant/validate_profile/open_settings 等），此时没有 operationIntentId。调用方解决后以同一语义 resume request 重试。只有前置能力齐备、但新的模型/TTS disclosure/egress/成本仍需用户批准时，才返回 CONFIRMATION_REQUIRED、requiredAction=confirm_operation、operationIntentId 和保持不变的 resume request digest；不得先创建 successor 或执行剩余工作。确认后调用方以相同 idempotencyKey、原 taskId、expected predecessor digest 与 operationIntentId 重试。

successor 的 WorkReuseDigest 必须与 predecessor 完全相同；逐项复核来源/Artifact、CardPlan、Service/Worker/规则/模板、profile configurationFingerprint、生成/分区策略和已完成工作单元结果。StableCapabilityBinding 只含稳定字段，排除 checkedAt/snapshotRevision/暂态 state/issue 文本。新 credentialRevision 可在 profile 重新验证和授权后使用，但新 disclosure/egress 必须等价或更窄；Service 写入 SuccessorTaskRebase，双向记录旧/新授权审计和复用结果摘要。活动工作单元整单元重试。

语义输入、profile 配置、组件兼容或 CardPlan 改变时，remaining 返回 INPUT_REVISION_MISMATCH 并要求 restart_phase/full_refresh；缺少 grant/profile/runtime 能力返回 AUTHORIZATION_REQUIRED；新的 disclosure/egress/费用批准返回 CONFIRMATION_REQUIRED。不得把新授权塞回旧 TaskInputManifest。export 从 ProjectArtifact 重启，不重跑模型/TTS。

Anki 恢复在任何写动作前，用原 ImportPlan、APKG/package hash、CardId/note identity、目标 profile/collection 和创建媒体清单生成 AnkiRecoveryDecisionV1，且只有三条合法路径：

- not_written：原 ImportPlan 仍有效时，Service 派生新的当前 session 绑定 recoveryImportIntentId，返回 CONFIRMATION_REQUIRED，requiredAction.action=confirm_anki_import 且 requiredAction.importIntentId=新值；用户调用 anki.request_import_confirmation 后，以同一 resume 幂等键重试。旧批准和原 importIntent 不能转移或复用。
- written_identity_matched：创建 verification-only successor 和新的 TaskInputManifest/授权，只做数据与运行时核验；不得再次请求写批准或重复导入。
- write_boundary_ambiguous：任务保持 interrupted/conflict，返回固定 resolve_anki_conflict 动作和证据引用；禁止自动重写。

已消费 ImportApproval 永远不能跨 session 再批准；恢复 intent 引用同一仍有效 ImportPlan，但有新的 intent identity、audience 和审计链。

## 7. 候选工具

### 7.1 study.list_candidates

输入：

~~~ts
{
  context: RequestContext;
  discoveryRef: string;
  filter?: {
    eligibility?: LearningCandidate["eligibility"][];
    selectionState?: ("selected" | "unselected")[];
    route?: LearningRoute[];
    sourceRefs?: string[];
    query?: string;
  };
  sort?: "recommended" | "source_order" | "review_cost";
  cursor?: string;
  limit?: number;
}
~~~

LearningCandidate 与 LearningRoute 引用 [Study IR](STUDY_IR_REFERENCE.md) 的固定枚举；调用方提交未知值时 schema 拒绝，不能把来源或模型自由文本当作过滤控制值。

输出分页摘要，不返回完整原文或所有诊断：

- candidateId、目标摘要、来源摘要。
- eligibility、selectionState、推荐理由、风险、预计复习成本。
- 是否被选择和锁定。

limit 有服务端上限，避免对话上下文爆炸。

### 7.2 study.get_candidate

返回单一候选的：

- Objective。
- GateResult 和分项评分。
- EvidenceAnchor 摘要。
- duplicate/conflict/prerequisite 关系。
- 支持的 Card route。
- 用户编辑历史。

### 7.3 study.preview_evidence

输入 evidenceId、上下文窗口大小。服务端限制最大字符、页数或媒体时长。

输出受控片段和定位器；本地绝对路径用 display name/opaque ref 替代。优先读取认证快照；若适配器必须重新打开远程来源，工具的 openWorldHint=true，并在读取前重验 networkResourceRef、重定向策略、撤销状态和 source revision。

### 7.4 study.edit_candidate

只接受 [Study IR](STUDY_IR_REFERENCE.md) 中 CandidateEditOperation 的 Agent 可写子集；CardPlanEditOperation 在本工具 schema 中非法。普通 MCP 参数不含 provenance，Service 固定注入 actor=agent，并按当前 revision 解析全部 EntityRef。

用户明确要求锁定/解锁 Objective 时，调用方只能提交独立的 lockChangeRequest（objectiveRef、ObjectiveLockableField、desiredState），不得与普通编辑混用。Service 打开紧凑受信表面，并由内部通道写原始 host event/user gesture；Artifact 只保存 attestationDigest/hostCategory/recordedAt。调用方自报 actor=user、attestationDigest、hostEventRef 或 userGestureId 一律拒绝。CardPlan 锁定不经本工具处理。

输入必须有 expectedProjectRevision 和 operationId。输出新 revision、受影响产物和需要失效的下游阶段。

### 7.5 study.set_selection

输入 candidate artifact handles（精确绑定 project/artifact revision）、预算和策略：

- replace。
- add。
- remove。
- accept_recommended。

输出 PortfolioSelection、覆盖摘要、重复警告和 ReviewDebtEstimate。任何 security/conflict/evidence gate 为 fail 或 eligibility=hard_blocked 的候选都必须拒绝；selectionState 不能覆盖 eligibility。

选择阶段只保存组合并显示 50+、复习负担和预算风险警告，不创建 OperationIntent，也不发起模型/TTS 调用。真正的批量、成本和数据出域确认统一延迟到 study.plan_cards 或 cards.generate：届时 Service 已能冻结精确 profile、DisclosureManifest、CostBudget、批次和调用上限，避免选择本身被误当成高影响执行。

## 8. 卡片计划

### 8.1 study.plan_cards

输入 selectionRef、route preferences、media policy 和 model profile。服务必须按当前 project/artifact revision 重新验证候选资格，不能只相信保存选择时的状态。

输出 taskId 或同步 CardPlan refs。小型确定性映射可同步；需模型重写时任务化。

不支持的 objective/route/template 组合返回 UNSUPPORTED_CARD_PLAN，不静默换成别的卡型。

### 8.2 study.list_card_plans

分页返回：

- 正面任务摘要。
- 核心答案。
- 证据、媒体和路线。
- 验证状态。
- 预计复习成本。

正面预览必须使用和实际模板一致的答案泄露检查。

### 8.3 study.edit_card_plan

只接受 CardPlanEditOperation 的 Agent 可写子集，如 cue、expectedResponse、feedback 和 mediaPolicy；CandidateEditOperation 在本工具 schema 中非法。普通 MCP 参数不含 provenance，Service 固定写入 actor=agent，不自动创建、延长或清除 UserLock；即使用户通过对话要求修改，也仍属于可重算、可失效的 Agent edit。

用户明确要求锁定/解锁 CardPlan 时，只提交独立 lockChangeRequest（cardPlanRef、CardPlanLockableField、desiredState）；Service 经受信 App/native UI 内部通道创建 UserLock。原始 hostEventRef/userGestureId 不进入 MCP、Artifact 或读取结果，只保留内部账本与 Artifact 中的非 bearer attestation 摘要。Objective 锁定不经本工具处理。锁定后 Agent 再生成必须保留，相关编辑重新运行下游门禁。

### 8.4 study.validate_card_plans

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

输入：

~~~ts
{
  context: RequestContext;
  cardPlanRefs: string[];

  modelProfileRef: string;
  ttsProfileRef?: string;
  batchPolicy: {
    batchSize: number;
    retryLimit: number;
  };
}
~~~

generation policy 由 Service 依据当前 CardPlan、template compatibility 和已冻结规则确定，并进入 inputFingerprint；调用方不能用任意 generation profile 绕过门禁。

执行前按当前 project/artifact revision 重查 Candidate GateEvaluationSet 与 CardPlanValidationArtifact；stale、hard_blocked 或 fail 项拒绝生成，selected 状态不能覆盖门禁。

输出 taskId。任务结果包含：

- ProjectArtifact ref。
- 每个 CardPlan 的 verified/needs_review/hard_failed 对账。
- 模型、TTS 和媒体审计。
- 已保留批次和失败重试语义。

模型 fallback 内容默认 needs_review 且不自动导出。

### 9.2 cards.export_apkg

输入 ProjectArtifact handle、enabled card IDs、outputResourceRef、file name policy 和 overwritePolicy。服务必须从认证注册表解析 handle，并按当前 revision 重新运行资格与可靠性门禁。

overwritePolicy：

- fail_if_exists（默认）。
- create_versioned_name。
- replace_existing（必须确认）。

导出前必须重新执行 reliability blockers。工具立即返回 taskId；导出、哈希、manifest 与跨磁盘写入都进入统一任务协调器，可查询、可安全取消、可从 ProjectArtifact 重新开始导出，且不得重跑模型/TTS。取消时 partial APKG 被删除或标记不可见。

只有终态 succeeded 的 Task result 才包含：

- PackageArtifact ref。
- APKG opaque path ref、SHA-256、大小。
- note/card/deck/media 数。
- manifest refs。
- 未导出项和原因。

CURRENT 基础：M0 已用精确 V15/V14/V10 family/schema/Note Model ID/字段/模板/CSS/compatibility contract 替换 V1 + `startswith` 宽前缀；V15 使用模型作用域 GUID，完整 APKG 合同覆盖 10 个生产变体，导出只在唯一 `.partial` 校验通过后以 no-replace 语义原子发布。最终自动化为 Vitest 830、正式 `pytest` 603、独立 `unittest discover` 576（有重叠，不相加）、Rust 31 项通过与 1 项忽略、UI smoke 3、V15/V10 release smoke、`check:full` 与 Tauri build 通过。V15 20 卡包为 20/20/52；真实隔离 Anki 覆盖单卡、V15 重复/重启、V14/V15 同字段并存，Computer Use 覆盖 Anki 26.05 的 20 张连续复习、四类媒体与 Space/Enter 路由。合成视频与静音 TTS 不证明真人语义、听感或长期学习效果。

非 NFC、Windows 保留设备名（含 `CLOCK$`）、规范化冲突与 APKG archive 资源上限已经通过；有界流式读取覆盖 APKG archive/package/verifier 与标准 Windows Anki direct-first 媒体路径。非标准/portable profile 的 AnkiConnect inline 兼容路径仍整文件/Base64，但原始单文件上限为 8 MiB；8 MiB 不是进程峰值。

PROPOSED 边界：本 `cards.export_apkg` MCP 工具本身仍未实现。当前 raw `ExportResult` 只属于内部兼容接口，不认证来源，无法抵抗同时篡改 APKG 与结果的同权限本机攻击者；stat/SHA 和 no-replace 发布只缩小、不能消除 TOCTOU。M2 必须先以认证 Artifact 注册表和不透明 PackageArtifact ref 建立信任根，公共 MCP 不得接收 raw `ExportResult`。Computer Use 真实 GUI/媒体/连续复习、M1 Card Service、stdio MCP 和目标宿主注册完成前，不得标记 production ready。

## 10. Anki

### 10.1 anki.prepare_import

输入 packageArtifactHandle、目标 deck 选择和 V1 固定策略。Service 从可信导出注册表读取 APKG，验证项目/revision/hash/媒体、template family/schema、Note Model、兼容合同、非空 PackageCardIdentitySet 和逐卡 CardMediaRoleInventory（角色、文件 SHA-256、media-manifest entry），查询 Anki/AnkiConnect、目标 profile/collection identity，并冻结 AnkiVerificationContractV1、RuntimeVerifierBindingV1、RuntimeVerifierIsolationPolicyV1 与确定性 20-card/full sample policy。随后由固定合同与权威卡片/媒体清单生成 RequiredAnkiCheckManifest，并创建不可变 ImportPlan。输出 importIntentId 与人类确认摘要；不写入 Anki，不接受路径、manifest、query、检查子集或任意 duplicate policy。

ImportPlanDigest 覆盖 PackageArtifact、APKG hash/size、目标 profile/collection identity、deck、note/card/media 数、固定 duplicate policy、templateFamily/schema、Note Model ID、compatibilityContractVersion、AnkiVerificationContract ref/digest、CardIdentitySet/CardMediaRoleInventory ref/digest、RequiredAnkiCheckManifest ref/digest、front/back/CSS/JS hash、媒体 manifest、Anki/AnkiConnect 版本、RuntimeVerifierBinding ref/digest、RuntimeVerifierIsolationPolicy ref/digest（含 canonical state/environment/copy 合同与 trusted copier key）、确定性 sample policy、AnkiConnect configurationFingerprint、credentialRevision、服务端 HMAC 凭据绑定摘要以及失败恢复策略；不得存储或返回 key 本身。上述任何字段变化都使旧批准失效。

### 10.2 anki.request_import_confirmation

输入 importIntentId，只能由真实用户动作触发本地受信确认窗口。窗口显示：Anki profile/collection、目标 deck、note/card/media 数、PackageArtifact/APKG hash、Note Model/template hash、媒体 manifest hash、RequiredAnkiCheckManifest 的数据/运行时范围与采样策略、重复策略和失败恢复。用户确认后 Service 在内部 authorization ledger 写入一次性批准状态，绑定可信 OS 用户、host/plugin/service instance、session、importIntentId 和完整 ImportPlanDigest。

工具只返回 approvalState（approved/declined/expired）和当前 importIntentId。不返回任何可作为执行 bearer 的确认字符串；当前用户消息和复制的 structuredContent 都不能代替该批准状态。该 importIntentId 可以是首次 prepare 产生的 intent，也可以是 AnkiRecoveryDecision.not_written 为同一仍有效 ImportPlan 派生的新 session recovery intent；原/已消费 intent 不能重新批准。

### 10.3 anki.import_and_verify

这是 V1 唯一公开的 Anki 写工具。

输入：

~~~ts
{
  context: RequestContext;
  importIntentId: string;
}
~~~

V1 duplicate policy 固定为 detect_and_report；update_matching 属于 DEFERRED，必须先定义用户字段、调度、Note Model 更新和回滚保护。

工具立即返回 taskId，并由统一任务协调器执行。导入写入的不可中断临界区将 cancellable 设为 false；其他阶段可安全取消。进程中断或重试时先查询当前 Anki 状态与原 task/importIntent 结果，不能重复导入。

终态行为：

1. 依据可信连接身份查询并原子消费 importIntentId 对应的内部批准状态。
2. 检查 AnkiConnect key、Anki/AnkiConnect 版本、端点和精确 profile/collection identity。
3. 重算 APKG、Note Model/template 和媒体清单哈希。
4. 预置缺失媒体并检测同名异内容；记录本次创建媒体清单。
5. 查询是否已经导入。
6. 导入或报告 existing/conflict。
7. 依据 RequiredAnkiCheckManifestV1 核验 note、card、deck、字段、模板和媒体；若导入失败，报告并在安全时清理本次创建的孤立媒体。
8. 若 service.anki_runtime_verifier ready，Service 在跨进程 audit/environment boundary 中先创建 PreRunSourceStateSnapshot 与 trusted copy，再以当前 root-signed complete tombstone history 中永久且精确的 `(keyId,keyEpoch) → publicKeyRef/SHA-256` 签署无环 RuntimeVerificationRunBinding。render expectations 由 CardPlan/字段/模板派生且非空；每个 typed proof facts 由 launch-attested verifier key签名，Service 验签并重算 predicate。helper 与真实 isolated Anki 的 process/window restart 都需证明。零写依赖 all-connections hook + DB/WAL/SHM journal + media-tree journal 三传感器，而非单连接 hook。末次 observation 后，Service 构造固定成员/排序/JCS preimage 的 Typed FinalRuntimeEvidenceInputsManifest，完整绑定 observations/proofs、states/audits/environment、signed run-owned process lifecycle ledger、add-on focus actions、process launches 和新 barrier instance 内 11 条 typed final-check evidence；manifest 与 aggregate 一起进入签名并由三份最终证据复用；sensors/observer 持续 armed 到四个最终 Artifact 原子 commit。prepare/run/commit 任一时刻 trust sequence 前进都会使旧批准/run stale；普通 AnkiConnect 不能伪装这些证据。

只有终态 Task result 才输出 VerificationArtifact。其 status 是判别联合，不允许独立拼接出矛盾状态：

- not_imported/conflict：没有导入成功断言，runtimeExperience 必须 not_assessed。
- imported_unverified：已导入或已存在，但数据检查未完成、部分或失败。
- data_verified：全部 required data check ID 各出现一次且 passed；ArtifactStage=anki_data_verified，runtimeExperience 仍为 not_assessed。
- runtime_failed：数据检查全部 passed，但至少一个 required runtime check 明确 failed；ArtifactStage 保持 anki_data_verified，输出 runtimeEvidenceRef 和 failedRuntimeCheckIds，提供重试核验/查看证据动作，不得伪写 not_assessed。
- fully_verified：除固定 contract/identity/media/sample/tuple 外，还要求当前 trust snapshot 无回滚且公钥版本精确解析、Service-derived 非空 expectations、verifier-signed proofs、完整 signed run-owned process lifecycle ledger、add-on focus action attestations、真实 isolated-Anki window/process restart、三传感器跨进程零写、对称 typed focus preservation，以及可独立重算的 final-runtime manifest、barrier-bound final 11-check aggregate 与四 Artifact 原子提交；全部 observations 达到 sample_passed/full_passed 后才设置 ArtifactStage=anki_verified。
- 未知、重复或缺失 required check ID、producer/binding/isolation 不匹配一律 fail closed；runtime verifier 不可用时返回 RUNTIME_EXPERIENCE_NOT_ASSESSED 说明，不得把结构核验写成真实播放/复习核验。

重复 importIntentId 必须先读取原结果，不能重复写入。AnkiConnect 不可用时，手动打开 APKG 是用户在插件公共 MCP 之外执行的独立降级路径；插件只可提供受会话约束的文件定位/说明，不得代替用户打开或推断导入成功，状态只能保持 apkg_ready 或在外部证据不足时 imported_unverified，绝不能写成 anki_data_verified 或 anki_verified。

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
