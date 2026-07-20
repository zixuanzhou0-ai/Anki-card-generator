# 可追溯矩阵

> 基线日期：2026-07-20

## CURRENT 可追溯增量（2026-07-20）

| 要求 | 当前工具/实现 | 当前证明 | 剩余边界 |
|---|---|---|---|
| PR-201/PR-202 候选发现与可解释筛选 | `system.authorize_candidate_discovery`、`study.start_discovery`、`study.get_task`、candidate read tools | 固定 Hermes 授权、Service-owned scope/budget、异步任务、认证 Discovery/Candidate/evidence | 多来源适配、质量基准与更细恢复 |
| PR-301 / PR-404 项目状态找回 | `study.list_projects`、`study.get_project` | 认证分页 cursor、跨同宿主 session 续页、跨 scope/篡改/stale 拒绝、Workflow/Task 一致性、opaque latest Artifact handles；正式 Python `tests` 全集 1595 passed、1 skipped | 通用长任务恢复仍仅开放候选发现 |
| PR-207 Learning Contract 可版本化更新 | `study.update_learning_contract` + ProjectRegistry | 九类封闭语义操作、双 revision CAS、精确幂等、字段级失效矩阵、失效后 current Artifact 指针裁剪、opaque preserved handles | 跨 Project/Artifact/Task 的单一数据库事务仍未实现 |
| PR-305 / SR-008 明确且幂等的 Anki 导入 | ImportPlan → `anki.request_import_confirmation` → `anki.import_and_verify` | import intent 精确绑定、一次批准消费、相同 intent 不重复导入、写边界状态机 | 撤销管理和更完整恢复 UX |
| PR-404 / PR-501 当前外部能力与恢复 | HermesProxyManager + discovery preflight + `study.resume_task` | 8645 固定代理、当前 OAuth/health、首次/异步/恢复三条预检、上游故障→可重试 `MODEL_STALE`；Computer Use 真实 picker/授权 | xAI 公网路由恢复后的完整正例 |
| PR-305 / SR-012 Windows AnkiConnect 部署 | launcher `--anki-connect-url` + literal-loopback normalizer | 8765 默认、8785 隔离目标、非 loopback/hostname/query/userinfo 拒绝、Worker 与 probe 同端口 | 正式安装器端口发现与安装版复测 |
| PR-306 / RR-801 数据核验不冒充运行时核验 | `anki.import_and_verify` 的 receipt + data verification | 成功为 `anki_data_verified`，失败为 `imported_unverified` 或保持 `apkg_ready` | RR-802 的渲染/播放/reviewer/restart verifier 尚未实现 |
| PR-506 正式插件可安装性 | 被动 manifest/Skill + 开发态可信 stdio runtime | validator 与开发态测试 | 正式发布者签名、MCP 声明、安装验收、App UI |

后续历史表格中的 “PROPOSED/下一阶段/尚未开放” 只在本节没有 CURRENT 覆盖时有效。不得把既有 M0 Computer Use 证据当作通用插件 runtime verifier，也不得把开发态 runtime 当作已签名发布物。

> 状态：CURRENT M0/M1 与 M2 内部切片追踪 + PROPOSED 后续要求
> 日期：2026-07-19
> 目标：每个重要承诺都能追到领域契约、工具、测试和里程碑。

## 1. 产品要求

| ID | 要求 | 领域/架构 | 工具/界面 | 验证 | 里程碑 |
|---|---|---|---|---|---|
| PR-001 | 注册附件、文件、目录、URL | InputRef/SourceAsset + LocalResourceGrant | register_inputs | grant/来源 adapter corpus | M2 CURRENT 本地文件/目录；M3/M5 其他来源 |
| PR-002 | 稳定身份/修订 | SourceIdentity/ArtifactEnvelope | start_source_inspection | hash/revision/TOCTOU | M2 |
| PR-003 | 显示完整性 | CompletenessRecord | Inline/Fullscreen | partial/unknown cases | M2/M4 |
| PR-004 | 多源关系 | UnitRelation/ConflictSet | candidate detail | duplicate/conflict benchmark | M6 |
| PR-005 | 来源分级 | Tier A/B/C | source status | adapter release gate | M5/M7 |
| PR-101 | 候选有证据 | EvidenceAnchor | get_candidate/preview_evidence | replay 100% | M3/M6 |
| PR-102 | 未来行为明确 | LearningObjective | candidate view | route/scoring rubric | M3/M6 |
| PR-103 | 门禁先于排序 | GateResult | list_candidates | hard gate tests | M3 |
| PR-104 | 组合而非 Top-N | PortfolioSelection | set_selection | coverage/redundancy | M3/M6 |
| PR-105 | 用户语义编辑 | CandidateEditOperation/CardPlanEditOperation | edit_candidate/edit_card_plan | disjoint-schema/revision/idempotency | M6 |
| PR-106 | 锁定不覆盖 | UserLock | edit tools | locked overwrite = 0 | M2/M6 |
| PR-201 | 单一评分边界 | LearningObjective/CardPlan | plan/validate | scoreability rubric | M3/M6 |
| PR-202 | 正面不泄露 | CardPlan.validation | plan preview | leakage test | M3 |
| PR-203 | 答案有证据 | EvidenceAnchor | validate plans | unsupported facts = 0 | M6 |
| PR-204 | 支持非卡片任务 | PracticeTask/ReferenceNote | future UI | route suitability | M6 |
| PR-205 | 批量可恢复 | StudyTask/work units | get/cancel/resume | fault injection | M2/M3 |
| PR-206 | 模型 HTML 不直入模板 | safe renderer | generate | injection corpus | M0/M3 |
| PR-207 | Learning Contract 可版本化更新且正确失效 | LearningContractChangeSet + invalidation matrix | study.update_learning_contract | semantic-op/idempotency/revision/stale tests | M2/M3 |
| PR-301 | 产物状态严格区分 | ArtifactStage | WorkRail | state matrix | M3/M4 |
| PR-302 | 可靠性阻塞 | ReliabilityManifest | validate/export | fail-closed | M0/M3 |
| PR-303 | 部分成功自动排除 | SelectedPointOutcome | delivery UI | 10→9 scenario | M3/M4 |
| PR-304 | APKG 哈希/清单与原子发布 | PackageArtifact | export | 10 production variants + full package contract + partial/no-replace atomic publish | M0/M3 |
| PR-305 | Anki 明确授权 | CURRENT authenticated ImportPlan + session-bound ImportApproval ledger + trusted local confirmation；写任务仍 PROPOSED | prepare/confirm/import_and_verify | prepare 跨 audience/离线/幂等；确认覆盖 chat spoof、跨 session、篡改、过期与双消费；后续 no-confirm 写入 negative | M3 |
| PR-306 | Anki 数据与运行时核验不混淆 | authoritative identity/media + exact-key anti-rollback trust +无环 signed run + signed typed proofs/actors/focus actions + typed final-runtime manifest + barrier-bound final checks | import_and_verify/delivery UI | empty expectation + key-substitution/revoked-key/cross-run replay + actor/focus spoof + manifest omission + cross-process write/TOCTOU + 1/20/full | M0/M3 |
| PR-401 | 500ms 反馈 | StudyTaskSnapshot | 对话/tools + 条件 PiP/Inline | latency/UI tests | M3/M4 |
| PR-402 | 长任务可取消 | StudyTask | cancel_task | cancel terminal | M2/M3 |
| PR-403 | 单调进度 | TaskProgress | PiP | monotonic tests | M2 |
| PR-404 | 重启恢复且不复用旧授权 | WorkReuseDigest + successor task + StableCapabilityBinding | list_recoverable_tasks/resume_task | restart/re-auth/scope-rebase fault injection | M2/M3 |
| PR-405 | 旧结果不覆盖 | fingerprint/revision | all write tools | stale result test | M2 |
| PR-406 | 不保存秘密 | SecretRef | capability UI | canary scan | M2 |
| PR-407 | Anki 写边界恢复不重放批准 | AnkiRecoveryDecision + successor | resume_task/import_and_verify | pre-write/post-write/ambiguous crash matrix | M2/M3 |
| PR-501 | 统一能力快照 | SystemCapabilitySnapshot | system.get_capabilities | state conflict tests | M2/M3 |
| PR-502 | 每个 profile 验证绑定指纹/凭据版本 | ServiceProfileVerificationRecord | system.validate_profile | A-pass/B-fail、latest-failure、credential add/replace/delete/rollback/concurrency | M2 |
| PR-503 | 秘密走受信本地配置 | SecretRef/OS keyring | system.open_local_settings | MCP secret canary | M2/M3 |
| PR-504 | 不回读秘密 | secret_exists | system.list_profiles | tool inventory/output scan | M2 |
| PR-505 | V1 不运行时安装 | signed package policy | 无 install/repair_env 工具 | tool inventory/package tests | M3 |
| PR-506 | 宿主能力实测 | host capability snapshot | system.get_capabilities | manifest/stdio/tool/trusted-UI matrix | M3/M4 |
| PR-507 | raw URL 不进入 MCP | trusted-entry-only network grant | system.request_network_grant + trusted network window + URL-free InputRef | schema absence + ordinary/signed URL canary + persistent-state scan | CURRENT M2 |

当前 M2 内部证据：PR-002 的 ArtifactEnvelope/认证 Registry、legacy Project 非秘密 canonical projection 与确定性 Source Inspection，PR-205/402/403/404 的 StudyTask/检查点/successor，PR-207 的 Project/Contract 双 revision、语义操作、幂等与固定失效矩阵，SR-013 的 model/TTS OperationIntent/Approval/Authorization 账本内核，PR-406/502/504 的认证 SecretRef/credentialRevision、持久非秘密 Service Profile Registry 与逐 profile verification registry，以及 PR-001/SR-002/SR-003/SR-018 的 local/network resource registry 均已有服务端实现和自动化测试。本地资源链覆盖认证 resolution proof、task-bound staging receipt、有界复制、逐项 manifest、竞态/篡改复核和 Windows task SID 只读 DACL；Card Service 惰性组合单一 local grant/staging runtime。真实 picker 使用 AES-GCM 私有响应与 5 分钟精确 attestation；可信 stdio audience 进一步核对原生 launcher 直接父进程、固定可执行文件、OS 用户 SID 摘要和每进程 nonce。CURRENT 公共 surface 只在该 audience 下开放本地 source/output grant、`study.create_project`、`study.register_inputs`、`study.start_source_inspection`、`study.get_source_inspection`、`study.list_candidates`、`study.get_candidate`、`study.preview_evidence`、`study.set_selection`、`study.plan_cards`、`study.list_card_plans`、`study.edit_card_plan`、`study.validate_card_plans`、`cards.generate`、`cards.list`、`cards.export_apkg`、`study.get_task`、`study.cancel_task` 与只读 `anki.prepare_import`；检查与读取工具对文本/Markdown/代码/HTML/字幕和目录内受支持成员发布认证表示、覆盖率、支持级别与显式遗漏，结果不含正文、路径、InputRef、BlobRef、私有 receipt、proof、staging 或 Worker locator。正式 Python `tests` 全集当前为 1469 passed、1 skipped，launcher Rust 为 14 passed。内部 `candidate-gates-language-v1` 已能重放语言 span，并由服务端派生 evidence/goal/novelty/scoreability/card/conflict/review-value/security 八类门禁和 eligibility；模型不能自报 eligibility 或 scores。CandidateProposal/安全拒绝记录、GateEvaluation 与 Discovery 已可发布为单向认证 Artifact 图，证据必须回放到认证表示，eligibility 与 gate 结果不能由调用方篡改。内部双角色发现引擎进一步把高召回提案与有界上下文独立复核分成两个封闭 schema，敏感节点披露前剔除，越界 span 拒绝，复核缺失降级为 needs_review，ProposalBatch/ReviewBatch 都进入认证父图。内部 CandidateDiscoveryRuntime 进一步把当前 Inspection、合同修订、候选预算、模型配置/凭据修订、egress、OperationIntent、授权 scope/撤销 epoch 与成本预算冻结进可恢复 StudyTask；完成任务后的项目提交中断可精确重试而不重复模型调用。任务级 Service Broker 适配器进一步让 proposer/reviewer 使用同一可信短期授权但不同 workUnitId，Service 重建三类 Provider 请求、严格解析单一 JSON，并从当前 Broker 清单与精确项目/检查/预算 scope 派生非秘密授权摘要；调用方不能选择 Provider、URL、凭据或伪造授权字段。候选只读投影进一步要求当前最新 Discovery、同图 candidate membership 和 audience/session opaque handle；分页 cursor 绑定查询，证据从认证快照重放并独立复查整 node 敏感内容，公共输出不含内部 ref、BlobRef、路径或授权。CandidateSelectionRuntime 继续从同一认证图解析 opaque handles，以确定性 coverage-first 组合、硬门禁复核、Learning Contract 预算、保守 ReviewDebt 和幂等 StudyTask 发布 SelectionArtifact；selectionState 仅从当前有效选择派生，选择本身不调用模型、TTS、网络或 Anki。内部 CardPlanRuntime 又从精确当前 Selection 图发布认证 plan/set/validation 父图，只支持 `production`、`chunk_collocation`、`reading_recognition` 三条无需新增语义推断的路线，并把证据覆盖、评分边界、答案泄露、重复、冲突、模板、无媒体策略与空用户锁状态机器审计；不支持的翻译、语用/语法或媒体组合 fail closed，旧幂等结果在计划失效后不能复活。可信 MCP 现已注册 `study.plan_cards`、`study.list_card_plans`、`study.edit_card_plan` 与 `study.validate_card_plans`：规划只接收当前 selectionHandle 和封闭 RequestContext；只读工具以认证 cursor 分页并删除内部 refs、路径、授权、模型资料和 input fingerprint；Agent edit 只接受互斥的 cue/answer/feedback/media 操作，不能注入 provenance/evidence/user lock，服务保留原认证引用和锁、记录权威 taskId、发布同 identity 新 revision 并重放八项门禁。独立重验发布新 set/validation revision，支持 work unit 完成后到 project commit 前的精确恢复，且旧幂等结果不能覆盖更新 revision。当前仍是整段 discovery 工作单元检查点，宿主附件与 URL 输入生产 attestation、异步公共 discovery start/poll/cancel/resume、逐角色检查点、候选编辑、受信 CardPlan 用户锁通道、受信设置/验证任务、网络 staging、ImportApproval 撤销/恢复、Anki 写入/核验、其余公共 MCP、统一跨 Registry 事务和正式安装边界仍未完成。CURRENT APKG 路线已用认证 PackageArtifact、独立包/SQLite/模板重验、内容寻址 APKG Blob、目标同盘 `.partial` 与 no-replace 版本化发布闭合 PR-304/SR-007 的当前文本零媒体边界；83 项定向扩大回归与正式 Python `tests` 全集 1480 passed、1 skipped 已通过，但完整 M3 出口不因此提前满足。

## 2. 学习要求

| ID | 要求 | 契约 | 测试 | 指标 |
|---|---|---|---|---|
| LR-001 | 提取事件而非保存文本 | LearningObjective | scoreability rubric | 可评分通过率 |
| LR-002 | 目标驱动 | Learning Contract | expert benchmark | goal relevance |
| LR-003 | 一卡一目标 | granularity/scoringBoundary | independent score points | blocker = 0 |
| LR-004 | 路线区分 | route enum | route labels | route accuracy |
| LR-005 | 复习价值大于债务 | ReviewDebtEstimate | calibration study | gain/minute |
| LR-006 | 组合覆盖 | PortfolioSelection | top-N comparison | coverage/redundancy |
| LR-007 | 用户拥有 | UserLock/edit ops + LearningContractChangeSet | edit/recompute/invalidation tests | overwrite = 0 |
| LR-008 | 学习效果实测 | experiment protocol | A/B/C | 1/7/30 day |
| LR-009 | 复杂技能不硬制卡 | PracticeTask | suitability corpus | inappropriate card rate |
| LR-010 | 先尝试后揭示 | review template/UX | real Anki | reveal-before-attempt rate |

## 3. 安全要求

| ID | 要求 | 控制 | 工具边界 | 测试 | 里程碑 |
|---|---|---|---|---|---|
| SR-001 | 提示注入不提权 | untrusted data + internal authorization ledger | no raw actions | source/tool injection | M2/M3 |
| SR-002 | 不传原始路径 | resource handles + authenticated task staging | register_inputs | traversal/reparse/hardlink/race/receipt tamper | M2/M3 |
| SR-003 | 防 SSRF | network proxy | canonical networkResourceRef | DNS/rebind/redirect | M2/M3 |
| SR-004 | 文档资源隔离 | parser sandbox | adapter only | bomb/timeout/memory | M5 |
| SR-005 | 供应链固定 | hashes/SBOM/signature | no repair_env | PATH/package tamper | M1/M3 |
| SR-006 | 秘密不回读 | SecretRef | no load_secret | secret canary | M2 |
| SR-007 | APKG 认证注册；raw ExportResult 不作为公共信任根 | authenticated Artifact registry + PackageArtifact | import by opaque ref | forged APKG+ExportResult/replaced APKG/TOCTOU | M2/M3 |
| SR-008 | Anki 幂等 | importIntentId | import_and_verify | replay/concurrency | M3 |
| SR-009 | 媒体不越界 | manifest/hash/basename | no media_dir | conflict/traversal | M0/M3 |
| SR-010 | 日志脱敏 | field allowlist | diagnosticRef | log injection/canary | M2 |
| SR-011 | 内部授权最小权限 | InternalAuthorizationRecord | all write tools | expiry/scope/replay | M2 |
| SR-012 | 不监听 LAN | stdio/local runtime | no public port | process/network inspect | M1/M3 |
| SR-013 | 模型/TTS/成本/批量确认不可旁路 | OperationIntent + trusted approval ledger | request_operation_confirmation | mutation/replay/no-user-gesture | M2/M3 |
| SR-014 | 恶意媒体不能逃逸或耗尽宿主 | restricted child/job + protocol/demuxer allowlist + staging/resource caps | source adapters only | playlist/concat/subfile/protocol/decode-bomb corpus | M1/M3 |
| SR-015 | 所有当前已接线、未消费授权均可安全撤销 | CURRENT trusted authorization manager + per-ledger atomic revoke/consume + broker digest freshness | CURRENT system.revoke_grant 仅打开/轮询受信 UI；不接受目标 ID | revoke/consume race、repeat revoke、stale broker window、cross-audience、no-bearer | M2/M3 |
| SR-016 | 出域与成本边界可机器验证 | OperationRequestManifest + per-target DisclosureEntry + CostBudget + canonical profile/egress/audience manifests | request_operation_confirmation | canonical digest/cross-target mutation/unknown-price | M2/M3 |
| SR-017 | Worker 不持有服务秘密或公网能力 | typed BrokerRequest + authoritative locator + reservation ledger | structured task-owned IPC only | bypass/cross-target/text-swap/overlimit/revoke/crash/retry | M1/M2 |
| SR-018 | 插件摄取的 raw URL 不进入 MCP；trusted-entry 敏感值不进入模型/helper | trusted_entry-only + opaque networkResourceRef + network broker | public schema has no URL field | ordinary/signed MCP + model/process/log/crash canary | M2/M3 |
| SR-019 | 执行授权摘要无歧义 | AuthorizationBindingManifest canonical preimages | internal only | field mutation/order/duplicate/revocation epoch | M2 |
| SR-020 | Anki runtime verifier 不污染复习状态 | signed run + typed data/profile snapshots + full-interval 8-category write audit + signed run-owned process lifecycle/add-on actions + process/window manifests + copier/launch attestations + typed final-runtime manifest + final read barrier | import_and_verify | cross-run/tamper + zero writes + helper/isolated-Anki restart identity + existing-window preservation + TOCTOU | M2/M3 |

## 4. 可靠性要求

| ID | 阶段 | 证明 | 产物 | 测试 |
|---|---|---|---|---|
| RR-000 | P0 | CURRENT：verifier 精确区分 V15/V14/V10 与 V1xx 伪版本；10 个生产变体通过完整 APKG 合同并在 Anki 写入前复核 | release evidence + complete package report + import preflight | V15/V14/V10 positive + 10 variants + spoof/canonical/registry/template/archive-limit negative + CLI exit 1 + media/import zero-call |
| RR-001 | R0 | 授权有效 | authorization ledger audit | scope/replay |
| RR-002 | R0-R8 | CURRENT：公开产物/审计查询只接受当前受信会话的 opaque ArtifactHandle；已知 schema 只返回白名单摘要，未知 schema 只返回元数据 | authenticated Artifact envelope + bounded certificate | cross-session、任意 payload/路径/内部 ref 注入、父链截断、Anki runtime 未核验限制 |
| RR-101 | R1 | 来源身份/完整性 | SourceArtifact | hash/partial |
| RR-201 | R2 | 证据对齐 | SemanticArtifact | replay/span |
| RR-301 | R3 | 候选门禁 | DiscoveryArtifact | expert benchmark |
| RR-401 | R4 | CardPlan 可作答 | PlanArtifact | leakage/scoreability |
| RR-501 | R5 | CURRENT 受限文本路线：当前 PlanSet 八项门禁全通过后，CardArtifact、ReliabilityManifest、空 MediaLedger、SanitizedLegacyProjectArtifact 与 ProjectArtifact 逐卡闭合；恢复不重复发布 | ProjectArtifact + authenticated parent graph | blocked/stale/cross-audience/tampered cursor + interruption recovery + real Worker APKG projection smoke |
| RR-601 | R6 | CURRENT：`.partial` 经完整包合同后 no-replace 原子发布；目标已存在时拒绝覆盖，失败不产生新最终 APKG/伪 done | internal ExportResult + package report；M2 后迁移到认证 PackageArtifact | ZIP/JSON/model/deck/note/card/content/media/safe-HTML + no-replace atomic publish |
| RR-602 | R6 | CURRENT：受信跨盘媒体恢复竞态不覆盖并发创建的同名文件 | trusted Anki media fallback | identical-race idempotent + conflicting-race refuse-overwrite |
| RR-603 | R6 | CURRENT：导入只接受身份一致的 full + compact 导出证据，不回退到陈旧结果 | UI import gate | missing pair + path/hash/deck/model/contract/fingerprint mismatch |
| RR-701 | R7 | 真实导入授权 | ImportPlan + approval audit | session/plan binding，无 bearer |
| RR-801 | R8a | Anki 数据完整性 | VerificationArtifact status=data_verified | required data checks exactly once |
| RR-802 | R8b | Anki 真实渲染/播放/复习 | runtime_failed 或 fully_verified + exact-key current trust/signed proof/actor-focus provenance/typed final manifest/final barrier aggregate | fixed checks + nonempty render + 1/20/full + cross-process zero-write + real Anki restart + atomic commit |
| RR-901 | 恢复 | 失败不伪造成功、旧授权不转移 | Task/Checkpoint/SuccessorTaskRebase/AnkiRecoveryDecision | forced exits + re-auth + write-boundary matrix |
| RR-902 | 长导出/Anki | 终态前不伪造成功 | Task + Package/VerificationArtifact | cancel/crash/retry |

CURRENT M0 证据边界：最终自动化为 Vitest 830、正式 `pytest` 603、独立 `unittest discover` 576（有重叠，不相加）、Rust 31 项通过与 1 项按设计忽略、UI smoke 3、V15/V10 release smoke、`check:full` 与 Tauri build 通过。20 卡离线生产 V15 包为 20 notes / 20 cards / 52 media，manifest、逐媒体哈希、字幕对齐和模型作用域 GUID 闭合；隔离真实 Anki 覆盖 E→C 单卡、V15 20 卡重复/重启及 V14/V15 同字段并存。Computer Use 已在 Anki 26.05 完成 20 张连续复习、翻面、滚动、焦点、四类媒体、Space/Enter 路由与状态互斥。正式 profile/牌组未触碰。合成视频和静音 TTS 不证明真人语义、听感或长期学习效果。

非 NFC、Windows 保留设备名（含 `CLOCK$`）、大小写/规范化冲突和 APKG archive 资源上限已通过；流式读取覆盖 APKG archive/package/verifier 与标准 Windows Anki direct-first 媒体路径。64 MiB direct 样本在禁止整文件读取、Base64 与 AnkiConnect 媒体动作时通过，Python `tracemalloc` 峰值增量低于 32 MiB。非标准/portable profile 的 AnkiConnect inline 路径仍整文件/Base64，但原始媒体硬限制为 8 MiB，且部分写入账本与最终媒体 barrier 已冻结。raw `ExportResult` 仍只是内部兼容输入，不认证来源；partial 后的 no-replace 原子发布及导入前 stat/SHA 只缩小、不能消除 TOCTOU。SR-007 的 M2 认证 Artifact 注册表、不透明引用和受控文件句柄完成前，不能把当前入口公开为 MCP 写工具。

CURRENT 已开放固定 Hermes 候选发现、确定性文本 `cards.generate`/`cards.list`、异步 `cards.export_apkg`、ImportPlan/受信确认与 `anki.import_and_verify`，产出认证 Discovery、ProjectArtifact、PackageArtifact、ImportPlan、receipt 和数据级 VerificationArtifact；`study.get_artifact`/`study.get_audit` 只投影当前受信会话下的有界摘要与完整性证书。`integrityVerified=true` 仅证明本地认证 envelope、payload hash 与 lineage 通过，不证明外部语义正确；数据级 Anki 核验也不能升级为 reviewer 渲染、播放、焦点或重启复习已验证。尚未完成正式签名安装包、App UI、通用模型/TTS/媒体生成和 RR-802 runtime verifier。非标准 inline 限制、Anki 26.05 历史 add-on 证据和合成媒体也不能外推为通用 runtime 或学习效果证明。

## 5. UX 要求

| ID | 要求 | 表面 | 测试 |
|---|---|---|---|
| UX-001 | 对话表达意图，Rail 表达真相 | all | state consistency |
| UX-002 | 一个主动作 | Inline/Fullscreen | component assertions |
| UX-003 | 正常能力隐形 | all | ready state snapshots |
| UX-004 | 500ms 反馈 | PiP/Inline | latency |
| UX-005 | 长任务诚实进度 | PiP | monotonic/indeterminate |
| UX-006 | 失败说明保留与动作 | all | fault journeys |
| UX-007 | partial 可见 | sources/delivery | omitted cases |
| UX-008 | 键盘/焦点/ARIA | App UI | accessibility |
| UX-009 | 宿主形态自适配 | 条件 Inline/PiP/Fullscreen + tools-only | per-host compatibility matrix |
| UX-010 | 不依赖固定侧栏 | all | full journey without sidebar |
| UX-011 | 导入/数据核验/运行时核验文案严格区分 | tools-only + conditional UI | no false verified state |
| UX-012 | 任务终态在后续写动作前稳定可见 | tools-only + conditional UI | currentTaskId/acknowledgement state matrix |

## 6. 里程碑交付矩阵

| 里程碑 | 主要契约 | 主要工具 | 必须证据 |
|---|---|---|---|
| M0（实施中） | Worker/模板/Export/Anki frozen | 内部 | 最终自动化、20/20/52 离线媒体合同、E→C 单卡 1/1/6、隔离 Anki 20/20/52 数据级导入/重复/重启，以及标准 profile direct-first 流式预置、8 MiB inline 上限、ownership ledger 与最终媒体 barrier 已完成；真实 GUI 播放与连续复习、Computer Use 待验收 |
| M1 | Headless runtime | 内部 service | 桌面等价、process safety |
| M2 | Artifact/Task/Authorization/Secret/Profile verification/Anki check contract | task/artifact/capability | tamper/recovery/canary/profile isolation/check completeness |
| M3 | Language Objective/CardPlan compat | MVP MCP | Codex→Anki 端到端 |
| M4 | WorkRailViewModel | 条件 UI resources | 仅宿主实测支持形态 + tools-only fallback |
| M5 | stable source adapters | register/inspect | 每源 corpus/anchor |
| M6 | general Study IR | candidate/plan tools | knowledge benchmark |
| M7 | complex source | adapter tools | OCR/visual sandbox |
| M8 | learner feedback | history/profile tools（在 M8 完成权限设计后命名） | A/B/C learning |
| M9 | public distribution | 托管边界工具（在 M9 完成威胁模型后命名） | official submission/security |

## 7. 更新规则

实现 PR 必须：

1. 引用至少一个 requirement ID。
2. 说明影响的 schema/tool/Artifact。
3. 添加或更新对应测试。
4. 改变设计时更新 [决策记录](DECISIONS.md)。
5. 通过后把该项实现状态从 PROPOSED 更新为 CURRENT，并附代码/测试证据。
