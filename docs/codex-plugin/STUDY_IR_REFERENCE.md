# Study IR 参考

> 状态：PROPOSED 领域契约，尚未实现  
> 日期：2026-07-16  
> 本文中的类型用于设计、合同测试和后续迁移，不是当前 TypeScript API。

## 1. 目的

Study IR 是素材、学习目标、候选和卡片之间的稳定中间表示。它解决四个问题：

1. 不让文件格式直接决定卡片格式。
2. 不让一次模型回答成为唯一业务真相。
3. 让每个学习目标和卡片都能追溯到证据。
4. 让 Agent、App UI、桌面端兼容层和 Worker 使用同一语义。

当前 LearningPoint、Project、ExportResult 和 AnkiVerifyResult 会先经过服务边界 sanitizer，再作为 sanitized legacy payload 被包裹；GenerateRequest 只迁移去密配置和受控资源引用。不得把当前包含运行时配置/密钥的对象原样持久化。

## 2. 设计约定

- 所有持久对象有 schema、schemaVersion、id、revision 和内容哈希。
- 时间使用 UTC RFC 3339。
- ID 是不透明字符串，不让调用者从 ID 推断本地路径。
- 大型正文和媒体使用 BlobRef，不内嵌 MCP 返回。
- 所有来源文本视为不可信数据，不能改变 Agent 或工具策略。
- 用户锁定内容优先于 Agent 重算。
- 派生产物保留父产物引用和生产者版本。
- 已发布产物不可变；修改会生成新 revision。

## 3. 公共基础类型

~~~ts
type ArtifactId = string;
type ProjectId = string;
type TaskId = string;
type Revision = number;
type Sha256 = string;
type Timestamp = string;

type ProductStep = "source" | "select" | "deliver";
type ArtifactStage =
  | "empty"
  | "sources_ready"
  | "candidates_ready"
  | "selection_ready"
  | "plans_ready"
  | "cards_ready"
  | "apkg_ready"
  | "imported_unverified"
  | "anki_data_verified"
  | "anki_verified";
type OperationState =
  | "idle"
  | "queued"
  | "running"
  | "cancelling"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";
type WorkflowActionId =
  | "select_source"
  | "request_source_grant"
  | "request_output_grant"
  | "request_network_grant"
  | "open_settings"
  | "validate_profile"
  | "confirm_operation"
  | "inspect_source"
  | "discover_candidates"
  | "review_candidates"
  | "save_selection"
  | "plan_cards"
  | "validate_card_plans"
  | "generate_cards"
  | "export_apkg"
  | "prepare_anki_import"
  | "confirm_anki_import"
  | "resolve_anki_conflict"
  | "import_and_verify"
  | "resume_task"
  | "cancel_task"
  | "resolve_issue"
  | "retry"
  | "view_results"
  | "open_anki";
type LearningRoute =
  | "reading_recognition"
  | "listening_recognition"
  | "production"
  | "grammar_cloze"
  | "pronunciation"
  | "pragmatics_register"
  | "chunk_collocation"
  | "contrast"
  | "fact_recall"
  | "definition"
  | "concept_discrimination"
  | "causal_reconstruction"
  | "comparison"
  | "process_recall"
  | "argument_attribution"
  | "formula_application"
  | "application_transfer"
  | "procedural_decision"
  | "error_repair";

type CapabilityState =
  | "not_checked"
  | "unknown"
  | "checking"
  | "ready"
  | "stale"
  | "action_required"
  | "blocked"
  | "disabled"
  | "optional";

type CapabilityId =
  | "host.plugin_manifest"
  | "host.stdio_service_launch"
  | "host.tool_registration"
  | "host.trusted_local_ui"
  | "host.attachment_bridge"
  | "host.mcp_app_resources"
  | "runtime.card_service"
  | "runtime.worker"
  | "runtime.python"
  | "runtime.ffmpeg"
  | "runtime.yt_dlp"
  | "runtime.document_parsers"
  | "source.local_video"
  | "source.subtitle"
  | "source.public_video_url"
  | "source.text"
  | "source.pdf_text"
  | "source.web_snapshot"
  | "source.audio_podcast"
  | "source.directory"
  | "source.codex_attachment_bridge"
  | "source.ocr_visual"
  | "source.code_repository"
  | "service.anki"
  | "service.anki_runtime_verifier";

type ServiceProfileCapabilityId = "model" | "tts" | "anki_connect";

type MediaPreferenceKey =
  | "source_audio"
  | "source_video"
  | "sentence_tts"
  | "expression_tts";

type InputFingerprint = Sha256;

type ArtifactHandle = string; // MCP 只接收 opaque handle

type ArtifactRef = { // 仅 Card Service 内部解析
  artifactId: ArtifactId;
  projectId: ProjectId;
  projectRevision: Revision;
  artifactRevision: Revision;
  payloadSchema: string;
  payloadSchemaVersion: number;
  artifactDigest: Sha256;
  registryAuthRef: string;
};
type EntityRef = {
  artifactRef: ArtifactRef;
  entityId: string;
};

type BlobRef = {
  blobId: string;
  sha256: Sha256;
  sizeBytes: number;
  mediaType: string;
};

type ProducerRef = {
  component: string;
  version: string;
  modelRef?: string;
  configurationFingerprint?: string;
};
type ProvenanceRecord = {
  sourceKind: "user_input" | "deterministic_extractor" | "model_assisted" | "human_review" | "legacy_adapter";
  producer: ProducerRef;
  parentRefs: ArtifactRef[];
  method: string;
  observedAt: Timestamp;
};
~~~

## 4. ArtifactEnvelope

~~~ts
type ArtifactEnvelope<T> = {
  envelopeSchema: "study.artifact.envelope";
  envelopeSchemaVersion: 1;
  payloadSchema: string;
  payloadSchemaVersion: number;
  artifactId: ArtifactId;
  projectId: ProjectId;
  projectRevision: Revision;
  artifactRevision: Revision;
  payloadSha256: Sha256;
  artifactDigest: Sha256;
  registryAuthRef: string;
  createdAt: Timestamp;
  producer: ProducerRef;
  parents: ArtifactRef[];
  inputFingerprint: InputFingerprint;
  completeness: CompletenessRecord;
  issueRefs: string[];
  payload: T;
};
type CompletenessRecord = {
  state: "complete" | "partial_declared" | "unknown" | "blocked";
  expectedUnits?: number;
  processedUnits?: number;
  omittedLocators: SourceLocator[];
  reasonCodes: string[];
};

type ArtifactRegistryRecord = {
  registryAuthRef: string;
  artifactId: ArtifactId;
  projectId: ProjectId;
  projectOwnerDigest: Sha256;
  artifactDigest: Sha256;
  createdByServiceInstanceId: string;
  keyId: string;
  authTag: string; // HMAC 或等价认证标签
  revokedAt?: Timestamp;
};
~~~

不变量：

- payloadSha256 使用 RFC 8785 JSON Canonicalization Scheme（JCS）的 UTF-8 字节；非有限数字拒绝，缺失字段与 null 不等价，业务文本不做隐式 Unicode 归一化。Blob 使用原始字节 SHA-256。
- InputFingerprint 是 [目标架构](ARCHITECTURE.md) 中 TaskInputManifestV1 的 JCS SHA-256；它覆盖输入修订、组件/规则/模板版本、profile 与 credentialRevision、授权/egress 及成本批量策略，不能由调用方自报。
- artifactDigest 的 preimage 是将 artifactDigest 与 registryAuthRef 两个字段都省略后的 ArtifactEnvelopeV1，其余字段按 RFC 8785 JCS 规范化；该 preimage 覆盖 schema/version、ID、project/artifact revision、parents、input fingerprint、producer、completeness、issues 和 payload，禁止自引用哈希。
- registryAuthRef 指向 Service 认证账本中的 HMAC/签名记录；MCP 调用方只能提交 ArtifactHandle，不能自报 schema/revision/hash。
- 认证记录覆盖 artifact/project/owner/digest/service/key/revocation；handle 解析时同时校验当前调用者 owner/scope、authTag 和撤销状态，防止跨项目 transplant 或调用方重算哈希伪造。
- projectRevision 是项目整体乐观锁；artifactRevision 是某 Artifact 身份的版本；sourceRevision 属于 SourceAsset 内容身份，三者不能互换。
- complete 不能同时有未解释 omittedLocators。
- 任何父产物 revision 改变后，旧派生产物不得自动成为当前版本。
- issueRefs 必须引用结构化 Issue，不只保存日志字符串。

## 5. 输入引用与授权

~~~ts
type InputRef =
  | {
      kind: "host_attachment";
      attachmentRef: string;
      displayName: string;
      expectedRevision?: string;
    }
  | {
      kind: "local_file";
      fileResourceRef: string;
      displayName: string;
    }
  | {
      kind: "directory";
      directoryResourceRef: string;
      includeGlobs: string[];
      excludeGlobs: string[];
      maxDepth: number;
    }
  | {
      kind: "url";
      networkResourceRef: string;
      displayOrigin: string;
    };
~~~

InputRef 不携带永久原始绝对路径或 raw URL。fileResourceRef、directoryResourceRef 和 networkResourceRef 由本地服务通过受信授权流程签发；MCP 后续调用只能缩小范围，不能替换 URL path/query 或扩大目录。

## 5.1 Learning Contract 与偏好层

~~~ts
type LearningContract = {
  contractId: string;
  purpose: string;
  targetBehavior: string;
  learnerProfileRef?: string;
  learnerLevel?: string;
  routes: LearningRoute[];
  budget: {
    maxNewCards: number;
    targetDailyReviewMinutes?: number;
  };
  promptLanguage: string;
  answerLanguage: string;
  evidencePolicy: "automatic" | "review_tier_b" | "draft_only";
  exclusions: string[];
  contractRevision: Revision;
};

type LearningContractPatchOperation =
  | { op: "set_purpose"; purpose: string }
  | { op: "set_target_behavior"; targetBehavior: string }
  | { op: "set_learner_level"; learnerLevel: string | null }
  | { op: "replace_routes"; routes: LearningRoute[] }
  | { op: "set_budget"; maxNewCards: number; targetDailyReviewMinutes?: number }
  | { op: "set_languages"; promptLanguage: string; answerLanguage: string }
  | { op: "set_evidence_policy"; evidencePolicy: LearningContract["evidencePolicy"] }
  | { op: "add_exclusion"; exclusion: string }
  | { op: "remove_exclusion"; exclusion: string };

type LearningContractChangeSet = {
  expectedProjectRevision: Revision;
  expectedContractRevision: Revision;
  operationId: string;
  operations: LearningContractPatchOperation[];
};

type PreferenceValue<T> = {
  value: T;
  source:
    | "system_default"
    | "learner_profile"
    | "project_contract"
    | "source_override"
    | "objective_override"
    | "card_lock";
  locked: boolean;
  reason?: string;
};

type LearningPreferences = {
  difficulty: PreferenceValue<string>;
  routeWeights: PreferenceValue<Partial<Record<LearningRoute, number>>>;
  mediaPolicy: PreferenceValue<Partial<Record<MediaPreferenceKey, boolean>>>;
  explanationDepth: PreferenceValue<string>;
  reviewBudget: PreferenceValue<number>;
};
~~~

优先级从 system_default 到 card_lock 递增。高层默认值不能覆盖更具体或 locked 的值。每次解析后的有效偏好都保存 provenance，使 Agent 能解释“为什么这张卡使用产出路线/为什么有 TTS”。LearningContract 只通过版本化语义 patch 更新，不接受通用 JSON Patch：purpose、targetBehavior、routes、evidencePolicy 或 exclusions 改变会使 discovery 及全部下游 stale；语言改变使 CardPlan 及下游 stale；预算改变至少使 selection/plan 及下游 stale。运行中任务可完成到私有结果，但 compare-and-publish 必须因旧 contractRevision 失败。

LearnerProfile 只保存支持学习决策所需的最小状态，如已知/部分掌握/易混目标和复习预算。原始 Anki 历史属于受限数据，不自动进入模型上下文。

## 6. SourceAsset

~~~ts
type SourceAsset = {
  sourceId: string;
  inputRefKind: InputRef["kind"];
  displayName: string;
  sourceType:
    | "video"
    | "audio"
    | "subtitle"
    | "text"
    | "markdown"
    | "html"
    | "pdf"
    | "docx"
    | "epub"
    | "code"
    | "image"
    | "directory_manifest"
    | "unknown";
  sourceRevision: Revision;
  contentSha256?: Sha256;
  sourceIdentity: SourceIdentity;
  representations: SourceRepresentation[];
  provenance: ProvenanceRecord;
  supportTier: "A" | "B" | "C";
  status: "ready" | "conditional" | "blocked";
  issueRefs: string[];
};

type SourceIdentity = {
  stable: boolean;
  identityMethod:
    | "content_sha256"
    | "host_revision"
    | "verified_snapshot"
    | "size_mtime"
    | "model_relayed";
  observedAt: Timestamp;
};

type SourceRepresentation = {
  representationId: string;
  kind:
    | "original_bytes"
    | "plain_text"
    | "structured_document"
    | "transcript"
    | "subtitle_cues"
    | "ocr"
    | "thumbnail"
    | "audio_waveform";
  blobRef: BlobRef;
  extractor: ProducerRef;
  confidence: number | null;
  completeness: CompletenessRecord;
};
~~~

身份等级：

1. original_bytes + SHA-256。
2. 稳定宿主 revision。
3. 插件创建并哈希的快照。
4. 大小/mtime，仅用于检测，不足以跨机器证明身份。
5. model_relayed，只允许条件草稿。

## 7. 内容结构与定位器

~~~ts
type ContentNode = {
  nodeId: string;
  sourceId: string;
  parentNodeId?: string;
  order: number;
  kind:
    | "document"
    | "section"
    | "paragraph"
    | "sentence"
    | "list"
    | "list_item"
    | "table"
    | "table_cell"
    | "formula"
    | "code_block"
    | "transcript_turn"
    | "subtitle_cue"
    | "image_region";
  text?: string;
  blobRef?: BlobRef;
  locator: SourceLocator;
  extractionConfidence: number | null;
  attributes: Record<string, string | number | boolean>;
};

type SourceLocator =
  | { kind: "text_span"; nodeId: string; start: number; end: number }
  | { kind: "pdf"; page: number; bbox?: [number, number, number, number] }
  | { kind: "subtitle"; cueIds: string[]; startMs: number; endMs: number }
  | { kind: "audio"; startMs: number; endMs: number; speaker?: string }
  | { kind: "html"; snapshotSha256: Sha256; selector: string; textQuote: string }
  | { kind: "table"; nodeId: string; row: number; column: number }
  | { kind: "code"; pathRef: string; startLine: number; endLine: number }
  | { kind: "image"; pageOrFrame: number; bbox: [number, number, number, number] };
~~~

定位器必须在相同 source revision 上可重放。无法重放时产物变 stale。

## 8. EvidenceAnchor

~~~ts
type EvidenceAnchor = {
  evidenceId: string;
  sourceRef: ArtifactRef;
  locator: SourceLocator;
  quote?: string;
  quoteSha256?: Sha256;
  provenanceClass:
    | "source_direct"
    | "source_derived"
    | "external_corroboration"
    | "pedagogical_example";
  semanticRelation:
    | "supports"
    | "counters"
    | "context"
    | "example"
    | "nonexample";
  assessment: {
    producer: ProducerRef;
    method: "deterministic_replay" | "rule_based" | "model_assisted" | "human_review";
    confidence: number | null;
    independentlyVerified: boolean;
  };
  attribution: {
    author?: string;
    title?: string;
    publishedAt?: string;
    retrievedAt?: string;
  };
};
~~~

事实性已验证卡至少有一个 source_direct，或具备可复现推导记录的 source_derived；仅 model_assisted 自报 confidence 不能独立通过。Agent 生成例句使用 pedagogical_example + example，不能冒充原文。

## 9. SemanticUnit

~~~ts
type SemanticUnit =
  | {
      kind: "language_form";
      unitId: string;
      language: string;
      form: string;
      normalizedForm: string;
      formType: "word" | "phrase" | "grammar" | "pronunciation" | "pragmatic";
      meaningOrFunction: string;
      exactSpans: EvidenceAnchor[];
      register?: string;
      relations: UnitRelation[];
    }
  | {
      kind: "knowledge_claim";
      unitId: string;
      claimType:
        | "fact"
        | "definition"
        | "concept"
        | "causal"
        | "comparison"
        | "process"
        | "argument"
        | "formula"
        | "procedure";
      canonicalClaim: string;
      qualifiers: string[];
      scope: string[];
      temporalValidity?: { from?: string; until?: string };
      evidence: EvidenceAnchor[];
      relations: UnitRelation[];
    };

type UnitRelation = {
  kind:
    | "exact_duplicate"
    | "equivalent"
    | "overlaps"
    | "subsumes"
    | "prerequisite"
    | "supports"
    | "conflicts"
    | "alternate_form";
  targetUnitRef: EntityRef;
  confidence: number;
  evidenceRefs: EntityRef[];
};
~~~

SemanticUnit 表达“素材说了什么”，不等于“用户应该学什么”。

## 10. LearningObjective

~~~ts
type LearningObjective = {
  objectiveId: string;
  unitRefs: EntityRef[];
  route: LearningRoute;
  recallAction: string;
  cueSpec: string;
  responseSpec: string;
  scoringBoundary: string[];
  evidenceRefs: EntityRef[];
  prerequisiteObjectiveRefs: EntityRef[];
  granularity: GranularityAssessment;
  learnerFit: LearnerFit;
  routeDecision: {
    reasonCodes: string[];
    alternatives: string[];
  };
  provenance: ProducerRef;
  userLocks: UserLock[];
};

type GranularityAssessment = {
  atomicity: "pass" | "review" | "fail";
  contextSufficiency: "pass" | "review" | "fail";
  expectedAnswerSeconds: number;
  independentScorePoints: number;
  splitProposal?: string[];
};

type LearnerFit = {
  status: "new" | "partial" | "known" | "unknown";
  estimatedDifficulty: number;
  reasonCodes: string[];
};
~~~

LearningObjective 表达未来行为，是卡片选择的中心对象。

## 11. Candidate、关系与冲突

~~~ts
type LearningCandidate = {
  candidateId: string;
  objectiveRef: EntityRef;
  eligibility:
    | "recommended"
    | "candidate"
    | "duplicate"
    | "needs_review"
    | "hard_blocked"
    | "excluded";
  selectionState: "selected" | "unselected";
  gateEvaluationRef: ArtifactRef;
  gates: GateResult[]; // 当前 GateEvaluationSet 的只读摘要
  scores: CandidateScores;
  explanation: string[];
  relationRefs: EntityRef[];
  issueRefs: string[];
};
type GateId =
  | "evidence"
  | "goal_relevance"
  | "novelty"
  | "scoreability"
  | "card_suitability"
  | "conflict"
  | "review_value"
  | "security";

type GateResult = {
  gate: GateId;
  ruleId: string;
  ruleSetVersion: string;
  state: "pass" | "review" | "fail";
  reasonCode: string;
  producer: ProducerRef;
  evidenceRefs: EntityRef[];
  evaluatedAt: Timestamp;
};

type GateEvaluationSet = {
  evaluationId: string;
  candidateRef: EntityRef;
  projectRevision: Revision;
  candidateArtifactRevision: Revision;
  inputFingerprint: InputFingerprint;
  ruleSetVersion: string;
  results: GateResult[];
  derivedEligibility: LearningCandidate["eligibility"];
  evaluatedAt: Timestamp;
  producer: ProducerRef;
};

type CandidateScores = {
  goalRelevance: number;
  futureFrequencyOrStakes: number;
  bottleneckAndTransfer: number;
  forgettingOrConfusionRisk: number;
  evidenceConfidence: number;
  noveltyAndLearnerFit: number;
  scoreability: number;
  reviewCost: number;
};

type ConflictSet = {
  conflictId: string;
  unitRefs: EntityRef[];
  dimensions: ("value" | "scope" | "time" | "attribution" | "polarity")[];
  status: "unresolved" | "resolved" | "accepted_difference";
  resolution?: string;
  evidenceRefs: EntityRef[];
};
~~~

eligibility 只能由当前 GateEvaluationSet 按冻结规则派生，调用方不能直接写入。任一 evidence/conflict/security fail 必须派生 hard_blocked；其他 gate 的 fail/review 映射由 versioned rule set 明确。set_selection、plan_cards、cards.generate 和 cards.export_apkg 都校验 evaluation 的 project/artifact revision、inputFingerprint 和 ruleSetVersion；过期即 stale 并重评。

未解决 conflict 不能进入普通事实卡。可生成“不同来源如何主张”的论证/归因卡，但题面必须保留分歧。

## 12. 组合选择

~~~ts
type PortfolioSelection = {
  selectionId: string;
  projectRevision: Revision;
  candidateRefs: EntityRef[];
  budget: {
    maxNewCards: number;
    targetDailyReviewMinutes?: number;
  };
  coverage: {
    objectiveGroup: string;
    selectedCount: number;
    reason: string;
  }[];
  redundancyWarnings: string[];
  estimatedReviewDebt: ReviewDebtEstimate;
};

type ReviewDebtEstimate = {
  expectedFirstReviewMinutes: number;
  expectedDailyMinutesAtDay7: number;
  confidence: "low" | "medium" | "high";
  drivers: string[];
};
~~~

## 13. CardPlan

~~~ts
type CardPlan = {
  cardPlanId: string;
  objectiveRef: EntityRef;
  route: LearningObjective["route"];
  cue: {
    kind: "text" | "cloze" | "audio" | "video" | "image" | "scenario";
    content: string;
    mediaRefs: ArtifactRef[];
  };
  expectedResponse: {
    modality: "text" | "speech" | "choice" | "ordered_steps";
    coreAnswer: string;
    scoringPoints: string[];
    acceptedVariants: string[];
  };
  feedback: {
    explanation?: string;
    evidenceRefs: EntityRef[];
    examples: string[];
    nonexamples: string[];
  };
  mediaPolicy: {
    sourceAudio: boolean;
    sourceVideo: boolean;
    sentenceTts: boolean;
    expressionTts: boolean;
  };
  estimatedReviewSeconds: number;
  validation: {
    answerLeakage: "pass" | "fail";
    scoreability: "pass" | "review" | "fail";
    evidence: "pass" | "review" | "fail";
    templateCompatibility: "pass" | "fail";
  };
  userLocks: UserLock[];
};

type CardPlanCheckId =
  | "evidence_coverage"
  | "scoring_boundary"
  | "answer_leakage"
  | "duplicate"
  | "conflict"
  | "template_compatibility"
  | "media_generatability"
  | "user_lock_preservation";

type CardPlanValidationArtifactPayload = {
  cardPlanSetDigest: Sha256;
  ruleSetVersion: string;
  inputFingerprint: InputFingerprint;
  records: {
    cardPlanRef: EntityRef;
    checkId: CardPlanCheckId;
    state: "passed" | "needs_review" | "failed";
    producer: ProducerRef;
    evidenceRefs: EntityRef[];
  }[];
  eligibleCardPlanRefs: EntityRef[];
  blockedCardPlanRefs: EntityRef[];
};
~~~

CardPlan 不是最终 Anki 字段。生成适配器将其映射到当前 Project/Card 结构；无法无损映射时返回 typed blocker，不能静默降级。

## 14. 用户编辑

~~~ts
type UserEditProvenance = {
  actor: "user";
  attestationDigest: Sha256;
  hostCategory: "codex_trusted_ui" | "native_consent_ui" | "desktop_compat";
  recordedAt: Timestamp;
};

type EditProvenance =
  | UserEditProvenance
  | { actor: "agent"; taskId: string }
  | { actor: "system"; ruleId: string };

type ObjectiveLockableField =
  | "objective.route"
  | "objective.recallAction"
  | "objective.cueSpec"
  | "objective.responseSpec"
  | "objective.scoringBoundary"
  | "objective.evidence";

type CardPlanLockableField =
  | "card.cue"
  | "card.expectedResponse"
  | "card.feedback"
  | "card.mediaPolicy";

type CandidateEditOperation =
  | { kind: "lock_objective"; objectiveRef: EntityRef; field: ObjectiveLockableField; operationId: string; provenance: UserEditProvenance }
  | { kind: "unlock_objective"; objectiveRef: EntityRef; field: ObjectiveLockableField; operationId: string; provenance: UserEditProvenance }
  | { kind: "exclude"; candidateRef: EntityRef; operationId: string; provenance: EditProvenance }
  | { kind: "restore"; candidateRef: EntityRef; operationId: string; provenance: EditProvenance }
  | { kind: "split"; objectiveRef: EntityRef; proposal: string[]; operationId: string; provenance: EditProvenance }
  | { kind: "merge"; objectiveRefs: EntityRef[]; operationId: string; provenance: EditProvenance }
  | { kind: "change_route"; objectiveRef: EntityRef; route: LearningRoute; operationId: string; provenance: EditProvenance }
  | { kind: "replace_objective_evidence"; objectiveRef: EntityRef; evidenceRefs: EntityRef[]; operationId: string; provenance: EditProvenance }
  | { kind: "mark_known"; objectiveRef: EntityRef; operationId: string; provenance: EditProvenance };

type CardPlanEditOperation =
  | { kind: "lock_card_plan"; cardPlanRef: EntityRef; field: CardPlanLockableField; operationId: string; provenance: UserEditProvenance }
  | { kind: "unlock_card_plan"; cardPlanRef: EntityRef; field: CardPlanLockableField; operationId: string; provenance: UserEditProvenance }
  | { kind: "edit_card_cue"; cardPlanRef: EntityRef; cue: CardPlan["cue"]; operationId: string; provenance: EditProvenance }
  | { kind: "edit_card_answer"; cardPlanRef: EntityRef; expectedResponse: CardPlan["expectedResponse"]; operationId: string; provenance: EditProvenance }
  | { kind: "edit_card_feedback"; cardPlanRef: EntityRef; feedback: CardPlan["feedback"]; operationId: string; provenance: EditProvenance }
  | { kind: "edit_media_policy"; cardPlanRef: EntityRef; mediaPolicy: CardPlan["mediaPolicy"]; operationId: string; provenance: EditProvenance };

type StudyEditOperation = CandidateEditOperation | CardPlanEditOperation; // 仅内部审计总联合；公共工具必须按领域收窄

type UserLock = {
  field: ObjectiveLockableField | CardPlanLockableField;
  lockedAtRevision: Revision;
  provenance: UserEditProvenance;
  reason?: string;
};
~~~

服务使用 expectedProjectRevision，并校验每个 EntityRef 的 artifact/project revision，防止并发覆盖和 stale target。重复 operationId 必须返回原结果。study.edit_candidate 只接受 CandidateEditOperation 的 Agent 可写子集，study.edit_card_plan 只接受 CardPlanEditOperation 的 Agent 可写子集，禁止跨工具种类旁路。lock/unlock 只能由对应实体的受信 UI 内部通道构造 UserEditProvenance；原始 hostEventRef/userGestureId 只存在内部认证账本，Artifact/MCP/get_candidate/get_card_plan 仅保留非 bearer 的 attestationDigest、hostCategory 和 recordedAt。Agent edit 可重算且不能伪装为用户锁。任何编辑都重新运行受影响的 evidence、scoreability、security 和下游可靠性门禁。

## 14.1 核心 Artifact payload

M2/M3 必须正式实现：

~~~ts
type InspectionArtifactPayload = {
  sourceRefs: ArtifactRef[];
  completeness: CompletenessRecord;
  representationRefs: ArtifactRef[];
  supportTiers: Record<string, "A" | "B" | "C">;
  issueRefs: string[];
};

type ProjectArtifactPayload = {
  cardPlanRefs: ArtifactRef[];
  sanitizedLegacyProjectRef: ArtifactRef;
  cardIds: string[];
  reliabilityManifestRef: ArtifactRef;
  mediaLedgerRef: ArtifactRef;
};

type PackageArtifactPayload = {
  projectRef: ArtifactRef;
  projectRevision: Revision;
  apkgFileRef: string;
  apkgSha256: Sha256;
  sizeBytes: number;
  deckNames: string[];
  noteCount: number;
  cardCount: number;
  cardIdentitySetRef: ArtifactRef;
  cardIdentitySetDigest: Sha256;
  mediaCount: number;
  mediaManifestRef: ArtifactRef;
  mediaManifestDigest: Sha256;
  cardMediaRoleInventoryRef: ArtifactRef;
  cardMediaRoleInventoryDigest: Sha256;
  templateFamily: string;
  templateSchemaVersion: string;
  noteModelId: string;
  compatibilityContractVersion: string;
  frontTemplateSha256: Sha256;
  backTemplateSha256: Sha256;
  cssSha256: Sha256;
  scriptSha256?: Sha256;
  reliabilityManifestRef: ArtifactRef;
  exportProducer: ProducerRef;
};

type RuntimeVerifierBindingV1 =
  | {
      state: "unavailable";
      requiredCapabilityId: "service.anki_runtime_verifier";
      reasonCode: "not_installed" | "not_ready" | "incompatible";
    }
  | {
      state: "selected";
      method: "trusted_anki_addon" | "versioned_gui_protocol";
      implementationVersionOrDigest: string;
      compatibilityContractVersion: string;
      proofAuthentication: "ed25519-signed-proof-facts-v1";
      producerTrustKeyId: string;
      producerTrustKeyEpoch: number;
      producerTrustRevocationSnapshotRef: ArtifactRef;
      producerTrustRevocationSnapshotDigest: Sha256;
      producerTrustRevocationSnapshotSequence: number;
      protocolVersion: string;
    };

type RuntimeVerifierIsolationPolicyV1 = {
  schema: "study.anki.runtime-isolation-policy";
  schemaVersion: 1;
  mode: "read_only_in_profile_preview_plus_isolated_restart_copy";
  schedulingWrites: "forbidden";
  answerRatingWrites: "forbidden";
  reviewHistoryWrites: "forbidden";
  syncWrites: "forbidden";
  noteTemplateDeckModelWrites: "forbidden";
  otherCollectionWrites: "forbidden";
  mediaFileWrites: "forbidden";
  existingWindowPolicy: "do_not_close_do_not_steal_focus";
  restartPolicy: "isolated_anki_and_verifier_processes_only";
  runBindingContractVersion: "anki-runtime-run-binding-v1";
  trustRevocationContractVersion: "trust-revocation-snapshot-v1";
  runtimeProofAuthenticationContractVersion: "anki-runtime-proof-auth-v1";
  preRunSourceStateContractVersion: "anki-pre-run-source-state-v1";
  profileStateProjectionContractVersion: "anki-scheduling-review-v1";
  writeAuditContractVersion: "anki-write-audit-v1";
  environmentObservationContractVersion: "anki-process-window-v1";
  runOwnedProcessContractVersion: "anki-run-owned-process-lifecycle-v1";
  trustedAddonFocusActionContractVersion: "anki-addon-focus-action-v1";
  isolatedCopyContractVersion: "anki-isolated-copy-v1";
  finalDataCheckEvidenceContractVersion: "anki-final-data-check-evidence-v1";
  finalDataReverificationContractVersion: "anki-final-data-reverification-v1";
  finalRuntimeInputsContractVersion: "anki-final-runtime-inputs-v1";
  signatureAlgorithm: "ed25519";
  serviceAttestationSignerKeyId: string;
  serviceAttestationKeyEpoch: number;
  serviceAttestationRevocationSnapshotRef: ArtifactRef;
  serviceAttestationRevocationSnapshotDigest: Sha256;
  serviceAttestationRevocationSnapshotSequence: number;
  trustedCopierProducerKeyId: string;
  trustedCopierKeyEpoch: number;
  trustedCopierRevocationSnapshotRef: ArtifactRef;
  trustedCopierRevocationSnapshotDigest: Sha256;
  trustedCopierRevocationSnapshotSequence: number;
  requireSchedulingStatePrePostDigestEquality: true;
  requireReviewHistoryPrePostDigestEquality: true;
  requireFinalDataReverificationUnderReadBarrier: true;
  policyDigest: Sha256;
};

type ImportPlanPayload = {
  importIntentId: string;
  packageRef: ArtifactRef;
  projectRevision: Revision;
  apkgSha256: Sha256;
  apkgSizeBytes: number;
  ankiProfileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  ankiVersion: string;
  ankiConnectVersion: string;
  ankiConnectConfigurationFingerprint: Sha256;
  ankiConnectCredentialRevision: number;
  ankiConnectCredentialBindingDigest: Sha256;
  targetDeck: string;
  noteCount: number;
  cardCount: number;
  mediaCount: number;
  duplicatePolicy: "detect_and_report";
  templateFamily: string;
  templateSchemaVersion: string;
  noteModelId: string;
  compatibilityContractVersion: string;
  requiredAnkiCheckManifestRef: ArtifactRef;
  requiredAnkiCheckManifestDigest: Sha256;
  runtimeVerifierBinding: RuntimeVerifierBindingV1;
  runtimeVerifierBindingDigest: Sha256;
  runtimeIsolationPolicyRef: ArtifactRef;
  runtimeIsolationPolicyDigest: Sha256;
  frontTemplateSha256: Sha256;
  backTemplateSha256: Sha256;
  cssSha256: Sha256;
  scriptSha256?: Sha256;
  mediaManifestRef: ArtifactRef;
  mediaManifestDigest: Sha256;
  failurePolicy: "report_and_cleanup_created_media_when_safe";
  planDigest: Sha256;
  expiresAt: Timestamp;
};

type AnkiDataIntegrityCheckId =
  | "package_hash"
  | "import_plan_binding"
  | "profile_collection_identity"
  | "deck_identity"
  | "note_count"
  | "card_count"
  | "field_content"
  | "template_hash"
  | "media_manifest"
  | "audio_media_evidence"
  | "card_id_uniqueness";

type AnkiPreviewCardCheckId =
  | "front_render"
  | "back_render"
  | "flip"
  | "scroll"
  | "window_resize";

type AnkiMediaPlaybackCheckId =
  | "source_audio_playback"
  | "sentence_tts_playback"
  | "expression_tts_playback"
  | "video_playback";

type AnkiRuntimeCheckId =
  | AnkiPreviewCardCheckId
  | AnkiMediaPlaybackCheckId
  | "restart_review";

type MediaRoleRuntimeCheckBindingV1 =
  | { mediaRole: "source_audio"; checkId: "source_audio_playback" }
  | { mediaRole: "sentence_tts"; checkId: "sentence_tts_playback" }
  | { mediaRole: "expression_tts"; checkId: "expression_tts_playback" }
  | { mediaRole: "source_video"; checkId: "video_playback" };

type DetachedEd25519SignatureV1 = {
  algorithm: "ed25519";
  domain:
    | "study.anki.runtime-run-binding.v1"
    | "study.anki.trusted-copy-attestation.v1"
    | "study.anki.verifier-launch-attestation.v1"
    | "study.anki.read-barrier-attestation.v1"
    | "study.anki.runtime-proof.v1"
    | "study.anki.write-audit-sensor.v1"
    | "study.anki.run-owned-process-lifecycle.v1"
    | "study.anki.run-owned-process-launch.v1"
    | "study.anki.addon-focus-action.v1"
    | "study.trust.revocation-snapshot.v1";
  signerKeyId: string;
  keyEpoch: number;
  signedPayloadDigest: Sha256;
  signatureRef: BlobRef;
};

type TrustRevocationSnapshotSignedPayloadV1 = {
  schema: "study.trust.revocation-snapshot.signed-payload";
  schemaVersion: 1;
  contractVersion: "trust-revocation-snapshot-v1";
  authorityKeyId: string;
  sequence: number;
  previousSnapshotDigest: Sha256 | null;
  issuedAt: Timestamp;
  historyMode: "complete_append_only_tombstones";
  keyFamilies: {
    keyId: string;
    introducedAtSequence: number;
    minimumAcceptedEpoch: number;
    disabledAt: Timestamp | null;
    disabledAtSequence: number | null;
    versions: {
      keyEpoch: number;
      firstAuthorizedSequence: number;
      publicKeyRef: BlobRef;
      publicKeySha256: Sha256;
      state: "active" | "revoked";
      revokedAt: Timestamp | null;
      revokedAtSequence: number | null;
    }[];
  }[];
};

type TrustRevocationSnapshotArtifactPayloadV1 = {
  schema: "study.trust.revocation-snapshot";
  schemaVersion: 1;
  signedPayload: TrustRevocationSnapshotSignedPayloadV1;
  signedPayloadDigest: Sha256;
  rootSignature: DetachedEd25519SignatureV1 & {
    domain: "study.trust.revocation-snapshot.v1";
  };
  snapshotDigest: Sha256;
};

type TrustSnapshotBindingV1 = {
  purpose: "service_attestation" | "trusted_copier" | "runtime_verifier";
  snapshotRef: ArtifactRef;
  snapshotDigest: Sha256;
  snapshotSequence: number;
  authorityKeyId: string;
};

type RuntimeProofSignedBindingV1 = {
  schema: "study.anki.runtime-proof.signed-binding";
  schemaVersion: 1;
  contractVersion: "anki-runtime-proof-auth-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  runtimeVerifierBindingDigest: Sha256;
  proofFactsDigest: Sha256;
  producerProcessIdentityRef: ArtifactRef;
  producerProcessIdentityDigest: Sha256;
  producerLaunchAttestationRef: ArtifactRef;
  producerLaunchAttestationDigest: Sha256;
};

type RuntimeProofAuthenticationV1 = {
  contractVersion: "anki-runtime-proof-auth-v1";
  signedBinding: RuntimeProofSignedBindingV1;
  signedBindingDigest: Sha256;
  verifierSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.runtime-proof.v1";
  };
};

type AnkiVerificationContractV1 = {
  schema: "study.anki.verification-contract";
  schemaVersion: 1;
  verificationContractVersion: "anki-data-runtime-v1";
  dataRequired: readonly [
    "package_hash",
    "import_plan_binding",
    "profile_collection_identity",
    "deck_identity",
    "note_count",
    "card_count",
    "field_content",
    "template_hash",
    "media_manifest",
    "audio_media_evidence",
    "card_id_uniqueness"
  ];
  runtimeRequired: readonly [
    "front_render",
    "back_render",
    "flip",
    "scroll",
    "window_resize",
    "source_audio_playback",
    "sentence_tts_playback",
    "expression_tts_playback",
    "video_playback",
    "restart_review"
  ];
  mediaRoleRuntimeCheckBindings: readonly [
    { mediaRole: "source_audio"; checkId: "source_audio_playback" },
    { mediaRole: "sentence_tts"; checkId: "sentence_tts_playback" },
    { mediaRole: "expression_tts"; checkId: "expression_tts_playback" },
    { mediaRole: "source_video"; checkId: "video_playback" }
  ];
  requiredRenderViewports: readonly [
    { viewportId: "normal"; widthCssPx: 960; heightCssPx: 720 },
    { viewportId: "narrow"; widthCssPx: 600; heightCssPx: 720 }
  ];
  allowedRuntimeModes: readonly ["sample", "full"];
  minimumRuntimeSampleCards: 20;
  runBindingContractVersion: "anki-runtime-run-binding-v1";
  trustRevocationContractVersion: "trust-revocation-snapshot-v1";
  runtimeProofAuthenticationContractVersion: "anki-runtime-proof-auth-v1";
  preRunSourceStateContractVersion: "anki-pre-run-source-state-v1";
  renderProofContractVersion: "anki-render-proof-v1";
  interactionProofContractVersion: "anki-interaction-proof-v1";
  mediaPlaybackProofContractVersion: "anki-media-playback-proof-v1";
  restartProofContractVersion: "anki-restart-proof-v1";
  failureProofContractVersion: "anki-runtime-failure-proof-v1";
  dataStateContractVersion: "anki-data-state-v1";
  profileStateProjectionContractVersion: "anki-scheduling-review-v1";
  writeAuditContractVersion: "anki-write-audit-v1";
  environmentObservationContractVersion: "anki-process-window-v1";
  runOwnedProcessContractVersion: "anki-run-owned-process-lifecycle-v1";
  trustedAddonFocusActionContractVersion: "anki-addon-focus-action-v1";
  isolatedCopyContractVersion: "anki-isolated-copy-v1";
  finalDataCheckEvidenceContractVersion: "anki-final-data-check-evidence-v1";
  finalDataReverificationContractVersion: "anki-final-data-reverification-v1";
  finalRuntimeInputsContractVersion: "anki-final-runtime-inputs-v1";
  contractDigest: Sha256;
};

type PackageMediaManifestEntryV1 = {
  storedFileName: string;
  sizeBytes: number;
  sha256: Sha256;
  mimeType: string;
  entryDigest: Sha256;
};

type PackageMediaManifestPayloadV1 = {
  schema: "study.package.media-manifest";
  schemaVersion: 1;
  projectRef: ArtifactRef;
  projectRevision: Revision;
  entries: PackageMediaManifestEntryV1[];
  mediaCount: number;
  totalSizeBytes: number;
  manifestDigest: Sha256;
};

type PackageCardIdentitySetPayloadV1 = {
  schema: "study.package.card-identity-set";
  schemaVersion: 1;
  projectRef: ArtifactRef;
  projectRevision: Revision;
  cardIds: string[];
  cardCount: number;
  cardIdsDigest: Sha256;
  payloadDigest: Sha256;
};

type CardMediaRoleBindingV1 = {
  mediaRole: MediaPreferenceKey;
  mediaFileSha256: Sha256;
  mediaManifestEntryDigest: Sha256;
};

type CardMediaRolesV1 = {
  cardId: string;
  media: CardMediaRoleBindingV1[];
};

type PackageCardMediaRoleInventoryPayloadV1 = {
  schema: "study.package.card-media-role-inventory";
  schemaVersion: 1;
  cardIdentitySetRef: ArtifactRef;
  cardIdentitySetDigest: Sha256;
  mediaManifestRef: ArtifactRef;
  mediaManifestDigest: Sha256;
  entries: CardMediaRolesV1[];
  inventoryDigest: Sha256;
};

type RuntimeVerificationRunBindingSignedPayloadV1 = {
  schema: "study.anki.runtime-run-binding.signed-payload";
  schemaVersion: 1;
  contractVersion: "anki-runtime-run-binding-v1";
  runId: string;
  taskId: TaskId;
  inputFingerprint: InputFingerprint;
  audienceDigest: Sha256;
  serviceInstanceDigest: Sha256;
  serviceMainProcessIdentityRef: ArtifactRef;
  serviceMainProcessIdentityDigest: Sha256;
  importPlanRef: ArtifactRef;
  importPlanDigest: Sha256;
  requiredCheckManifestRef: ArtifactRef;
  requiredCheckManifestDigest: Sha256;
  expectedRuntimeObservationsDigest: Sha256;
  renderExpectationsDigest: Sha256;
  targetProfileIdentityDigest: Sha256;
  targetCollectionIdentityDigest: Sha256;
  sourceSnapshotRef: ArtifactRef;
  sourceSnapshotDigest: Sha256;
  isolatedCopyManifestRef: ArtifactRef;
  isolatedCopyManifestDigest: Sha256;
  trustedCopierAttestationRef: ArtifactRef;
  trustedCopierAttestationDigest: Sha256;
  isolatedProfileIdentityDigest: Sha256;
  isolatedCollectionIdentityDigest: Sha256;
  isolatedProfileRootResourceRef: string;
  runtimeVerifierBindingDigest: Sha256;
  runtimeIsolationPolicyDigest: Sha256;
  trustSnapshotBindings: readonly [
    TrustSnapshotBindingV1 & { purpose: "service_attestation" },
    TrustSnapshotBindingV1 & { purpose: "trusted_copier" },
    TrustSnapshotBindingV1 & { purpose: "runtime_verifier" }
  ];
  trustSnapshotBindingsDigest: Sha256;
  operationBoundaryId: string;
  createdAt: Timestamp;
  expiresAt: Timestamp;
};

type RuntimeVerificationRunBindingV1 = {
  schema: "study.anki.runtime-run-binding";
  schemaVersion: 1;
  signedPayload: RuntimeVerificationRunBindingSignedPayloadV1;
  signedPayloadDigest: Sha256;
  serviceSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.runtime-run-binding.v1";
  };
  bindingDigest: Sha256;
};

type ExpectedRuntimeObservationV1 =
  | {
      phase: "target_profile_preview";
      scope: "card";
      checkId: AnkiPreviewCardCheckId;
      cardId: string;
    }
  | ({
      phase: "target_profile_preview";
      scope: "card_media";
      cardId: string;
    } & MediaRoleRuntimeCheckBindingV1)
  | {
      phase: "isolated_restart_copy";
      scope: "post_restart_card";
      checkId: "restart_review";
      cardId: string;
    };

type CardRenderExpectedElementV1 = {
  elementKey: string;
  semanticRole: "card_root" | "cue" | "answer" | "content" | "media_control";
  expectedTextSha256: Sha256 | null;
};

type CardRenderExpectationV1 = {
  cardId: string;
  cardContentDigest: Sha256;
  derivationContractVersion: "anki-render-expectation-derivation-v1";
  cardPlanRef: ArtifactRef;
  cardPlanDigest: Sha256;
  fieldProjectionDigest: Sha256;
  templateDigest: Sha256;
  frontRequiredElements: readonly [
    CardRenderExpectedElementV1 & {
      semanticRole: "card_root";
      expectedTextSha256: null;
    },
    CardRenderExpectedElementV1 & {
      semanticRole: "cue" | "content";
      expectedTextSha256: Sha256;
    },
    ...CardRenderExpectedElementV1[]
  ];
  backRequiredElements: readonly [
    CardRenderExpectedElementV1 & {
      semanticRole: "card_root";
      expectedTextSha256: null;
    },
    CardRenderExpectedElementV1 & {
      semanticRole: "answer" | "content";
      expectedTextSha256: Sha256;
    },
    ...CardRenderExpectedElementV1[]
  ];
  expectationDigest: Sha256;
};

type AnkiRenderElementObservationV1 = {
  elementKey: string;
  semanticRole: "card_root" | "cue" | "answer" | "content" | "media_control";
  expectedTextSha256: Sha256 | null;
  observedTextSha256: Sha256 | null;
  boxMilliCssPx: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  visible: boolean;
  clipped: boolean;
};

type AnkiRenderViewportCaptureV1 = {
  viewport: {
    viewportId: "normal" | "narrow";
    widthCssPx: 960 | 600;
    heightCssPx: 720;
  };
  documentReadyState: "complete";
  cardRootVisible: boolean;
  horizontalOverflowMilliCssPx: number;
  fatalScriptErrors: {
    errorCode: string;
    messageDigest: Sha256;
  }[];
  requiredElements: AnkiRenderElementObservationV1[];
  canonicalRenderTreeEncoding: "jcs-array-utf8";
  canonicalRenderTreeRef: BlobRef;
  canonicalRenderTreeDigest: Sha256;
  screenshotPngRef: BlobRef;
};

type AnkiRenderProofArtifactPayloadV1 = {
  schema: "study.anki.render-proof";
  schemaVersion: 1;
  proofContractVersion: "anki-render-proof-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  observation: Extract<
    ExpectedRuntimeObservationV1,
    { scope: "card"; checkId: "front_render" | "back_render" }
  >;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  cardContentDigest: Sha256;
  templateDigest: Sha256;
  captures: readonly [
    AnkiRenderViewportCaptureV1 & {
      viewport: { viewportId: "normal"; widthCssPx: 960; heightCssPx: 720 };
    },
    AnkiRenderViewportCaptureV1 & {
      viewport: { viewportId: "narrow"; widthCssPx: 600; heightCssPx: 720 };
    }
  ];
  producer: ProducerRef;
  proofAuthentication: RuntimeProofAuthenticationV1;
  proofDigest: Sha256;
};

type AnkiInteractionEventV1 = {
  sequence: number;
  event:
    | "invoke_flip"
    | "observe_back"
    | "scroll_to_end"
    | "resize_normal"
    | "resize_narrow";
  cardSide: "front" | "back";
  viewportId: "normal" | "narrow";
  scrollTopMilliCssPx: number;
  scrollRangeMilliCssPx: number;
  horizontalOverflowMilliCssPx: number;
  requiredContentVisible: boolean;
  observedAt: Timestamp;
};

type AnkiInteractionProofArtifactPayloadV1 = {
  schema: "study.anki.interaction-proof";
  schemaVersion: 1;
  proofContractVersion: "anki-interaction-proof-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  observation: Extract<
    ExpectedRuntimeObservationV1,
    { scope: "card"; checkId: "flip" | "scroll" | "window_resize" }
  >;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  events: AnkiInteractionEventV1[];
  fatalScriptErrors: {
    errorCode: string;
    messageDigest: Sha256;
  }[];
  producer: ProducerRef;
  proofAuthentication: RuntimeProofAuthenticationV1;
  proofDigest: Sha256;
};

type AnkiMediaPlaybackEventV1 = {
  sequence: number;
  event: "loadedmetadata" | "canplay" | "play" | "timeupdate" | "pause" | "ended" | "error";
  currentTimeMs: number;
  durationMs: number;
  errorCode?: string;
  observedAt: Timestamp;
};

type AnkiMediaPlaybackProofArtifactPayloadV1 = {
  schema: "study.anki.media-playback-proof";
  schemaVersion: 1;
  proofContractVersion: "anki-media-playback-proof-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  observation: Extract<ExpectedRuntimeObservationV1, { scope: "card_media" }>;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  mediaFileSha256: Sha256;
  mediaManifestEntryDigest: Sha256;
  resolvedMediaSourceSha256: Sha256;
  events: AnkiMediaPlaybackEventV1[];
  producer: ProducerRef;
  proofAuthentication: RuntimeProofAuthenticationV1;
  proofDigest: Sha256;
};

type AnkiReviewCardStateV1 = {
  cardId: string;
  cardSide: "front" | "back";
  visibleContentSha256: Sha256;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  schedulingStateDigest: Sha256;
  capturedAt: Timestamp;
};

type AnkiRestartEventV1 =
  | {
      sequence: number;
      event: "anki_exit_observed";
      isolatedAnkiProcessIdentityDigest: Sha256;
      isolatedAnkiWindowIdentityDigest: Sha256;
      observedAt: Timestamp;
    }
  | {
      sequence: number;
      event: "anki_start_observed";
      isolatedAnkiProcessIdentityDigest: Sha256;
      isolatedAnkiWindowIdentityDigest: null;
      observedAt: Timestamp;
    }
  | {
      sequence: number;
      event: "collection_opened" | "card_reopened";
      isolatedAnkiProcessIdentityDigest: Sha256;
      isolatedAnkiWindowIdentityDigest: Sha256;
      observedAt: Timestamp;
    };

type AnkiRestartContinuityProofArtifactPayloadV1 = {
  schema: "study.anki.restart-continuity-proof";
  schemaVersion: 1;
  proofContractVersion: "anki-restart-proof-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  observation: Extract<
    ExpectedRuntimeObservationV1,
    { phase: "isolated_restart_copy"; checkId: "restart_review" }
  >;
  isolatedCopyManifestRef: ArtifactRef;
  isolatedCopyManifestDigest: Sha256;
  isolatedProfileIdentityDigest: Sha256;
  isolatedCollectionIdentityDigest: Sha256;
  isolatedAnkiProcessBeforeRef: ArtifactRef;
  isolatedAnkiProcessBeforeDigest: Sha256;
  isolatedAnkiLaunchBeforeAttestationRef: ArtifactRef;
  isolatedAnkiLaunchBeforeAttestationDigest: Sha256;
  isolatedAnkiProcessAfterRef: ArtifactRef;
  isolatedAnkiProcessAfterDigest: Sha256;
  isolatedAnkiLaunchAfterAttestationRef: ArtifactRef;
  isolatedAnkiLaunchAfterAttestationDigest: Sha256;
  isolatedAnkiWindowBefore: AnkiWindowIdentityV1;
  isolatedAnkiWindowAfter: AnkiWindowIdentityV1;
  reopenedWindowIdentityDigest: Sha256;
  beforeState: AnkiReviewCardStateV1;
  afterState: AnkiReviewCardStateV1;
  events: AnkiRestartEventV1[];
  producer: ProducerRef;
  proofAuthentication: RuntimeProofAuthenticationV1;
  proofDigest: Sha256;
};

type RuntimeObservationFailureProofArtifactPayloadV1 = {
  schema: "study.anki.runtime-failure-proof";
  schemaVersion: 1;
  proofContractVersion: "anki-runtime-failure-proof-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  observation: ExpectedRuntimeObservationV1;
  errorCode: string;
  diagnosticSummaryDigest: Sha256;
  diagnosticEvidenceRef: BlobRef;
  producer: ProducerRef;
  proofAuthentication: RuntimeProofAuthenticationV1;
  proofDigest: Sha256;
};

type RuntimeObservationProofRefV1 =
  | { kind: "render"; proofRef: ArtifactRef; proofDigest: Sha256 }
  | { kind: "interaction"; proofRef: ArtifactRef; proofDigest: Sha256 }
  | { kind: "media_playback"; proofRef: ArtifactRef; proofDigest: Sha256 }
  | { kind: "restart_continuity"; proofRef: ArtifactRef; proofDigest: Sha256 }
  | { kind: "failure"; proofRef: ArtifactRef; proofDigest: Sha256 };

type RuntimeObservationEvidenceArtifactPayloadV1 = {
  schema: "study.anki.runtime-observation-evidence";
  schemaVersion: 1;
  evidenceContractVersion: "anki-runtime-observation-evidence-v1";
  runBindingRef: ArtifactRef;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  importPlanRef: ArtifactRef;
  importPlanDigest: Sha256;
  requiredCheckManifestRef: ArtifactRef;
  requiredCheckManifestDigest: Sha256;
  observation: ExpectedRuntimeObservationV1;
  state: "passed" | "failed";
  proof: RuntimeObservationProofRefV1;
  producer: ProducerRef;
  runtimeVerifierBindingDigest: Sha256;
  phaseProfileIdentityDigest: Sha256;
  phaseCollectionIdentityDigest: Sha256;
  startedAt: Timestamp;
  endedAt: Timestamp;
  evidenceDigest: Sha256;
};

type RuntimeObservationRecordV1 = ExpectedRuntimeObservationV1 & {
  state: "passed" | "failed";
  evidenceRef: ArtifactRef;
  evidenceDigest: Sha256;
  startedAt: Timestamp;
  endedAt: Timestamp;
};

type DeterministicRuntimeSamplePolicyV1 = {
  mode: "sample" | "full";
  algorithm: "sha256_rendezvous_v1";
  cardIdentitySetRef: ArtifactRef;
  cardIdentitySetDigest: Sha256;
  samplingSeedDigest: Sha256;
  eligibleCardIds: string[];
  eligibleCardIdsDigest: Sha256;
  eligibleCardCount: number;
  selectedCardIds: string[];
  selectedCardIdsDigest: Sha256;
  minimumCards: 20;
  selectedCardCount: number;
  requireEveryPresentMediaRole: true;
};

type ExpectedMediaRolesByCardV1 = CardMediaRolesV1;

type RequiredAnkiCheckManifestV1 = {
  schema: "study.anki.required-checks";
  schemaVersion: 1;
  verificationContractRef: ArtifactRef;
  verificationContractVersion: "anki-data-runtime-v1";
  verificationContractDigest: Sha256;
  dataRequired: AnkiDataIntegrityCheckId[];
  runtimeRequired: AnkiRuntimeCheckId[];
  cardIdentitySetRef: ArtifactRef;
  cardIdentitySetDigest: Sha256;
  mediaManifestRef: ArtifactRef;
  mediaManifestDigest: Sha256;
  cardMediaRoleInventoryRef: ArtifactRef;
  cardMediaRoleInventoryDigest: Sha256;
  runtimeSamplePolicy: DeterministicRuntimeSamplePolicyV1;
  mediaRoleRuntimeCheckBindings: MediaRoleRuntimeCheckBindingV1[];
  expectedMediaRolesByCard: ExpectedMediaRolesByCardV1[];
  expectedMediaRolesByCardDigest: Sha256;
  expectedRuntimeObservations: ExpectedRuntimeObservationV1[];
  expectedRuntimeObservationsDigest: Sha256;
  renderExpectations: CardRenderExpectationV1[];
  renderExpectationsDigest: Sha256;
  runtimeVerifierBindingDigest: Sha256;
  runtimeIsolationPolicyDigest: Sha256;
  manifestDigest: Sha256;
};

type AnkiDataCardRecordV1 = {
  cardId: string;
  noteId: string;
  deckId: string;
  ordinal: number;
};

type AnkiDataNoteRecordV1 = {
  noteId: string;
  noteModelId: string;
  fieldValueSha256ByOrdinal: Sha256[];
  tagsDigest: Sha256;
};

type AnkiDataDeckRecordV1 = {
  deckId: string;
  deckNameDigest: Sha256;
  deckConfigurationDigest: Sha256;
};

type AnkiDataNoteModelRecordV1 = {
  noteModelId: string;
  fieldSchemaDigest: Sha256;
  frontTemplateSha256: Sha256;
  backTemplateSha256: Sha256;
  cssSha256: Sha256;
  scriptSha256: Sha256 | null;
};

type AnkiDataStateSnapshotArtifactPayloadV1 = {
  schema: "study.anki.data-state-snapshot";
  schemaVersion: 1;
  dataStateContractVersion: "anki-data-state-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  position: "before_runtime" | "after_runtime";
  importPlanRef: ArtifactRef;
  importPlanDigest: Sha256;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  cardIdentitySetDigest: Sha256;
  cards: AnkiDataCardRecordV1[];
  cardsDigest: Sha256;
  notes: AnkiDataNoteRecordV1[];
  notesDigest: Sha256;
  decks: AnkiDataDeckRecordV1[];
  decksDigest: Sha256;
  noteModels: AnkiDataNoteModelRecordV1[];
  noteModelsDigest: Sha256;
  liveMediaDirectoryScan: PackageMediaManifestEntryV1[];
  liveMediaDirectoryScanDigest: Sha256;
  producer: ProducerRef;
  capturedAt: Timestamp;
  snapshotDigest: Sha256;
};

type VerificationRegistryCommitDescriptorV1 = {
  schema: "study.anki.verification-registry-commit";
  schemaVersion: 1;
  registryTransactionId: string;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  members: readonly [
    { artifactId: ArtifactId; schema: "study.anki.read-barrier-attestation" },
    { artifactId: ArtifactId; schema: "study.anki.final-data-reverification" },
    { artifactId: ArtifactId; schema: "study.anki.runtime-evidence" },
    { artifactId: ArtifactId; schema: "study.anki.verification" }
  ];
  releaseCondition: "after_atomic_verification_artifact_commit";
  descriptorDigest: Sha256;
};

type FinalRuntimeArtifactBindingV1 = {
  artifactRef: ArtifactRef;
  artifactDigest: Sha256;
};

type FinalRuntimeObservationInputV1 = {
  observation: ExpectedRuntimeObservationV1;
  observationDigest: Sha256;
  evidenceRef: ArtifactRef;
  evidenceDigest: Sha256;
  proof: RuntimeObservationProofRefV1;
};

type FinalRuntimeDataCheckInputV1 = {
  checkId: AnkiDataIntegrityCheckId;
  evidenceRef: ArtifactRef;
  evidenceDigest: Sha256;
};

type FinalRuntimeEvidenceInputsManifestV1 = {
  schema: "study.anki.final-runtime-evidence-inputs-manifest";
  schemaVersion: 1;
  contractVersion: "anki-final-runtime-inputs-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  expectedRuntimeObservationsDigest: Sha256;
  trustSnapshotBindingsDigest: Sha256;
  observations: FinalRuntimeObservationInputV1[];
  dataStateInputs: readonly [
    FinalRuntimeArtifactBindingV1 & { position: "before_runtime" },
    FinalRuntimeArtifactBindingV1 & { position: "after_runtime" }
  ];
  profileStateInputs: readonly [
    FinalRuntimeArtifactBindingV1 & {
      phase: "target_profile_preview";
      position: "before";
    },
    FinalRuntimeArtifactBindingV1 & {
      phase: "target_profile_preview";
      position: "after";
    },
    FinalRuntimeArtifactBindingV1 & {
      phase: "isolated_restart_copy";
      position: "before";
    },
    FinalRuntimeArtifactBindingV1 & {
      phase: "isolated_restart_copy";
      position: "after";
    }
  ];
  writeAuditInputs: readonly [
    FinalRuntimeArtifactBindingV1 & { phase: "target_profile_full_run" },
    FinalRuntimeArtifactBindingV1 & { phase: "isolated_restart_copy" }
  ];
  environmentInputs: {
    beforeSnapshot: FinalRuntimeArtifactBindingV1;
    afterSnapshot: FinalRuntimeArtifactBindingV1;
    eventTrace: FinalRuntimeArtifactBindingV1;
  };
  runOwnedProcessLifecycleLedger: FinalRuntimeArtifactBindingV1;
  processAndLaunchInputs: readonly [
    FinalRuntimeArtifactBindingV1 & {
      role: "runtime_verifier";
      position: "before";
      launchAttestationRef: ArtifactRef;
      launchAttestationDigest: Sha256;
    },
    FinalRuntimeArtifactBindingV1 & {
      role: "runtime_verifier";
      position: "after";
      launchAttestationRef: ArtifactRef;
      launchAttestationDigest: Sha256;
    },
    FinalRuntimeArtifactBindingV1 & {
      role: "isolated_anki";
      position: "before";
      launchAttestationRef: ArtifactRef;
      launchAttestationDigest: Sha256;
    },
    FinalRuntimeArtifactBindingV1 & {
      role: "isolated_anki";
      position: "after";
      launchAttestationRef: ArtifactRef;
      launchAttestationDigest: Sha256;
    }
  ];
  trustedAddonFocusActionAttestations: {
    actionSequence: number;
    attestationRef: ArtifactRef;
    attestationDigest: Sha256;
  }[];
  finalDataCheckInputs: readonly [
    FinalRuntimeDataCheckInputV1 & { checkId: "package_hash" },
    FinalRuntimeDataCheckInputV1 & { checkId: "import_plan_binding" },
    FinalRuntimeDataCheckInputV1 & { checkId: "profile_collection_identity" },
    FinalRuntimeDataCheckInputV1 & { checkId: "deck_identity" },
    FinalRuntimeDataCheckInputV1 & { checkId: "note_count" },
    FinalRuntimeDataCheckInputV1 & { checkId: "card_count" },
    FinalRuntimeDataCheckInputV1 & { checkId: "field_content" },
    FinalRuntimeDataCheckInputV1 & { checkId: "template_hash" },
    FinalRuntimeDataCheckInputV1 & { checkId: "media_manifest" },
    FinalRuntimeDataCheckInputV1 & { checkId: "audio_media_evidence" },
    FinalRuntimeDataCheckInputV1 & { checkId: "card_id_uniqueness" }
  ];
  finalDataChecksAggregateDigest: Sha256;
  manifestDigest: Sha256;
};

type VerificationReadBarrierSignedPayloadV1 = {
  schema: "study.anki.read-barrier.signed-payload";
  schemaVersion: 1;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  protectedCardIdentitySetDigest: Sha256;
  protectedMediaManifestDigest: Sha256;
  readBarrierInstanceId: string;
  finalReadSnapshotIdentityDigest: Sha256;
  finalDataChecksAggregateDigest: Sha256;
  finalRuntimeEvidenceInputs: FinalRuntimeEvidenceInputsManifestV1;
  finalRuntimeEvidenceInputsDigest: Sha256;
  postCutoffMonitorPolicy: "abort_private_write_set_on_any_audit_or_environment_event";
  postCutoffDisqualifyingEventCount: 0;
  intervalStartedAt: Timestamp;
  intervalEndedAt: Timestamp;
  registryCommitDescriptorRef: string;
  registryCommitDescriptorDigest: Sha256;
  trustSnapshotBindings: readonly [
    TrustSnapshotBindingV1 & { purpose: "service_attestation" },
    TrustSnapshotBindingV1 & { purpose: "trusted_copier" },
    TrustSnapshotBindingV1 & { purpose: "runtime_verifier" }
  ];
  trustSnapshotBindingsDigest: Sha256;
  releaseCondition: "after_atomic_verification_artifact_commit";
  blockedWriteAttemptCount: number;
};

type VerificationReadBarrierAttestationV1 = {
  schema: "study.anki.read-barrier-attestation";
  schemaVersion: 1;
  signedPayload: VerificationReadBarrierSignedPayloadV1;
  signedPayloadDigest: Sha256;
  serviceSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.read-barrier-attestation.v1";
  };
  attestationDigest: Sha256;
};

type FinalAnkiDataCheckEvidenceArtifactPayloadV1 = {
  schema: "study.anki.final-data-check-evidence";
  schemaVersion: 1;
  contractVersion: "anki-final-data-check-evidence-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  readBarrierInstanceId: string;
  registryCommitDescriptorRef: string;
  registryCommitDescriptorDigest: Sha256;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  finalReadSnapshotIdentityDigest: Sha256;
  checkId: AnkiDataIntegrityCheckId;
  sourceEvidence: {
    evidenceRef: ArtifactRef;
    evidenceDigest: Sha256;
  }[];
  capturedAt: Timestamp;
  producer: ProducerRef;
  evidenceDigest: Sha256;
};
type FinalAnkiDataCheckRecordV1 = {
  checkId: AnkiDataIntegrityCheckId;
  state: "passed";
  readBarrierInstanceId: string;
  finalReadSnapshotIdentityDigest: Sha256;
  evidenceRef: ArtifactRef;
  evidenceDigest: Sha256;
};

type FinalAnkiDataReverificationArtifactPayloadV1 = {
  schema: "study.anki.final-data-reverification";
  schemaVersion: 1;
  contractVersion: "anki-final-data-reverification-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  importPlanRef: ArtifactRef;
  importPlanDigest: Sha256;
  requiredCheckManifestRef: ArtifactRef;
  requiredCheckManifestDigest: Sha256;
  dataStateBeforeRef: ArtifactRef;
  dataStateBeforeDigest: Sha256;
  dataStateAfterRef: ArtifactRef;
  dataStateAfterDigest: Sha256;
  readBarrierAttestationRef: ArtifactRef;
  readBarrierAttestationDigest: Sha256;
  readBarrierInstanceId: string;
  finalReadSnapshotIdentityDigest: Sha256;
  finalDataChecks: FinalAnkiDataCheckRecordV1[];
  finalDataChecksAggregateDigest: Sha256;
  finalRuntimeEvidenceInputs: FinalRuntimeEvidenceInputsManifestV1;
  finalRuntimeEvidenceInputsDigest: Sha256;
  finalizedAt: Timestamp;
  producer: ProducerRef;
  reverificationDigest: Sha256;
};

type CanonicalSignedDecimalString = string;

type CanonicalAnkiSchedulingRowV1 = {
  id: CanonicalSignedDecimalString;
  nid: CanonicalSignedDecimalString;
  did: CanonicalSignedDecimalString;
  ord: CanonicalSignedDecimalString;
  mod: CanonicalSignedDecimalString;
  usn: CanonicalSignedDecimalString;
  type: CanonicalSignedDecimalString;
  queue: CanonicalSignedDecimalString;
  due: CanonicalSignedDecimalString;
  ivl: CanonicalSignedDecimalString;
  factor: CanonicalSignedDecimalString;
  reps: CanonicalSignedDecimalString;
  lapses: CanonicalSignedDecimalString;
  left: CanonicalSignedDecimalString;
  odue: CanonicalSignedDecimalString;
  odid: CanonicalSignedDecimalString;
  flags: CanonicalSignedDecimalString;
  dataSha256: Sha256;
};

type CanonicalAnkiReviewHistoryRowV1 = {
  id: CanonicalSignedDecimalString;
  cid: CanonicalSignedDecimalString;
  usn: CanonicalSignedDecimalString;
  ease: CanonicalSignedDecimalString;
  ivl: CanonicalSignedDecimalString;
  lastIvl: CanonicalSignedDecimalString;
  factor: CanonicalSignedDecimalString;
  time: CanonicalSignedDecimalString;
  type: CanonicalSignedDecimalString;
};

type AnkiProfileStateSnapshotArtifactPayloadV1 = {
  schema: "study.anki.profile-state-snapshot";
  schemaVersion: 1;
  projectionContractVersion: "anki-scheduling-review-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  ankiVersion: string;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  scope: "entire_collection";
  schedulingRowsEncoding: "jcs-array-utf8";
  schedulingRowsRef: BlobRef;
  schedulingRowsDigest: Sha256;
  schedulingRowCount: number;
  reviewHistoryRowsEncoding: "jcs-array-utf8";
  reviewHistoryRowsRef: BlobRef;
  reviewHistoryRowsDigest: Sha256;
  reviewHistoryRowCount: number;
  captureBoundary: {
    phase: "target_profile_preview" | "isolated_restart_copy";
    position: "before" | "after";
    sqliteReadSnapshotIdentityDigest: Sha256;
    startedAt: Timestamp;
    endedAt: Timestamp;
  };
  producer: ProducerRef;
  snapshotDigest: Sha256;
};

type AnkiWriteAuditSensorId =
  | "anki_addon_all_sqlite_connections"
  | "collection_db_wal_cross_process_journal"
  | "media_tree_cross_process_journal";

type AnkiMonitoredStorageResourceV1 = {
  resourceRole: "collection_db" | "collection_wal" | "collection_shm" | "media_tree";
  resourceBindingRef: string;
  initialResourceIdentityDigest: Sha256;
  initialResourceStateDigest: Sha256;
};

type AnkiWriteAuditSensorSignedPayloadV1 = {
  schema: "study.anki.write-audit-sensor.signed-payload";
  schemaVersion: 1;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  phase: "target_profile_full_run" | "isolated_restart_copy";
  sensorId: AnkiWriteAuditSensorId;
  implementationVersionOrDigest: string;
  monitoredResources: AnkiMonitoredStorageResourceV1[];
  monitoredResourceSetDigest: Sha256;
  intervalStartedAt: Timestamp;
  intervalEndedAt: Timestamp;
  baselineCursorDigest: Sha256;
  terminalCursorDigest: Sha256;
  coverageGapCount: number;
  overflowOrResetCount: number;
};

type AnkiWriteAuditSensorCoverageV1 = {
  signedPayload: AnkiWriteAuditSensorSignedPayloadV1;
  signedPayloadDigest: Sha256;
  serviceSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.write-audit-sensor.v1";
  };
  coverageDigest: Sha256;
};

type AnkiWriteEventV1 = {
  sequence: number;
  sensorId: AnkiWriteAuditSensorId;
  resourceRole: "collection_db" | "collection_wal" | "collection_shm" | "media_tree";
  category:
    | "rating"
    | "scheduling"
    | "review_history"
    | "sync"
    | "note_or_template"
    | "deck_or_model"
    | "other_collection"
    | "media_file";
  operation: "insert" | "update" | "delete" | "create" | "rename" | "replace";
  targetIdentityDigest: Sha256;
  changedColumns: string[];
  osJournalRecordIdentityDigest: Sha256 | null;
  observedAt: Timestamp;
};

type AnkiWriteAuditArtifactPayloadV1 = {
  schema: "study.anki.write-audit";
  schemaVersion: 1;
  auditContractVersion: "anki-write-audit-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  phase: "target_profile_full_run" | "isolated_restart_copy";
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  method: "multi-sensor-cross-process-write-audit-v1";
  intervalStartedAt: Timestamp;
  intervalEndedAt: Timestamp;
  sensorCoverages: readonly [
    AnkiWriteAuditSensorCoverageV1 & {
      signedPayload: AnkiWriteAuditSensorSignedPayloadV1 & {
        sensorId: "anki_addon_all_sqlite_connections";
      };
    },
    AnkiWriteAuditSensorCoverageV1 & {
      signedPayload: AnkiWriteAuditSensorSignedPayloadV1 & {
        sensorId: "collection_db_wal_cross_process_journal";
      };
    },
    AnkiWriteAuditSensorCoverageV1 & {
      signedPayload: AnkiWriteAuditSensorSignedPayloadV1 & {
        sensorId: "media_tree_cross_process_journal";
      };
    }
  ];
  monitoredResourceSetDigest: Sha256;
  coverageGapCount: number;
  overflowOrResetCount: number;
  coveredObservationEvidenceDigests: Sha256[];
  events: AnkiWriteEventV1[];
  eventsDigest: Sha256;
  ratingWritesObserved: number;
  schedulingWritesObserved: number;
  reviewHistoryWritesObserved: number;
  syncWritesObserved: number;
  noteOrTemplateWritesObserved: number;
  deckOrModelWritesObserved: number;
  otherCollectionWritesObserved: number;
  mediaFileWritesObserved: number;
  producer: ProducerRef;
  auditDigest: Sha256;
};
type ProfileReadOnlyEvidenceV1 = {
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  stateSnapshotBeforeRef: ArtifactRef;
  stateSnapshotBeforeDigest: Sha256;
  stateSnapshotAfterRef: ArtifactRef;
  stateSnapshotAfterDigest: Sha256;
  schedulingStateDigestBefore: Sha256;
  schedulingStateDigestAfter: Sha256;
  reviewHistoryDigestBefore: Sha256;
  reviewHistoryDigestAfter: Sha256;
  writeAuditRef: ArtifactRef;
  writeAuditDigest: Sha256;
  ratingWritesObserved: number;
  schedulingWritesObserved: number;
  reviewHistoryWritesObserved: number;
  syncWritesObserved: number;
  noteOrTemplateWritesObserved: number;
  deckOrModelWritesObserved: number;
  otherCollectionWritesObserved: number;
  mediaFileWritesObserved: number;
};

type ProcessLaunchContractV1 = {
  schema: "study.local.process-launch-contract";
  schemaVersion: 1;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  role: "runtime_verifier" | "isolated_anki";
  phase: "isolated_restart_copy";
  profileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  profileRootResourceRef: string;
  isolatedCopyManifestRef: ArtifactRef;
  isolatedCopyManifestDigest: Sha256;
  executableSha256: Sha256;
  argvTemplateId: string;
  argvTemplateVersion: string;
  opaqueArgumentBindingsDigest: Sha256;
  sandboxManifestRef: ArtifactRef;
  sandboxManifestDigest: Sha256;
  parentServiceInstanceDigest: Sha256;
  runtimeProofSignerKeyId: string | null;
  runtimeProofSignerKeyEpoch: number | null;
  runtimeProofSignerBindingDigest: Sha256 | null;
  contractDigest: Sha256;
};

type LocalProcessIdentityManifestV1 = {
  schema: "study.local.process-identity";
  schemaVersion: 1;
  role:
    | "preexisting_user_anki"
    | "card_service_main"
    | "card_service_child"
    | "runtime_verifier"
    | "isolated_anki";
  osProcessId: number;
  processCreationTimeUtc: Timestamp;
  executableSha256: Sha256;
  signerCertificateSha256: Sha256;
  launchContractRef?: ArtifactRef;
  launchContractDigest?: Sha256;
  osUserSidDigest: Sha256;
  parentProcessIdentityDigest?: Sha256;
  observedByServiceInstanceDigest: Sha256;
  observedAt: Timestamp;
  producer: ProducerRef;
  manifestDigest: Sha256;
};

type RunOwnedProcessRoleV1 =
  | "card_service_main"
  | "card_service_child"
  | "runtime_verifier"
  | "isolated_anki";

type RunOwnedProcessLaunchAttestationSignedPayloadV1 = {
  schema: "study.anki.run-owned-process-launch.signed-payload";
  schemaVersion: 1;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  osJobObjectIdentityDigest: Sha256;
  role: Exclude<RunOwnedProcessRoleV1, "card_service_main">;
  processIdentityRef: ArtifactRef;
  processIdentityDigest: Sha256;
  parentProcessIdentityDigest: Sha256;
  launchedAt: Timestamp;
};

type RunOwnedProcessLaunchAttestationV1 = {
  schema: "study.anki.run-owned-process-launch-attestation";
  schemaVersion: 1;
  signedPayload: RunOwnedProcessLaunchAttestationSignedPayloadV1;
  signedPayloadDigest: Sha256;
  serviceSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.run-owned-process-launch.v1";
  };
  attestationDigest: Sha256;
};

type RunOwnedProcessLifecycleActorV1 = {
  role: RunOwnedProcessRoleV1;
  processIdentityRef: ArtifactRef;
  processIdentityDigest: Sha256;
  registration:
    | {
        kind: "signed_run_service_main";
        runBindingRef: ArtifactRef;
        runBindingDigest: Sha256;
      }
    | {
        kind: "service_signed_job_launch";
        launchAttestationRef: ArtifactRef;
        launchAttestationDigest: Sha256;
      };
};

type RunOwnedProcessLifecycleEventV1 =
  | {
      sequence: number;
      kind: "joined";
      processIdentityDigest: Sha256;
      osJobMembershipRecordDigest: Sha256;
      observedAt: Timestamp;
    }
  | {
      sequence: number;
      kind: "exited";
      processIdentityDigest: Sha256;
      exitStatusDigest: Sha256;
      osJobMembershipRecordDigest: Sha256;
      observedAt: Timestamp;
    };

type RunOwnedProcessLifecycleLedgerSignedPayloadV1 = {
  schema: "study.anki.run-owned-process-lifecycle.signed-payload";
  schemaVersion: 1;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  serviceInstanceDigest: Sha256;
  osJobObjectIdentityDigest: Sha256;
  jobPolicy: "kill_on_close_no_breakaway";
  observationIntervalStartedAt: Timestamp;
  observationCutoffAt: Timestamp;
  actors: readonly [
    RunOwnedProcessLifecycleActorV1 & {
      role: "card_service_main";
      registration: {
        kind: "signed_run_service_main";
        runBindingRef: ArtifactRef;
        runBindingDigest: Sha256;
      };
    },
    ...(RunOwnedProcessLifecycleActorV1 & {
      role: "card_service_child" | "runtime_verifier" | "isolated_anki";
      registration: {
        kind: "service_signed_job_launch";
        launchAttestationRef: ArtifactRef;
        launchAttestationDigest: Sha256;
      };
    })[]
  ];
  lifecycleEvents: RunOwnedProcessLifecycleEventV1[];
  activeAtCutoffProcessIdentityDigests: Sha256[];
  activeAtCutoffJobMembershipSnapshotDigest: Sha256;
  lifecycleDigest: Sha256;
};

type RunOwnedProcessLifecycleLedgerArtifactPayloadV1 = {
  schema: "study.anki.run-owned-process-lifecycle";
  schemaVersion: 1;
  signedPayload: RunOwnedProcessLifecycleLedgerSignedPayloadV1;
  signedPayloadDigest: Sha256;
  serviceSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.run-owned-process-lifecycle.v1";
  };
  ledgerDigest: Sha256;
};

type TrustedAddonFocusActionSignedPayloadV1 = {
  schema: "study.anki.addon-focus-action.signed-payload";
  schemaVersion: 1;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  runtimeVerifierBindingDigest: Sha256;
  hostProcessIdentityRef: ArtifactRef;
  hostProcessIdentityDigest: Sha256;
  actionSequence: number;
  action: "raise_window" | "activate_window" | "set_foreground_window" | "other_focus_affecting";
  fromForegroundWindowIdentityDigest: Sha256 | null;
  toForegroundWindowIdentityDigest: Sha256 | null;
  issuedAt: Timestamp;
};

type TrustedAddonFocusActionAttestationV1 = {
  schema: "study.anki.addon-focus-action-attestation";
  schemaVersion: 1;
  signedPayload: TrustedAddonFocusActionSignedPayloadV1;
  signedPayloadDigest: Sha256;
  verifierSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.addon-focus-action.v1";
  };
  attestationDigest: Sha256;
};

type VerifierLaunchAttestationSignedPayloadV1 = {
  schema: "study.anki.verifier-launch.signed-payload";
  schemaVersion: 1;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  processIdentityRef: ArtifactRef;
  processIdentityDigest: Sha256;
  launchContractRef: ArtifactRef;
  launchContractDigest: Sha256;
  role: "runtime_verifier" | "isolated_anki";
  isolatedProfileIdentityDigest: Sha256;
  isolatedCollectionIdentityDigest: Sha256;
  isolatedProfileRootResourceRef: string;
  isolatedCopyManifestRef: ArtifactRef;
  isolatedCopyManifestDigest: Sha256;
  launchedAt: Timestamp;
};

type VerifierLaunchAttestationV1 = {
  schema: "study.anki.verifier-launch-attestation";
  schemaVersion: 1;
  signedPayload: VerifierLaunchAttestationSignedPayloadV1;
  signedPayloadDigest: Sha256;
  serviceSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.verifier-launch-attestation.v1";
  };
  attestationDigest: Sha256;
};

type AnkiWindowIdentityPreimageV1 = {
  owningProcessIdentityDigest: Sha256;
  osWindowHandleDecimal: CanonicalSignedDecimalString;
  owningProcessCreationTimeUtc: Timestamp;
  serviceHmacKeyId: string;
  windowClassHmacSha256: Sha256;
  titleHmacSha256: Sha256;
};

type AnkiWindowIdentityV1 = {
  preimage: AnkiWindowIdentityPreimageV1;
  windowIdentityDigest: Sha256;
};

type ExistingAnkiEnvironmentSnapshotArtifactPayloadV1 = {
  schema: "study.anki.environment-snapshot";
  schemaVersion: 1;
  observationContractVersion: "anki-process-window-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  position: "before" | "after";
  processes: {
    identityRef: ArtifactRef;
    identityDigest: Sha256;
  }[];
  windows: AnkiWindowIdentityV1[];
  processSetDigest: Sha256;
  windowSetDigest: Sha256;
  foregroundWindowIdentityDigest: Sha256 | null;
  observerProcessIdentityRef: ArtifactRef;
  observerProcessIdentityDigest: Sha256;
  capturedAt: Timestamp;
  producer: ProducerRef;
  snapshotDigest: Sha256;
};

type AnkiFocusChangeAttributionV1 =
  | {
      state: "resolved_non_run_action";
      initiatorProcessIdentityDigest: Sha256;
      attributionEvidenceRef: ArtifactRef;
      attributionEvidenceDigest: Sha256;
    }
  | {
      state: "resolved_run_owned_process";
      initiatorProcessIdentityDigest: Sha256;
      runOwnedProcessLifecycleLedgerRef: ArtifactRef;
      runOwnedProcessLifecycleLedgerDigest: Sha256;
    }
  | {
      state: "resolved_trusted_addon_action";
      initiatorProcessIdentityDigest: Sha256;
      focusActionAttestationRef: ArtifactRef;
      focusActionAttestationDigest: Sha256;
    };

type AnkiEnvironmentEventV1 =
  | {
      sequence: number;
      kind: "process_closed";
      targetProcessIdentityDigest: Sha256;
      initiatorProcessIdentityDigest: Sha256;
      attributionState: "trusted_os_attribution";
      observedAt: Timestamp;
    }
  | {
      sequence: number;
      kind: "process_restarted";
      beforeProcessIdentityDigest: Sha256;
      afterProcessIdentityDigest: Sha256;
      initiatorProcessIdentityDigest: Sha256;
      attributionState: "trusted_os_attribution";
      observedAt: Timestamp;
    }
  | {
      sequence: number;
      kind: "window_closed";
      targetWindowIdentityDigest: Sha256;
      owningProcessIdentityDigest: Sha256;
      initiatorProcessIdentityDigest: Sha256;
      attributionState: "trusted_os_attribution";
      observedAt: Timestamp;
    }
  | {
      sequence: number;
      kind: "focus_changed";
      fromForegroundWindowIdentityDigest: Sha256 | null;
      toForegroundWindowIdentityDigest: Sha256 | null;
      attribution: AnkiFocusChangeAttributionV1;
      attributionState: "trusted_os_attribution";
      observedAt: Timestamp;
    };

type AnkiEnvironmentEventTraceArtifactPayloadV1 = {
  schema: "study.anki.environment-event-trace";
  schemaVersion: 1;
  observationContractVersion: "anki-process-window-v1";
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  beforeSnapshotRef: ArtifactRef;
  beforeSnapshotDigest: Sha256;
  afterSnapshotRef: ArtifactRef;
  afterSnapshotDigest: Sha256;
  runOwnedProcessLifecycleLedgerRef: ArtifactRef;
  runOwnedProcessLifecycleLedgerDigest: Sha256;
  trustedAddonFocusActionAttestationSetDigest: Sha256;
  intervalStartedAt: Timestamp;
  intervalEndedAt: Timestamp;
  coveredObservationEvidenceDigests: Sha256[];
  events: AnkiEnvironmentEventV1[];
  observerProcessIdentityRef: ArtifactRef;
  observerProcessIdentityDigest: Sha256;
  producer: ProducerRef;
  traceDigest: Sha256;
};

type PreRunAnkiSourceStateSnapshotArtifactPayloadV1 = {
  schema: "study.anki.pre-run-source-state-snapshot";
  schemaVersion: 1;
  contractVersion: "anki-pre-run-source-state-v1";
  provisionalRunId: string;
  operationBoundaryId: string;
  inputFingerprint: InputFingerprint;
  importPlanRef: ArtifactRef;
  importPlanDigest: Sha256;
  targetProfileIdentityDigest: Sha256;
  targetCollectionIdentityDigest: Sha256;
  cardIdentitySetDigest: Sha256;
  mediaManifestDigest: Sha256;
  r8aVerificationArtifactRef: ArtifactRef;
  r8aVerificationArtifactDigest: Sha256;
  collectionReadSnapshotIdentityDigest: Sha256;
  capturedAt: Timestamp;
  producer: ProducerRef;
  snapshotDigest: Sha256;
};
type AnkiCollectionSourceSnapshotArtifactPayloadV1 = {
  schema: "study.anki.collection-source-snapshot";
  schemaVersion: 1;
  snapshotContractVersion: "anki-isolated-copy-v1";
  targetProfileIdentityDigest: Sha256;
  targetCollectionIdentityDigest: Sha256;
  preRunStateSnapshotRef: ArtifactRef;
  preRunStateSnapshotDigest: Sha256;
  collectionSnapshotBlobRef: BlobRef;
  collectionSnapshotBlobDigest: Sha256;
  requiredMediaArchiveRef: BlobRef;
  requiredMediaArchiveDigest: Sha256;
  cardMediaRoleInventoryRef: ArtifactRef;
  cardMediaRoleInventoryDigest: Sha256;
  producer: ProducerRef;
  snapshotDigest: Sha256;
};

type IsolatedCopySubjectV1 = {
  sourceSnapshotRef: ArtifactRef;
  sourceSnapshotDigest: Sha256;
  isolatedCopyProfileIdentityDigest: Sha256;
  isolatedCopyCollectionIdentityDigest: Sha256;
  isolatedCollectionBlobSha256: Sha256;
  isolatedMediaInventoryDigest: Sha256;
  runtimeIsolationPolicyDigest: Sha256;
};

type TrustedCopierSignedPayloadV1 = {
  schema: "study.anki.trusted-copy.signed-payload";
  schemaVersion: 1;
  copyContractVersion: "anki-isolated-copy-v1";
  subject: IsolatedCopySubjectV1;
  subjectDigest: Sha256;
  copierImplementationVersionOrDigest: string;
  copierProtocolVersion: string;
  copierProducer: ProducerRef;
  copiedAt: Timestamp;
};

type TrustedCopierAttestationArtifactPayloadV1 = {
  schema: "study.anki.trusted-copy-attestation";
  schemaVersion: 1;
  signedPayload: TrustedCopierSignedPayloadV1;
  signedPayloadDigest: Sha256;
  copierSignature: DetachedEd25519SignatureV1 & {
    domain: "study.anki.trusted-copy-attestation.v1";
  };
  attestationDigest: Sha256;
};

type IsolatedAnkiCopyManifestArtifactPayloadV1 = {
  schema: "study.anki.isolated-copy-manifest";
  schemaVersion: 1;
  copyContractVersion: "anki-isolated-copy-v1";
  subject: IsolatedCopySubjectV1;
  subjectDigest: Sha256;
  copierAttestationRef: ArtifactRef;
  copierAttestationDigest: Sha256;
  isolatedProfileRootResourceRef: string;
  createdAt: Timestamp;
  manifestDigest: Sha256;
};

type AnkiRuntimeEvidenceArtifactPayload = {
  schema: "study.anki.runtime-evidence";
  schemaVersion: 1;
  runBindingRef: ArtifactRef;
  runBindingDigest: Sha256;
  operationBoundaryId: string;
  importPlanRef: ArtifactRef;
  importPlanDigest: Sha256;
  requiredCheckManifestRef: ArtifactRef;
  requiredCheckManifestDigest: Sha256;
  expectedRuntimeObservationsDigest: Sha256;
  runtimeVerifierBinding: Extract<RuntimeVerifierBindingV1, { state: "selected" }>;
  runtimeVerifierBindingDigest: Sha256;
  runtimeIsolationPolicyRef: ArtifactRef;
  runtimeIsolationPolicyDigest: Sha256;
  sample: DeterministicRuntimeSamplePolicyV1;
  actualMediaRolesByCard: ExpectedMediaRolesByCardV1[];
  actualMediaRolesByCardDigest: Sha256;
  dataStateBeforeRef: ArtifactRef;
  dataStateBeforeDigest: Sha256;
  dataStateAfterRef: ArtifactRef;
  dataStateAfterDigest: Sha256;
  finalDataReverificationRef: ArtifactRef;
  finalDataReverificationDigest: Sha256;
  finalRuntimeEvidenceInputs: FinalRuntimeEvidenceInputsManifestV1;
  finalRuntimeEvidenceInputsDigest: Sha256;
  targetPreviewEvidence: {
    phase: "target_profile_preview";
    target: ProfileReadOnlyEvidenceV1;
    records: Extract<
      RuntimeObservationRecordV1,
      { phase: "target_profile_preview" }
    >[];
  };
  isolatedRestartEvidence: {
    phase: "isolated_restart_copy";
    sourceSnapshotRef: ArtifactRef;
    sourceSnapshotDigest: Sha256;
    isolatedCopyManifestRef: ArtifactRef;
    isolatedCopyManifestDigest: Sha256;
    trustedCopierAttestationRef: ArtifactRef;
    trustedCopierAttestationDigest: Sha256;
    copyLineageDigest: Sha256;
    verifierProcessBeforeRef: ArtifactRef;
    verifierProcessBeforeDigest: Sha256;
    verifierLaunchBeforeAttestationRef: ArtifactRef;
    verifierLaunchBeforeAttestationDigest: Sha256;
    verifierProcessAfterRef: ArtifactRef;
    verifierProcessAfterDigest: Sha256;
    verifierLaunchAfterAttestationRef: ArtifactRef;
    verifierLaunchAfterAttestationDigest: Sha256;
    isolatedAnkiProcessBeforeRef: ArtifactRef;
    isolatedAnkiProcessBeforeDigest: Sha256;
    isolatedAnkiLaunchBeforeAttestationRef: ArtifactRef;
    isolatedAnkiLaunchBeforeAttestationDigest: Sha256;
    isolatedAnkiProcessAfterRef: ArtifactRef;
    isolatedAnkiProcessAfterDigest: Sha256;
    isolatedAnkiLaunchAfterAttestationRef: ArtifactRef;
    isolatedAnkiLaunchAfterAttestationDigest: Sha256;
    processRestartObserved: true;
    isolatedCopy: ProfileReadOnlyEvidenceV1;
    records: Extract<
      RuntimeObservationRecordV1,
      { phase: "isolated_restart_copy" }
    >[];
  };
  userEnvironmentPreservation: {
    beforeSnapshotRef: ArtifactRef;
    beforeSnapshotDigest: Sha256;
    afterSnapshotRef: ArtifactRef;
    afterSnapshotDigest: Sha256;
    eventTraceRef: ArtifactRef;
    eventTraceDigest: Sha256;
    runOwnedProcessLifecycleLedgerRef: ArtifactRef;
    runOwnedProcessLifecycleLedgerDigest: Sha256;
    trustedAddonFocusActionAttestationSetDigest: Sha256;
    existingAnkiProcessSetDigestBefore: Sha256;
    existingAnkiProcessSetDigestAfter: Sha256;
    existingAnkiWindowSetDigestBefore: Sha256;
    existingAnkiWindowSetDigestAfter: Sha256;
    closedExistingWindowsObserved: number;
    restartedExistingProcessesObserved: number;
    focusStealEventsObserved: number;
  };
  evidenceDigest: Sha256;
};
type AnkiVerificationRecord =
  | {
      domain: "data_integrity";
      checkId: AnkiDataIntegrityCheckId;
      state: "passed" | "failed";
      method: "ankiconnect_query" | "package_reverification" | "content_hash";
      producer: ProducerRef;
      evidenceRefs: ArtifactRef[];
      checkedAt: Timestamp;
    }
  | {
      domain: "runtime_experience";
      checkId: AnkiRuntimeCheckId;
      state: "passed" | "failed" | "not_assessed";
      method: "trusted_anki_addon" | "versioned_gui_protocol";
      producer: ProducerRef;
      evidenceRefs: ArtifactRef[];
      ankiVersion: string;
      verifierVersion: string;
      checkedAt: Timestamp;
    };

type ImportVerificationStatus =
  | {
      state: "not_imported";
      dataIntegrity: "not_assessed";
      runtimeExperience: "not_assessed";
    }
  | {
      state: "conflict";
      dataIntegrity: "not_assessed" | "failed";
      runtimeExperience: "not_assessed";
    }
  | {
      state: "imported_unverified";
      importDisposition: "imported" | "existing";
      dataIntegrity: "not_assessed" | "partial" | "failed";
      runtimeExperience: "not_assessed";
    }
  | {
      state: "data_verified";
      importDisposition: "imported" | "existing";
      dataIntegrity: "passed";
      runtimeExperience: "not_assessed";
    }
  | {
      state: "runtime_failed";
      importDisposition: "imported" | "existing";
      dataIntegrity: "passed";
      runtimeExperience: "failed";
      runtimeEvidenceRef: ArtifactRef;
      failedRuntimeCheckIds: AnkiRuntimeCheckId[];
    }
  | {
      state: "fully_verified";
      importDisposition: "imported" | "existing";
      dataIntegrity: "passed";
      runtimeExperience: "sample_passed" | "full_passed";
      runtimeEvidenceRef: ArtifactRef;
    };

type AnkiVerificationArtifactPayload = {
  schema: "study.anki.verification";
  schemaVersion: 1;
  packageRef: ArtifactRef;
  importPlanRef: ArtifactRef;
  ankiProfileIdentityDigest: Sha256;
  collectionIdentityDigest: Sha256;
  ankiVersion: string;
  ankiConnectVersion: string;
  importIntentId: string;
  verificationContractVersion: string;
  requiredCheckManifestRef: ArtifactRef;
  requiredCheckManifestDigest: Sha256;
  runBindingRef?: ArtifactRef;
  runBindingDigest?: Sha256;
  operationBoundaryId?: string;
  finalDataReverificationRef?: ArtifactRef;
  finalDataReverificationDigest?: Sha256;
  status: ImportVerificationStatus;
  noteCount: number;
  cardCount: number;
  mediaCount: number;
  createdMediaManifestDigest?: Sha256;
  orphanMediaState: "none" | "reported" | "cleaned" | "unknown";
  checks: AnkiVerificationRecord[];
  failedCheckIds: (AnkiDataIntegrityCheckId | AnkiRuntimeCheckId)[];
  missingRequiredCheckIds: (AnkiDataIntegrityCheckId | AnkiRuntimeCheckId)[];
  verificationDigest: Sha256;
};

type AnkiRecoveryDecisionV1 =
  | {
      state: "not_written";
      packageRef: ArtifactRef;
      importPlanRef: ArtifactRef;
      importPlanDigest: Sha256;
      requiredAction: "confirm_anki_import";
      recoveryImportIntentId: string;
    }
  | {
      state: "written_identity_matched";
      packageRef: ArtifactRef;
      originalImportPlanRef: ArtifactRef;
      matchedCardIdentitySetDigest: Sha256;
      nextAction: "verification_only_successor";
    }
  | {
      state: "write_boundary_ambiguous";
      packageRef: ArtifactRef;
      originalImportPlanRef: ArtifactRef;
      evidenceRefs: ArtifactRef[];
      nextAction: "stop_and_resolve_conflict";
    };

type WorkflowSnapshot = {
  projectId: ProjectId;
  projectRevision: Revision;
  productStep: ProductStep;
  artifactStage: ArtifactStage;
  operationState: OperationState;
  currentTaskId?: TaskId;
  lastAcknowledgedTaskId?: TaskId;
  terminalOutcomeAcknowledgedAt?: Timestamp;
  primaryActionId: WorkflowActionId;
  blockerIssueRefs: string[];
};

type FixedCapabilityStatus = {
  capabilityId: CapabilityId;
  state: CapabilityState;
  implementationVersionOrDigest?: string;
  compatibilityContractVersion?: string;
  checkedAt?: Timestamp;
  issueRefs: string[];
};

type ServiceProfileVerificationRecord = {
  verificationId: string;
  sequence: number;
  capability: ServiceProfileCapabilityId;
  profileRef: string;
  configurationFingerprint: Sha256;
  credentialRevision: number;
  status: "passed" | "failed";
  checkedAt: Timestamp;
  latencyMs?: number;
  errorCode?:
    | "auth_failed"
    | "invalid_configuration"
    | "network_unreachable"
    | "rate_limited"
    | "service_unavailable"
    | "timeout"
    | "response_incompatible"
    | "unknown_redacted";
  retryable?: boolean;
};

type ServiceProfileCapabilityStatus = {
  capability: ServiceProfileCapabilityId;
  profileRef: string;
  configurationFingerprint: Sha256;
  credentialRevision: number;
  state: CapabilityState;
  latestVerification?: ServiceProfileVerificationRecord;
  issueRefs: string[];
};

type ServiceCapabilityAggregate = {
  capability: ServiceProfileCapabilityId;
  displayState: "none_configured" | "none_ready" | "some_ready" | "all_ready";
  configuredCount: number;
  readyCount: number;
};

type SystemCapabilitySnapshot = {
  snapshotRevision: Revision;
  fixedCapabilities: Record<CapabilityId, FixedCapabilityStatus>;
  serviceProfiles: ServiceProfileCapabilityStatus[];
  serviceAggregates: Record<ServiceProfileCapabilityId, ServiceCapabilityAggregate>;
};

~~~

CapabilityId、ServiceProfileCapabilityId、LearningRoute、MediaPreferenceKey、WorkflowActionId、ProductStep、ArtifactStage 和 OperationState 都是控制面固定枚举；适配器、服务类型或路线扩展必须提升相应 schema 版本，不得把来源/模型自由文本写成新枚举值。model/TTS/AnkiConnect 的 ready 只按精确 (capability, profileRef, configurationFingerprint, credentialRevision) 判断；同一键 sequence 最大的记录是唯一最新真相，最新 failed 覆盖历史 passed。serviceAggregates 仅用于展示 any/all 统计，永远不能作为工作流 gate。

credentialRevision 由 Card Service 的凭据账本原子维护：新增、替换、删除/清空凭据，以及 OAuth 账户或 token material 改变时都必须严格单调递增；旧 revision 永不复用，回滚到旧 secret 也产生新 revision。并发更新只有一个序列化顺序，任何成功更新都立即使旧验证、OperationApproval 与能力绑定 stale。configurationFingerprint 不含秘密，绝不能用“指纹未变”替代 revision bump。发布测试必须覆盖 add/replace/delete/rollback/concurrent update。

~~~ts
type UserNotice = {
  noticeCode: string;
  severity: "info" | "warning" | "error";
  title: string;
  detail: string;
  actionId?: WorkflowActionId;
};
~~~

WorkflowSnapshot 的任务不变量：初始 idle 时 currentTaskId 缺省；queued/running/cancelling 和四种未被后续写动作取代的终态都必须存在 currentTaskId，且对应 StudyTaskSnapshot.state 与 operationState 完全一致。只读查询、切换宿主表面和展示结果不能清除终态。下一个写动作被 Service 接受时，必须在同一事务记录 lastAcknowledgedTaskId/terminalOutcomeAcknowledgedAt；若它创建异步任务则原子替换 currentTaskId，否则清空 currentTaskId 并进入 idle。这样 tools-only 对话和条件 App UI 都能确定性显示最后结果，不需要从通知文案猜测。

**摘要与签名的统一规则。** 本节所有 `...Digest` 都是小写十六进制 SHA-256。除另有说明外，带末尾摘要字段的对象使用 `SHA-256(JCS(object 省略该对象自己的末尾摘要字段))`；数组顺序是合同的一部分，禁止解析后自行重排。除 runtime-proof 外，`DetachedEd25519SignatureV1.signedPayloadDigest` 必须等于 `SHA-256(JCS(signedPayload))`；runtime-proof 中它必须等于 `SHA-256(JCS(signedBinding))`。签名消息统一严格为 `UTF8(domain) || 0x00 || raw_32_byte_digest`，算法只能是 Ed25519；`signatureRef` 是 64 字节原始签名 Blob。run/launch/barrier/write-audit-sensor/run-owned-process-lifecycle/run-owned-process-launch 域使用 isolation policy 的 service signer，trusted-copy 使用 copier signer，runtime-proof 与 addon-focus-action 使用 RuntimeVerifierBinding 的 producer signer，trust-revocation-snapshot 使用预置 root trust anchor；domain、keyId、keyEpoch 与 root-signed snapshot 中精确公钥版本必须逐项匹配。binding/attestation 的外层摘要只省略自己的末尾 digest，因而覆盖 signed payload、signature 元数据和 BlobRef；signature 只签 payload digest，不签外层摘要，消除自引用环。

**撤销状态不可回滚。** pinned root trust anchor 是随已签名 Card Service 发布物安装的不可变 `(rootKeyId,rootKeyEpoch,rawEd25519PublicKey,publicKeySha256)` 元组；启动时先重哈希 raw key，root signature 的 keyId/epoch 与公钥必须逐字节等于该元组，不能从 snapshot、调用方或网络解析另一个 root。`TrustRevocationSnapshotArtifactPayloadV1` 由该 pinned root key 使用独立域签署；sequence 必须为非负安全整数并严格递增，除 genesis 外 `previousSnapshotDigest` 必须等于同 authority 前一序列。

`historyMode` 只能是 `complete_append_only_tombstones`。每张 snapshot 都必须携带该 authority 从 genesis 至当前的完整 key family/version 历史：families 按 keyId UTF-8 排序且唯一，versions 按 keyEpoch 数值升序且唯一。genesis 中 introduced/firstAuthorized sequence 为 0；后续新增 family/version 的相应 sequence 必须等于当前 snapshot.sequence。每个 `publicKeyRef` 必须解析为恰好 32 字节的原始 Ed25519 公钥，Blob 内容 SHA-256 必须等于 `publicKeySha256`。

对每个非 genesis snapshot，Service 必须先解析并验签 immediate previous snapshot，再执行逐字段差分：上一张中的每个 family/version 必须继续存在；同一 `(keyId,keyEpoch)` 的 `introducedAtSequence/firstAuthorizedSequence/publicKeyRef/publicKeySha256` 永久不可变；active 只能单向变为 revoked，且首次变化时 `revokedAtSequence=current sequence`、`revokedAt<=issuedAt`，之后 state/revokedAt/revokedAtSequence 作为 tombstone 永久不变；family.disabledAt 也只能从 null 单向变为时间戳并记录当前 disabledAtSequence，之后永久不变。`minimumAcceptedEpoch` 只能单调上升。新 version 的 keyEpoch 必须大于该 family 历史最大 epoch，且其 `publicKeySha256` 在该 authority 的全部 family/version 历史中从未出现；禁止把旧公钥别名到更高 epoch、另一 keyId 或复活 tombstone。删除历史条目、revoked→active、disabled→enabled、同 key version 换 ref/hash、复用公钥 hash 或回退 floor 都 fail closed。

active 条目要求 revokedAt/revokedAtSequence 均为 null；revoked 条目二者均非空。active family 要求 disabledAt/disabledAtSequence 均为 null，且至少有一个 state=active、epoch 不低于 minimumAcceptedEpoch 的 version；disabled family 二者均非空。Card Service 在 OS 保护的本地状态中为每个 authority 保存 anti-rollback floor `(sequence, snapshotDigest)`，任何低于 floor、同 sequence 异 digest、断链、过期 root 或无效 root signature 都 fail closed。验签时只能以签名中的 `(keyId,keyEpoch)` 在当前 root-signed snapshot 中精确解析唯一 version，要求 family 未禁用、`keyEpoch >= minimumAcceptedEpoch`、version.state=active，并逐字节使用其 `publicKeyRef/publicKeySha256`；不得由 keyId 约定、外部 keyring、调用方字段或“更高 epoch”自报另选公钥。

prepare ImportPlan、开始 run 和最终 registry commit 三个边界都必须重新解析“当前最高序列”的 service/copier/runtime-verifier snapshots，并与本地 floor 比较。`trustSnapshotBindings` 固定按 service、copier、runtime-verifier 排序，`trustSnapshotBindingsDigest = SHA-256(JCS(array))`；run binding 与 final read-barrier signature 都直接覆盖同一三元组。snapshot、key epoch 或 floor 在任一边界改变，ImportApproval 与旧 run 立即 stale，必须生成新计划/运行，不能携旧 snapshot 回滚已撤销 key。
**固定核验合同。** `AnkiVerificationContractV1` 是受认证 Artifact registry 管理的不可变合同。`contractDigest = SHA-256(JCS(contract 省略 contractDigest))`；`verificationContractVersion=anki-data-runtime-v1` 必须逐项等于类型中冻结的 11 个 data checks、10 个 runtime checks、四个媒体角色映射、normal 960×720 与 narrow 600×720 两个视口、sample/full 模式、20 张最小样本和所有子合同版本。`RequiredAnkiCheckManifestV1` 的 contract ref/version/digest、两组 checks、媒体映射、两个视口派生的 render expectations、运行时绑定与隔离策略必须逐字节匹配，禁止空集、子集、额外项、未知项或运行时降级；`manifestDigest` 是省略自身后的完整 JCS。合同、manifest、producer trust 或版本任一不匹配都 fail closed；AnkiConnect 的数据查询最多只能形成 `data_verified`，不能推导真实渲染与播放通过。

**权威媒体清单。** `PackageMediaManifestEntryV1.storedFileName` 必须是 NFC 规范化的 basename，不得包含 `/` 或 `\` 路径分隔符，不得为空或等于 `.` / `..`，也不得含控制字符或平台保留路径成分；`sizeBytes`、`mediaCount`、`totalSizeBytes` 必须是非负安全整数，MIME 规范化为小写 `type/subtype` 且不带参数。`entryDigest = SHA-256(JCS(entry 省略 entryDigest))`。entries 按 `storedFileName` UTF-8 字节序、再按 sha256 排序，拒绝重复文件名、重复条目或同名异哈希；`manifestDigest = SHA-256(JCS(payload 省略 manifestDigest))`，计数和总字节必须由 entries 重算。PackageArtifact、ImportPlan、RequiredAnkiCheckManifest 和媒体角色 inventory 的 media ref/digest 必须完全相同。

`PackageCardIdentitySetPayloadV1.cardIds` 必须非空、NFC 规范化、按 UTF-8 字节序排序并拒绝重复；`cardCount` 等于长度，`cardIdsDigest = SHA-256(JCS(cardIds))`，`payloadDigest = SHA-256(JCS(payload 省略 payloadDigest))`。`PackageCardMediaRoleInventoryPayloadV1` 对身份集中每张卡恰好一条 entry，包括 `media=[]` 的卡；不得多卡、漏卡或额外卡。media bindings 按固定 `source_audio`、`sentence_tts`、`expression_tts`、`source_video` 次序排序，拒绝重复角色，并绑定权威 `mediaFileSha256` 与 `mediaManifestEntryDigest`；每个绑定必须解析到同一媒体清单中的唯一 entry。entries 按 CardId 排序，`inventoryDigest = SHA-256(JCS(payload 省略 inventoryDigest))`。R8a 必须先证明实际导入 CardIdentitySet、字段、模板与所需媒体等于这条权威链，R8b 才可开始。

**一次运行的签名根。** Card Service 先从密码学安全随机源分配 base64url 无填充、解码后至少 16 字节的 `runId` 与 `operationBoundaryId`，把 `createdAt` 固定为该边界开始时刻，并从受信 OS API 采集 Card Service 主进程 identity；signed run 的 `serviceMainProcessIdentityRef/digest` 必须解析为该 identity 且 serviceInstanceDigest 一致。随后启动 target write audit 与 user-environment observer、采集 before baseline，再制作 source snapshot 和受信隔离副本。`PreRunAnkiSourceStateSnapshotArtifactPayloadV1` 只绑定 provisionalRunId、operationBoundary、input fingerprint、ImportPlan、当前 R8a VerificationArtifact、目标 identity 与 collection read-snapshot identity，明确不含 `runBindingDigest`；source snapshot 只能引用这个 pre-run 类型。待 plan/manifest/source/copy/attestation 全部冻结后，Service 在任何 preview/restart action 前创建并签署 `RuntimeVerificationRunBindingV1`，并要求 provisionalRunId/boundary 精确相等；run Envelope 以 plan、manifest、pre-run state、source、copy、copier attestation 和 policy 为 parents。这个单向 `pre-run → source/copy → signed run → runtime evidence` 图不存在 run→source→state→run 哈希环。`expiresAt` 必须晚于 `createdAt`；签名完成前任何预备证据都不得对外成为可复用 runtime evidence。
同一运行的 observation evidence、proof、data/profile snapshot、write audit、environment trace、process launch contract/attestation、final data reverification 和 runtime evidence 必须逐字节复用相同 `runBindingDigest`、`operationBoundaryId`、ImportPlan、required manifest 与 input fingerprint。其 ArtifactEnvelope 的 `inputFingerprint` 必须等于 run binding，`parents` 至少包含当前 run binding、ImportPlan、required manifest；复制或启动类证据还必须包含各自 source/copy/launch 父 Artifact。所有时间都在 run 的 `[createdAt, expiresAt]` 内，且事件时间落在所属证据区间。禁止跨 run、跨 plan、跨 profile、跨 service instance 或跨 audience 重用证据；旧 run 即使字节相同也不能为新 run 续命。

**确定性样本与渲染期望。** `runtimeSamplePolicy.cardIdentitySetRef/digest` 必须等于 manifest；eligibleCardIds 逐项等于完整权威 CardIdentitySet。minimumCards 只能为 20。`samplingSeedDigest = SHA-256(JCS({ schema: "study.anki.runtime-sample-seed", schemaVersion: 1, apkgSha256, verificationContractVersion }))`；`sha256_rendezvous_v1` 对每个 CardId 计算 `SHA-256(JCS({ samplingSeedDigest, cardId }))`，按 score 原始字节升序、CardId UTF-8 次序打破平局。sample 选择 `min(eligibleCount, 20)`，full 选择全部；selectedCardIds 最后按 CardId 排序。任一 count/digest/集合不一致或 eligible=0 都不能形成运行时通过。

`expectedMediaRolesByCard` 是权威 inventory 在 selectedCardIds 上的精确投影。`expectedRuntimeObservations` 为唯一 tuple 集：每卡五个 preview checks、每个实际媒体角色一个 playback check，以及每卡一个 isolated restart check；按 phase、scope、checkId、cardId、mediaRole-or-empty 的 UTF-8 次序排序并拒绝重复。

`CardRenderExpectationV1` 不能由 verifier 或模型提交；Card Service 按 `anki-render-expectation-derivation-v1` 从受认证 CardPlan、冻结字段投影和 PackageArtifact template digest 确定性派生。每张 selected card 恰好一条：front tuple 的第一项必须是唯一 `card_root`，第二项必须是带非空 text SHA 的 cue/content；back 第一项是唯一 root，第二项是带非空 text SHA 的 answer/content，后续 elementKey 在单侧唯一。`cardPlanDigest`、fieldProjectionDigest、templateDigest 和 cardContentDigest 都必须等于父 Artifact。`expectationDigest` 省略自身后计算，数组按 CardId 排序；空 expectation、全 null 文本或调用方自造 expectation 一律失败。manifest 与 signed run 同时绑定总 digest，records 与 expected tuple 必须一一相等。
**证据不是“通过”声明。** 每条 `RuntimeObservationRecordV1` 只能引用同 run 的 `RuntimeObservationEvidenceArtifactPayloadV1`；evidence/proof 的末尾 digest 都按省略自身字段的完整 JCS 计算，ArtifactRef、observation、时间、phase profile/collection 必须一致。proof Artifact 与 evidence Artifact 的 Envelope parents 包含 run/plan/manifest/expectation/media/process 证据。Runtime Verifier 只提交规范化观测事实；`state` 由 Card Service 重新解析 proof、执行固定 pass predicate 后计算，不能接受 producer 自报布尔值。

每个 passed 或 failure proof 都必须携 `RuntimeProofAuthenticationV1`。先计算 `proofFactsDigest = SHA-256(JCS(proof 省略 proofAuthentication 与 proofDigest))`，再把该 digest、run/boundary、RuntimeVerifierBinding、producer process identity 与 service-signed launch attestation 放入 `RuntimeProofSignedBindingV1`；`signedBindingDigest = SHA-256(JCS(signedBinding))`，verifier signature 使用 `study.anki.runtime-proof.v1` 域签它。这样签名 facts 不能与另一进程/launch attestation 调包；signer key/epoch/snapshot 必须等于 RuntimeVerifierBinding，并在当前 anti-rollback floor 有效。authentication 引用的 process identity 与 service-signed launch attestation 必须是同 run/copy/root 的 `runtime_verifier`，其 ProcessLaunchContract 的 proof signer key/epoch/binding digest 与签名一致。payload 中 `producer` 只作冗余显示，Service 必须从验签 key和认证 IPC/launch identity 派生并要求相等，调用方不能冒充。proof kind、签名、进程、Blob、摘要、父链任一错误均为 `ANKI_VERIFY_FAILED`，不是一次真实 `runtime_failed`。
- Render proof：每个 front/back observation 必须精确携带 `[normal 960×720, narrow 600×720]` 两个 captures，顺序固定。每个 canonicalRenderTree Blob 必须解码为 JCS UTF-8 的 `AnkiRenderElementObservationV1[]`，按确定性 DOM preorder 输出，元素键唯一，Blob SHA/size/MIME 与 ref 一致；PNG screenshot 必须有效且像素尺寸等于相应 viewport。通过要求 document complete、horizontal overflow 精确为 0、fatal script errors 为空、requiredElements 与该侧非空 expectation 一一相等、文本哈希相等、所有必需框宽高为正且 `visible=true`、`clipped=false`。`cardRootVisible` 不能独立采信：canonical tree 中必须恰有一个与 expectation root key 相同的 `card_root`，Service 从其 visible/box/clipped 重新派生该值并要求冗余字段相等。
- Interaction proof：events 的 sequence 从 0 连续递增并按时间非递减。flip 必须精确观察 `invoke_flip → observe_back` 且最终 back/answer 可见；scroll 必须 `scroll_to_end`，`scrollTop=scrollRange`（range=0 合法）且 required content visible；window_resize 必须依次覆盖 normal 与 narrow，两个阶段 horizontal overflow 都为 0。任何 fatal script error、额外/缺失/乱序关键事件均失败。
- Media playback proof：events sequence 连续，必须出现 `loadedmetadata → canplay → play → 至少一个 timeupdate → pause 或 ended`，不得出现 error；currentTime/duration 是非负安全整数、currentTime 单调且不超过正的 duration。duration≥250ms 时播放推进至少 250ms；更短媒体必须观察 ended 且最终 currentTime=duration。`resolvedMediaSourceSha256` 必须等于该卡该角色 inventory 中的 file SHA，entry digest 也必须相等。
- Restart proof：必须引用同一 isolated copy/profile/collection 中实际 `isolated_anki` 的前后 process identity、两份 service-signed launch attestation，以及 before/after 两个 `AnkiWindowIdentityV1`。before window owner 必须是 before process，after/reopened window owner 必须是 after process，`reopenedWindowIdentityDigest` 精确等于 after window。events sequence 固定为：exit 使用 before process+before window；start 使用 after process+null window；collection_opened 与 card_reopened 都使用 after process+after window。PID/creation-time 证明进程不同，before/after 为同 card/side/content/scheduling state；任何第三 profile 或旧窗口重放都失败。
- Failure proof：只能以 `kind=failure` 形成 `state=failed`，errorCode、diagnostic digest 与受认证本地 Blob 必须可解析；它不能替代任何 passed proof。

**R8a 与 R8b 之间的 TOCTOU 闭合。** `AnkiDataStateSnapshotArtifactPayloadV1.before_runtime` 在首次 R8a 全通过之后、首个 runtime action 之前采集；`after_runtime` 在最后一个 runtime observation 之后采集。cards/notes/decks/noteModels 分别按 cardId/noteId/deckId/noteModelId UTF-8 字节序排序且 ID 唯一，字段哈希按 ordinal 保序；每个数组 digest 由其 JCS 重算。`liveMediaDirectoryScan` 不是把用户所有历史媒体与本包比较，而是对权威 manifest 中每个 storedFileName 做一次 live lookup、尺寸与内容重哈希的精确结果；缺失、同名异哈希或多重解析均失败。before/after 必须与 PackageArtifact、ImportPlan、identity set、模板和媒体清单一致。

`FinalAnkiDataReverificationArtifactPayloadV1` 在全部 runtime observations 结束后，于短时 read barrier 内重新执行合同中顺序固定的全部 11 个 R8a checks。每次 barrier attempt 新建至少 128-bit 随机 `readBarrierInstanceId` 和受信 SQLite final-read snapshot identity；每条 record 必须引用 typed `FinalAnkiDataCheckEvidenceArtifactPayloadV1`，其 run/boundary/barrier instance、commit descriptor ref/digest、profile/collection、read snapshot 和 capturedAt 全部相等，sourceEvidence 只引用该 snapshot 内本次读取的证据。按 contract 顺序对 `{checkId,evidenceDigest}` 数组做 JCS SHA-256 得到 `finalDataChecksAggregateDigest`，FinalReverification 与 signed barrier payload 必须同时覆盖同一值；旧 R8a evidence、旧 barrier attempt 或 commit descriptor 不匹配不能复用。11 条必须恰好一次、全 passed，最终 before/after data 与 package/import 的 identity、字段、deck/model/template 和媒体仍完全一致。

`FinalRuntimeEvidenceInputsManifestV1` 是签名前唯一允许的 runtime 输入聚合 preimage。observations 必须按 required manifest 的 expected tuple 次序逐项一一对应，并显式绑定 observation/evidence/proof；两个 data states、四个 profile states、target/isolated 两个 audits、before/after/environment trace、完整 signed run-owned process lifecycle ledger、四组 verifier/isolated-Anki process+launch、全部 trusted-add-on focus action attestations，以及按固定 11-check 次序排列的 final evidence 都有类型固定的 cardinality。可变数组分别按 expected tuple、actionSequence 排序且拒绝重复；addon attestation 列表必须恰好等于 event trace 中 `resolved_trusted_addon_action` 的投影，`trustedAddonFocusActionAttestationSetDigest = SHA-256(JCS([{ actionSequence, attestationRef, attestationDigest }, ...]))` 并与 trace 字段相等。每个 ref 必须解析为所列 digest、同 run/boundary/profile/phase；`manifestDigest = SHA-256(JCS(manifest 省略 manifestDigest))`，并等于 barrier、FinalReverification 和 RuntimeEvidence 三处的 `finalRuntimeEvidenceInputsDigest`，三处内嵌 manifest 必须逐字节相同。遗漏类别、额外成员、排序差异、旧 evidence 或只聚合摘要文本均 fail closed。

`VerificationRegistryCommitDescriptorV1` 解决 read-barrier 与最终 Artifact 的自引用：Card Service 先预分配 128-bit 随机 registryTransactionId 和四个不可变 ArtifactId，members 必须按类型中固定顺序恰好为 read-barrier attestation、final reverification、runtime evidence、verification；`descriptorDigest = SHA-256(JCS(descriptor 省略 descriptorDigest))`，认证 transaction journal 以 `registryCommitDescriptorRef` 解析，`registryCommitDescriptorDigest` 必须逐字节等于所解析 descriptor 的 `descriptorDigest`。它只绑定预分配 ID、schema、run 和 operation boundary，不包含这四个尚未完成的内容摘要，因此无哈希环。服务在 barrier 内完成最终读取后把当前时刻写为 `intervalEndedAt`（签名观测截止点），构造上述 typed manifest，逐项解析全部引用并验证 JCS digest 与 parent/reference 图，预计算四个 Envelope，签署覆盖完整 manifest 的 attestation，再在同一 registry transaction 原子写入四个 Envelope 和认证记录；commit 成功后才按 `after_atomic_verification_artifact_commit` 释放 barrier。三个 write sensors 与 environment observer 在截止点后继续保持 armed；若签名后到 commit 前出现任何写入、进程/窗口或焦点等 disqualifying event，服务必须中止私有 write set、丢弃签名并重做。只有无事件时 `postCutoffDisqualifyingEventCount=0`，且 attestation 固定 `abort_private_write_set_on_any_audit_or_environment_event`；在任何时刻都不得让缺少 attestation 的最终结果对调用方可见。barrier 期间任何写入尝试（即使被阻止或随后回滚）都中止本次 fully_verified，`blockedWriteAttemptCount` 必须为 0。

**完整只读审计。** `AnkiProfileStateSnapshotArtifactPayloadV1` 的 canonical decimal 只允许 `0` 或 `-?[1-9][0-9]*`，禁止加号、前导零和超出 Anki 字段域；cards 与 revlog 行分别按有符号数值 id 升序排序且 ID 唯一，JCS 数组字节同时决定 Blob SHA 和 rowsDigest。before/after 属于同 run/boundary/profile/collection 的 entire_collection、同一 phase，并由受信 SQLite read snapshot 采集。

`AnkiWriteAuditArtifactPayloadV1.method` 固定为 `multi-sensor-cross-process-write-audit-v1`，connection-local hook 只能是补充，不能单独成为零写证明。每个 phase 必须同时有三份 `AnkiWriteAuditSensorCoverageV1`：trusted add-on 对自身所有 SQLite connections 的 authorizer/change-hook；Card Service 对 collection DB/WAL/SHM 的跨进程 storage journal；对 `collection.media` 树的跨进程 storage journal。Windows M3 必须使用带稳定文件 ID 和不可回滚 cursor 的 ETW/USN/等价受信日志；仅 `ReadDirectoryChangesW` 且可能静默溢出不够。非 NTFS、日志不可用、cursor 回退、journal reset/overflow 或权限不足时 runtime verifier 为 unavailable，不能降级成空事件通过。

每个 sensor signed payload 绑定同 run/boundary/phase、精确 resource refs 与 initial identity/state、implementation、interval 和 baseline/terminal cursor，并由当前 service key 使用 `study.anki.write-audit-sensor.v1` 域签署；三个 interval 都必须覆盖外层 audit interval，`coverageGapCount=0`、`overflowOrResetCount=0`。monitored resources 集合至少包含 collection DB、当前/可能创建的 WAL/SHM 和 media tree；缺失文件用受认证 absent-state digest 表示，随后 create 也必须产生事件。外部 DB/WAL/SHM 任一写事件即归 `other_collection` 并失败，无需猜字段；add-on 内部事件再细分 rating/scheduling/review_history/sync/note_or_template/deck_or_model，media journal 归 media_file。

各 sensor 原始记录先按 observedAt、固定 sensor 次序、OS journal identity 排序，再由 Service 分配从 0 连续的 `AnkiWriteEventV1.sequence`；changedColumns NFC 规范化、UTF-8 排序且唯一，eventsDigest 从完整 JCS 重算。八个计数由 events 重算并全部为 0。target audit 在 environment baseline 与 source snapshot/copy 前开始，连续覆盖复制准备、before data/profile snapshot、target preview、after snapshot、final reverify与 read-barrier 观测截止点；isolated audit 覆盖隔离副本首次打开、全部 restart observations 和 after snapshot。`coveredObservationEvidenceDigests` 等于该 phase 完整 evidence 集。ProfileReadOnlyEvidence 的快照、audit 与冗余计数必须完全匹配；即使另一进程写入后恢复原字节，storage journal 事件仍使核验失败。
**进程、窗口与环境身份。** `ProcessLaunchContractV1.contractDigest` 省略自身后计算，绑定 run/boundary、role、isolated profile/collection/root、copy manifest、exe、argv template、opaque argument bindings、sandbox 和父 service；role=runtime_verifier 时 proof signer key/epoch/binding digest 必须等于 RuntimeVerifierBinding，role=isolated_anki 时三个 signer 字段必须为 null。`LocalProcessIdentityManifestV1` 的 PID 是安全整数、creation time 为 UTC，exe/signer/SID/parent/observer 从受信 OS API 采集；`runtime_verifier` 与 `isolated_anki` 必须有 launch contract ref/digest。`VerifierLaunchAttestationV1` 按统一 Ed25519 规则签署并与 process identity、launch contract、copy/root 完全相等，禁止只凭进程名或窗口标题认定身份。

signed run 绑定 Card Service 主进程；其余任何能代表本 run 操作窗口或焦点的 Card Service child/proxy、runtime verifier 与 isolated Anki 都必须由同一受信 OS Job Object 管理；Job 固定 `kill_on_close_no_breakaway`，禁止 silent breakaway，并各自产生 service-signed `RunOwnedProcessLaunchAttestationV1`。`LocalProcessIdentityManifestV1.role` 必须与 lifecycle actor role 相等，因而 Service main/child、verifier、isolated Anki 都有合法 typed identity；PID 复用由 creation time + identityDigest 区分。

`RunOwnedProcessLifecycleLedgerArtifactPayloadV1` 不是 cutoff 活跃集合，而是整个 observation interval 的 append-only 历史账本。actors 的第一项必须是 signed run 中的 service main，后续 entries 按 role、process creation time、identityDigest 排序且唯一；actors 恰好等于所有 `joined` 事件的 process 集。lifecycleEvents sequence 从 0 连续、时间非递减；main 必须在 sequence 0 joined，每个 actor 恰好一次 joined、至多一次更晚的 exited，未 joined 不得 exited，退出后不得以同 identity 再加入。主进程使用 signed-run registration，其余全部使用同 run/boundary/job 的 launch attestation。`activeAtCutoffProcessIdentityDigests` 按 identityDigest 排序且唯一，必须恰好等于“已 joined 且在 observationCutoffAt 前未 exited”的 actors，并与受信 OS 在 cutoff 读取的 Job membership 及 `activeAtCutoffJobMembershipSnapshotDigest` 相等；因此 restart 前已退出的 verifier/isolated-Anki 仍保留历史身份，但不伪装成 cutoff active。

`observationIntervalStartedAt` 必须不晚于 environment before baseline；`observationCutoffAt` 必须逐字节等于 environment trace.intervalEndedAt、两相位审计的最终覆盖截止点与 read-barrier `intervalEndedAt`，所有 lifecycle event 都落在该闭区间。`lifecycleDigest = SHA-256(JCS({ actors, lifecycleEvents, activeAtCutoffProcessIdentityDigests, activeAtCutoffJobMembershipSnapshotDigest }))`。缺少历史进程、额外未注册代理、事件断序、Job membership 不可证明、parent/identity/attestation 不一致均使 runtime verifier unavailable。ledger 由当前 service key 在 `study.anki.run-owned-process-lifecycle.v1` 域签署；outer `ledgerDigest` 覆盖 signed payload/signature。environment trace、RuntimeEvidence 与 final runtime inputs manifest 必须引用同一 ledger。

trusted add-on 运行在既有用户 Anki 进程内，不能把宿主进程本身粗暴标为 run-owned。每次 add-on 发起 raise/activate/set-foreground 或任何其他可能改变前台窗口的动作都必须先产生 `TrustedAddonFocusActionAttestationV1`：actionSequence 从 0 连续、from/to 与实际 focus event 相等，且 `0 <= focusEvent.observedAt - issuedAt <= 250ms`；同一 event 必须恰好匹配一条尚未消费的 attestation，零条或多条都不可归因。签名使用 RuntimeVerifierBinding 中 `(keyId,keyEpoch)` 精确解析的公钥和 `study.anki.addon-focus-action.v1` 域。observer 必须把它关联为 `resolved_trusted_addon_action`；发现动作但没有 attestation、attestation 没有事件、同一 attestation 重用或时间/host process/window 不一致都 fail closed。

`AnkiWindowIdentityPreimageV1.osWindowHandleDecimal` 使用 canonical decimal。原始 class/title 不落盘：`windowClassHmacSha256 = HMAC-SHA256(serviceWindowKey, UTF8("study.anki.window-class.v1") || 0x00 || UTF8(NFC(rawClass)))`，title 使用独立域 `study.anki.window-title.v1`；`windowIdentityDigest = SHA-256(JCS(preimage))`。process arrays 按 identityDigest、window arrays 按 owning process/window identity 排序并去重，foreground 只能为 null 或集合成员。environment trace 在 source snapshot/copy 前启动，在 after snapshot 与 final data capture 后形成观测截止点，sequence 从 0 连续；预备事件由受信 observer 按 provisional runId/boundary 缓冲，signed run 形成后才可封装 Artifact。process_closed/restarted/window_closed 的 target 与 initiator 均必填；focus_changed 必须携 from/to foreground（允许 null）与 `AnkiFocusChangeAttributionV1`。每次归因必须是受信 OS 证明的非 run action、signed run-owned process lifecycle ledger 中在事件时刻处于 joined-not-exited 区间的成员，或 verifier-key 签名且与 host process/from/to 一致的 trusted-add-on focus action。判别顺序固定：initiator 在 focusEvent.observedAt 命中 ledger 的有效生命周期区间时只能是 `resolved_run_owned_process`；否则若时间窗口内有未消费且 from/to 相等的 add-on attestation，只能是 `resolved_trusted_addon_action`；仅两者都不命中且 attribution evidence 明确证明外部/用户动作时才可为 `resolved_non_run_action`。若 run-owned actor 通过 shell、accessibility service、窗口管理器或其他 OS broker 间接请求焦点变化，authenticated causal provenance 必须追溯到原 run actor 并按 `resolved_run_owned_process` 处理；无法追溯不得当成 non-run。无法区分用户动作、外部动作、Service 主进程/后代/代理动作或 add-on 动作时，整份 runtime evidence unavailable。

`focusStealEventsObserved` 的唯一 predicate 是：`from` 或 `to` 任一属于 before baseline 的既有用户 Anki window，二者不同，且 attribution 为 `resolved_run_owned_process` 或 `resolved_trusted_addon_action`；按 typed events 重算必须为 0。该对称规则明确把 `null/其他应用 → 用户 Anki`、`用户 Anki → null/其他应用`、Service 主进程、所有 Job Object 后代/代理和 add-on 的所有 focus-affecting 动作都纳入，不能只检查“离开 Anki”的单向事件。前后既有 process/window 集合相等，关闭/重启计数也必须为 0。

**受信复制与真正的隔离重启。** `AnkiCollectionSourceSnapshot` 的目标 profile/collection 必须等于 ImportPlan，并且 `preRunStateSnapshotRef/digest` 只能解析为同 provisional runId/boundary 的 `PreRunAnkiSourceStateSnapshotArtifactPayloadV1`；它再绑定刚通过的 R8a、collection read snapshot、CardIdentitySet 与 media manifest。SourceSnapshot 同时绑定 collection Blob、required media archive 和权威 inventory；敏感副本只在本机 ACL/加密的短期 store 中存在，绝不进入 MCP 或模型。`IsolatedCopySubjectV1.subjectDigest = SHA-256(JCS(subject))`。`TrustedCopierSignedPayloadV1.signedPayloadDigest = SHA-256(JCS(signedPayload))`，attestation 使用 `study.anki.trusted-copy-attestation.v1` 域、policy 中精确 copier key/epoch/revocation snapshot 验签；`attestationDigest` 省略自身后覆盖 signature，所以没有循环。copy manifest 的 subject/digest/attestation 必须完全相等，`manifestDigest` 省略自身后计算。

`copyLineageDigest = SHA-256(JCS({ sourceSnapshotRef, sourceSnapshotDigest, isolatedCopyManifestRef, isolatedCopyManifestDigest, trustedCopierAttestationRef, trustedCopierAttestationDigest, runtimeIsolationPolicyDigest }))`。source identity 等于 ImportPlan 目标；isolated profile/collection identity 等于 subject 且都不同于目标；collection Blob 与媒体 inventory 必须等于 copy subject。隔离重启必须同时证明 helper `runtime_verifier` 和真实 `isolated_anki` 的 before/after process identity、launch contract 与服务签名 attestation；两对都必须是不同进程实例，但所有 launch contract 都绑定同 run/copy/profile/root/sandbox。Restart proof 引用的 isolated Anki pair 必须逐字节等于 runtime evidence 顶层 pair。只允许重启这两个隔离角色，绝不关闭、重启或抢焦点到既有用户 Anki。

`RuntimeVerifierBindingV1` 与 `RuntimeVerifierIsolationPolicyV1` 都是 ImportPlan 批准前输入：binding digest 是完整 JCS，policy digest 省略自身。binding 冻结 proof authentication、producer key/epoch 和 root-signed revocation snapshot；policy 冻结所有子合同、service/copier key/epoch/snapshot、三传感器跨进程 write audit、最终 read barrier 和“只重启隔离 Anki + verifier”。run 与 barrier 的三项 trustSnapshotBindings 必须分别等于 binding/policy 并通过当前 anti-rollback floor。`AnkiRuntimeEvidenceArtifactPayload.evidenceDigest` 省略自身后计算；sample、actual media、data snapshots、final evidence/reverification、target/isolated readonly evidence、两类 process/window launch proof、write sensor coverages 与 user environment 必须属于同一 signed run。实现、协议、producer trust、snapshot sequence、复制策略、identity/media inventory、样本或 expected observation 任一变化，都使旧 ImportApproval 与旧 runtime evidence 失效。
**状态推导。** 若某个必需 observation 具有结构正确、同 run、可信的 failure proof，则形成 `runtime_failed`，数据状态保持 passed；合同、tuple、proof predicate、签名、run binding、CardIdentitySet、media、snapshot/audit、typed final-runtime manifest、final reverification、copy/run-owned-process/window/environment 或 producer trust/public-key resolution 任一结构/安全不一致，则返回 `ANKI_VERIFY_FAILED`，不得伪装成业务播放失败。只有全部 observations passed、target 与 isolated 写审计为零、最终 11 项 R8a 在 read barrier 中通过、四个最终 Artifact 原子提交后，sample 才形成 `sample_passed`、full 才形成 `full_passed` 与 `fully_verified`。宿主无法取得可信 runtime 证据时状态只能是 `not_assessed`；不得制造假失败或假通过。`AnkiVerificationArtifactPayload.verificationDigest` 省略自身后计算；runtime_failed/fully_verified 时 run/boundary/final reverification 字段必须全部存在并匹配，data_verified 可缺省这些 runtime-only 字段。

AnkiRecoveryDecisionV1 是写边界恢复的唯一判别结果。not_written 只能为仍有效的原 ImportPlan 派生新的、当前 session 绑定的 recoveryImportIntentId，并重新取得一次性确认；written_identity_matched 只能创建 verification-only successor，禁止再次写入；write_boundary_ambiguous 必须停在 conflict/interrupted，等待用户解决。旧 audience 的批准、已消费 ImportApproval 和原 importIntentId 都只保留审计用途，不能转移或再次消费。

PackageArtifact 与 ImportPlan 必须分别保存 templateFamily、templateSchemaVersion、noteModelId 和 compatibilityContractVersion，任何一轴都不能从另一轴或名称前缀推断。planDigest 的 preimage 是省略 planDigest 字段后的 ImportPlanPayloadV1 JCS；不得形成自引用。ankiConnectCredentialBindingDigest 是 Card Service 用本机服务密钥生成的 HMAC/等价绑定，不是对低熵 key 的裸哈希，也不能用于回读 key。

M6 才实现但现在冻结语义：

~~~ts
type PracticeTask = {
  practiceTaskId: string;
  objectiveRef: EntityRef;
  scenario: string;
  requiredActions: string[];
  scoringRubric: string[];
  evidenceRefs: ArtifactRef[];
};

type ReferenceNote = {
  referenceNoteId: string;
  topic: string;
  content: string;
  evidenceRefs: ArtifactRef[];
  reasonNotCard: string;
};
~~~

所有以上 payload 都由 ArtifactEnvelope 承载；MCP 只提交 opaque handle，Service 从项目认证注册表解析。
## 15. Issue

ToolErrorCode 与 TaskStage 从 [MCP 工具参考](MCP_TOOL_REFERENCE.md) 的共享版本化错误 schema 导入；实现不得在两个包中维护不同副本。

~~~ts
type StudyIssueCode =
  | ToolErrorCode
  | "SOURCE_OMISSION"
  | "LOW_CONFIDENCE"
  | "REVIEW_REQUIRED"
  | "DUPLICATE_CANDIDATE"
  | "RUNTIME_EXPERIENCE_NOT_ASSESSED"
  | "COST_UNKNOWN";

type StudyIssue = {
  issueId: string;
  code: StudyIssueCode;
  severity: "info" | "warning" | "blocking";
  stage: TaskStage;
  title: string;
  detail: string;
  affectedRefs: ArtifactRef[];
  recoverability: "automatic" | "user_action" | "retry" | "not_recoverable";
  suggestedActionId?: WorkflowActionId;
  suggestedActionText?: string;
  diagnosticRef?: string;
};
~~~

title、detail 和 suggestedActionText 都属于 UntrustedData；它们不能产生工具调用或授权。只有 Service 按 schema 签发的 suggestedActionId 可进入控制面。上述文本均不能包含密钥、Cookie、OAuth token 或未经裁剪的本地绝对路径。

## 15.1 Legacy payload 净化

CURRENT 的 GenerateRequest/Project 可能携带 api_config、tts_config 和 api_key 等运行时配置；桌面端目前在 applyGeneratedProject 后执行秘密剥离。Headless Card Service 必须把这一行为前移到“任何 Artifact/任务/检查点持久化之前”。

~~~ts
type SanitizedLegacyResourceSlotV1 =
  | {
      slotId: string;
      jsonPointer: string;
      kind: "source_file" | "source_directory" | "output_directory" | "media_file";
      internalResourceBindingId: string;
      resourceRevisionDigest: Sha256;
    }
  | {
      slotId: string;
      jsonPointer: string;
      kind: "source_network";
      internalResourceBindingId: string;
      resourceRevisionDigest: Sha256;
      canonicalRequestDigest: Sha256;
      displayOrigin: string;
      queryRedactionDigest: Sha256;
    };

type SanitizedLegacyProjectPayloadV1 = {
  legacyProjectSchema: string;
  legacyProjectSchemaVersion: number;
  projectionSchema: "legacy.project.nonsecret.v1";
  projectionSchemaSha256: Sha256;
  projectProjection: BlobRef;
  projectProjectionSha256: Sha256;
  resourceSlots: SanitizedLegacyResourceSlotV1[];
  sourceAssetRefs: ArtifactRef[];
  mediaLedgerRef: ArtifactRef;
  reliabilityManifestRef?: ArtifactRef;
  learningPointInventoryRef?: ArtifactRef;
  generationDiagnosticsRef?: ArtifactRef;
  serviceBindings: {
    capability: "model" | "tts";
    profileRef: string;
    configurationFingerprint: Sha256;
  }[];
};

type SanitizedLegacyPayloadV1 = {
  sanitizerSchema: "study.legacy.sanitized";
  sanitizerVersion: 1;
  originalSchema: string;
  removedFieldPaths: string[];
  replacedResourcePaths: string[];
  payload: SanitizedLegacyProjectPayloadV1;
};
~~~

最低规则：

- SanitizedLegacyPayloadV1 是 Card Service 内部兼容产物；study.get_artifact 只可返回 schema、hash、净化统计和审计引用，不能返回 projectProjection blob、internalResourceBindingId 或重建后的 Worker payload。
- 递归拒绝 api_key、tts_api_key、password、secret、token、cookie、authorization、client_secret 等字段，而不是只删除已知顶层键。
- provider/model/voice 等非秘密配置改为逐 capability 的 serviceBindings；model 与 TTS 各自绑定 profileRef + configurationFingerprint，不能压成一个共享指纹。
- 输入/输出绝对路径改为 fileResourceRef/outputResourceRef；所有 source/final/redirect URL 递归替换为 source_network slot。诊断只保存脱敏 displayName/displayOrigin、canonical request/query digest，不保存 raw URL、userinfo、fragment、signed query 或认证 header。
- sanitizer 后再次执行 forbidden-key scan 和 secret canary scan。
- 不可证明安全的 legacy payload 拒绝持久化；不能“先保存再清理”。
- payload hash 在净化后计算，并记录 sanitizer 版本。
- projectProjection 是通过固定 JSON Schema（additionalProperties=false）验证后的 canonical JSON blob；该 schema 必须无损保留当前 export 所需的所有非秘密 Project 结构，包括 segments/cards、reliability_manifest、learning_point_inventory、生成诊断、卡片启用状态和媒体对账字段，而不是压平成 cards 列表。
- 路径和网络位置改写为 resourceSlots；raw source/final/redirect URL 与 api_config/tts_config 等秘密配置完全从 projection 删除。M0 必须用本地与 signed-URL Project/export fixture 证明“业务非秘密字段无损，绝对路径、raw URL/query 与秘密字段为零”。
- 持久化类型只能是 SanitizedLegacyPayloadV1，不能用泛型 T 让原始 Project 在类型上继续合法。
- M0/M1 用包含嵌套 api_config/tts_config 的 fixture 做正负合同测试。

CURRENT M2 已实现内部 `LegacyProjectProjectionPublisher`：顶层 Project allowlist 与投影 envelope 使用封闭字段集，嵌套 JSON 仍按原 Project 结构保留，但受递归 secret/config/resource 扫描、节点/深度/字节/安全整数上限约束。它在任一 Blob/Artifact 写入前完成净化，并把同项目 SourceAsset、MediaLedger 及可选 reliability/inventory/diagnostics refs 绑定为认证父链；内部 resolve 重新验证 canonical Blob、schema digest、slot pointer 和父引用，public summary 只返回计数/布尔状态。

这只是 sanitize/publish 合同，不是 15.2 的运行时重建。生产 ResourceBinding 签发、全部嵌套结构的逐类型 closed schema、受权 rehydration、跨 Registry 原子事务、孤儿 Blob 保留清理和公共 MCP 接线仍是未完成门槛；因此 raw Project 仍不能成为公共工具输入或输出。

## 15.2 Legacy 运行时重建

sanitized Artifact 不能直接传给仍依赖 api_config/tts_config 和本地路径的现有 Worker。Card Service 使用显式、仅内存适配器：

~~~ts
type RuntimeRehydrationContext = {
  projectRef: ArtifactRef;
  serviceBindings: {
    capability: "model" | "tts";
    profileRef: string;
    configurationFingerprint: Sha256;
    credentialRevision: number;
  }[];
  sourceAuthorizationIds: string[];
  outputAuthorizationId?: string;
  modelTtsBrokerBindingDigest: Sha256;
  taskId: TaskId;
};

type AuthorizedTextLocatorV1 = {
  disclosureEntryId: string;
  artifactRef: ArtifactRef;
  entityId: string;
  field:
    | "source_excerpt"
    | "candidate_evidence"
    | "learning_objective"
    | "card_plan_front"
    | "card_plan_back"
    | "tts_text";
  normalizedTextSha256: Sha256;
  maxCharacters: number;
};

type BrokerLogicalCallV1 = {
  phase: "profile_validation" | "discovery" | "planning" | "generation" | "tts";
  entityId: string;
  operation: "model_inference" | "tts_synthesis";
  ordinal: number;
};

type BrokerRequestContextV1 = {
  schema: "study.broker.request-context";
  schemaVersion: 1;
  taskId: TaskId;
  workUnitId: string;
  logicalCall: BrokerLogicalCallV1;
  audienceDigest: Sha256;
  operationIntentDigest: Sha256;
  authorizationBindingDigest: Sha256;
  capability: "model" | "tts";
  profileRef: string;
  configurationFingerprint: Sha256;
  credentialRevision: number;
  disclosureEntryIds: string[];
  disclosureManifestDigest: Sha256;
  egressManifestDigest: Sha256;
  costBudgetDigest: Sha256;
  requestIdempotencyKey: string;
  requestPayloadDigest: Sha256;
};

type BrokerModelRequestV1 = {
  kind: "model";
  context: BrokerRequestContextV1 & { capability: "model" };
  templateId: string;
  templateVersion: string;
  inputLocators: AuthorizedTextLocatorV1[];
  outputSchemaId: string;
  outputSchemaVersion: string;
  maxInputTokens: number;
  maxOutputTokens: number;
};

type BrokerTtsRequestV1 = {
  kind: "tts";
  context: BrokerRequestContextV1 & { capability: "tts" };
  textLocator: AuthorizedTextLocatorV1 & { field: "tts_text" };
  voiceRef: string;
  language: string;
  output: {
    container: "mp3" | "ogg" | "wav";
    sampleRateHz: number;
    bitrateKbps?: number;
  };
  maxCharacters: number;
  maxAudioSeconds: number;
};

type BrokerUsageV1 = {
  requestBytes: number;
  inputTokens: number;
  outputTokens: number;
  ttsCharacters: number;
  ttsAudioSeconds: number;
  remoteCalls: number;
  minorUnits: number | null;
};

type BrokerReservationLedgerV1 = {
  schema: "study.broker.reservation";
  schemaVersion: 1;
  ledgerId: string;
  requestIdempotencyKey: string;
  requestPayloadDigest: Sha256;
  audienceDigest: Sha256;
  operationIntentDigest: Sha256;
  authorizationBindingDigest: Sha256;
  profileBindingDigest: Sha256;
  disclosureEntryIds: string[];
  disclosureManifestDigest: Sha256;
  costBudgetDigest: Sha256;
  state:
    | "reserved"
    | "sent"
    | "settled"
    | "possible_incurred"
    | "released_before_send"
    | "blocked";
  reservedMaximum: BrokerUsageV1;
  settledActual?: BrokerUsageV1;
  sequence: number;
  createdAt: Timestamp;
  reservedAt?: Timestamp;
  sentAt?: Timestamp;
  settledAt?: Timestamp;
  providerEvidenceDigest?: Sha256;
};
~~~

Broker 请求先把 context.requestPayloadDigest 与 context.requestIdempotencyKey 都设为缺省，对其余完整请求做 JCS 并计算 requestPayloadDigest。logicalCall.ordinal 必须是非负安全整数；phase/operation 使用固定 enum，entityId 先 NFC 规范化。随后 Card Service 构造 { schema: "study.broker.idempotency", schemaVersion: 1, taskId, workUnitId, logicalCall, requestPayloadDigest }，对其 JCS UTF-8 字节执行 HMAC-SHA-256，并以 unpadded base64url 编码得到 requestIdempotencyKey。context.disclosureEntryIds 按 NFC 字符串的 UTF-8 字节序排序并拒绝重复。每个 input locator 先验证 ArtifactRef 全部字段，再令 artifactRefSortKey = JCS(artifactRef) 的 UTF-8 字节；inputLocators 按 disclosureEntryId 的 NFC UTF-8、artifactRefSortKey 原始字节、entityId 的 NFC UTF-8、field 固定 enum 的 UTF-8 组成的四元组依次比较，并以同一四元组判定重复。每个 locator 必须引用已选择 entry，所有已选择 entry 必须具有同一 target，且与 context capability/profile/egress 完全一致；允许一个模型请求组合该同一目标下的多个数据类别，但禁止跨 target 拼接。两个摘要/幂等字段都由 Service 写回，Worker 不能自选；同一 key 携带不同 payload digest 必须拒绝，因此不存在摘要/幂等键循环。

profileBindingDigest = SHA-256(JCS({ capability, profileRef, configurationFingerprint, credentialRevision, egressManifestDigest }))。每次调用在一个原子事务中复核 audience、OperationIntent、AuthorizationBinding、profile binding、逐目标 DisclosureEntry、EgressManifest、撤销 epoch 和剩余 CostBudget；失败只写 blocked，成功才写 reserved。状态迁移仅允许 blocked 终止，reserved → sent 或 released_before_send，sent → settled 或 possible_incurred；其他迁移全部拒绝。发送后未取得权威 usage 的崩溃转 possible_incurred，按 reservedMaximum 扣留预算并禁止盲目重发。settle 只能单调写一次，actual usage 各轴不得超过 reservation；服务商不返回计量时以 reservedMaximum 结算。TTS 正文必须由 textLocator 在 Service 内重新解析并核对 digest，Worker 不能提交任意原始文本替代权威字段。

流程：

1. 从认证项目注册表加载 sanitized payload。
2. 逐 capability 校验当前 task/project revision、profileRef、configurationFingerprint、credentialRevision 和内部 authorization ID；model 与 TTS 任一绑定 stale 都不能复用另一项的验证。
3. 真实路径只在受限执行适配器中解析；SecretRef 只由 Card Service 的 model/TTS broker 解析。Legacy Worker 不获得 provider secret、OAuth/Cookie、真实远程 Base URL或直接公网能力。
4. 校验 projectionSchemaSha256 和 projectProjectionSha256，按 resourceSlots 恢复受控文件句柄。legacy api_config/tts_config 被替换为 task-owned 本地 broker transport descriptor（认证 named pipe/等价 IPC），不是 provider 凭据；descriptor 绑定 task、audience、OperationIntent、profile 和预算，不能跨进程树/任务复用。
5. Worker 只能发送结构化 BrokerModelRequest/BrokerTtsRequest：模板/操作 ID、授权 Artifact/locator refs、输出 schema 或精确 TTS text digest。Card Service 重建最终 provider request，逐项验证 DisclosureManifest；不提供 raw HTTP、任意 URL/header 或任意 prompt 透传。
6. 每次上游调用前，broker 在同一原子事务校验撤销状态并 reserve 最大请求字节/token、TTS 字符/秒数、调用数和成本预算；收到 usage/响应后 settle 实际值。幂等 request key 防并发双发；crash-after-send 记 possible/incurred，重试不能把未知费用当作 0，也不能越过剩余硬上限。
7. Worker/job 的网络策略只允许 task-owned broker IPC；尝试直连公网、绕过 broker、扩大 source refs 或超过 reserve 均 fail closed。Worker 结束后关闭 IPC、清零短期缓冲，只持久化净化结果和计量审计。
8. export 通过同一适配器恢复受控路径，但不注入 model/TTS 凭据；MCP 调用方不能提交 api_config/tts_config。

用 nested api_config/tts_config、provider secret canary、绕过/超量/并发、broker 撤销、crash-after-send、retry 和进程崩溃 fixture 验证：Worker 不持有真实秘密、不直连公网，且每次远程副作用都有原子 reserve/settle 审计。
## 16. 与当前模型的迁移

| PROPOSED | CURRENT | 首次适配 |
|---|---|---|
| SourceAsset | GenerateRequest 中 source 字段 | 只支持当前 local/url/document 子集 |
| LanguageObjective | LearningPoint | 无损保留 exact_span、offset、时间和 ID |
| CardPlan | 选择 ID + card_types + 偏好 | 受限映射，不支持组合返回 blocker |
| SanitizedLegacyProjectArtifact | Project 经 Service sanitizer | 移除 api_config/tts_config 中的秘密并把路径改为受控引用 |
| PackageArtifact | ExportResult | 保留 media ledger、哈希与审计 |
| VerificationArtifact | AnkiVerifyResult | 保留失败检查和证据 |

首阶段禁止把 legacy verified 解释为事实正确。它证明当前结构、来源映射、媒体和导入一致性。

## 17. 合同不变量

- 正式候选证据锚覆盖率 100%。
- 已验证事实卡至少一个可重放支持证据。
- 未解决阻塞冲突不能进入普通事实卡。
- exact duplicate 不生成两个确定性 CardId。
- 用户锁定字段不能被 Agent 覆盖。
- stale objective 不能进入新生成任务。
- partial source 必须在候选和交付中可见。
- 模型原始输出不是 Artifact，只有通过 schema、门禁和保存后才是。
- 所有导入核验都引用唯一 APKG 哈希。
- `data_verified` 绝不推导真实渲染/播放/复习；只有固定 R8b 合同的全部证据才能形成 `fully_verified`。
- 每个受信 Ed25519 签名都从当前 root-signed snapshot 精确解析 `(keyId,keyEpoch,publicKeySha256)`，调用方不能替换公钥。
- 最终 read barrier、FinalReverification 与 RuntimeEvidence 必须逐字节复用同一 Typed FinalRuntimeEvidenceInputsManifest。
- 任一由本 run 触发且触及既有用户 Anki 的 focus change 都失败；谓词必须对称覆盖 from/to、Service 主进程/后代/代理和 add-on 动作。

