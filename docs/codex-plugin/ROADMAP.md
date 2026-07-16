# 实施路线图

> 状态：PROPOSED  
> 日期：2026-07-16  
> 顺序以风险消除和可验证产物为准，不以功能数量为准。

## 1. 总策略

~~~text
冻结当前契约
→ 独立 Headless Runtime
→ 共享任务/产物/权限
→ 语言能力插件化
→ 条件 App UI（先验证目标 Codex 宿主）
→ 扩展来源
→ 通用 Study IR
→ 学习反馈
→ 公共分发
~~~

任何阶段只有在出口条件全部通过后进入下一阶段。

## 2. 产品线定位

- Codex Plugin：未来主入口。
- Windows 桌面端：兼容入口、调试/验证场和无 Codex fallback。
- Web Helper：冻结为旧规划；吸收 opaque file ref、job 和安全概念，不单独发展第二套 runtime。
- 核心可靠性：共享 Card Service/Worker，不在三个入口复制。

## 3. M0：冻结基线与清除发布阻塞

### 目标

在新入口出现前证明当前可靠性内核的真实边界。

### 工作

- 为九个 Worker 命令建立正式 schema/golden fixtures。
- 固定错误码、进度、Project、ExportResult、AnkiVerifyResult。
- 分离 template family、template schema、Note Model ID。
- 修复 workers/verify_apkg.py 的 V1 + startswith 宽前缀 fail-open，建立精确 family/schema/Note Model 兼容判定。
- 增加 V14 精确正例、V13/V15/V199/近似前缀负例和旧版本明确兼容 release smoke。
- 跑通 1 张、20 张、跨磁盘、重复导入。
- 把旧 README/用户指南中与当前三步流程冲突内容列入后续文档修订。

### 出口

- 当前桌面行为零回归。
- 最新生产模板使用与 release 相同 verifier 通过。
- 已知 CURRENT/PROPOSED 清单签字确认。
- 建立 Git 回退 tag。

## 4. M1：Headless Legacy Runtime

### 目标

不启动 Tauri UI，也能安全调用现有内核。

### 工作

- 提取 Worker supervision、任务、路径、秘密和 Anki 能力为本地 Card Service。
- 保持现有 Worker 不重写。
- 创建内部受限 service API。
- 实现最小受信 local-settings 与 consent-ui 启动器，使 tools-only 宿主也能配置凭据和签发本地授权。
- Tauri 暂时可继续旧路径，但增加等价性测试。
- 使用受管工具绝对路径。
- 将 FFmpeg/ffprobe、yt-dlp 和解析 helper 迁入每任务受限子进程：Windows task-owned Job Object + AppContainer/专用 restricted SID 与 staging DACL + broker/代理端点强制出站策略，固定 protocol/demuxer allowlist、无 Shell和资源配额；仅有 low-priv token 不算完成。
- 禁止 Legacy Worker 持有 provider secret 或直连公网；增加 Card Service model/TTS broker 与 task-owned IPC，结构化构造请求并逐调用原子 reserve/settle token、字节、TTS、调用数和成本。

### 出口

- 同一输入在桌面端和 Headless Runtime 得到语义等价 Project、media ledger 和验证结果。
- 进度、取消、超时和错误一致。
- 没有通用 Shell/Worker API。
- 恶意 playlist/concat/subfile/协议、畸形容器、外部配置/exec 和解码资源耗尽不能逃逸沙箱，也不能影响 Card Service 或其他任务。
- Worker 直连公网、provider secret canary、broker 超量/并发/撤销、crash-after-send 与 retry 测试通过；每个远程副作用都有可对账 reserve/settle 记录。

## 5. M2：Artifact、任务和权限基础

### 目标

建立插件可依赖的权威状态。

### 工作

- ArtifactEnvelope、认证项目注册表和 Blob store；MCP 只接受 opaque handle，持久产物使用省略 artifactDigest/registryAuthRef 的明确 canonical preimage digest + 服务端认证记录。
- StudyTask 外层工作单元、work units、checkpoint 与结构化 failure。
- 分离 TaskInputManifestDigest（执行实例）与 WorkReuseDigest（语义工作单元），实现重启后重新授权的 successor task、StableCapabilityBinding 和双重授权审计；不得把新会话授权回填旧任务。
- revision/expectedRevision/idempotency。
- 可信 stdio 握手、AudienceBindingManifest（canonical OS SID digest + host/plugin/service/session）、项目 owner/scope 与应用数据 ACL。
- InternalAuthorizationRecord、OperationIntent/ImportPlan 服务端 approval ledger、file/output/network refs、canonical ProfileConfiguration/RequestParameterPolicy/Egress manifest、逐目标 DisclosureEntry、模型/TTS/成本/批量与 Anki 的完整绑定、过期/撤销/一次性消费。
- 冻结 BrokerModelRequest/BrokerTtsRequest、权威文本 locator 与 BrokerReservationLedger：每次调用绑定 task/work unit/audience/intent/授权/profile/disclosure/egress/budget，覆盖 reserve/sent/settle、未知费用、crash-before/after-send 和 retry。
- SecretRef 与原子单调 credentialRevision；add/replace/delete/rollback/OAuth material change 和并发更新均有合同测试。
- fixedCapabilities 与逐 profile ServiceProfileVerificationRecord；最新失败覆盖旧成功，聚合状态不驱动 gate。
- 固定 Anki 合同、权威 identity/media、Service-derived 非空 expectations、pre-run 无环 signed run、root-signed、append-only tombstone 且逐 key-version 永久绑定唯一公钥的 anti-rollback trust snapshots、verifier-signed typed proofs、signed run-owned process lifecycle ledger、add-on focus action attestations、三传感器跨进程写审计、对称 typed focus/process/window、真实 isolated-Anki restart、Typed FinalRuntimeEvidenceInputsManifest + barrier-bound final 11 checks、原子 RuntimeEvidence 与 RecoveryDecision。
- 原子检查点、.bak 和审计。
- 将当前 legacy Project 先经递归 sanitizer 生成完整非秘密 canonical projection，segments/cards、reliability manifest 和 export 必需字段必须无损；路径改为 resource slots，任何 Artifact 持久化前拒绝秘密字段。

### 出口

- 产物篡改被拒绝。
- 任务中断后可在 WorkReuseDigest 与授权范围证明通过时创建 successor 并恢复已有产物；已完成工作单元不重复调用，范围扩大/语义变化阻止复用。
- 输入改变不被旧结果覆盖。
- 密钥 canary 不进入任何产物/日志。
- 空 checks/expectations、漏卡/媒体、撤销快照/公钥映射回滚、unsigned/cross-run proof、另一连接写后恢复、sensor gap/overflow、run actor/add-on focus 归因缺失或单向谓词、旧窗口/helper-only 假重启、缺成员或不可重算的 final-runtime manifest、旧 final evidence、post-cutoff event 或非原子 commit 均不能得到 fully_verified。
- 路径/授权攻击测试通过，包括无授权、过期、越权、跨任务/URL/profile/credentialRevision/egress/费用/批量/策略重放、复制 handle、并发消费和撤销；OperationIntent 参数变化必须重新确认；文件/网络、OperationApproval 和 ImportApproval 的撤销/消费竞态只有一个原子胜者。

## 6. M3：语言插件 MVP

### 目标

首个可安装的 Codex-first 语言制卡闭环。

### 范围

- Skill。
- 本地 stdio MCP。
- 无 App UI 也可通过对话完成。
- 本地视频+字幕、视频 URL。
- 当前语言 LearningPoint 兼容层。
- 候选选择、生成、APKG、显式 Anki 导入；AnkiConnect 数据核验与版本化 trusted add-on/GUI protocol 运行时核验严格分层。
- 中断恢复。

### 工具最小集

- system.get_capabilities、system.list_profiles、system.open_local_settings、system.validate_profile。
- system.request_source_grant、system.request_output_grant、system.request_network_grant、system.request_operation_confirmation、system.revoke_grant。
- study.list_projects、study.get_project、study.create_project、study.update_learning_contract、study.register_inputs、study.start_source_inspection、study.get_source_inspection。
- study.start_discovery、study.get_task、study.list_recoverable_tasks、study.cancel_task、study.resume_task。
- study.list_candidates、study.get_candidate、study.preview_evidence、study.edit_candidate、study.set_selection。
- study.plan_cards、study.list_card_plans、study.edit_card_plan、study.validate_card_plans、cards.generate、cards.export_apkg。
- anki.prepare_import、anki.request_import_confirmation、anki.import_and_verify(importIntentId)。
- study.get_artifact、study.get_audit。

### 出口

- 用发布目标 Codex 版本完成 plugin manifest、stdio Service 启动、工具注册和重连预检；失败必须阻断，不用 App UI 假定掩盖。
- 从真实 Codex tools-only 对话完成 1 张和 20 张；分别保存数据完整性证书与真实渲染/播放/重启复习 runtime evidence。
- 高风险动作确认。
- 提示注入、路径、SSRF、秘密、APKG 攻击通过；M3 视频 corpus 必须证明 FFmpeg/yt-dlp 沙箱、协议 allowlist、资源配额和 staging 边界有效。
- 桌面端与插件生成结果可靠性等价。
- Git/本地 Marketplace 安装、升级、卸载通过。
- 若目标宿主/系统无法启动受信本地确认表面，M3 降为只生成/导出 APKG；不得承诺 Anki 写入闭环。

## 7. M4：条件 App UI

### 目标

提供可监督的控制台，不依赖固定右侧栏。

### 进入门槛

- 用目标 Codex Desktop 版本和工作区验证：插件内本地 stdio MCP 是否能注册并提供 MCP App resource、宿主桥接和目标展示模式。
- 若不支持，M4 改为 tools-only 增强或单独的 App/托管 MCP 方案；plugin.json 不声明 apps。
- CLI/IDE 默认不承诺 App UI。

### 工作

- WorkRailViewModel。
- Inline 状态卡。
- PiP 长任务。
- Fullscreen 候选/证据/CardPlan/交付。
- 键盘、ARIA、缩放和减少动效。
- 宿主 bridge 事件丢失恢复。

### 出口

- 仅对宿主兼容实验确认可用的形态承诺共享状态；tools-only 始终可完成核心闭环。
- 0/1/49/50/100 候选。
- 任务/失败/恢复/Anki 状态无矛盾。
- 没有页面级关键溢出。
- 固定侧栏不存在时仍完成所有主路径。

## 8. M5：稳定文本来源

### 顺序

1. TXT/Markdown。
2. 文本型 PDF。
3. DOCX/EPUB。
4. HTML 快照。
5. 受限文件夹 manifest。
6. 播客/音频转写。

### 每个适配器要求

- 身份、完整性、EvidenceAnchor。
- 资源上限/沙箱。
- golden/恶意 corpus。
- 一张与 20 张真实 Anki。

### 出口

- “任意 Codex 附件”在有稳定 attachment ref 时可以走对应适配器。
- model-relayed 明确 draft_only。
- partial 覆盖不静默。

## 9. M6：通用 Study IR 与知识路线

### 目标

从语言专用 LearningPoint 演进到通用学习目标。

### 工作

- ContentNode/EvidenceAnchor/SemanticUnit。
- LearningObjective 和 CardPlan。
- 事实、定义、概念、因果、比较、流程、论点、公式、应用、决策、纠错路线。
- 同源精确去重。
- 跨源语义关系。
- ConflictSet 和先修关系。
- PracticeTask/ReferenceNote。

### 风险控制

- 先 envelope sanitized legacy payload，不一次替换；净化失败时 fail closed。
- 无证据不得正式生成。
- 不支持的路线返回 blocker。
- 事实可靠性与结构可靠性分开。

### 出口

- PDF/网页专家标注 benchmark。
- 未解决冲突进入普通事实卡 0。
- 用户锁定/编辑可追溯。
- 通用知识 1/20 张真实 Anki。

## 10. M7：复杂来源

### 范围

- 扫描 PDF/OCR。
- 表格、图表、公式。
- 图片区域。
- 代码仓库快照。
- 多说话人高噪声媒体。

### 出口

- 结构定位可重放。
- OCR/视觉置信度和遗漏明确。
- 解析器沙箱/DoS 测试。
- Tier B 不被静默升级为 A。

## 11. M8：学习者模型与反馈闭环

### 目标

从“一次生成”变为持续优化。

### 工作

- 导入后 card identity 与复习事件关联。
- known/partial/confusion。
- 编辑、删除、暂停和响应时间。
- 复习债务校准。
- 对比卡/路线调整建议。
- 个性化开关与数据保留。

### 实验

- Agent-generated learner-owned vs 手工制卡 vs 阅读/摘要。
- 1/7/30 天识别、产出和迁移。
- 学习增益/分钟。

### 出口

- 隐私和本地存储说明通过。
- 不以用户困难自动归因于用户。
- 只有真实实验支持的效果声明。

## 12. M9：公共发布与跨平台评估

### 工作

- 决定本地 stdio 与公开 HTTP MCP 的产品形态。
- 生产 MCP/配对本地执行器威胁模型。
- 域名、隐私、条款、支持。
- 官方测试案例。
- 可复现构建、签名、SBOM。
- macOS/Linux feasibility。

### 出口

- 不削弱本地来源和 Anki 权限边界。
- 公共 MCP 不接收原始本机路径/密钥。
- 高级 Git 用户版本稳定后才提交公开目录。

## 13. Future：官方侧栏适配

触发条件：

- OpenAI 发布稳定公共侧栏/扩展位置接口。
- 权限、生命周期、宽度和通信文档明确。

工作仅限：

- 实现 FutureSidebarAdapter。
- 复用 WorkRailViewModel。
- 增加宿主尺寸/焦点测试。

不迁移业务状态，不改变 MCP/Study IR。

## 14. 提交边界建议

每个阶段拆分：

1. schema/测试先行。
2. runtime 内核。
3. 兼容适配。
4. UI/Skill。
5. E2E 与文档。

示例提交：

~~~text
test: freeze worker and template contracts
fix: align v14 apkg release verification
feat: add headless card service runtime
feat: persist versioned study artifacts
feat: expose bounded study mcp tools
feat: add codex study workflow skill
feat: add mcp app work rail
~~~

每个里程碑前创建回退点；禁止 git add .；本机缓存、密钥和媒体不入库。

## 15. 阶段风险

| 阶段 | 最大风险 | 缓解 |
|---|---|---|
| M0 | 误以为基线已绿 | 真实 V14/Anki 证据 |
| M1 | 两套调度分叉 | 共享 Runtime/等价测试 |
| M2 | 过度设计 Study IR | 先 legacy envelope |
| M3 | Agent 权限扩大 | 窄工具/内部授权记录 |
| M4 | 误把 ChatGPT App 模式当作 Codex 通用能力 | 逐宿主实验 + tools-only fallback |
| M5 | “能读”冒充完整 | completeness/anchor |
| M6 | 事实幻觉 | 冲突/证据门禁 |
| M7 | 解析器攻击 | 沙箱/资源限制 |
| M8 | 虚假学习效果 | 真实对照实验 |
| M9 | 云化泄露本地边界 | 本地执行器隔离 |

## 16. 发布版本建议

- 0.1.x：开发者本地，语言视频闭环。
- 0.2.x：经宿主验证的条件 App UI，以及稳定文本来源。
- 0.3.x：通用知识 Study IR。
- 0.x 始终允许协议演进，但已发布产物必须有迁移。
- 1.0 条件：工具/Study IR 稳定、真实 Anki 和安全门禁长期通过、公开支持矩阵清晰。

版本号仅为建议，不代替每个里程碑出口。
