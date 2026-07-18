# 可追溯矩阵

> 状态：CURRENT M0/M1 与 M2 内部切片追踪 + PROPOSED 后续要求
> 日期：2026-07-18
> 目标：每个重要承诺都能追到领域契约、工具、测试和里程碑。

## 1. 产品要求

| ID | 要求 | 领域/架构 | 工具/界面 | 验证 | 里程碑 |
|---|---|---|---|---|---|
| PR-001 | 注册附件、文件、目录、URL | InputRef/SourceAsset | register_inputs | 来源 adapter corpus | M3/M5 |
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
| PR-305 | Anki 明确授权 | ImportPlan + internal approval ledger | prepare/confirm/import_and_verify | no-confirm/session-replay negative | M3 |
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
| PR-507 | raw URL 不进入 MCP | trusted-entry-only network grant | system.request_network_grant | schema absence + ordinary/signed URL canary | M2/M3 |

当前 M2 内部证据：PR-002 的 ArtifactEnvelope/认证 Registry 与 legacy Project 非秘密 canonical projection、PR-205/402/403/404 的 StudyTask/检查点/successor、PR-207 的 Project/Contract 双 revision、语义操作、幂等与固定失效矩阵、SR-013 的 model/TTS OperationIntent/Approval/Authorization 账本内核，以及 PR-406/502/504 的认证 SecretRef/credentialRevision、持久非秘密 Service Profile Registry 与逐 profile verification registry 已有服务端实现和自动化测试。Legacy sanitizer 覆盖 fixed schema、递归 secret/config 移除、raw URL/path→精确 resource slot、同项目证据父链、canonical Blob/marker 复核与 public summary 最小披露；Profile 配置闭包、规范指纹、revision CAS、幂等、身份路径、凭据实时绑定、外部替换/删除 uncertain，以及凭据 add/replace/delete/rollback/OAuth/concurrency、歧义 crash、latest-failure、stale-at-publish、TTL 与旧备份防回滚均覆盖。M2 八组安全组件联合回归为 192 passed，正式 Python 全集为 1154 passed、1 skipped。受信窗口生产 attestation 适配、受信设置/验证任务、生产 ResourceBinding/运行时 rehydration、资源/ImportApproval、公共 MCP 工具、统一事务接线和正式安装边界仍未完成，表中 M3 出口不因此提前满足。

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
| SR-002 | 不传原始路径 | resource handles + internal ledger | register_inputs | traversal/reparse | M2 |
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
| SR-015 | 所有未消费授权均可安全撤销 | unified trusted authorization manager + atomic ledgers | system.revoke_grant 仅打开受信 UI | revoke/consume race、repeat revoke、no-bearer | M2/M3 |
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
| RR-101 | R1 | 来源身份/完整性 | SourceArtifact | hash/partial |
| RR-201 | R2 | 证据对齐 | SemanticArtifact | replay/span |
| RR-301 | R3 | 候选门禁 | DiscoveryArtifact | expert benchmark |
| RR-401 | R4 | CardPlan 可作答 | PlanArtifact | leakage/scoreability |
| RR-501 | R5 | 卡片/媒体一致 | ProjectArtifact | card/media ledger |
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

M0 已完成；插件/MCP/M1+ 仍未实现。非标准 inline 兼容路径与双进程 RSS、Anki add-on 仅声明支持 26.05、合成媒体不证明真人学习效果仍是明确限制。RR-000/RR-601/RR-801 的 M0 子项已有自动化、数据级与 GUI 证据，但不能外推为 RR-802 的通用 runtime 或 Codex 插件已经完成。

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
