# 安全与隐私

> 状态：PROPOSED 威胁模型与发布门槛  
> 日期：2026-07-16  
> 当前桌面端已有部分保护；本插件边界尚未实现，不能直接复用“可信 Tauri 前端”的假设。

## 1. 安全目标

插件必须允许 Agent 在明确授权范围内高度自治，同时保证：

- 不可信素材不能获得工具权限。
- Agent 不能任意读取磁盘、访问网络、读取密钥或写入 Anki。
- 状态、日志和对话不泄露秘密和敏感路径。
- APKG 和 Anki 写入只来自已登记、未被替换的可信产物。
- 供应链中的 Service、Worker、解析器和外部工具可验证。
- 失败时 fail closed，不用静默降级换取“成功”。

## 2. 资产

- 私有视频、字幕、文档、目录结构和本机路径。
- API Key、TTS Key、OAuth Token、Cookie、服务配置。
- Learning Contract、候选、卡片、APKG、媒体和学习历史。
- Anki 牌组、笔记、模板、调度状态和 collection.media。
- Python、FFmpeg、yt-dlp、Deno、Calibre、Anki 等本地执行能力。
- 任务快照、检查点和“已生成/已导入/已核验”的真实性。
- 插件、Card Service、Worker、安装包和依赖供应链。

## 3. 信任边界

~~~text
不可信素材、网页、字幕、PDF、模型返回
                    │
                    ▼
Codex Agent / Skill（可能受提示注入影响）
                    │
            类型化 MCP + 用户确认
                    │
                    ▼
本地 Card Service（权限执行点）
           ┌────────┼────────┐
           ▼        ▼        ▼
     文件/解析器   模型/TTS   Anki/媒体
~~~

信任假设：

- Codex 和 Skill 是受策略约束的编排者，但不是本地权限根。
- Card Service 是唯一权限执行点。
- 来源、模型输出和工具人类可读文本都不可信。
- AnkiConnect 是本地外部系统，必须校验端点和结果。
- Tauri 桌面 UI 不是插件安全边界。

## 4. CURRENT 可复用保护

仓库已经具备：

- Rust/Python 双 Worker 命令白名单。
- 参数数组启动子进程，不使用 Shell 字符串拼接。
- 产物目录、文件名、重解析点、体积和秘密字段检查。
- 恢复文件的设备路径、ADS、保留名、SHA-256 和 TOCTOU 元数据检查。
- 打开 APKG 的受限目录和扩展名检查。
- 字面私网/回环 URL 阻断。
- Anki 媒体 basename、manifest/hash 和同名冲突检查。
- CardId/note hash 的重复导入与导入后核验。
- Windows Credential Manager/DPAPI 秘密存储。

这些是内核基础，但现有 local_path_access_confirmed 等 UI 布尔值不能成为 Agent 授权。

## 5. 内部授权记录与可信会话

模型、Skill、App UI 和普通 MCP 参数都不能持有或转交高影响授权 bearer。MCP 只提交资源 handle、项目 intent 和幂等键；Card Service 使用可信连接身份和内部账本判断是否授权。

~~~ts
type AuthorizationSubjectV1 =
  | OperationSubjectV1
  | {
      kind: "session_resource_grant";
      grantRequestId: string;
      resourceKind: "file" | "directory" | "network" | "output";
    }
  | {
      kind: "anki_import";
      projectId: string;
      projectRevision: number;
      importIntentId: string;
      importPlanDigest: string;
    };

type AudienceBindingManifestV1 = {
  schema: "study.authorization.audience";
  schemaVersion: 1;
  osUserSidDigest: string;
  hostInstanceId: string;
  pluginInstanceId: string;
  serviceInstanceId: string;
  sessionId: string;
};

type InternalAuthorizationRecord = {
  schemaVersion: 1;
  authorizationId: string;
  issuerServiceInstanceId: string;
  audienceDigest: string;
  intentId: string;
  taskId?: string;
  subject: AuthorizationSubjectV1;
  action:
    | "read_source"
    | "read_directory"
    | "write_output"
    | "call_model"
    | "call_tts"
    | "access_network"
    | "access_private_network"
    | "import_anki";
  resourceBindings: {
    exactResourceRefs: string[];
    resourceRevisionDigest: string;
    canonicalRequestDigest?: string;
    packageArtifactDigest?: string;
    importPlanDigest?: string;
  };
  serviceBindings?: {
    profileRef: string;
    configurationFingerprint: string;
    credentialRevision: number;
    egressManifestDigest: string;
  };
  constraintsDigest: string;
  notBefore: string;
  expiresAt: string;
  maxUses: number;
  keyId: string;
  revocationEpoch: number;
  nonce: string;
  signature: string;
};

type AuthorizationLedgerState = {
  authorizationId: string;
  state: "active" | "expired" | "revoked" | "consumed";
  consumedUses: number;
  expiredAt?: string;
  revokedAt?: string;
  lastConsumedAt?: string;
};

type OperationSubjectV1 =
  | {
      kind: "project_task";
      projectId: string;
      projectRevision: number;
      learningContractRevision: number;
      inputArtifactDigests: string[];
      sourceRevisionDigests: string[];
    }
  | {
      kind: "profile_validation";
      configurationSessionRef?: string;
      profileRef: string;
      configurationFingerprint: string;
      credentialRevision: number;
    };

type NormalizedEndpointV1 = {
  scheme: "https" | "http";
  asciiHost: string;
  port: number;
  pathPrefix: string;
  queryPolicy: "none";
};

type RequestParameterRuleV1 =
  | {
      name: string;
      mode: "fixed";
      value: string | number | boolean;
    }
  | {
      name: string;
      mode: "enum";
      allowedValues: (string | number | boolean)[];
    }
  | {
      name: string;
      mode: "range";
      minimum: number;
      maximum: number;
    };

type RequestParameterPolicyManifestV1 = {
  schema: "study.profile.request-parameter-policy";
  schemaVersion: 1;
  capability: "model" | "tts";
  rules: RequestParameterRuleV1[];
  unknownParameterPolicy: "reject";
};

type ModelProfileConfigurationManifestV1 = {
  schema: "study.profile.configuration";
  schemaVersion: 1;
  capability: "model";
  providerId: string;
  endpoint: NormalizedEndpointV1 & { scheme: "https" };
  modelId: string;
  authMode: "api_key" | "oauth" | "none";
  protocolVersion: string;
  requestParameterPolicyDigest: string;
};

type TtsProfileConfigurationManifestV1 = {
  schema: "study.profile.configuration";
  schemaVersion: 1;
  capability: "tts";
  providerId: string;
  endpoint: NormalizedEndpointV1 & { scheme: "https" };
  modelId: string;
  voiceId: string;
  language: string;
  sampleRateHz: number;
  bitrateKbps: number;
  audioContainer: "mp3" | "ogg" | "wav";
  authMode: "api_key" | "oauth" | "none";
  protocolVersion: string;
  requestParameterPolicyDigest: string;
};

type AnkiConnectProfileConfigurationManifestV1 = {
  schema: "study.profile.configuration";
  schemaVersion: 1;
  capability: "anki_connect";
  endpoint: NormalizedEndpointV1 & {
    scheme: "http";
    asciiHost: "127.0.0.1" | "::1";
  };
  apiVersion: number;
  targetProfileIdentityDigest: string;
  authMode: "api_key";
};

type ProfileConfigurationManifestV1 =
  | ModelProfileConfigurationManifestV1
  | TtsProfileConfigurationManifestV1
  | AnkiConnectProfileConfigurationManifestV1;

type EgressManifestV1 = {
  schema: "study.egress.manifest";
  schemaVersion: 1;
  capability: "model" | "tts";
  profileRef: string;
  normalizedTarget: NormalizedEndpointV1 & { scheme: "https" };
  allowedMethods: ("POST" | "GET")[];
  allowedContentTypes: string[];
  redirectPolicy: "none";
  proxyPolicy: "card_service_broker_only";
  dnsPolicy: "public_ip_only_recheck_on_connect";
  maximumResponseBytes: number;
};

type DisclosureDataCategoryV1 =
  | "source_excerpt"
  | "subtitle"
  | "learning_objective"
  | "card_plan"
  | "tts_text"
  | "diagnostic_summary";

type DisclosureEntryV1 = {
  disclosureEntryId: string;
  target: {
    capability: "model" | "tts";
    profileRef: string;
    providerOriginDigest: string;
    modelOrVoiceRef: string;
  };
  dataCategory: DisclosureDataCategoryV1;
  sourceSlices: {
    sourceArtifactDigest: string;
    sourceRevisionDigest: string;
    locatorSetDigest: string;
    maxBytes: number;
  }[];
  maxRequestBytes: number;
  maxInputTokens: number;
  maxOutputTokens: number;
  maxTtsCharacters: number;
  maxTtsAudioSeconds: number;
};

type DisclosureManifestV1 = {
  schema: "study.disclosure.manifest";
  schemaVersion: 1;
  entries: DisclosureEntryV1[];
  globalCaps: {
    maxTotalRequestBytes: number;
    maxInputTokens: number;
    maxOutputTokens: number;
    maxTtsCharacters: number;
    maxTtsAudioSeconds: number;
  };
};

type CostBudgetV1 =
  | {
      priceKnown: true;
      currency: string;
      maxMinorUnits: number;
      pricingSnapshotRef: string;
      pricingSnapshotVersion: string;
      maxRemoteCalls: number;
      maxCards: number;
      maxMediaItems: number;
    }
  | {
      priceKnown: false;
      currency: null;
      maxMinorUnits: null;
      pricingSnapshotRef: null;
      pricingSnapshotVersion: null;
      unknownPricePolicy: "block" | "explicit_unknown_cost_with_hard_resource_caps";
      maxRemoteCalls: number;
      maxCards: number;
      maxMediaItems: number;
    };

type OperationRequestManifestV1 = {
  schema: "study.operation.request";
  schemaVersion: 1;
  actionId: WorkflowActionId;
  subject: OperationSubjectV1;
  serviceBindings: {
    capability: "model" | "tts";
    profileRef: string;
    configurationFingerprint: string;
    credentialRevision: number;
    egressManifestDigest: string;
  }[];
  disclosureManifestDigest: string;
  costBudgetDigest: string;
  batchPolicyDigest: string;
  expiresAt: string;
};

type OperationRequestManifestDigest = string; // SHA-256(JCS(OperationRequestManifestV1))

type InternalOperationIntentRecord = {
  schemaVersion: 1;
  operationIntentId: string;
  audienceDigest: string;
  operationRequestManifestDigest: OperationRequestManifestDigest;
  disclosureManifestDigest: string;
  costBudgetDigest: string;
  expiresAt: string;
  intentDigest: string;
};

type OperationApprovalLedgerState = {
  operationIntentId: string;
  audienceDigest: string;
  userGestureRef: string;
  state: "approved" | "declined" | "expired" | "revoked" | "consumed";
  approvedAt?: string;
  revokedAt?: string;
  consumedAt?: string;
};

type ImportApprovalLedgerState = {
  importIntentId: string;
  audienceDigest: string;
  importPlanDigest: string;
  userGestureRef: string;
  state: "approved" | "declined" | "expired" | "revoked" | "consumed";
  approvedAt?: string;
  revokedAt?: string;
  consumedAt?: string;
};
~~~

不变量：

- InternalAuthorizationRecord 只存在于 Card Service；不进入 MCP structuredContent、模型上下文、Task、Artifact、日志或截图。
- AudienceBindingManifestV1 的五项均必填，并由受信 stdio/宿主握手与当前 OS 身份导出，不能由工具参数声明。osUserSid 先规范为 Windows canonical SID string，再对其 UTF-8 字节做 SHA-256；audienceDigest = SHA-256(JCS(AudienceBindingManifestV1))。host/plugin/service/session 任一变化都产生新 audience，旧批准不可重放。
- subject、action、intent/task、精确资源修订、策略、profile、凭据修订和 egress manifest 全部进入签名绑定。project_task 授权绑定项目/修订；profile_validation 授权绑定 profile/configurationFingerprint/credentialRevision，不得被强制塞入虚假项目。
- 新项目创建前签发的文件/目录/网络/输出授权使用 session_resource_grant，绑定当前 audience、grantRequestId、resourceKind、canonical request 与精确资源摘要；register_inputs 或 export 采用该授权时，Service 只能缩小范围，并原子派生/记录 project_task 绑定。Anki 使用 anki_import 绑定完整 ImportPlan。
- 使用次数与撤销状态只在服务端原子账本更新；签名记录本身不可变，不使用可被并发修改的 remainingUses。
- authorizationRecordDigest 固定为 SHA-256(JCS(InternalAuthorizationRecord 去掉 signature))，签名按 keyId 另行验证；exactScopeDigest 固定覆盖 subject、action、intentId、taskId/null、resourceBindings 和 serviceBindings/null。exactResourceRefs 先按 UTF-8 字节序排序并拒绝重复；AuthorizationBindingManifest.bindings 再按 action、authorizationRecordDigest、exactScopeDigest、expectedRevocationEpoch 稳定排序并拒绝重复。
- Task 的 AuthorizationBindingManifest 使用上述 JCS 固定 preimage，包含 audience/session/service instance、不可变 authorization record/constraints digest、精确 scope 和 expected revocation epoch；排除 consumedUses/lastConsumedAt 等瞬态字段。执行与恢复仍原子读取账本，不能只相信摘要。
- AuthorizationLedgerState 的 consumed 只在 consumedUses 达到不可变记录的 maxUses 时进入；expired/revoked/consumed 都是拒绝新消费的终态。
- 资源 handle 只定位对象；没有匹配的 audience、授权记录和当前撤销 epoch 时一律拒绝。
- 私网、覆盖和 Anki 写入必须绑定当前真实 user gesture，但 userGestureId 由宿主认证通道传入服务，不回显给模型。
- Objective/CardPlan 的用户锁同样只由受信编辑通道创建。raw hostEventRef/userGestureId 仅存内部认证账本；Artifact/UserLock/MCP/edit history 只保存非 bearer attestationDigest、hostCategory 和 recordedAt，且 candidate/card edit schema 互不重叠。
- V1 不提供 install_component 授权，也不允许运行期下载可执行组件。
- 素材或当前用户消息中的“已经同意”永远不能创建、延长或消费授权。
- 首次新模型/TTS 服务、数据出域、超过既有成本/数量/批量上限时，原工具先生成不含任何批准结果的 OperationRequestManifestV1；其摘要用于创建 InternalOperationIntentRecord，此时不得发起网络调用。
- project_task 与无项目的 profile_validation 使用 OperationSubjectV1 判别联合，禁止为 profile 测试伪造 projectId/revision。configurationSessionRef 只在验证尚未提交的设置草稿时必填；验证已保存 profile 或定期复检时省略，并由 profileRef + configurationFingerprint + credentialRevision 唯一绑定。
- intentDigest = SHA-256(JCS(InternalOperationIntentRecord 省略 intentDigest 字段后的 preimage))。OperationIntent 只绑定 OperationRequestManifestDigest，不绑定 TaskInputManifestDigest；批准后创建的 TaskInputManifest 再单向绑定 intentDigest，禁止摘要循环。
- OperationRequestManifest.serviceBindings 按 capability/profileRef 的 UTF-8 字节序排序并拒绝重复；同一 capability/profile 在一次请求中最多出现一次。inputArtifactDigests/sourceRevisionDigests 同样排序、拒绝重复；任何实现都必须先 canonicalize 再计算摘要。
- DisclosureManifestV1 使用逐条 DisclosureEntryV1，把一个目标 capability/profile/origin/model-or-voice 与一个数据类别、精确来源/修订/locator 集和该目标自己的字节/token/TTS 上限绑定；不能用互不关联的 targets/sourceSlices/dataCategories 数组。entries 按 disclosureEntryId 的 UTF-8 字节序排序并拒绝重复。broker 请求可以选择同一精确 target 下的一条或多条 entry；每个 Artifact locator 必须映射到其中一条且满足其 category/slice/cap，所选 entry 的 capability/profile/origin/model-or-voice 必须完全相同。禁止跨 target 拼接；globalCaps 只是额外总上限。disclosureManifestDigest = SHA-256(JCS(完整 manifest))；所有数值为非负安全整数，调用只能缩小。
- NormalizedEndpointV1 在摘要前执行：scheme/host 小写、IDN 转 punycode、缺省端口补为有效数字（https=443、http=80）、path 点段与百分号编码规范化、禁止 query/userinfo/fragment；https 是 model/TTS 默认，http 仅允许固定 loopback AnkiConnect。ProfileConfigurationManifestV1 的字段按 capability 判别联合封闭，configurationFingerprint = SHA-256(JCS(manifest))，秘密值不进入 preimage，credentialRevision 独立绑定。
- RequestParameterPolicyManifestV1 只允许 fixed/enum/range 三种非秘密规则，unknownParameterPolicy 固定 reject。rule 按 NFC 规范化 name 的 UTF-8 字节序排序并拒绝重复；enum allowedValues 先按“JSON 类型标签 + JCS 标量 UTF-8”排序并拒绝重复；number 必须有限，minimum<=maximum。requestParameterPolicyDigest = SHA-256(JCS(manifest))，并作为 model/TTS configurationFingerprint 的 preimage 字段；任何参数策略变化都使 profile 验证与批准 stale。
- EgressManifestV1 从已保存 profile 派生，不接受 Agent 自报。allowedMethods/contentTypes 先按 UTF-8 字节序排序并拒绝重复；egressManifestDigest = SHA-256(JCS(manifest))。origin/path/method/content-type/redirect/proxy/DNS/响应上限任一变化都使旧批准失效。
- CostBudgetV1 使用 ISO 4217 货币、整数最小货币单位和版本化 pricing snapshot。价格未知时必须明确显示 unknown；只有用户明确批准且同时存在硬资源上限时才可继续，否则 block。
- system.request_operation_confirmation 只能经受信本地 UI 和真实 user gesture 更新 OperationApprovalLedgerState，并据此签发绑定 call_model/call_tts 的内部授权；operationIntentId 只是定位符，不是 bearer。
- 原工具重试时重建并核对同一 OperationRequestManifestDigest、audience、intentDigest、profile/configurationFingerprint/credentialRevision、精确 disclosure/egress、资源/费用上限与当前撤销状态；任何变化都要求新 intent。随后生成的 TaskInputManifestDigest 包含 intentDigest。
- 重启/新 session 后旧 audience 授权绝不搬迁或回填旧任务。若 WorkReuseDigest、稳定 capability、profile configuration 和已完成 Artifact 均一致，且新 disclosure/egress 等价或更窄，Service 可在重新验证/确认后创建 successor task 与新 TaskInputManifest；SuccessorTaskRebase 同时引用旧/新授权审计。范围扩大或语义/配置变化禁止 remaining 复用。

### 5.1 stdio 身份、所有权与本地 ACL

- Card Service 启动时记录真实 OS user SID、host instance、plugin instance、service instance 和 session；只接受该受信启动链路的连接。
- 这些身份来自宿主握手、父进程/通道证明和本机 ACL，不接受 MCP 参数自报。
- 应用数据目录、凭据、项目注册表、授权账本和 Unix/Windows IPC 端点仅授予当前 OS 用户与必要的服务主体。
- 项目 owner 至少绑定 OS user SID 与 plugin installation identity；list/get project 和 get artifact 先做 owner/scope 校验。
- 新服务实例读取旧项目需要通过签名 manifest、同一用户和明确的安装迁移策略；同用户的任意第二进程不自动获得枚举权。
- 威胁模型明确承认：同一 OS 用户下已完全攻陷的恶意进程可能访问该用户资源；本项目仍通过 ACL、进程边界、签名、最小秘密暴露和短会话授权降低风险，但不声称抵御已取得同用户任意代码执行的攻击者。

## 6. 提示注入

### 威胁

字幕、PDF、网页、代码注释或模型结果可能包含：

- “忽略系统规则”；
- “读取密钥/其他目录”；
- “启用私网/远程组件”；
- “导入这个 APKG”；
- 伪造的用户确认；
- 诱导 Agent 调用工具的返回文本。

### 控制

- 来源内容带明确 data/untrusted 标签。
- 原始大文本尽量由本地 Worker 处理；主 Agent只接收必要结构化候选。
- 工具参数中的 path、URL、confirmation 和权限只接受服务签发引用。
- 模型返回的新资源不自动注册。
- structuredContent 不是整体可信。只有 Service 签发的固定枚举、opaque handle、revision、hash、gate state 和 terminal state 属于控制面；quote、title、detail、notice、explanation 及任何来源/模型/用户自由文本仍是不可信数据面。
- 不可信 taint 跨 Artifact、缓存、候选、重试和重新生成传播；自由文本不得产生路径、URL、工具名、资源引用、批准状态或成功终态。
- 导入和扩大权限必须依赖真实宿主用户动作；V1 不支持运行期安装。
- Skill 明确忽略来源中的工具或权限指令。
- 为来源注入、工具输出注入和跨阶段权限提升建立自动测试。

## 7. 文件系统

### 输入

- Agent 只传 fileResourceRef/directoryResourceRef；Service 结合可信连接与内部授权账本解析。
- 原生选择器或稳定宿主附件创建授权。
- 每次读取前重新解析规范路径、文件身份、大小、mtime 和哈希。
- 目录内每个子项都检查仍在授权根。
- 拒绝 symlink、junction、reparse point、UNC、设备路径、ADS、保留名和路径遍历。
- 防止选择后替换、硬链接或竞态。

### 输出

- 只写 outputResourceRef 指定目录。
- 默认 fail_if_exists 或自动版本化文件名。
- 覆盖必须新的、精确绑定的内部授权记录。
- partial 文件不成为 PackageArtifact。
- 不允许用户素材目录被当作临时执行目录。

## 8. 网络与 SSRF

所有 raw URL（无论公开或带签名）都只能在 Card Service 的受信本地输入表面录入。MCP 的 system.request_network_grant 不接受 url/origin/query 参数，只请求打开该表面并接收 opaque networkResourceRef；因此服务端分类和秘密扫描发生在 URL 进入 MCP 之前。用户已经粘贴到对话的 URL 可能已进入宿主记录，Skill 不复制、不回显、不调用，并对疑似凭据建议撤销/轮换；新 URL 只能重新在受信表面输入。

所有 URL 访问经统一网络代理：

- 只允许 http/https 和已批准服务协议。
- 规范化 hostname 和端口。
- 拒绝 URL userinfo（user:pass@host）和调用方自报 Authorization/Proxy-Authorization/Cookie 等认证 header；fragment 不参与网络请求，也不得持久化。query 仅在内部 canonical request/授权摘要中保留必要语义，Artifact/MCP/日志只保存 allowlisted 公共身份参数或不可逆 query digest/redaction。
- 解析全部 A/AAAA；任何非公网目标默认拒绝。
- 连接时复核解析目标，防 DNS rebinding。
- 每次重定向重新校验。
- 重定向 Artifact 只记录脱敏 origin 与 canonical request digest；不得保存含 token/signed query 的 raw Location。HTTP 元数据使用字段 allowlist，排除 Set-Cookie、认证/代理头和浏览器会话状态。
- 阻断回环、私网、链路本地、保留、云元数据和特殊数字 IP 表示。
- 私网访问使用一次性强确认的内部授权记录。
- networkResourceRef 绑定完整 canonical request digest：scheme、punycode hostname、port、method、path policy、query digest/脱敏策略、redirect policy、最大响应体和超时；后续请求只能缩小，不能替换 path/query。
- Provider profile 固定 Base URL；Agent 不能提交任意 Base URL。模型/TTS 授权绑定 profileRef、configurationFingerprint、credentialRevision 和 egressManifestDigest。
- 统一网络代理默认不携带浏览器 Cookie、系统凭据、NTLM/Kerberos、客户端证书或环境代理认证。
- AnkiConnect 固定明确回环端点、配置的 API key 和版本范围，不跟随重定向。
- yt-dlp 走等价网络约束，不能成为代理绕过。

当前 M1 只实现上述目标的一条窄路径：`source.youtube_subtitles` 由 Service 从任务授权中重建固定 YouTube video identity，Worker 只能提交 video ID、语言和 `vtt`。Service 只访问 `youtube.com`/`www.youtube.com` 的 watch 与 `/api/timedtext`，解析全部 DNS 结果且任一非公网地址即拒绝，连接时固定已验证公网 IP并保留 TLS SNI/hostname 校验；重定向、userinfo、非 443 端口、fragment、非固定 host/path、超时和超限响应均 fail closed。caption signed query 不返回 Worker、不写 ledger。该切片尚未实现 M2 的 opaque `networkResourceRef`、逐请求批准/撤销账本或完整视频下载；托管 Worker 的直接联网 yt-dlp 因此一律在启动前拒绝。

## 9. 文档与媒体解析及资源隔离

### 9.1 文档解析

- 文档解析在受限子进程。
- 文件大小、页数、成员数、解压字节、压缩比、字符数有上限。
- CPU、内存、墙钟时间和进程数有限制。
- PDF/XML/HTML/Office/EPUB 的崩溃不影响 Card Service。
- 外部程序使用受信绝对路径和哈希。
- 默认禁用宏、外部实体、远程资源和嵌入执行。
- 解析器输出继续视为不可信。

### 9.2 媒体下载与解析沙箱

M3 的本地/URL 视频链把 FFmpeg、ffprobe、yt-dlp 及任何辅助运行时视为不可信解析器，而不是 Card Service 的同权限扩展：

- 每次 helper 调用都在独立受限子进程中运行。Windows 发布基线必须把 Job Object 的 CPU/内存/墙钟/子进程/输出限制，与可证明的文件系统和网络隔离组合：使用 AppContainer 身份，或专用 restricted SID + 仅对 staging/精确输入开放的 DACL；同时禁止继承非必要句柄。仅有 low-priv token/Job Object 不足以通过。其他系统使用等价的 sandbox/seccomp/cgroup/seatbelt 与文件/网络策略。
- launcher 只执行签名 manifest 中固定绝对路径和哈希的二进制；命令行由 Service 根据固定 schema 生成，不经 Shell，不接受用户、来源或模型提供的 filter、postprocessor、输出模板、配置文件或额外参数。
- yt-dlp 使用 `--ignore-config` 和专用 staging 目录。命令行、环境变量、响应文件、日志和崩溃转储不得出现 raw URL/signed query：Service 只在受控内存中解析 networkResourceRef，并通过继承的单次匿名管道（例如 stdin batch input）或 task-bound opaque broker locator 交付目标；管道写后清零并关闭。网络必须经过统一受控代理。禁止 ambient Cookie、浏览器 profile、netrc、系统集成认证、外部 downloader、任意 postprocessor、`--exec`、远程组件和任意输出路径。
- Windows 上 yt-dlp 的进程出站必须被 AppContainer capability/防火墙-WFP 等可验证策略限制为 broker/受控代理端点，不能只靠 `--proxy` 参数约定；FFmpeg/ffprobe 和其他本地解析 helper 为零网络。若当前机器无法建立文件 ACL 隔离或强制出站边界，相关 URL adapter 必须 fail closed，本地 adapter 也不得在宽权限 helper 下继续。
- 代理/broker 对每个请求重新解析 networkResourceRef 的 canonical policy、DNS/redirect 和剩余字节/时间预算；helper 不能自报 Authorization/Cookie/header 或替换 origin/path/query。若目标必须使用 signed query，它只存在于授权账本、broker 和受限 helper 短期内存，不落盘、不回显。
- yt-dlp 的下载与 FFmpeg 解码分阶段。FFmpeg/ffprobe 不接收远程 URL，只读取 Service 提供的只读本地资源句柄或受控 staging 副本，并写入单次任务专用输出目录；进程网络默认禁用。
- protocol 与 demuxer allowlist 按 adapter/version 冻结。当前 M1 本地媒体实现只允许 `file`，明确拒绝 pipe、concat、subfile、crypto、data、http/https、ftp、tcp/udp、rtmp 及未列入协议；playlist、response file、外部字幕/附件和嵌套资源不得隐式打开。若未来来源确实需要 pipe 或新增协议，必须提升适配器版本并单独安全评审。
- 每个任务冻结输入总字节、流数量、元数据大小、时长、帧数、分辨率、像素总量、采样率、声道数、码率、解码输出字节和临时磁盘上限；超限、未知持续增长、畸形时间戳或流探测不一致一律 fail closed。
- 输出重新探测并校验允许的媒体类型、哈希、大小、时长、流布局和目标目录；只有通过校验的 basename/Artifact 才能进入媒体账本。helper 崩溃、超时或沙箱违规只使对应工作单元失败，不得影响 Service 或发布半成品 Artifact。
- 恶意 corpus 至少包含 playlist/manifest 注入、concat/subfile/协议走私、畸形容器、超大元数据/附件、极端帧数/分辨率/采样率、无限或循环流、解码炸弹、磁盘填充、外部配置发现、同名输出与路径穿越。

## 10. 模型、TTS 与秘密

- UI/Agent 只使用 providerProfileRef、modelProfileRef、ttsProfileRef 和 credentialRef。
- 插件只可查询 secret_exists 或能力状态。
- load_secret 永不成为 MCP 工具。
- 只有 Card Service 内的 model/TTS broker 可在受控内存中解析 SecretRef 并调用固定 profile 服务；其他模块和 Worker 不接触明文秘密。
- Legacy Worker 无 provider secret、真实远程 Base URL 或公网权限；模型/TTS 只经 task-owned 认证 IPC 调用 Card Service broker。Worker 只能提交 StudyIR 冻结的 BrokerModelRequestV1/BrokerTtsRequestV1；每个请求绑定 task/work unit、audience、OperationIntent、AuthorizationBinding、精确 profile/configuration/credential、DisclosureEntry、EgressManifest、CostBudget、权威 Artifact locator、payload digest 和服务端 HMAC 幂等键。Service 重建最终请求；不存在 raw HTTP、任意 URL/header/prompt/text 透传。
- broker 每次调用前在一个原子事务校验授权/撤销并写 BrokerReservationLedgerV1.reserved，预留最大调用数、字节/token、TTS 字符/时长和成本。只有 reserved 可 sent；发送前崩溃释放，发送后崩溃转 possible_incurred 并保留最大预留，不能盲目重发；settle 单调一次，未知 usage 按上限结算。同一 idempotency key 配不同 payload digest 必须拒绝。
- TTS 文本由 Service 按 AuthorizedTextLocatorV1 从权威 Artifact 重读、规范化并核对 SHA-256；Worker 提交的任何替代文本都无效。TTS 请求只选择其 tts_text entry；模型请求可组合同一 target 的多条 entry，但不能把片段改送另一 capability/profile/origin/model。
- 向远程服务发送前展示数据域、服务商、用途和范围。
- 配置验证记录绑定精确 capability/profileRef/configurationFingerprint/credentialRevision，展示 aggregate 永不解锁具体 profile。
- 凭据账本在新增、替换、删除/清空、OAuth 账户或 token material 变化时原子单调递增 credentialRevision；旧 revision 永不复用，即使回滚到旧 secret 也生成新 revision。并发修改必须序列化，每次成功修改立即使旧验证、批准和能力绑定 stale。
- 服务错误正文先脱敏再返回。
- broker 不提供 raw HTTP、任意 URL/header/prompt 透传；Worker 直连公网、越过 broker、跨 task descriptor 或扩大 Artifact/locator 一律阻断。

使用秘密 canary 验证它不会出现在：

- MCP 参数/结果。
- 模型上下文。
- StudyTaskSnapshot/Artifact/Checkpoint。
- stdout/stderr、诊断包和崩溃报告。
- App UI、截图和通知。

## 11. 外部工具与供应链

禁止公共工具：

- repair_env。
- pip/winget/任意安装。
- 任意 Shell。
- 启用 yt-dlp remote components。

发布要求：

- 固定 Python 包版本和哈希。
- 固定 Worker、FFmpeg、yt-dlp、运行时及解析器哈希。
- 优先捆绑，不能从不可信 PATH 解析。
- 使用固定发布者信任根签署 canonical release manifest；外层安装包使用 Authenticode/等价包签名，并由宿主或安装器在 launcher 启动前验证。
- canonical manifest 覆盖 plugin manifest、Skill、MCP 配置、App 映射、Card Service、Worker、FFmpeg、yt-dlp、schemas、SBOM 和所有资源哈希。
- manifest 包含 keyId、签名时间、有效期、撤销信息、最低允许版本和兼容范围；密钥轮换和撤销有离线可验证策略。
- launcher 只信任已经通过外层签名验证的 manifest；不能仅靠 launcher 内嵌哈希自证。
- 可复现构建、SBOM、签名和第三方许可。
- 回退只能到仍在允许清单中的已签名版本，拒绝已撤销或低于最低版本的降级包。
- V1 禁止动态安装组件、下载可执行 remote component、curl-pipe-shell 和运行未经签名仓库脚本。

当前 M1 实现已把内层托管运行包从“自报哈希”升级为 detached Ed25519 验签：正式模式不接受运行包自带的任意公钥，必须由受信 launcher 提供独立 canonical trust policy；同时验证签名期限、密钥撤销、最低版本、trust sequence、防同版本换内容和 SPDX 文件级覆盖。CPython 3.13 / cp313 / win_amd64 的直接与传递 wheel 使用 25 项精确版本/SHA-256 lock，包内必须携带该锁且核心包版本不符即拒绝；便携 Python 只允许离线、only-binary、require-hashes 组装，排除 ambient 包/工具并拒绝 pyc。其有界 canonical build metadata 必须在 staging 前与实际 lock digest/条目数匹配，并以独立资源进入 SBOM/签名 manifest；正式加载时再次交叉验证，阻止把来自不同构建的 Python root 与锁拼接。短期本地宿主探针签名每次使用随机密钥且私钥不落盘，只证明内层验签路径，不能替代发布密钥；宿主探针还关闭与验证无关的 plugin 远程同步，避免网络更新改变本地供应链结论。该边界不替代外层 Authenticode/等价签名，因此在 M4 发布链完成前仍 fail closed 地标记为未完成发布态。

当前外层 launcher 进一步把 runtime manifest 与 trust policy 的精确 SHA-256 编入原生二进制，并在任何包内 Python 运行前逐项验证 manifest 固定的 4380 个资源和精确文件集合；它拒绝 reparse、路径逃逸、路径碰撞、Windows 保留名、缺失/额外文件与哈希/大小变化，只接受固定 stdio 模式并清除 Python 路径注入变量。launcher 构建器先验证内层签名，随后使用锁定依赖、离线 Cargo、禁用增量、固定 epoch 和 MSVC `/Brepro`；两次隔离构建字节一致。策略/资源篡改负例与真实 Codex 独立副本探针均通过。该 pin 只有在 launcher/安装包本身由受信发布者签名后才建立发行者信任；当前机器没有可用代码签名证书，探针只使用临时内层策略，因此插件 manifest 仍不声明 MCP。

外层候选包构建器只允许被动插件、固定 launcher、已签名 runtime 和独立 trust policy，生成覆盖精确文件集合的 canonical manifest 与 SPDX；任何 MCP/App 声明、源插件 `server/`、reparse、路径碰撞、复制中变化、缺失/额外文件或哈希差异都 fail closed。外层树使用当前用户/SYSTEM/Administrators 的受保护 DACL，runtime 子树再用固定 AppContainer SID 的只读执行 DACL，构建前后逐项读回。受限宿主缺失 `PROCESSOR_ARCHITECTURE` 时，launcher 固定声明其自身 AMD64 构建架构，未来运行包同时从 `sysconfig` 标签判定，不依赖可被裁剪的 ambient machine 字符串。候选包仍把 installable、MCP 声明、外层签名与发布密钥管理全部固定为 false；这条链验证装配和宿主行为，不提供发行者身份。

外层发布签名现增加“仓库内只生成请求、仓库外私钥签名、仓库内独立验签”的封闭接口。签名请求只能从完整验证过的候选目录生成，trust policy 必须由候选包之外的受信发布面提供；请求以 `study.plugin-release-manifest.v1` 域绑定候选 manifest、package/version、key epoch 和时间窗，脚本没有任何私钥参数。验签器拒绝非 canonical 策略/签名、未受信或撤销密钥、超长期限、过期签名、低于最低版本、撤销版本/manifest、trust sequence 回退/分叉和同版本换内容。该实现没有生成正式发布密钥，也没有创建签名或 MCP 映射；Authenticode/等价代码签名和最终安装器验证仍是独立硬门槛。

候选 DACL 的只读验证不再调用 `CreateAppContainerProfile`：微软将该 API 定义为创建 [per-user、per-app profile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile)，而创建 AppContainer 进程的安全属性消费的是 [`SECURITY_CAPABILITIES.AppContainerSid`](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-security_capabilities)。因此验证阶段只从 moniker 派生 SID，profile 创建保留为显式 provisioning 操作。这样受限 Codex 令牌可以验证既有候选，而不会因缺少“创建每用户 profile”的权限误报 DACL 损坏，也不会让验签产生系统状态副作用。真实候选已在受限 shell 中完成该无副作用验证；正式安装器仍需单独证明 profile provisioning、失败恢复和卸载策略。

当前 M1 本地媒体切片还把 FFmpeg/ffprobe/yt-dlp 固定为签名 manifest 中的精确绝对资源：FFmpeg/ffprobe 只接收绝对本地普通文件和固定 `file` protocol/demuxer allowlist，拒绝 playlist、concat/subfile、网络协议、UNC/NT 设备/ADS 路径、任一祖先 symlink/junction/reparse 和调用方策略覆盖；所有调用均无 Shell、stdin 关闭且超时有界。托管 yt-dlp 不采用会写死构建机 Python 的 pip console launcher，而使用无第三方依赖的 Rust 启动器从自身受信位置解析包内 Python，固定执行 `-I -B -m yt_dlp`、移除 Python 路径覆盖变量并传递真实退出码。托管 FFmpeg 启动前还会用限时、限输出、最多 32 流的 FFprobe 证据冻结总输入字节、时长、码率、尺寸/像素、帧率/帧数、采样率、声道和逻辑解码量；输入在探测期间变化、证据缺失、附件或任何上限超出均 fail closed。命令语法只允许一个本地普通文件输入和一个新的最终输出；多输入/多输出、循环/实时参数、未知选项、任意滤镜和显式输出格式在启动前拒绝，`-vf`/`-af` 只接受固定缩放与音量表达式。输出统一加 512 MiB `-fs`，触顶结果会删除；非零退出、超时、空输出和未产出文件的假成功同样不能留下可消费半成品。受限子进程以自己的 task workspace 为 cwd；Service 对目录执行不跟随 link/reparse 的逻辑字节/条目预算，超限时终止进程并拒绝成功结果。跨任务准入在同一进程内原子预留每个活动任务的最坏剩余增长，把终态遗留文件按真实大小/条目计入默认 8 GiB/100,000 项总上限；启动、运行中每秒复核与成功接纳使用 4 GiB 卷剩余空间缓冲，容量无法证明或跌破缓冲线即终止并拒绝结果。该机制是 process-scoped admission/periodic 防线，不是跨多个 Service 实例的原子账本，也不能阻止任意外部进程在复核间隔内写满磁盘；能力摘要必须明确报告它不是 external-writer hard quota。终态目录不会在 Artifact 引用与保留合同完成前自动递归删除，避免为释放空间破坏仍被结果引用的媒体。托管 yt-dlp 强制忽略外部配置、禁用插件/exec/playlist，并无条件拒绝 remote components；在托管 Worker 内直接调用联网 yt-dlp 现在会在创建子进程前 fail closed。受控来源 Broker 已覆盖 YouTube 字幕-only 获取、固定端点、DNS/IP pinning、TLS hostname 校验、无重定向、任务绑定和有界 VTT 证据；完整视频/音频下载仍未开放。真实畸形容器已在 AppContainer + Job + DACL 内失败且未改动旁侧文件，真实 FFmpeg 多输出/循环参数在启动前被拒绝，真实受限 Worker 写超限文件也会被拒绝。新增的小于 1 MiB 实物语料覆盖极宽、高帧率、稀疏超长时轴、逻辑解码量大于 16 TiB 和 33 流扇出，五类都在正式媒体策略解码前 fail closed 且无输出；逻辑解码炸弹和稀疏时轴容器还在 AppContainer + Job + DACL 内完成真实探测并保持旁侧文件不变。命令级循环、playlist 和 concat 没有可接受语法；更广泛的 codec parser 崩溃/fuzz corpus、跨进程协调和 M2 安全保留清理仍是未完成边界。

当前 M1 Provider Egress 切片把 Worker 请求缩到固定 operation 的 `{workUnitId, request}`；所有 profile、origin、endpoint、model/voice、credential revision、operation intent、预算和预留成本由 Service 闭包绑定，认证头只在 Service 传输前构造。远程 origin 必须 HTTPS 且固定到官方/项目已知 host；Hermes 仅允许字面 loopback，任意 custom compatible origin 暂不开放。默认传输禁用 ambient proxy、拒绝 redirect、限制请求 schema/长度、超时和响应字节。Legacy Worker 的 OpenAI-compatible、Anthropic、Gemini 模型入口和生产 TTS/TTS 测试均已走 task-owned broker；TTS Worker 请求不包含 provider、origin、model、voice 或 credential，Service 固定 OpenAI/xAI/MIMO/Qwen/Gemini 适配器并校验返回音频的 Base64、长度、SHA-256、MIME 与 PCM 采样率。Qwen 二次 URL 被拒绝，受管 Vertex 模型/TTS 在 Service OAuth egress 完成前 fail closed。真实受限 Worker已分别完成无 Worker secret/origin 的卡片生成和 TTS 测试。

正式 stdio 现由 `ServiceBrokerRuntime` 解析 Service-owned 启动授权：清单只能来自固定 state dir 的 `trusted-surfaces/authorizations`，必须是 canonical V1、最长 24 小时并精确绑定方法→能力→profile、configuration fingerprint、credential revision、intent ref 和硬预算。正常签发路径进一步把期限限制为最多 60 分钟、远程调用/请求/响应/成本限制在发行器硬上限内；账本按 operationIntentRef 在全部消费 task 间合计这些额度，不能通过创建新 task 重置预算。可信窗口以可滚动文本展示规范化 provider origin、model/voice、方法、来源和“本授权合计预算”，HMAC 验证真实点击后才由 Service 写入清单并内部热加载；热加载不仅检查固定目录和 canonical schema，还必须与签发时保留在 Service 内存中的 expected digest 相等，阻止签发后同目录替换。远程 credential revision 由 Service 从 OS 凭据元数据冻结，凭据在窗口打开后变化会使签发失败；Hermes 固定 revision 0。任务创建前复核清单期限和凭据版本，每次出站前再次复核期限；任务请求递归拒绝 profileRef、credentialRevision、operationIntentRef、budget、reservedCost、serviceBindings、brokerDescriptor 和 configurationFingerprint 等 Service-owned 字段。能力查询和 trusted-surface 结果只返回 digest、期限和数量，不返回路径、配置执行 token 或 secret。任务在创建时冻结 Broker factory，因此授权热切换不会扩大已排队任务的权限。该边界证明 Agent/Worker 不能绕过受信点击选择授权，但 M2 每次 OperationIntent 的持久批准、撤销与原子消费账本仍未交付；真实公网凭据调用也未验证，因此还不能声明全部模型/TTS 出站边界完成。

受信 UI 的用户手势响应现使用每会话 256-bit HMAC 密钥和 `study.trusted-surface-response.v1` 域隔离；密钥只在 digest-pinned 子进程启动后经 stdin 传递，session/response 文件和公开结果均不含密钥。Service 必须先校验 MAC，再校验 session/nonce，并在首次成功后从内存删除密钥；无 MAC、错误 MAC、改 nonce 或重复启动均 fail closed。这只认证“哪个受信窗口产生了该响应”，尚不等同于 M2 的 OperationApproval/ImportApproval 持久账本、撤销和原子消费。

## 12. Anki 持久写入

风险：APKG 可包含模板 JavaScript、媒体并影响已有 Note Model。因此导入是高影响持久写入。

唯一公开写接口是 anki.import_and_verify(importIntentId)。importIntentId 只定位服务器端不可变 ImportPlan 和批准状态，本身不是授权 bearer。

服务必须：

1. anki.prepare_import 从导出注册表加载 PackageArtifact，不接受任意路径，并冻结完整 ImportPlanDigest。
2. ImportPlan 绑定项目修订、APKG SHA-256/大小、目标 Anki profile/collection、deck、note/card/media 数、固定 duplicate policy、template family/schema、Note Model、兼容合同、AnkiVerificationContract、权威 CardIdentitySet/CardMediaRoleInventory、RequiredAnkiCheckManifest、front/back/CSS/JS 与媒体哈希、Anki/AnkiConnect 版本、RuntimeVerifierBinding（实现/兼容合同/producer trust/protocol）及摘要、RuntimeVerifierIsolationPolicy 及摘要、确定性采样、AnkiConnect configurationFingerprint/credentialRevision、服务端 HMAC 凭据绑定和失败恢复；不得保存或显示 key。
3. anki.request_import_confirmation 在模型外的受信窗口展示完整计划；真实用户确认只写入当前 audience/session 的内部 authorization ledger，不返回 token/ref。
4. anki.import_and_verify 仅凭 importIntentId 查询并原子消费该会话的批准状态，重新验证完整计划和文件身份。
5. 拒绝调用方传入任意 anki_query、manifest、media_dir、路径、duplicate/update policy 或 import action。
6. V1 duplicate policy 固定为 detect_and_report；update_matching 延后到单独破坏性设计和确认。
7. 预置媒体本身是持久写入，必须记录本次创建清单；后续失败时报告或安全清理孤立媒体。
8. 使用 importIntentId 做并发和重放幂等，执行前先查询是否已发生导入。
9. 检测同名异哈希媒体和 Note Model 冲突；实际导入 CardId 必须等于非空权威 CardIdentitySet，每卡必须恰好一条 CardMediaRoleInventory 记录并绑定角色、文件 SHA-256 与 media-manifest entry。按固定 AnkiVerificationContract/RequiredAnkiCheckManifest 完成字段、模板、媒体和 TTS 文件证据；空集、子集、缺失、重复、未知检查或合同版本不匹配一律失败。
10. 仅 AnkiConnect 的结构/数据证据最多成为 anki_data_verified；正背面渲染、翻面、滚动、缩放、媒体实际播放和重启复习必须来自版本化 trusted Anki add-on 或 GUI protocol 的 AnkiRuntimeEvidenceArtifactPayload。
11. RuntimeVerifierBinding、producer proof key/epoch、root-signed revocation snapshot、固定 11/10 checks、权威 identity/media、Service-derived nonempty双视口 expectations、sample/tuples 与 IsolationPolicy 都进入 ImportPlanDigest。R8b 先在 audit/environment boundary 内创建不含 run digest 的 PreRunSourceStateSnapshot 与 trusted copy，再签无环 RuntimeVerificationRunBinding。service/copier/verifier snapshots 各有单调 sequence、逐 `(keyId,keyEpoch)` 的 root-signed raw Ed25519 publicKeyRef/SHA-256 映射、完整 append-only tombstone history 与 OS-protected anti-rollback floor；prepare、run start、final commit 都重查当前最高序列和精确公钥版本，旧快照、撤销 key 或 keyId 同名换钥不可回滚。
12. passed 不能来自 payload 自报。所有 passed/failure proof facts 使用 `study.anki.runtime-proof.v1` 域，由 launch-attested verifier process 的绑定 key 签名；Service 从签名/认证通道派生 producer，并执行 typed predicate。正背面 expectation 必须由 CardPlan/字段/模板派生且各有 root+非空关键文本；媒体事件与 resolved SHA 有效；restart 精确绑定 helper 和真实 isolated-Anki 的 before/after process、launch attestation、window owner 与四事件映射。错 proof/signature/process/window/Blob 立即 ANKI_VERIFY_FAILED。
13. 零写审计不能只用 connection-local SQLite hook。每相位必须同时具备 add-on all-connections hook、collection DB/WAL/SHM 跨进程 storage journal、media-tree journal三份 service-signed coverage；稳定资源身份/cursor、gap、overflow、reset 可重算，后三项必须为 0。typed focus event 强制 from/to 与可信动作归因：signed append-only run-owned process lifecycle ledger 必须覆盖 Service main、全部曾加入 Job Object 的 child/proxy、join/exit 历史和独立 cutoff-active subset；focus 按事件时 membership 归因，既有 Anki 内 add-on 的 raise/activate/set-foreground 必须逐动作签名；无法区分用户/外部/run/add-on 动作即 unavailable。谓词对称检查 from 或 to 触及 baseline 用户 Anki，任一外部写后恢复、关闭/重启/抢焦点用户 Anki 都失败。
14. final read barrier 每次使用新 instance/read-snapshot identity；11 条 typed final-check evidence 绑定 run/boundary/commit descriptor/capturedAt；Typed FinalRuntimeEvidenceInputsManifest 以固定成员、cardinality、排序和 JCS preimage 绑定全部 observations/proofs、data/profile states、audits、environment、run-owned lifecycle ledger/process launches、add-on focus attestations 与 final checks，其 digest 和 aggregate 同时进入 barrier signature并由 FinalReverification/RuntimeEvidence复用。write sensors 与 environment observer 在签名 cutoff 后继续 armed，commit 前任一 disqualifying event 中止私有 write set。barrier attestation、final reverification、runtime evidence 与 VerificationArtifact 以预分配 ID 原子提交后才释放。可信 failure proof 返回 runtime_failed；合同/签名/run/TOCTOU 形状不一致返回 ANKI_VERIFY_FAILED；只有最终数据、零写和全部 observations 通过才为 anki_verified。15. 手动打开 APKG 由用户在插件公共 MCP 之外执行；插件不得代替用户打开或从窗口出现推断成功，只能保持 apkg_ready，或在检测到导入但证据不完整时标记 imported_unverified。
16. 跨会话/崩溃恢复先生成 AnkiRecoveryDecisionV1：确定未写入时为同一仍有效 ImportPlan 派生新的 session-bound recoveryImportIntentId 并重新确认；身份完全匹配已写入时仅创建 verification-only successor；写边界不明时停在 conflict/interrupted。旧批准和已消费 importIntent 只审计，不转移、不复用。

## 13. 数据最小化与保留

默认：

- 来源和产物保存在本机项目目录。
- 对话只接收候选摘要和必要证据片段。
- 远程模型只接收完成当前子任务的最小片段。
- 日志使用 opaque ref，不记录完整来源。
- 本地审计默认保留 30 天或由用户策略配置。
- APKG 和用户明确保留的项目不随插件卸载删除。

用户可以查看：

- 哪些来源被读取。
- 哪些片段发送给哪个服务。
- 哪些本地目录被授权。
- 哪些 Anki 内容被创建/更新。

## 14. 日志与诊断

结构化日志字段有 allowlist。禁止：

- 认证头、查询 token、Cookie。
- 源正文全文。
- 未裁剪绝对路径。
- 原始服务商错误体。
- 任意环境变量转储。

诊断包生成前运行：

- secret canary scan。
- 路径脱敏。
- 来源片段截断。
- 用户预览和明确保存。

插件不默认上传遥测。

## 15. 权限撤销

- system.revoke_grant 只打开受信本地授权管理器；MCP 不接收或返回 authorizationId、ledger key、userGestureRef 或撤销 bearer。
- 受信 UI 可按项目查看并单独撤销文件/目录/网络授权、模型/TTS OperationApproval、Anki ImportApproval 和尚未消费的内部授权记录。
- AuthorizationLedgerState、OperationApprovalLedgerState 与 ImportApprovalLedgerState 都有 revoked 终态；消费与撤销使用同一服务端原子事务，竞态只能有一个成功。
- 撤销后新调用立即失败；运行中任务在安全点取消，不得继续扩大读取或开始新的远程批次。
- 已完成的远程调用、已写入 Anki 的内容和本地产物不会被伪装成已回滚；产物保留并记录撤销时间与影响。
- 删除本地数据是独立的预览与确认流程，不与撤销混为一谈。

## 16. 发布阻断测试

至少覆盖：

1. 字幕/PDF/网页/模型结果中的工具指令不改变权限；结构化自由文本也不能进入控制面。
2. 工具输出注入不触发敏感调用，requiredAction 只能使用固定 enum。
3. 任意路径、伪造确认布尔值、复制 handle 或自报 session 被拒绝。
4. symlink/junction/reparse/UNC/ADS/设备路径/硬链接/TOCTOU 无法逃逸。
5. ZIP bomb、挂死 PDF、巨大文本在资源上限内失败。
6. FFmpeg/ffprobe/yt-dlp 的 protocol、playlist、concat/subfile、外部配置、任意 postprocessor/exec、畸形容器和解码资源耗尽 corpus 在沙箱内 fail closed；helper 无法联网越界、读取额外文件或写出 staging 目录。
7. IPv4/IPv6/数字变体/DNS rebinding/重定向到私网被拒绝。
8. 内部授权记录不能跨 task、intent、完整 URL、profile、credential revision、策略、项目、会话、客户端或 service instance 重放；canonical authorization/scope preimage 的字段、顺序、重复项和 expected revocation epoch 任一变更都使摘要变化，并发消费只有一次成功。
9. OperationRequestManifest → OperationIntent → TaskInputManifest 的摘要链无循环；profile_validation 可在无项目、无 configurationSessionRef 的已保存 profile 复检场景合法构造。
10. DisclosureManifest 每条 target/category/source locator/cap 与全局 caps、CostBudget 计价快照/硬上限逐字段 mutation 都使批准失效；跨 target 交换 slice/category、重复 entry 或非 canonical 顺序被拒绝。AudienceBindingManifest、ProfileConfigurationManifest 和 EgressManifest 的任一 canonical 字段变化同样阻断重放。
11. system.request_network_grant schema 对普通和敏感 URL 都没有 raw url/origin/query/header 字段；所有插件摄取 URL 只能经受信输入表面进入内部 broker。networkResourceRef 不能替换 path/query，网络请求不携带浏览器/系统集成认证；经 trusted-entry 新输入的 signed/token canary 不得出现在 MCP 请求/响应、模型上下文、helper 命令行/环境/响应文件、日志或崩溃转储。预先粘贴到聊天的 canary 只验证“不复述、不转发、不调用并警告轮换”。
12. Agent 不能启用远程组件或任意 Base URL。
13. PATH 同名恶意程序不会执行。
14. 明文秘密不能进入任何 MCP、任务、Artifact、日志或截图。
15. 凭据 add/replace/delete/rollback/concurrent update 均严格 bump credentialRevision，并使旧 profile verification、OperationApproval 与执行绑定 stale；profile A 的 passed 不得解锁 profile B。
16. Legacy Worker 无 provider secret/公网，只能提交冻结的 BrokerModelRequest/BrokerTtsRequest；task/work unit/audience/intent/授权/profile/DisclosureEntry/egress/budget/locator 任一替换失败。BrokerReservationLedger 覆盖并发、撤销、over-budget、crash-before/after-send、usage 缺失、同 key 异 payload 与 retry；未知费用按最大预留。
17. repair_env、load_secret、run_worker 和 raw AnkiConnect 不在工具清单。
18. 调用方重算哈希后篡改 Artifact、替换父产物、跨项目 transplant 或伪造 PackageArtifact 都被拒绝。
19. 外部/替换/篡改 APKG 导入前被拒绝。
20. Anki 批准状态绑定完整 ImportPlan、profile/collection、策略、revision 和 hash；MCP 不获得 bearer token。
21. 文件/网络授权、OperationApproval 与 ImportApproval 在消费前都可由受信管理器撤销；撤销与消费竞态只能有一个原子胜者。
22. 并发/重复导入不产生重复卡；媒体预置失败可对账孤立媒体。
23. 假 AnkiConnect、错误 key/版本/profile、重定向和媒体目录伪造失败。
24. 空/自造 render expectation、unsigned/wrong-process proof、撤销快照/验签公钥映射回滚、pre-run/run 哈希环、跨 run/plan 复用、copier/launch attestation 伪造、helper-only 或旧窗口假重启都不能成为 anki_verified。只用 connection-local hook、跨进程 DB/WAL 写后恢复、sensor gap/overflow、focus 缺 from/to/可信动作归因、run-owned process lifecycle ledger 漏 main/child/proxy、add-on action 无签名、单向 focus 谓词、final-runtime manifest 漏成员/不可重算、旧 R8a 冒充 barrier evidence、descriptor digest 不等、post-cutoff event 或最终 Artifact 非原子提交均失败；只有结构正确且 verifier-signed 的 failure proof 才形成 runtime_failed/anki_data_verified。
25. 媒体路径遍历、同名异哈希和目标 symlink 失败。
26. 乱序事件、崩溃或取消不产生假终态；强制结束无法证明写入边界时必须为 interrupted。Anki 写前/写后/边界不明分别只允许新 intent 重新确认、verification-only successor、stop conflict，旧批准和已消费 intent 不复用。
27. launcher、payload 和 hash 表一起被替换时外层签名失败；撤销密钥与降级包被拒绝。

完整发布测试见 [基准与评估](BENCHMARK_AND_EVALUATION.md)。

## 17. 安全事件

发现潜在泄漏或越权时：

1. 停止相关任务和写操作。
2. 保存不含秘密的最小审计。
3. 撤销相关内部授权记录和本地会话。
4. 标记受影响产物 untrusted。
5. 提醒用户轮换可能泄露凭据。
6. 禁止自动上传诊断。
7. 修复后运行全部安全门禁与真实 Anki 回归。
