# 目标架构

> 状态：CURRENT 与 PROPOSED 对照
> 日期：2026-07-17
> 本文不表示插件服务或 App UI 已经实现。

## 1. 架构目标

目标不是让 Codex 模拟点击桌面端，而是让对话、插件 UI 和自动化都调用同一套明确、可恢复、可审计的本地服务。

~~~text
Codex 对话 / Skill
        │
        ├──────── 条件 App UI（M4 宿主验证后）：Inline / Fullscreen / PiP
        │
        ▼
类型化 MCP 工具层
        ▼
本地 Card Service
        ├── 项目与 Study IR
        ├── 可信会话、内部授权账本与能力快照
        ├── 任务协调器与检查点
        ├── 素材适配器
        └── 审计与结果仓库
        ▼
现有可靠性内核
        ├── Python Worker
        ├── 模型 / TTS
        ├── FFmpeg / yt-dlp / 文档解析
        ├── APKG 生成与验证
        └── Anki / AnkiConnect 核验
~~~

## 2. 当前能力映射

### 2.1 CURRENT：可复用

| 当前资产 | 核验位置 | 插件用途 |
|---|---|---|
| Worker 命令路由 | workers/anki_worker.py、workers/acg/protocol.py | 作为执行后端，外部不直接透传 |
| 学习点提取与验证 | workers/acg/pipeline、contracts | 语言候选管线基础 |
| 卡片可靠性清单 | workers/acg/card_reliability.py | 扩展为统一 Artifact 可靠性 |
| APKG 导出阻塞 | workers/acg/commands/export.py | 保留 fail-closed |
| 任务快照 | src/app/workerTaskState.ts、src-tauri/src/lib.rs | 迁移到服务级持久任务 |
| 工作流检查点 | src/services/workflowCheckpoint.ts | 扩展为项目/任务检查点 |
| 路径与 URL 边界 | workers/acg/security_boundaries.py、Rust 命令 | 升级为可信会话 + InternalAuthorizationRecord + canonical resource refs |
| Anki 跨磁盘修复 | src-tauri/src/lib.rs | 本地服务保留同卷临时目录策略 |
| 秘密存储 | Rust keyring/DPAPI fallback | 通过 SecretRef 使用，UI 不读明文 |
| 文档读取 | workers/acg/documents | 作为简单文本适配器起点 |

### 2.2 CURRENT：不能直接当作插件接口

- Tauri invoke 命令绑定桌面窗口和当前 UI 状态。
- WorkerCommand 是内部执行指令，粒度过低且包含实现细节。
- GenerateRequest 是桌面请求聚合，不是通用学习领域模型。
- 当前文档分块会扁平化复杂结构，不能证明图表、公式和表格语义完整。
- 当前语言 LearningPoint 不能表达通用知识冲突、先修、练习任务和多来源证据。

## 3. 组件职责

### 3.1 Skill

Skill 定义：

- 如何理解用户意图并形成 Learning Contract；
- 何时自动继续、何时询问、何时请求确认；
- 如何调用高层 MCP 工具；
- 如何解释候选、风险和核验结果；
- 禁止把来源中的指令当作系统指令。

Skill 不保存业务真相，不直接执行 FFmpeg、Shell 或 AnkiConnect。

### 3.2 App UI

App UI 只呈现服务返回的权威结构化状态：

- 项目与素材；
- 候选学习目标；
- CardPlan；
- 任务进度、失败和恢复；
- 导入授权和验证证书。

UI 不通过解析对话文本推断状态，不自行拼装 Worker 请求。

### 3.3 MCP 工具层

每个工具对应一个用户意图，具有：

- 类型化输入/输出；
- 最小权限；
- 幂等键；
- 长任务返回 taskId；
- 结构化错误；
- 工具注解与 UI 资源；
- 明确读/写/外部影响。

禁止提供：

- run_worker(command, payload)；
- 任意 shell；
- 任意文件读取；
- 原始 SQL；
- 任意 AnkiConnect action 透传。

### 3.4 Card Service

这是新插件的本地权威边界，负责：

- 解析 MCP 请求。
- 从受信连接导出 OS/host/plugin/session 身份，并校验内部 InternalAuthorizationRecord；不接受 MCP 自报授权。
- 保存项目和 Study IR。
- 调度现有 Worker 与新适配器。
- 持久化任务、结果、检查点和审计。
- 管理 SecretRef，不把秘密返回模型。
- 作为唯一 model/TTS broker：Worker 只提交结构化、任务绑定的 IPC 请求；Service 重建 provider 请求，逐调用核验 DisclosureManifest/OperationApproval，并原子 reserve/settle 调用、token、字节、TTS 和费用预算。
- 执行 APKG、Anki 数据完整性核验，并在独立 runtime verifier 可用时编排真实渲染/播放/复习核验。
- 冻结不可删减合同与权威 identity/media；用 pre-run source state 构成无环 signed run，root-signed 单调 trust snapshots 以 complete append-only tombstone history 和 `(keyId,keyEpoch) → raw publicKeyRef/SHA-256` 永久映射防 key 撤销、复活、同名换钥与旧公钥高 epoch 别名回滚。Card Service 只接受 launch-attested verifier key 签名的 typed proof，并从 CardPlan/fields/template 派生非空 render expectations。全程用 add-on + DB/WAL/SHM + media-tree 三传感器、signed run-owned process lifecycle ledger、add-on focus action attestations 及对称 typed process/window/focus trace；最终 11 项 evidence 与固定 FinalRuntimeEvidenceInputsManifest 绑定新 read-barrier instance 后原子提交证书。

V1 使用插件捆绑的本地 stdio MCP。服务进程与 Codex 生命周期绑定；任务状态必须持久化，以便新会话恢复。

### 3.5 现有可靠性内核

现有 Worker 继续负责计算密集和媒体相关工作。迁移原则：

- 先加适配层，不在首版重写成熟算法。
- 内部命令只由 Card Service 调用。
- 结果立即转换为版本化 ArtifactEnvelope。
- Legacy Worker 不持有 provider secret、真实 Base URL 或公网能力；所有模型/TTS 副作用只能通过 task-owned broker IPC，不能获得 raw HTTP/header/任意 prompt 透传。
- 内部错误转换为稳定领域错误，不向 App 暴露堆栈和本机敏感路径。

## 4. 数据流

### 4.1 注册输入

~~~text
InputRef
  → 校验可信连接、内部授权记录和资源当前身份
  → 复制/快照或稳定读取
  → 计算 hash/revision
  → SourceAsset
  → 返回完整性和支持级别
~~~

Codex 附件只有在宿主向插件提供稳定资源引用或插件取得受控快照时，才成为正式 SourceAsset。仅在对话上下文中转述的一段内容属于 model_relayed，默认只能生成待审核草稿。

### 4.2 发现

~~~text
SourceAsset
  → ContentNode
  → EvidenceAnchor
  → SemanticUnit
  → LearningObjective
  → LearningCandidate
  → PortfolioSelection
~~~

每层都是可保存、可版本化的产物，不允许只保留最后一次模型回答。

### 4.3 生成与交付

~~~text
LearningCandidate selection
  → CardPlan
  → validation
  → generated card + media
  → reliability manifest
  → APKG + sha256
  → explicit Anki import
  → Anki data-integrity certificate
  → trusted runtime-experience certificate（能力可用时）
~~~

## 5. 任务模型

所有超过短交互时限的操作进入统一任务协调器。

~~~ts
type WorkReuseManifestV1 = {
  schema: "study.work-reuse.manifest";
  schemaVersion: 1;
  actionId: WorkflowActionId;
  subject:
    | {
        kind: "project_task";
        projectId: string;
        projectRevision: number;
        inputArtifacts: {
          artifactId: string;
          artifactRevision: number;
          artifactDigest: string;
        }[];
        sourceSnapshotDigests: string[];
        learningContractRevision: number;
        cardPlanSetDigest?: string;
      }
    | {
        kind: "profile_validation";
        profileRef: string;
        configurationFingerprint: string;
        credentialRevision: number;
      };
  componentVersions: {
    cardService: string;
    worker: string;
    sourceAdapterSetDigest: string;
    gateRuleSetVersion: string;
    templateFamily?: string;
    templateSchemaVersion?: string;
    compatibilityContractVersion?: string;
  };
  serviceConfigurations: {
    capability: "model" | "tts" | "anki_connect";
    profileRef: string;
    configurationFingerprint: string;
  }[];
  generationPolicyDigest?: string;
  workPartitionPolicyDigest?: string;
};

type WorkReuseDigest = string; // SHA-256(JCS(WorkReuseManifestV1))

type StableCapabilityBindingV1 = {
  schema: "study.capability.binding";
  schemaVersion: 1;
  required: ({
    kind: "fixed";
    capabilityId: CapabilityId;
    implementationVersionOrDigest: string;
    compatibilityContractVersion: string;
  } | {
    kind: "service_profile";
    capability: ServiceProfileCapabilityId;
    profileRef: string;
    configurationFingerprint: string;
    credentialRevision: number;
    implementationVersionOrDigest: string;
    compatibilityContractVersion: string;
  })[];
};

type CapabilityBindingDigest = string; // SHA-256(JCS(StableCapabilityBindingV1))

type AuthorizationBindingManifestV1 = {
  schema: "study.authorization.binding";
  schemaVersion: 1;
  audience: {
    osUserSidDigest: string;
    hostInstanceId: string;
    pluginInstanceId: string;
    serviceInstanceId: string;
    sessionId: string;
  };
  bindings: {
    action: InternalAuthorizationRecord["action"];
    authorizationRecordDigest: string;
    constraintsDigest: string;
    exactScopeDigest: string;
    expectedRevocationEpoch: number;
  }[];
};

type AuthorizationRecordDigest = string;
// SHA-256(JCS(InternalAuthorizationRecord 中除 signature 外的全部字段))

type ExactAuthorizationScopeV1 = {
  subject: InternalAuthorizationRecord["subject"];
  action: InternalAuthorizationRecord["action"];
  intentId: string;
  taskId: string | null;
  resourceBindings: InternalAuthorizationRecord["resourceBindings"];
  serviceBindings: InternalAuthorizationRecord["serviceBindings"] | null;
};
type ExactScopeDigest = string; // SHA-256(JCS(ExactAuthorizationScopeV1))
type AuthorizationBindingDigest = string; // SHA-256(JCS(AuthorizationBindingManifestV1))

type TaskInputManifestV1 = {
  schema: "study.task.input-manifest";
  schemaVersion: 1;
  actionId: WorkflowActionId;
  workReuseDigest: WorkReuseDigest;
  subject:
    | {
        kind: "project_task";
        projectId: string;
        projectRevision: number;
        inputArtifacts: {
          artifactId: string;
          artifactRevision: number;
          artifactDigest: string;
        }[];
        sourceSnapshotDigests: string[];
        learningContractRevision: number;
      }
    | {
        kind: "profile_validation";
        configurationSessionRef?: string;
        profileRef: string;
        configurationFingerprint: string;
        credentialRevision: number;
      };
  authorizationBindingDigest: AuthorizationBindingDigest;
  capabilityBindingDigest: CapabilityBindingDigest;
  operationIntentDigest?: string;
  componentVersions: {
    cardService: string;
    worker: string;
    sourceAdapterSetDigest: string;
    gateRuleSetVersion: string;
    templateFamily?: string;
    templateSchemaVersion?: string;
    compatibilityContractVersion?: string;
  };
  serviceBindings: {
    capability: "model" | "tts" | "anki_connect";
    profileRef: string;
    configurationFingerprint: string;
    credentialRevision: number;
    egressManifestDigest?: string;
  }[];
  generationPolicyDigest?: string;
  costBudgetDigest?: string;
  batchPolicyDigest?: string;
  successorRebaseDigest?: string;
};

type TaskInputManifestDigest = string; // SHA-256(JCS(TaskInputManifestV1))

type SuccessorTaskRebaseV1 = {
  schema: "study.task.successor-rebase";
  schemaVersion: 1;
  predecessorTaskId: string;
  predecessorTaskInputDigest: TaskInputManifestDigest;
  successorTaskId: string;
  workReuseDigest: WorkReuseDigest;
  scopeRelation: "equivalent" | "narrower";
  reusedWorkUnits: {
    workUnitId: string;
    resultArtifactDigests: string[];
  }[];
  predecessorAuthorizationAuditRef: string;
  successorAuthorizationAuditRef: string;
};

type SuccessorTaskRebaseDigest = string; // SHA-256(JCS(SuccessorTaskRebaseV1))

type TaskState =
  | "queued"
  | "running"
  | "cancelling"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

type StudyWorkUnitSnapshot = {
  workUnitId: string;
  phase: string;
  workReuseDigest: WorkReuseDigest;
  state: "pending" | "active" | "completed" | "failed" | "cancelled";
  attempt: number;
  resultHandles: string[];
};

// ToolErrorCode 与 TaskStage 复用 MCP 工具合同中的固定 enum。
type StudyTaskFailure = {
  code: ToolErrorCode;
  stage: TaskStage;
  retryable: boolean;
  remoteCostState: "none" | "possible" | "incurred" | "unknown";
  retryScope: "none" | "item" | "batch" | "phase" | "whole_task";
  authorizationState: "not_required" | "valid" | "required" | "expired" | "revoked";
  preservedArtifactHandles: string[];
  requiredAction?: WorkflowActionId;
  requiredActionContextRef?: string;
};

type StudyTaskSnapshot = {
  schema: "study.task.snapshot";
  schemaVersion: 1;
  taskRevision: number;
  taskId: string;
  intent: WorkflowActionId;
  state: TaskState;
  inputFingerprint: TaskInputManifestDigest;
  workReuseDigest: WorkReuseDigest;
  predecessorTaskId?: string;
  progress: {
    phase: string;
    phasePercent: number | null;
    overallPercent: number | null;
    completedItems?: number;
    totalItems?: number;
    completedBatches?: number;
    totalBatches?: number;
    lastProgressAt: string;
  };
  cancellable: boolean;
  resumability: "none" | "restart_phase" | "resume_remaining";
  checkpointHandle?: string;
  workUnits: StudyWorkUnitSnapshot[];
  resultHandles: string[];
  issueRefs: string[];
  failure?: StudyTaskFailure;
  createdAt: string;
  updatedAt: string;
};
~~~

CURRENT 的 src/app/workerTaskState.ts::TaskSnapshot 是桌面 Worker 叶子任务，虽然同为 schemaVersion 1，但字段语义不同。插件的 StudyTaskSnapshot 使用独立 schema 标识；LegacyWorkerTaskSnapshot 只能作为内部 child execution 引用，并必须通过显式适配器迁移，不能直接反序列化为 StudyTaskSnapshot。

约束：

- 总体进度单调；只有 succeeded 为 100%。
- 所有任务变更都必须携带 expectedRevision 和 operationId；Service 在同一存储事务中执行 CAS、记录 operation digest，并让相同 operationId + 相同输入幂等返回、相同 operationId + 不同输入失败。taskRevision 每次成功变更严格递增，读取和 checkpoint 不增加 revision。
- 事件和轮询按 taskId 幂等合并。
- authorizationRecordDigest 固定为 SHA-256(JCS(InternalAuthorizationRecord 去掉 signature 字段))；signature 必须在使用前按 keyId 独立验证。exactScopeDigest 固定为 SHA-256(JCS({ subject, action, intentId, taskId: taskId ?? null, resourceBindings, serviceBindings: serviceBindings ?? null }))。exactResourceRefs 先按 UTF-8 字节序稳定排序并拒绝重复；AuthorizationBindingManifestV1.bindings 再按 action、authorizationRecordDigest、exactScopeDigest、expectedRevocationEpoch 排序并拒绝重复，等价授权不得因数组顺序产生不同摘要。
- authorizationBindingDigest 只对上述 canonical AuthorizationBindingManifestV1 做 JCS：绑定当前 audience/session/service instance、不可变授权记录/constraints、精确 scope 和 expected revocation epoch；明确排除 consumedUses、lastConsumedAt、当前时间和错误文本。每次执行/恢复仍在服务端原子读取 active/revoked/expired/consumed 状态，摘要不能代替账本。
- CURRENT 内部 AuthorizationLedger 把 OperationIntent、一次性 OperationApproval 消费、task-bound InternalAuthorization、逐调用 usage 和共享 operation remote-call 上限保存在一个 HMAC 认证、文件锁串行化的原子记录中。Task manifest binding 与内部 authorizationId 分离；未配置受信手势 attestation verifier 时所有批准/撤销写入失败关闭。本地资源 picker 的正式 verifier 已接入独立资源账本，并已通过可信 stdio 暴露 source/output grant；Operation/ImportApproval、URL 输入和其余公共 MCP 尚未接线。
- inputFingerprint 是 canonical TaskInputManifestDigest，不是调用方自报字符串；它描述一次具体执行实例，绑定当前 authorizationBindingDigest、operationIntentDigest、credentialRevision、egress、成本/批量和 successorRebaseDigest。subject 用 project_task/profile_validation 判别联合；profile_validation 仅在未提交草稿场景包含 configurationSessionRef。OperationRequestManifestDigest → intentDigest → TaskInputManifestDigest 单向构造，不形成摘要循环。
- audienceDigest 固定为 SHA-256(JCS(AudienceBindingManifestV1))；其 preimage 含 canonical OS SID digest、host/plugin/service/session 五项，全部来自受信启动链路。任一实例或会话变化都会使旧授权不可重放。
- configurationFingerprint 固定为 SHA-256(JCS(ProfileConfigurationManifestV1))；endpoint 在摘要前完成 scheme/IDN host/default port/path 规范化且禁止 query/userinfo/fragment，秘密值排除、credentialRevision 独立绑定。egressManifestDigest 同理绑定规范目标、method/content-type、redirect/proxy/DNS 与响应上限。
- model/TTS 的 requestParameterPolicyDigest 对 fixed/enum/range + reject-unknown 的 canonical manifest 做 SHA-256(JCS)；规则名 NFC 化、稳定排序、拒绝重复，有限数值/enum 标量也 canonicalize。摘要进入 ProfileConfigurationManifest，因此参数策略变化不能复用旧验证。
- DisclosureManifest 使用逐目标 DisclosureEntry；每条把 capability/profile/origin/model-or-voice、单一数据类别、精确 Artifact/revision/locator 和独立资源上限绑在一起。Broker 请求可组合同一精确 target 的多条 entry，且每个 locator 必须映射到一条 entry；不允许把已批准片段改送另一 target，全局 caps 只是附加上限。
- capabilityBindingDigest 只对 StableCapabilityBindingV1 做 JCS：fixed 分支绑定 CapabilityId/实现版本/兼容合同；service_profile 分支绑定 ServiceProfileCapabilityId + profileRef + configurationFingerprint + credentialRevision。明确排除 snapshotRevision、checkedAt、暂态 state、延迟、issueRefs 和人类错误文本。原任务保留旧能力证据，恢复时用当前 binding 做兼容判断；展示 aggregate 不得进入 gate 或摘要。
- workReuseDigest 是与执行授权分离的语义/工作单元身份。project_task 绑定项目/输入 Artifact/来源/学习合同/CardPlan、组件与规则/模板、profile configurationFingerprint、生成和工作分区策略，但不绑定 session/service instance、authorizationId、user gesture、credentialRevision、OperationIntent、成本余额、checkedAt 或任务状态。profile_validation 是明确例外：credentialRevision 本身就是被验证输入，必须进入 WorkReuseDigest，旧连接测试绝不跨凭据修订复用。
- 同一 taskId 只在完整 TaskInputManifestDigest 未变且原授权仍有效时原地继续。Codex/Card Service 重启、会话改变或授权过期后不得修改旧 TaskInputManifest；Service 创建新 taskId 和新的 TaskInputManifest，并以 SuccessorTaskRebaseV1 显式连接 predecessor。
- successor 复用要求 workReuseDigest 完全相同、已完成 work unit 的 Artifact hash/parents/gate 重新通过、组件兼容、profile configurationFingerprint 不变，且新授权/Disclosure/egress 范围等价或更窄。credentialRevision 可以变化，但必须先重新验证 profile 并取得新授权；活动/未提交 work unit 整单元重试。
- model/TTS 子调用只接受 BrokerModelRequestV1/BrokerTtsRequestV1：绑定 task/work unit、audience、intent/authorization、profile、逐目标 disclosure、egress、budget、权威 text locator、payload digest 与服务端 HMAC 幂等键。BrokerReservationLedger 的 reserved → sent → settled/possible_incurred/released_before_send 状态单调；发送后未知成本按最大预留处理，禁止盲重发。
- Anki 运行时证据绑定 ImportPlan、无环 signed run、精确公钥版本的当前 anti-rollback trust set、确定性样本、Service-derived expectations、verifier-signed proofs、signed run-owned process lifecycle ledger、add-on focus attestations、typed final-runtime input manifest 与三传感器只读策略。只有可信 failure proof 才形成 runtime_failed；外部写后恢复、用户 Anki 干扰、错误 process/window restart、跨 run 证据、旧 final-check evidence 或 post-cutoff event 均拒绝 fully_verified。写边界恢复仍只有 not_written / verification-only successor / ambiguous stop。
- SuccessorTaskRebaseV1 同时记录旧/新授权审计引用和每个复用结果摘要；旧执行授权绝不转移。范围扩大、profile/生成/CardPlan/来源/组件不兼容时 remaining 复用失败，要求明确 restart_phase 或 full_refresh；旧产物保留但不覆盖当前结果。
- WorkflowSnapshot.currentTaskId 在活动态和未被后续写动作取代的四种终态都必须存在，且其 StudyTaskSnapshot.state 与 operationState 相同；只读请求不能清除。下一写动作被接受时原子记录 acknowledgement，并替换新 taskId，或在同步写动作后转 idle。
- credentialRevision 由 Service 账本在 add/replace/delete/rollback/OAuth material change 时原子单调递增且永不复用；并发更新序列化。每次成功更新立即使旧 profile verification、approval 与 capability binding stale。
- 取消写入终态，不永久停留在 cancelling。safe 取消在最后一个原子边界完成且检查点可证明一致时为 cancelled；force 终止或无法证明最后写入边界时必须为 interrupted，绝不能按调用方偏好二选一。每个可强制终止 helper 必须属于单一 task 的 OS job/process tree；共享 Card Service/Worker 池和其他任务永不属于 force 作用域。
- 活动批次中断时整批重试，完成批次不重复。
- 任务结果使用引用，不把大型媒体或项目塞入聊天上下文。

## 6. 检查点与产物仓库

建议目录逻辑：

~~~text
app-data/
  projects/<project-id>/
    project.json
    artifacts/<artifact-id>.json
    blobs/<sha256>
    tasks/<task-id>.json
    tasks/<task-id>.result.json
    checkpoints/current.json
    checkpoints/current.json.bak
    audits/<audit-id>.json
~~~

规则：

- 同目录临时文件原子替换。
- 每个 JSON 有 schemaVersion。
- Blob 内容寻址，避免重复。
- 不在项目 JSON 中保存密钥。
- 清除检查点不删除用户素材和已生成 APKG。
- 恢复时验证路径、文件身份、哈希和输入修订。

## 7. 并发与一致性

- 项目修改使用 revision + expectedRevision 乐观并发。
- 每个语义编辑有 operationId，重复调用不重复应用。
- 长任务捕获输入修订，完成时进行 compare-and-publish。
- 同一项目默认只允许一个会改变相同产物阶段的写任务。
- 只读检查和预览可以并发。
- Anki 导入使用 import intent/idempotency key，重试前先检查是否已存在。

CURRENT 内部 `ProjectRegistry` 已实现 projectRevision + contractRevision 双 CAS、项目创建 idempotency key 与语义 operationId 幂等、固定 Learning Contract ChangeSet 以及按实际变化字段计算的失效矩阵。记录使用 canonical JSON、域隔离 HMAC、跨进程文件锁、no-replace 创建和认证备份；公开快照不包含内部账本或认证数据。它尚未与 Artifact Registry/StudyTask 组成单一 compare-and-publish 事务，也尚未暴露为 MCP 工具，因此不能把内部实现推导为项目工具已经发布。

## 8. 能力与秘密

能力状态严格分层：fixedCapabilities 表达宿主、本地运行时、来源适配器、Anki 和 runtime verifier；serviceProfiles 对 model/TTS/AnkiConnect 的每个 profile 单独记录。ServiceProfileVerificationRecord 绑定 capability、profileRef、configurationFingerprint、credentialRevision、单调 sequence、checkedAt 与结果/错误码；最新失败覆盖旧成功，service aggregate 只用于展示。

秘密只以 SecretRef 进入配置。MCP 工具、App UI、任务快照、日志和审计不能返回密钥明文。

CURRENT 内部 `CredentialStore` 已把真实秘密限制在 OS credential backend，并以 HMAC 派生 SecretRef、material MAC、high-water revision、expectedRevision CAS 和跨进程文件锁维护认证事务。add/replace/delete/rollback/OAuth material change 都生成不复用的新 revision；崩溃后只有 intended 或 previous material 能被证明时才提交/回退，其他材料进入 `uncertain` 并禁止 broker 解析。认证密钥按需保存在同一秘密后端，所以 Hermes revision 0 路径不会凭空创建 provider credential；Card Service 的本地 grant 与 staging receipt key 也从该 OS-backed 根材料按 purpose/context 域隔离派生，派生 key 不落盘。service instance ID 只在当前进程生命周期内随机生成，不从持久材料恢复。该实现尚未形成公共设置工具，正式 service key rotation/ACL 仍未完成。

CURRENT 内部 `ServiceProfileRegistry` 已持久化封闭、规范化且不含秘密的 model/TTS/AnkiConnect 配置。固定 provider 继续复用 Provider Egress 的 origin/模型/voice 约束，Hermes 和 AnkiConnect 只允许字面 loopback；configurationFingerprint 是 canonical 配置的纯 SHA-256。profileRevision 使用 expectedRevision CAS，operationId 只以 HMAC 摘要落盘；记录采用 canonical JSON、域隔离 HMAC、跨进程锁、no-replace 创建和审计备份，并严格校验字段闭包、身份路径、历史操作与保存时凭据绑定。公开快照不返回 SecretRef、秘密或原始 operationId；每次解析都从 `CredentialStore` 读取当前 credentialRevision/state，所以外部替换或删除保持 `uncertain` 并失败关闭。

CURRENT 内部 `ServiceProfileVerificationRegistry` 现可直接使用上述持久 Registry 作为受信 resolver，在结果发布时和能力读取时分别解析当前绑定；结果精确绑定 capability/profile/fingerprint/revision 与单调 sequence，支持 stale-at-publish、7 天过期和 latest-failure-wins。账本为 canonical JSON + 域隔离 HMAC + 跨进程锁；损坏时旧 `.bak` 只供审计，绝不恢复旧 ready。两者仍未接入统一任务协调器、受信设置事务或公共 `system.validate_profile`，aggregate 也不提供 gate API；Profile Registry 认证密钥的生产保护/轮换和应用数据 ACL 仍是后续边界。

## 9. 宿主适配

定义与宿主无关的 WorkRailViewModel，然后分别映射：

- Inline：当前状态、最多三个关键问题和一个主动作。
- PiP：进行中任务、进度、暂停/取消和打开详情。
- Fullscreen：素材、候选、证据、卡片计划、审核和诊断。
- FutureSidebarAdapter：DEFERRED，仅在官方稳定接口出现时实现。

固定侧栏不是业务协议的一部分，因此不会影响任务恢复或项目格式。

## 10. 版本与兼容

- MCP tool 名称稳定；破坏性变化发布新工具版本或协议主版本。
- ArtifactEnvelope 与 Study IR 各自带 schemaVersion。
- Card Service 对当前 WorkerCommand 建适配器，允许内部演进。
- CURRENT 卡片 family 为 immersive_v11，生产 template schema 为 V15。M0 已移除 V1 + `startswith` 宽前缀，冻结 V15/V14/V10 的精确 family/schema/Note Model ID、完整字段/模板/model extras/CSS 与 compatibility contract；V15 使用模型作用域 GUID，历史 V10/V12/V14 GUID 不变。完整 APKG 合同进一步闭合 ZIP/JSON、模型/牌组/note/card、CardId/纯内容 SHA、媒体账本和安全 HTML；10 个生产生成变体均通过真实导出验证。
- CURRENT 导出使用同目录唯一 `.partial` → 整包校验 → no-replace 原子发布，目标路径已存在时拒绝覆盖，失败不发布新最终包或 done。Anki 写入前会重验内部 raw `ExportResult` 与整包；但 raw `ExportResult` 不认证来源，不能防止同权限攻击者同时篡改包和结果，重复 stat/SHA 与 no-replace 发布也只缩小、不消除 TOCTOU。M2 的认证 Artifact 注册表、不透明引用与受控文件句柄是公共插件边界。
- M0 最终证据保存在独立验证报告；最新 M1 分支证据为正式 `pytest tests` 961 项通过、1 项按环境跳过，Vitest 830 项、Worker `unittest discover` 599 项、原生插件 launcher 13 项 Rust 单元测试与严格 clippy、托管 yt-dlp launcher 2 项 Rust 测试，以及 Tauri 31 项通过、1 项按设计忽略。各集合有重叠，不相加；安装最终化实物证据见 [M1 安装最终化验证报告](M1_INSTALL_FINALIZER_VERIFICATION_2026-07-18.md)，完整发布回归仍以路线图出口为准。
- CURRENT 20 卡生产 V15 离线包为 20 notes / 20 cards / 52 个唯一媒体，manifest、逐媒体哈希、字幕对齐和模型作用域 GUID 闭合。真实隔离 Anki 证据包括 E→C 单卡、V15 20 卡重复/重启及 V14/V15 同字段并存；Computer Use 在 Anki 26.05 完成了 20 张连续复习、翻面、滚动、焦点和四类媒体交互。素材为合成视频与静音 TTS，不构成真人语义、听感或长期学习效果证据。
- 非 NFC、Windows 保留设备名（含 `CLOCK$`）、大小写/规范化冲突和 APKG archive 资源上限已 fail closed；有界流式读取覆盖 APKG archive/package/verifier 与标准 Windows Anki direct-first 媒体路径。非标准/portable profile 的 AnkiConnect inline 兼容仍整文件/Base64，原始单文件上限为 8 MiB；8 MiB 不是进程峰值。
- M0 已完成。M1 Card Service 与最小 stdio MCP 已在开发态、签名 packaged runtime、独立复制的原生 pinned launcher 和完整被动离线候选包下通过真实 Codex `0.144.1` 宿主注册/只读调用；launcher 在启动 Python 前验证精确 manifest/trust pins、全部资源和文件集合，候选包再绑定外层 SPDX/manifest 与双层精确 DACL。原生启动器现在还以独立安装签名域区分被动/可安装布局：被动构建拒绝任何 MCP/App 接线；可安装构建必须显式 pin 外部策略并验证安装 manifest/signature、固定 MCP 命令、外层资源和委托 runtime pins。仓库已实现无私钥、无联网的 install candidate、public-key-only signing request 与 finalizer；finalizer 依次执行签名、WinTrust/AuthentiCode pin、隔离 staging、精确 DACL、原生 install-only 预检、原子发布和发布后复核，正式 API 不能注入伪验证器或任意验证时间。正常 `--stdio` 运行在全部资源通过后才推进单调回滚地板，install-only 预检不推进。M1 仍未完成正式发布密钥/HSM 返回物、真实 Authenticode 正例、完整桌面等价矩阵和插件侧通用 runtime verifier。Anki 媒体快捷键 add-on 当前只声明支持 26.05。
- M1 外层实物探针使用最长 24 小时、随机且不落盘的本地私钥，对 289,210,657-byte 候选生成公钥策略/请求/signature；独立 CLI 重新验证完整 payload 和 detached signature，二者都绑定 manifest `9ab03b75dc2a0c2197e280fdd47a9f9a83c2fe25fc786459822cfcbf23f262d6` 并保持不可安装。候选 DACL 验证只派生 AppContainer SID，不再隐式创建 per-user profile；profile provisioning 是未来安装器的显式职责。
- M1 外层 launcher 现有独立 Authenticode 验证适配器：先由 Windows `WinVerifyTrust` 在 cache-only、chain-exclude-root 撤销模式验证，再从 provider evidence 提取 signer certificate，执行外部 DER digest/subject/status pin、Code Signing EKU、KeyUsage、非 CA、密钥强度、有效期、可信时间戳和验证期间文件不变检查。适配器不联网、不安装证书、不生成发布身份。当前 launcher 为 `NotSigned`，所以真实结论仍是 fail closed；正式 CA/企业证书、时间戳和生产 pin policy 是可安装 finalizer 的未完成输入。
- M1 原生安装 verifier 使用 `ed25519-dalek 3.0.0` 对 `study.plugin-install-manifest.v1` 域执行 strict verify；策略、manifest、signature 与 MCP 元数据均要求有界 canonical JSON，路径必须可移植且无 reparse/碰撞/保留名，外层文件集合必须精确。完整资源验证后才用 write-through 原子替换推进本机回滚地板，拒绝策略/版本回退、策略分叉和同版本换内容。加入 finalizer 专用 install-only 模式后，两个隔离 `/Brepro` 构建得到相同 315,392-byte launcher（SHA-256 `b73d06c4739d9db5d76184c0261ba53220f2f2dc1abffe2bb4d1327b4ae16619`）；新版 4391 项被动候选为 289,217,313 bytes，manifest `66a5ebaa23529415c5d3e9117302d8c79ff8dc2bee5e99a47846ae180b87bdc1`，官方 validator、真实 Codex 连续两次宿主调用和被动 `--verify-install-only` 退出 125 的负向实物均通过。该候选仍没有正式外层签名与 Authenticode 正例，不能安装。
- M1 的便携 CPython 使用 25 项精确 wheel 锁离线装配；有界 canonical `python-runtime-build-v1.json` 绑定 Python identity、lock SHA-256、wheel 数和无网络事实。staging 前与正式包加载时都会把它和实际锁交叉验证，并以 `managed-python:build-metadata` 纳入 SBOM/签名资源，禁止把来自不同构建的 Python root 与依赖锁拼接。
- M1 的签名运行时等价合同现在覆盖真实 AppContainer 内的 Service-owned 整句/表达 TTS 和 APKG 导出。Service 创建的输出根、restricted token 默认 DACL 与 Worker 新建子目录共享 task capability 边界；托管媒体工具必须位于签名 runtime root，所有媒体输入/输出必须位于 task workspace，边界内逐组件拒绝 reparse，不能通过不可访问的盘符祖先误报或放宽检查。托管音频审计不可用、超时、非法或非正时长均 fail closed；如果远程 TTS 已返回而本地审计失败，不重复计费调用。临时签名实物为 4385 项、286,933,332 bytes，manifest SHA-256 `6073b8f7743fcd51a3ac599d6a7816bee4e5c582570c4517231029a197cde990`；它证明调度/媒体语义和包不可变性，不代表正式发行身份。
- CURRENT M2 的 `LegacyProjectProjectionPublisher` 是旧桌面 Project 与 Artifact Registry 之间的内部桥。它先在内存中递归净化，再验证同项目 SourceAsset/MediaLedger/可靠性/清单/诊断父 Artifact，最后写入固定 schema SHA-256 绑定的 JCS Blob 和认证 envelope；raw Project 永远不是 Artifact payload。
- Project 中的 raw http(s)、本机路径、盘符相对路径和上级穿越路径只能由受信资源层提供的精确 `LegacyResourceBinding` 替换为 `$resourceSlot`。原值摘要只用于发布前比对，不进入持久 slot；slot 只保存内部绑定 ID、资源 revision 摘要，以及网络资源的 canonical request/query-redaction 摘要和无 userinfo/query/fragment 的 display origin。对外 summary 不暴露这些内部绑定、Blob 或 profile identity。
- CURRENT M2 的 `LocalResourceGrantRegistry` 已在 Card Service 内部为本地文件、输入目录和输出目录签发短期 opaque ref。私有记录使用 canonical JSON、域隔离 HMAC、跨进程锁、审计备份和 no-replace/原子替换；ref 与 owner/host/plugin/session/service instance 共同绑定。文件逐次使用前重验 regular-file 身份、唯一链接、大小、mtime 和 SHA-256；输入目录重验根身份/mtime，输出目录重验稳定身份。权限只允许缩小，过期、次数耗尽、撤销 epoch、资源变化或记录篡改均失败关闭。
- raw path 只存在于该认证私有账本；公开 summary 与 legacy projection 都不返回路径。受控消费结果可以为完全相同的 Project pointer/path/kind 生成精确 `LegacyResourceBinding`，但这仍是内部合同，不是公共 bearer。
- CURRENT M2 的 `NetworkResourceGrantRegistry` 已在 Card Service 内部签发 audience/service 绑定的 `networkResourceRef`。raw/signed URL 只存在于当前 Service 进程的短期 locator 内存；认证持久记录只保存 HMAC 摘要、脱敏 display origin、封闭策略、次数、期限与撤销状态。签发、消费和每个重定向 hop 都重新解析全部地址，任一非公网结果即拒绝；传输固定到已验证 IP，同时保留 TLS SNI/hostname 校验，不读取环境代理、Cookie 或系统集成凭据。Service 重启后旧 ref 变为 `reauthorization_required`，不能从持久摘要恢复 URL。
- CURRENT M2 的内部 `TaskResourceStager` 会重新验证已消费 local grant 的 proof、audience、撤销 epoch、revision、约束和当前快照，再以独占句柄和有界流复制到 task workspace。目录复制产生排序、认证的逐项 manifest，并拒绝 reparse、hardlink、名称碰撞、资源越界和复制期变化；Worker 只得到 workspace-relative locator。
- staging receipt 以域隔离 HMAC 绑定 source ref 摘要、task/audience/service、workspace identity、manifest 与暂存字节。Windows staged payload 对 task SID 只授予 read/execute；生产模式没有正式 hardener 就失败关闭。当前实现以跨进程锁串行化完整复制阶段，优先保证原子性与幂等，后续再优化大型目录吞吐。
- CURRENT `ServiceResourceRuntime` 已由 Card Service 惰性拥有同一个 local grant registry 和 stager；packaged runtime 只绑定正式 `harden_staged_path`，并拒绝调用方注入 gesture verifier。能力快照不披露路径、key 或私有 receipt。
- CURRENT `TrustedSurfaceManager` 的 `local_resource_picker` 会在独立本地窗口取得真实选择，以 session/nonce/surface 绑定的 AES-256-GCM 私有响应把 raw path 交回 Service；公开响应只含固定安全标签。5 分钟 attestation 在首次使用时绑定精确 audience/request digest，完成或过期后清除路径。Card Service adapter 据此签发 opaque local resource ref，并拒绝服务状态根。
- CURRENT stdio audience 由原生 launcher 建立：launcher 每次启动用 OS CSPRNG 生成 256-bit nonce，并把自身 PID 与 nonce 仅传给直接 Python 子进程；MCP 入口消费并删除这两个环境值，要求 PID 等于真实父 PID、父可执行文件与固定安装布局中的 `anki-study-agent` 为同一文件，并从当前 OS 用户 SID 摘要、launcher identity 和 nonce 派生 host/session binding。MCP 请求字段不能覆盖 owner/host/plugin/session。该证明认证的是“固定 launcher 的直接子进程会话”，尚不证明 launcher 的父进程一定是某个 Codex 版本；安装签名、精确文件清单、DACL 和未来宿主 attestation 仍是不同层。
- CURRENT 公共 MCP 在可信 audience 存在时额外声明 `system.request_source_grant` 与 `system.request_output_grant`。source 只接受 `grantRequestId` 和 `selectionKind=file|directory`，output 只接受 `grantRequestId`；路径、URL、权限、replace、attestation 和 audience 均不存在于 schema。Service 固定约束、打开 picker，并只返回 opaque ref、显示名、revision 摘要、约束和有效期。没有可信 audience 时只声明只读能力工具；开发态的 audience 必须由显式双开关启用。
- CURRENT `StudyRuntime` 已把 Project Registry、Artifact Registry、StudyTaskCoordinator、task source binding、`SourceRegistrationRuntime`、`SourceInspectionRuntime`、`CandidateDiscoveryRuntime`、`CandidateQueryRuntime`、`CandidateSelectionRuntime`、`CardPlanRuntime`、`CardPlanQueryRuntime`、`CardPlanRevisionRuntime`、`CardArtifactRuntime` 与 `CardArtifactQueryRuntime` 组合到与 local grant/stager 相同的 service instance，并从 OS 保护的单一主凭据派生域隔离密钥；可信 MCP 已开放幂等 `study.create_project`、`study.register_inputs`、`study.start_source_inspection`、`study.get_source_inspection` 以及 `study.list_candidates`、`study.get_candidate`、`study.preview_evidence`、`study.set_selection`、`study.plan_cards`、`study.list_card_plans`、`study.edit_card_plan`、`study.validate_card_plans`、`cards.generate` 与 `cards.list`。本地 file/directory ref 会进入可恢复 StudyTask，形成 task-local snapshot、内容寻址 Blob/目录 manifest、认证 `study.source-asset`，并以 expectedRevision 把项目推进到 `sources_ready`。确定性检查再验证 Blob，发布不内联正文的 ContentNode 表示、逐来源覆盖记录和汇总 Inspection；文本/Markdown/代码/HTML/字幕与受限目录成员可解析，缺少安全解析器或超出同步上限时显式阻塞。内部双角色发现可通过 Service Broker 形成 CandidateProposal → GateEvaluation → Discovery 的认证单向图；公开查询只接受最新 Discovery/Candidate opaque handle，分页 cursor 绑定查询，证据只从认证快照有界重放并再次执行敏感披露检查。公开结果不会回显路径、完整正文、InputRef、BlobRef、内部 ArtifactRef、私有 receipt、授权或 Worker locator。选择运行时从同一当前认证图解析 candidate handles，以确定性覆盖优先策略和 Learning Contract 预算发布 `study.portfolio-selection`，同时提供保守 ReviewDebt；hard gate 失败不可被用户选择覆盖，旧选择在上游失效后不再投影，整个动作不访问模型、TTS、网络或 Anki。内部 CardPlan 运行时会再次解析精确当前 Selection 图，只对 `production`、`chunk_collocation`、`reading_recognition` 三条无需额外语义推断的路线发布认证 `study.card-plan`、`study.card-plan-set` 与 `study.card-plan-validation`，并执行证据覆盖、单一评分边界、答案泄露、重复、冲突、模板兼容、媒体可生成性和用户锁保留检查；需要翻译、语用/语法推断或媒体语义时以 `UNSUPPORTED_CARD_PLAN` 失败关闭。它不调用模型、TTS、网络或 Anki；可信 MCP 的 `study.plan_cards` 只接收当前 selectionHandle 和封闭 RequestContext，最多同步处理 100 项，超限要求未来异步 planner，`study.list_card_plans` 以 PlanSet/service 绑定认证游标返回学习者可见投影，均不披露 ArtifactRef、路径、授权或 input fingerprint。CardPlan Agent 编辑与独立重验现已开放：编辑 schema 与 Candidate 操作互斥，调用方不能提交 provenance/evidence/user lock，服务保留认证引用与锁、记录权威 taskId、发布同 identity 新 revision 并重放八项门禁；重验发布新的 set/validation revision。语义新增无法由冻结证据确定性证明时保持 `needs_review`，破坏评分边界或请求未实现媒体时 fail closed；中断恢复按 Artifact identity 而不是可变 opaque handle 比较。该 composition root 仍不是完整事务边界：同步内部 discovery 尚未开放为公共 `study.start_discovery`，必须先完成异步 start/poll/cancel/resume。CURRENT outputRef 已绑定异步 `cards.export_apkg`：Worker 输出先在 task workspace 内完成，Card Service 独立重验完整包、SQLite 身份、模板摘要与媒体清单，发布认证 PackageArtifact 图，再以目标目录同盘 `.partial` 和 no-replace 版本化文件交付；项目提交窗口未闭合时不得公开 succeeded，精确重试只补项目提交而不重跑 Worker。宿主附件、受信 URL 输入、网络 staging、逐子项公共 ref、候选编辑、用户锁定通道与 Anki 写工具仍未接线。卡片生成和公开 APKG 导出当前只在文本、零媒体、八项门禁全通过的确定性边界内开放；需要模型、TTS 或媒体的路线仍失败关闭。Card/Candidate/CardPlan 三类认证 cursor 都要求 canonical Base64URL 表示；APKG 异步切片的 83 项定向扩大回归已通过；正式 Python `tests` 全集为 1480 passed、1 skipped。Artifact publish 失败可能留下已经净化的内容寻址孤儿 Blob；跨 Registry 原子事务和保留清理属于后续 M2。
- 旧桌面项目可通过显式迁移器导入，不直接假设字段等价。

## 11. 进程与部署

### V1

- 插件本地 stdio MCP 启动 Card Service。
- 受信启动握手派生 OS user SID、host instance、plugin instance、service instance 和 session；工具参数不能自报这些身份。
- Card Service 查找经签名 manifest 固定的 Worker 和依赖。
- 使用当前用户 ACL 保护的应用数据目录持久化；项目 owner/scope 控制 list/get/artifact 读取。
- Codex 退出可能结束进程；下次启动将运行中任务标为 interrupted，并提供恢复。

### DEFERRED

- 可选本地守护进程/托盘服务，实现宿主关闭后继续运行。
- 公共目录需要的生产托管 MCP。
- 多设备同步和远程媒体存储。

## 12. 关键失败策略

| 失败 | 行为 |
|---|---|
| 来源中途变化 | 停止发布结果，要求重新快照 |
| 部分文件不可读 | 显示覆盖清单；不得静默声称完整 |
| 模型输出不合约 | 有限重试，之后保留证据和失败项 |
| TTS 失败 | 视频卡按策略阻塞；非必需路线可明确降级 |
| Worker 崩溃 | 任务 failed/interrupted，保留安全产物 |
| 取消导出 | 删除/忽略 partial 文件，不显示已导出 |
| AnkiConnect 不可用 | 保留 APKG，提供启动/手动回退，不伪造导入或数据核验 |
| Anki runtime verifier 不可用 | 最多 anki_data_verified，明确运行时体验 not_assessed |
| Anki runtime 合同/证据形状无效 | 返回 ANKI_VERIFY_FAILED，保留数据核验结果，不伪造 runtime_failed 或 fully_verified |
| 重复导入 | V1 先查询导入证据，只返回 existing/conflict 或继续未完成核验；不得 update_matching |
| App UI 丢失事件 | 轮询权威任务快照恢复 |

## 13. 架构验收

- 对话和所有 UI 读取同一服务快照。
- 没有公共通用执行器。
- 每个写工具声明影响范围，并由 Service 校验可信会话和内部授权记录。
- 每个正式卡片可追溯到版本化 SourceAsset 和 EvidenceAnchor。
- 任务可重启恢复且不重复已确认昂贵步骤。
- 本地路径、秘密和内部堆栈不会进入模型上下文。
- 不依赖私有 Codex DOM 或固定侧栏。
- 现有 APKG/Anki 数据可靠性闸门没有因新入口而旁路；完整 anki_verified 另需受信 runtime evidence。

接口细节见 [Study IR](STUDY_IR_REFERENCE.md) 和 [MCP 工具参考](MCP_TOOL_REFERENCE.md)。
