# 实施路线图

> 基线日期：2026-07-20

## CURRENT 增量出口（2026-07-19）

在下文带日期的历史切片之后，当前代码又关闭了六个纵向出口：

1. 候选发现公共出口：新增 `system.authorize_candidate_discovery` 与 `study.start_discovery`。前者只批准固定 `hermes_grok_4_5`，后者异步启动并由 `study.get_task` 轮询；调用方无法注入 Provider、模型、endpoint、凭据、prompt、原始来源正文或服务端授权字段。
2. Anki 数据闭环出口：`anki.import_and_verify` 已公开，使用已确认的 `importIntentId` 幂等执行导入并发布 receipt/data verification。成功上限为 `anki_data_verified`；写后核验失败为 `imported_unverified`；不确定写边界要求 `inspect_before_retry`。
3. 受信网络来源出口：`system.request_network_grant` 只打开本地受信 URL 输入窗口，raw URL 不进入 MCP；`study.register_inputs` 已能对静态网页做匿名固定 IP HTTPS 快照，并把 YouTube public_video 缩成规范化 videoId 后获取字幕快照。网络授权可由统一管理器撤销，Service 重启后旧 ref 要求重新授权。
4. Learning Contract 更新出口：`study.update_learning_contract` 只接受九类封闭语义操作、当前 project/contract revision 与稳定 operationId。Service 按真实变化从 discovery、selection 或 planning 开始失效下游，把过期 Artifact 从项目 current/latest 指针中移除，同时保留不可变审计历史；公共响应只返回仍可靠的 opaque ArtifactHandle。
5. 候选发现恢复加固：active Worker 使用认证短租约、心跳与单调 fencing token 证明跨进程所有权；同步兼容入口也不能绕过租约。恢复与 successor 冲突检查读取只含 active/recoverable/pending-commit 项的认证索引，不再扫描全部历史 JSON；公开恢复列表增加 query/audience/index-generation 绑定 cursor，并在 current/stale 过滤后满足 limit。模型工作成功但项目提交中断时只重放本地幂等提交，提交前验证 Discovery bundle，提交后用持久 lineage closure 阻止迟到 successor；旧版无 completion binding 的成功任务可确定性迁移。第二个 Service 实例不能把第一实例的活任务误判为 orphan，无关损坏文件也不能通过第 2049 条记录永久禁用恢复。
6. 高级用户开发安装出口：仓库新增 `anki-study-agent-local` Marketplace、固定参数的开发 stdio 启动器和只使用 `codex plugin`/`codex mcp` CLI 改变宿主配置的安装器。可信 MCP 不再执行宽 ACL 的 Git 工作区：安装器把 Card Service/Worker/launcher 和可选媒体工具复制为 `%USERPROFILE%\.anki-study-agent\codex-dev-runtime\<manifest-sha256>` 内容寻址快照，逐文件绑定角色、大小和 SHA-256，并为应用根、状态和所有快照文件设置受保护的精确 DACL。MCP 直接指向具体 digest，不经过可变 `current` 链接；稳定安装身份保证换快照后 host scope 不变、session nonce 仍逐进程轮换。升级调用 Plugin Creator 官方 cachebuster，安装/升级/卸载对陌生或并发变化的同名对象失败关闭，并在后段失败时反向恢复本次新增的 MCP、Marketplace、Plugin/manifest。该路径明确报告 `productionSigned=false`，没有生成源码 `.mcp.json`，仍不替代正式发布者签名。

网络切片的历史证据是 98 项定向回归、`1653 passed, 1 skipped` 的当时 Python 全集和 Computer Use 受信窗口验证；Learning Contract 公共出口新增 73 项定向组合回归。文本层 PDF 切片补充了独立 Worker、页覆盖关系、20,000 节点、沙箱错误、真实遗漏计数和下游页证据测试；其当时正式 Python `tests` 全集为 `1681 passed, 1 skipped`。随后新增的嵌入媒体字幕/Podcast 快照切片通过 100 项定向回归，包括真实 FFmpeg MP4 + mov_text 提取、有界 FFprobe 输出/超时、媒体关系矛盾拒绝和 feed/直链冻结；切片合入后的正式 Python 全集为 `1698 passed, 1 skipped`。前端 830 项、Worker 600 项、UI smoke、Rust 31 项通过与 1 项按设计忽略是前一基线，plugin/Skill validator 会在本切片归档前重跑；真实 Codex `0.144.1` app-server 已验证可信会话枚举 38 个工具并实际创建项目/更新合同到 projectRevision=2、contractRevision=2，不可信会话仍只枚举 `system.get_capabilities`。真实公网长期可用性、正式安装布局与完整媒体 acquisition 仍属于后续验收，不能从这些切片提前推导。

因此，“公共 start_discovery 尚未注册”“anki.import_and_verify 是下一出口”“Anki 写工具仍未开放”“生产受信 URL 输入尚未接线”“Learning Contract 只在内部实现”“PDF 一律不支持”“Podcast 一律在 fetch 前阻塞”等句子只记录早期切片，已被本节取代。CURRENT 新增两条受限解析：文本层 PDF 仅在签名托管 runtime 的 Windows AppContainer + Job Object 中运行固定 pypdf Worker，页码和真实遗漏计数进入认证来源图；音视频仅在同一沙箱内用固定哈希 FFprobe/FFmpeg 读取受支持的嵌入字幕并保留 cue 时间，缺字幕不调用 ASR。Podcast 只冻结用户明确授权的 HTTPS feed 或小型直链，不自动追随 enclosure。开发态、扫描件、无字幕媒体或沙箱/工具不可用时失败关闭。仍未完成的是：宿主附件、完整视频/音频 acquisition、ASR、Office/扫描 PDF、动态或登录网页、模型扩写/TTS/媒体生成、非发现任务恢复、R8b runtime rendering/playback/restart verifier，以及正式发布签名与可安装插件/App UI。

> 状态：CURRENT 实施跟踪 + PROPOSED 后续路线
> 日期：2026-07-17
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

### CURRENT 状态（2026-07-17，已完成）

已经进入当前工作分支并由自动化合同覆盖：

- 九个现有 Worker 命令的版本化 schema 与 golden exchanges，包含结果/进度 schema 版本、核心错误与秘密剥离边界。
- template family、template schema、Note Model ID 与 compatibility contract 已分离；生成和核验共享精确合同注册表，Note Model serializer 固定为 `genanki==0.13.1`。
- 完整 APKG 包合同覆盖 ZIP/JSON 唯一性与限额、collection/media 映射、模型/牌组/note/card 关系、CardId/纯内容 SHA、媒体 manifest/ledger/card-media ledger 和安全展示 HTML；10 个生产生成变体都以真实导出产物通过该验证器。
- 导出采用“最终目录唯一 `.partial` → 完整包校验 → no-replace 原子发布最终 APKG”；目标路径已存在时拒绝覆盖，校验或发布失败会清理/隔离 partial，且不能发出 100%/done。
- 生产 V15、V14 与明确支持的 V10 兼容模型由精确合同注册表驱动；release smoke 继续覆盖 V14/V10。V13、V199、近似名称、非规范 ID/整数、完整字段/模板/model extras 篡改、models registry 偏差、双 collection/重复关键条目和解压限额超限由负向合同测试拒绝。
- V15 使用模型作用域 GUID；V10/V12/V14 保持历史 GUID 规则。字段完全相同的冻结 V14 与最终 V15 已在真实 Anki 中同时存在，重复导入和重启均不合并、不重复。
- 生产 `verify_anki_import` 在媒体预置前核对内部、证据完整的 raw `ExportResult`、payload 覆盖、绝对路径、APKG 哈希/大小与完整包合同；媒体准备后、紧贴 `importPackage` 前再次 stat + SHA。任一失败都不得调用导入写动作。raw `ExportResult` 不认证来源，不能抵抗同时篡改 APKG 与结果的同权限本机攻击者；上述复核只缩小、不能消除 TOCTOU，M2 仍需认证 Artifact 注册表、不透明句柄和受控文件句柄。
- 当前自动化回归通过 Vitest 830、正式 `pytest` 603、独立 `unittest discover` 576、Rust 31 项通过与 1 项按设计忽略、UI smoke 3、V15/V10 release smoke 和 `npm run check:full`。两套 Python 运行有重叠，不相加。
- 20 卡生产 V15 离线媒体包通过完整合同：20 notes / 20 cards / 52 个唯一媒体，manifest、逐媒体哈希、字幕对齐与模型作用域 GUID 闭合。它使用合成视频和静音 TTS，不代表真人语义、听感或长期学习效果。
- 隔离真实 Anki 已完成 E→C 单卡数据核验：1 note / 1 card / 6 media；6/6 均为 `direct-first / trusted_atomic_copy`，逐媒体大小/SHA-256 一致，`retrieveMediaFile`/`storeMediaFile` 均为 0 次；重复导入跳过且 `duplicates=0`，真实重启后再次通过。
- 20 卡包完成隔离 Anki 数据级核验：首次导入 20 notes / 20 cards / 52 media；52/52 均为 `direct-first / trusted_atomic_copy`，52 个媒体哈希与 120 个归属一致，媒体传输 API 为 0 次；重复导入跳过且 `duplicates=0`，真实重启后仍为 20/20/52。正式 profile/牌组未触碰，隔离进程已关闭。该结果不包含 GUI 翻面或实际播放。
- 非 NFC、Windows 保留设备名（含 `CLOCK$`）、大小写/规范化冲突与 APKG archive 资源上限已通过。
- 标准 Windows Anki profile 的缺失媒体恢复已改成 direct-first：使用同一源句柄与目标临时文件句柄、1 MiB 固定块、边复制边计数/SHA-256、flush/fsync、文件/目录 identity 复核和 same-dir no-replace 发布，不再先调用 AnkiConnect 或构造 Base64。64 MiB 自动化样本在强制禁用 `Path.read_bytes`、Base64 与 AnkiConnect 媒体 API 时通过，Python `tracemalloc` 峰值增量低于 32 MiB。
- 非标准/portable profile 与非 Windows 只保留原始媒体不超过 8 MiB 的 AnkiConnect inline 兼容路径；8 MiB+1 在任何媒体 API 前 fail closed。8 MiB 是原始媒体协议上限，不是进程内存峰值；该小文件路径仍会整块 Base64，不能概括为全部媒体路径均已流式化。
- 多文件部分预置、超时结果未知、意外后缀孤儿与清理失败均进入 ownership ledger；导入前存在最终媒体 barrier，任一 missing/conflict/inaccessible/recovery failure 都禁止 `importPackage`。
- 先前合同未对齐的真实尝试由 preflight/final gate fail closed，目标保持 0 note / 0 card / 0 media。

M0 出口已经关闭：

- Computer Use 已在真实 Windows Anki 26.05 中完成翻面、布局、焦点、Space/Enter 媒体路由、四类媒体互斥和 20 张连续复习。
- 最终 V15 20 卡 APKG 为 20 notes / 20 cards / 52 media；真实 Anki 导入、52 个媒体 SHA-256、重复导入和重启全部通过。
- 冻结 V14 与最终 V15 的 50 个字段值完全相同，但真实 Anki note/model/GUID 分离；重启前后结构化证据一致。
- 根 README、`docs/USER_GUIDE.md`、`docs/ARCHITECTURE.md` 与历史 reports 的冲突已经在本目录 README 登记；历史报告保持不变。

### 工作

- [x] 为九个 Worker 命令建立正式 schema/golden fixtures。
- [x] 固定结果与进度 schema、核心错误、Project/ExportResult/AnkiVerifyResult 的当前线协议边界。
- [x] 分离 template family、template schema、Note Model ID 与 compatibility contract，并固定 `genanki==0.13.1` serializer 基线。
- [x] 移除 Note Model 宽前缀判定，建立精确 family/schema/ID/字段/模板/CSS/静态行为合同，并严格验证 APKG 关键条目、解压限额、registry 与实际 notes 引用。
- [x] 增加 V15/V14/V10 精确正例合同与 V13/V199/近似及篡改负例合同测试。
- [x] 建立完整 APKG 包合同，并让 10 个生产生成变体的真实导出产物通过同一验证器。
- [x] 实现 `.partial` 完整校验后 no-replace 原子发布，目标已存在时拒绝覆盖，失败不留下新最终 APKG 或伪成功状态。
- [x] 在生产 Anki 导入路径增加媒体前 APKG/hash/完整包合同 preflight，以及紧贴 `importPackage` 前的 TOCTOU 完整性复核。
- [x] 在隔离真实 Anki profile 完成单卡 `1/1`、媒体 `6/6` 和重复导入不重复的数据核验。
- [x] 完成 20 notes / 20 cards / 52 media、每卡 6 引用与 120 个归属的离线生产 V14 包合同验收。
- [x] 完成真实 E 盘 APKG/媒体源 → C 盘 Anki profile/`collection.media` 的单卡 6 媒体跨盘验收。
- [x] 完成隔离真实 Anki 20 notes / 20 cards / 52 media 的首次导入、52 哈希、120 归属、重复跳过与重启数据级验收。
- [x] 在真实 Anki GUI 完成至少 20 张连续复习、翻面和媒体实际播放。
- [x] 完成非 NFC、`CLOCK$` 等 Windows 名称冲突与 APKG archive/package/verifier 有界流式读取回归。
- [x] 将标准 Windows Anki 媒体恢复改为 direct-first 有界流式复制，并把非标准 AnkiConnect 整文件/Base64 兼容路径收紧到 8 MiB 原始媒体上限；冻结 response cap、部分写入账本和最终导入 barrier。
- [x] 在 Computer Use 可用的真实 Windows 桌面环境完成视觉/交互验收。
- [x] 完成前端、Python、Rust、UI smoke、V15/V10 release smoke 与 `check:full` 的最终回归；归档见 [M0 验证报告](M0_VERIFICATION_REPORT_2026-07-17.md)。
- [x] 登记根 README、用户指南、旧架构和历史 reports 的冲突；不改写历史报告。

### 出口

- 当前桌面自动化行为零回归。
- 最新生产模板使用与 release 相同 verifier 通过。
- 真实 Anki 单卡与 20 卡数据级导入、重复、重启和 E→C 跨盘已经通过；最终 V15 又在真实 GUI 中完成 20 张连续复习、四类媒体交互和 Computer Use 桌面验收。合成视频与 fixture TTS 仍不证明真人语义、听感或学习效果。
- 已知 CURRENT/PROPOSED 清单签字确认。
- 建立 Git 回退 tag。

**里程碑判定：M0 已完成。下一阶段为 M1；不能据 M0 完成推导插件已可安装或 M1 已完成。**

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

### 当前实施进度（2026-07-18）

- 已创建仓库内 `plugins/anki-study-agent` 被动插件包：manifest、Skill、Agent metadata 和学习/工作流/安全参考合同均通过官方 plugin/Skill 验证器与 3 项仓库合同测试。manifest 明确不声明尚未安装的 MCP/App；独立前向测试证明工具缺席时 Skill 会诚实停止，不会用 Shell 绕过或伪造 APKG/Anki 核验。该结果不等于插件已安装。
- 已实现最小真实 MCP stdio 协议桥，支持 `initialize`、`ping`、`tools/list` 和 `tools/call`，当前仅公开只读、零参数的 `system.get_capabilities`。Card Service 错误只返回限长错误码和可重试性，不回显本机路径、凭据或 Worker 细节；生成、导出、Anki 写入、凭据与通用 Worker 命令均未暴露。
- 已使用真实 Codex `0.144.1` app-server 在隔离 `CODEX_HOME` 中完成开发态和正式 packaged mode 两种宿主探针：宿主均成功注册并调用上述唯一工具，确认 stdio MCP 协议版本 `2025-11-25`、`genericShell=false`、`secretBearingRequests=false`。最新 packaged 探针从 4380 项、286,759,977 bytes 的完整运行包启动，内层 Ed25519 签名与精确 Windows DACL 均报告 true；本地探针签名使用每次随机、最长 24 小时且私钥不落盘的临时密钥，不冒充发布签名。隔离探针显式关闭 Codex plugin/remote-plugin 同步，避免与 MCP 验收无关的网络目录更新阻塞或污染结论；它不修改用户 MCP 配置，也不安装插件。仓库插件 manifest 仍保持被动，因为外层受信 launcher、正式发布密钥/外层签名和独立复制后的可安装插件验证尚未完成；在此之前不写入会失效的 `.mcp.json`。
- 已实现原生 pinned launcher 与离线构建器：launcher 把精确 runtime manifest/trust-policy 摘要编入自身，启动前拒绝 reparse/路径逃逸/额外文件并流式复核全部 4380 项 size/SHA-256；正常运行只接受 `--stdio`，安装 finalizer 另有不启动 Python、不推进回滚地板的 `--verify-install-only` 模式，且被动构建固定拒绝该模式。构建使用 Cargo.lock、`--offline`、`/Brepro`、固定 epoch 和禁用增量；加入 install-only 最终预检后的两个全新 target 得到相同的 315,392-byte 二进制，SHA-256 为 `b73d06c4739d9db5d76184c0261ba53220f2f2dc1abffe2bb4d1327b4ae16619`。launcher 为受限宿主固定 AMD64 构建架构，未来运行包同时从 Python `sysconfig` 标签判定平台。独立候选通过官方 validator，真实 Codex `0.144.1` 连续两次从该 launcher 完成唯一只读工具调用；被动 `--verify-install-only` 在启动 Python 前退出 125。正式 Authenticode/等价外层签名和发行密钥管理仍未完成，因此仓库插件继续不声明 `.mcp.json`。
- 已实现外层被动离线候选包构建器与验证器：只接受不声明 MCP/App 的插件、固定 launcher、已签名 runtime 和独立 trust policy，生成覆盖精确 4391 项的 canonical 外层 manifest 与 SPDX，并对外层/运行时分别应用和复核精确 Windows DACL。使用 install-only 预检版被动闸门的最新实物为 289,217,313 bytes，manifest SHA-256 `66a5ebaa23529415c5d3e9117302d8c79ff8dc2bee5e99a47846ae180b87bdc1`；官方 validator 与真实 Codex 候选目录连续宿主调用均通过。候选固定 `installable=false`、`mcpDeclared=false`、`outerSignatureVerified=false`、`publisherKeyManaged=false`，不是可安装发布物；旧候选外层签名不能复用于该新 manifest。
- 已建立外层发布签名的 public-key-only 交接合同：签名请求只能从经过完整候选验证的 canonical manifest 生成，使用独立 `study.plugin-release-manifest.v1` 域绑定 package/version/manifest/key epoch/时间窗；生产脚本没有私钥参数且不联网。独立 trust policy/验签器覆盖 key status、版本与 manifest 撤销、最低版本、最长寿命、过期、trust sequence 分叉/回退和同版本异内容。当前没有正式发布公钥策略、HSM 返回签名或 Authenticode 证书，因此该切片不改变候选的四个 false，也不允许新增 `.mcp.json`。
- 最长 24 小时的本地外层探针已对 289,210,657-byte 真实候选生成不落盘私钥的 detached signature；独立 CLI 再次验证完整 payload、外部公钥策略和 signature，二者均绑定 manifest `9ab03b75dc2a0c2197e280fdd47a9f9a83c2fe25fc786459822cfcbf23f262d6`。这只是协议实物证明，不是正式发布签名。同期把 AppContainer SID 验证改成无副作用纯派生，避免受限宿主因不能创建 per-user profile 而把合法 DACL 误报为损坏；profile provisioning 仍是未来安装器门槛。
- 已实现 Windows launcher Authenticode 发布闸门和独立 CLI：外部 canonical policy 精确钉扎 signer certificate DER SHA-256/subject/status、Code Signing EKU、KeyUsage、非 CA、RSA/EC 强度与可信时间戳；WinVerifyTrust 仅使用本地缓存验证 chain-exclude-root 撤销状态，验证前后 launcher digest 必须一致。当前真实 launcher 为 `NotSigned` 且本机没有 CurrentUser 代码签名证书，所以真实负例按设计阻断；正向合同由不落盘、不安装的内存 X.509 fixture 覆盖。正式证书、时间戳、生产 pin policy 和真实签名正例仍未完成，候选继续不可安装。
- 已把“可安装接线”移入原生启动器的独立签名域，并实现仓库内无私钥、无联网的 install candidate/signing request/finalizer：候选只接受外部发布策略、签名 runtime 与 Authenticode 已验证的 install-enabled launcher，生成固定 `.mcp.json`、MCP-wired plugin manifest、canonical `install-package-v1.json`、外层 SPDX 和委托 runtime pins，但在 detached signature 与原生预检完成前始终报告不可安装；finalizer 在隔离 staging 中验证 `study.plugin-install-manifest.v1` detached signature、外部 Authenticode pin、精确 DACL 和原生 `--verify-install-only`，原子发布后再全部复核，正式 API 不允许注入测试验证器或覆盖当前时间。5 项新增 Python 测试与 35 项发布链聚类回归覆盖确定性、跨域签名、篡改、未签名 launcher、原生拒绝和原子失败；13 项 Rust 测试继续覆盖 canonical/路径/资源、过期、撤销、降级、被动绕过和回滚地板。当前真实 launcher 仍为 `NotSigned`，也没有生产发布策略/HSM signature，因此真实 finalizer 必须失败关闭，本切片不改变可安装状态。
- 已完成受限 Card Service API、任务快照/恢复、进度/取消/超时、无通用 Shell、Worker 运行时清单、受信本地设置与授权入口、Broker 账本与 task-owned HMAC IPC。
- 已完成 Windows task-owned Job、restricted primary token、AppContainer、每任务 capability SID、runtime/task workspace 精确 DACL 和无网络 capability 的真实负面测试。
- 已完成托管运行包内层供应链边界：canonical `runtime-package-v1.json`、detached Ed25519 签名、由受信 launcher 单独提供的发布者策略、签名有效期/密钥撤销/最低版本、同 sequence 分叉与本机版本回退拒绝，以及覆盖全部运行资源的 canonical SPDX 2.3 SBOM。
- 已新增离线、确定性、原子且拒绝覆盖已有目录的正式 staging 构建器 `scripts/build_managed_runtime.py`：只收集显式仓库源码、预装配 Python 运行时、完整 Python lock 和固定 FFmpeg/ffprobe/yt-dlp，逐文件复制后复核 SHA-256，生成精确 SPDX 2.3 与 canonical manifest。构建前必须读取有界、canonical 的 `python-runtime-build-v1.json`，证明该便携 Python 的 lock SHA-256 与 wheel 数精确匹配所给 25 项锁；构建元数据本身以 `managed-python:build-metadata` 纳入签名 manifest，运行包验签时再次与 `metadata:python-runtime-lock` 交叉验证，不能再把两个分别有效但彼此无关的产物拼接。包内 Python 模块布局固定为顶层 `card_service/` 与 `workers/`，不依赖 `PYTHONPATH` 注入。相同输入与显式 UTC 时间产生相同 manifest/SBOM；构建器不接收、读取或输出发布私钥，也不在运行时联网下载组件。复制时同步计算源摘要并独立回读目标验证，删除资源枚举阶段重复的逐文件 realpath，但复制前的严格 realpath/reparse/file-kind 闸门保持不变；CLI 每 250 项输出不含路径的结构化进度，使 4,000+ 文件的发行构建不再表现为无反馈卡死。manifest、SBOM、Python lock、Python build metadata、签名、信任策略和回退 floor 均先检查文件大小再有界读取，避免超大元数据在拒绝前耗尽内存。
- 正式 packaged mode 现在必须同时提供运行包和受信策略；运行包不能通过自带公钥建立信任。测试私钥只存在于测试代码内，仓库和运行包均不包含发布私钥。
- Python 供应链已完成本切片：`workers/requirements-win-cp313.lock` 对 CPython 3.13 / cp313 / win_amd64 的 25 个直接和传递 wheel 逐项固定版本与 SHA-256；生成器会拒绝 sdist、额外文件、重复包、根版本不符和 wheel 哈希变化。`scripts/assemble_managed_python.py` 使用 `--no-index --require-hashes --only-binary` 离线装配 CPython 3.13.12，排除环境 site-packages/工具/缓存并拒绝任何 pyc；实物结果为 1666 个核心文件、25 个 wheel、84,257,415 bytes。最终发布仍需真实离线/HSM 发布签名、外层 Authenticode/等价安装包签名与可复现构建环境证明。
- 已把 FFmpeg、ffprobe 和 yt-dlp 绑定到签名运行包中的精确资源。托管 FFmpeg/ffprobe 只接受绝对本地普通文件，固定 `file` protocol 与显式 demuxer allowlist，拒绝 playlist、concat/subfile、网络协议、策略覆盖、reparse 输入、Shell/stdin 覆盖，并施加 300 秒上限；托管 yt-dlp 使用无依赖 Rust 启动器从自身位置解析包内 `python.exe -I -B -m yt_dlp`，不搜索 PATH、不调用 Shell、不接受 build machine 的硬编码 Python 路径，实测返回锁定版本 `2026.07.04`。yt-dlp 仍忽略外部配置和插件，禁止 exec、playlist 与 remote components，并锁定受信 FFmpeg 目录。
- 真实畸形 MP4 已在 Windows AppContainer + task-owned Job + 专用 DACL 中 fail closed；正常 WAV→MP3 和 H.264/AAC 切片仍通过。受限子进程现在真实以自己的 task workspace 为工作目录，不再以只读运行包目录为 cwd；Service 对该目录按不跟随 link/reparse 的逻辑字节与条目数实施持续预算，默认 2 GiB/20,000 项、硬上限 8 GiB/100,000 项，超限会终止任务并拒绝结果。开发模式也使用独立工作目录和预算，但只有正式 packaged DACL 模式能把它作为文件系统写边界。
- 托管 FFmpeg 现增加执行前资源证据闸门：同一命令输入合计最多 8 GiB、32 个流、12 小时，视频限制单轴 8192、每帧最多 8192×4320 像素、240 fps、300 万帧及 16 TiB 逻辑解码量，音频限制 192 kHz、8 声道及 64 GiB 逻辑解码量；FFprobe 输出、探测耗时和码率也有限。输入在探测期间变化会拒绝，所有输出统一施加 512 MiB `-fs` 硬上限，达到上限的半成品会删除。FFmpeg 参数现只允许产品实际使用的单本地输入、单最终输出语法；第二输入/输出、循环/实时参数、任意滤镜、显式输出格式和未知选项在进程启动前拒绝，`-vf`/`-af` 只接受固定缩放与音量表达式。目标必须是新文件，失败、超时、空输出和假成功不会留下可消费的半成品。
- 真实正常 WAV/MP4、真实 FFmpeg 多输出/循环参数负例、伪造极端媒体证据以及会真实写超限文件的受限 Worker 负例均通过。新增小于 1 MiB 的实物容器语料覆盖 9000 像素单轴、300 fps、超过 50000 秒的稀疏 PTS、8192×4320/240 fps/超过 1200 秒且逻辑解码量大于 16 TiB，以及 33 流扇出；五类输入都在正式 `run_ffmpeg` 解码前 fail closed 且不留下输出。逻辑解码炸弹和稀疏超长时轴的真实 FFprobe 还在 Windows AppContainer + task-owned Job + 专用 DACL 内完成探测，网络/文件系统隔离证明成立且旁侧文件未变。命令级循环、playlist 和 concat 不属于可接受语法，因此没有可进入解码器的循环命令路径；更广泛的 codec parser 崩溃/fuzz corpus 仍留在 M3。
- 同一 Card Service 进程现在原子预留全部并发任务的最坏增长，将已终止任务留下的真实占用计入默认 8 GiB/100,000 项总预算；准入、每秒运行复核和成功接纳使用 4 GiB 卷剩余空间缓冲，跌破时终止活动任务并拒绝结果。这是 process-scoped admission/periodic 闸门，不是跨 Service 进程或约束任意外部写入者的 OS 硬配额。尚未完成的边界是安全 Artifact 保留清理、跨进程单实例/卷级协调，以及把已完成的根级 opaque file/directory grant 接入受控 staging 和目录逐子项安全句柄。
- 已实现 Service-owned Provider Egress 和任务授权闭包：Worker 只能提交 `{workUnitId, request}`，不能提交 URL、Header、profile、credential revision、operation intent 或预算；Service 重建 endpoint、模型/voice 和认证头。当前固定 OpenAI、xAI、Anthropic、Gemini、已知项目 gateway host，以及字面 loopback Hermes；任意自定义 OpenAI-compatible origin 在 M2 受信 origin 授权与连接时地址约束完成前拒绝。
- 受限 fake Worker 已通过认证 stdio 调用真实 task handler；默认传输已对临时 Hermes-style loopback 完成真实 POST 并拒绝 redirect。provider secret canary 只在 Service 传输闭包内出现，未进入任务、Broker ledger 或其他 JSON。未知真实费用按预留上限结算；发送后异常立即进入 `possible_incurred`。
- Legacy Worker 的 OpenAI-compatible、Anthropic 和 Gemini 生产模型入口已迁到受管 broker；受管模式不再因为缺少 Worker 内 API Key 而误判模型不可用。内部重试和批次重试使用确定性的独立 work unit，Worker 请求会递归拒绝 URL、Header、secret、profile、credential revision、intent 和 budget 等 Service-owned 字段。Gemini Vertex 在 Service-owned OAuth egress 完成前明确 fail closed，不允许退回 Worker 调用 `gcloud`。
- 真实受限 Legacy Worker 已通过认证 stdio 完成一次“选中学习点 → Service Provider Egress → 完整卡片项目”闭环：Worker 请求不含 API Key/Base URL，Service 覆盖 Worker model hint、注入 Service-owned credential，Broker ledger 正常 settle 且持久 JSON 无 secret canary。
- 生产 TTS 与 TTS 测试现已迁入同一 task-owned broker：Worker 只提交文本/语言/音频格式意图，Service 固定 provider、origin、model、voice、认证和预算；MIMO/Qwen/Gemini JSON 音频与 OpenAI/xAI binary 音频均返回统一的长度、SHA-256、MIME 证据，Qwen 二次媒体 URL fail closed。真实受限 Legacy Worker 已通过认证 stdio 完成一次无 Worker secret/origin/model/voice 的 TTS 测试并结算 ledger。
- 正式 stdio 启动器现已装配 Service-owned profile/intent resolver。启动清单必须是 canonical JSON、短期有效、位于固定 state dir 的 `trusted-surfaces/authorizations` 受信目录；它绑定方法→能力→profile、固定 provider/origin/model/voice、configuration fingerprint、credential revision、调用/请求/响应/成本预算与 intent ref。Card Service 在任务创建和每次 Broker 调用前复核过期及凭据版本，且拒绝任务自报 profile、revision、intent、budget、预留成本或 broker descriptor。能力摘要只暴露清单 digest/期限/计数，不暴露路径或秘密。
- 受信本地设置/确认窗口的响应通道已从“请求文件中的可读 nonce”加固为每会话一次性 HMAC：256-bit 响应密钥只经启动后的私有 stdin 交付窗口，不写 session/response 文件、不返回调用方；响应必须通过域隔离 MAC，读取 nonce 后伪造批准、篡改响应或重复启动同一会话都会被拒绝。Worker/UI 任意 details 不进入控制面。
- 已完成 M1 短期 Broker 启动授权的受信签发闭环：`system.open_broker_authorization` 只接受固定 schema 的 provider/profile、方法绑定、来源能力、有效期和硬预算；Service 解析并规范化 provider origin/model/voice，远程 profile 的 credential revision 直接从 OS 凭据元数据冻结，Hermes 固定 revision 0。可信窗口以可滚动正文展示全部授权范围，HMAC 验证真实点击后才在固定 authorizations 目录签发 canonical manifest；公开结果仅返回 digest、期限和数量，不返回路径、secret 或执行 token。调用/请求/响应/成本预算按 operation intent 在所有消费任务间合计，不能通过创建多个 task 放大。运行中的 Card Service 随后内部热加载该清单，排队任务则继续使用创建时冻结的 Broker factory，不会借用后批准的新授权。
- 2026-07-20 运行态预检增量：固定 Hermes endpoint 已与官方代理对齐为 `127.0.0.1:8645/v1`；授权批准、首次 discovery、异步 discovery 与恢复 discovery 都检查/启动当前代理。真实上游不可达时任务以可重试 `MODEL_STALE` 停止。AnkiConnect 由 launcher 固定显式 IPv4 loopback 端口，解决默认 8765 落入 Windows 排除范围时的 8785 隔离部署，而不允许 MCP 选择地址。
- 已交付首个受控来源切片：正式授权清单可按方法绑定 `source.youtube_subtitles`；旧 V1 清单不含来源策略时保持兼容并默认关闭该能力。Service 只接受任务已授权的 YouTube video ID、字幕语言和 VTT 格式，固定访问 YouTube watch/timedtext 端点，解析全部 DNS 地址并拒绝任一非公网答案，连接固定公网 IP 且保留 TLS hostname 校验，不跟随重定向，并限制 watch/subtitle 响应字节和超时。signed caption query 只存在于 Service 短期内存，不进入 Worker、结果或 ledger；Worker 仅接收含有效时间 cue、长度和 SHA-256 的规范化 VTT。托管 Worker 直接运行联网 yt-dlp 会在创建子进程前 fail closed。
- 真实受限 Legacy Worker 已完成“受控 YouTube 字幕 → 本地候选 → Service 模型 Broker → 学习点结果”认证 stdio 闭环；source/model 两类 reservation 均结算，持久 JSON 不含 provider secret 或 signed caption query canary。该证明使用确定性 fake transport，不是一次真实 YouTube 公网可用性测试。
- 已增加首条桌面/Headless 语义等价合同：同一个冻结的单学习点请求分别由桌面 Legacy Worker 直调与 Headless Card Service 执行，核心 Project/segments/生成学习点一致；两边随后独立导出，Note Model 合同、media manifest、card-media ledger 和 audio audit 一致，任务终态均为 100%。同一“未选择学习点”请求的 code/message/retryable/stage 也一致；Card Service 现在保留经过 allowlist/限长的 Worker stage/fallbacks，但不持久化任意 details。
- 已补齐签名 packaged runtime 的受限 TTS/APKG 等价实物：4385 项、286,933,332 bytes 的临时签名运行包在真实 Windows AppContainer、restricted token、task-owned Job 和专用 DACL 下，通过 Service-owned broker 生成整句与表达 TTS，再完成 APKG 导出；桌面与 Headless 的 Note Model、媒体清单、card-media ledger、音频 SHA/时长和任务终态一致。证明同时确认调用方输出目录未被使用、provider secret 未进入持久 JSON、运行包文件集合及 manifest `6073b8f7743fcd51a3ac599d6a7816bee4e5c582570c4517231029a197cde990` 前后不变且无 pyc/pyo。该包使用最长 24 小时、不落盘私钥的本地临时签名，只是受限运行语义证明，不是发布签名。
- 这条实物暴露并修复了四个生产边界：Service 创建的导出目录显式获得 task capability 写权限；restricted token 默认 DACL 让 Worker 新建子目录继续继承同一任务权限；托管 Windows 导出使用不可预测名称与原子 mkdir，避开 Python 3.13 `mkdtemp(mode=0o700)` 覆盖沙箱 ACL；媒体工具和输入/输出只在受信 runtime/task boundary 内做 reparse 检查。托管音频时长审计现在 fail closed，且本地审计失败不会重复发起已付费 TTS broker 调用。
- 本里程碑仍未完成：M2 的逐 OperationIntent approval ledger、撤销/原子消费和正式 profile 注册尚未实现；公网 provider 也未做真实用户凭据调用，Vertex TTS OAuth egress 仍 fail closed。完整 YouTube 视频/音频获取仍未开放，托管模式不会静默退回直接 yt-dlp；更广泛的 codec parser 崩溃/fuzz corpus、安全 Artifact 保留清理、真实视频桌面/Headless 等价、真实 Anki verify 与完整取消矩阵，以及正式发布密钥、外层 Authenticode/等价签名与正式可安装包仍在后续切片。真实候选包宿主探针证明完整被动目录能够注册并完成只读调用，但不等于插件已安装，也不等于发行者身份和供应链出口完成。
- 当前回归证据包括正式 Python `tests/` 全集 961 项通过、1 项按环境跳过，正式 Worker `unittest discover` 599 项、Vitest 830 项，以及 lint、类型检查和生产构建，以及真实受限 Legacy Worker 的模型、TTS、字幕→模型三条认证 stdio 闭环、桌面/Headless 单卡语义等价合同和签名 AppContainer TTS/APKG 等价实物；这些集合有重叠且不是整个插件完成判定。原生插件 launcher 另有 13 项 Rust 单元测试、严格 clippy 和 release 构建，托管 yt-dlp launcher 为 2 项 Rust 测试，Tauri 为 31 项通过、1 项按设计忽略。安装最终化切片的实物与负向证据见 [M1 安装最终化验证报告](M1_INSTALL_FINALIZER_VERIFICATION_2026-07-18.md)。裸 `pytest` 会误收集历史 `target/test-results/tmp` 运行包副本，因此正式范围固定为 `pytest tests`，不通过删除历史证据来获得假绿。

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

当前已完成 M2 的第一个内部切片：新增不可变 ArtifactEnvelope/RegistryRecord/handle binding 与内容寻址 Blob store。Artifact/payload 摘要使用 JCS canonical bytes，认证记录与撤销记录使用域隔离 HMAC；随机 handle 只以 SHA-256 保存，并绑定 owner、host、plugin、session 与 service instance。解析会递归复核 payload、envelope、认证记录、项目 scope、直接及传递父 revision、撤销状态和 Blob 字节，跨项目 transplant、重算摘要伪造、元数据篡改、并发撤销、secret/path 字段及 Windows 重解析目录写逃逸均失败关闭。该切片 21 项定向测试和正式 Python 全集 `982 passed, 1 skipped` 已通过。

第二个内部切片已经冻结 WorkReuseManifestV1、StableCapabilityBindingV1、AuthorizationBindingManifestV1、TaskInputManifestV1 与 SuccessorTaskRebaseV1 的服务端 canonical builder。输入 Artifact、来源快照、服务配置、能力和授权集合使用稳定排序并拒绝重复；项目语义身份明确排除 session/service/authorization/credential revision，profile validation 则把 credential revision 作为被验证输入；具体执行身份另行绑定当前 audience、授权、能力、credential revision、egress、OperationIntent、成本、批次与 successor rebase。字段突变、顺序、重复、范围扩大、secret/path 与未知控制面值由 21 项新测试覆盖，正式 Python 全集为 `1003 passed, 1 skipped`。

第三个内部切片已经实现认证 StudyTask 存储、work unit 状态机、单调进度、结构化 failure、取消终态、revision CAS、每任务 operationId 幂等账本和 scope checkpoint。任务记录与 current/.bak checkpoint 使用域隔离 HMAC、canonical JSON、no-replace/同目录原子替换和跨协调器文件锁；task 主记录损坏时不会用可能更旧的 `.bak` 回滚，checkpoint 指针则可从 `.bak` 恢复并标记任务已经前进。公开快照只签发当前会话 Artifact handle，不持久化 raw handle，也不返回 HMAC、内部 task record digest 或 project scope digest。

同一 audience 仍可原任务继续；session/service 改变时旧任务只能标记 interrupted，随后以新 audience、能力和授权创建新 taskId。successor 保持 WorkReuseDigest，重建 TaskInputManifest/SuccessorTaskRebase，只复用状态为 completed、结果非空且重新通过 Artifact 完整性/父链/scope 校验的 work unit；活动或失败单元整单元重试。稳定 profile 配置和实现不变时允许重新验证后的 credentialRevision 变化，能力变化或授权绑定集合扩大则拒绝。当前“narrower”证明只支持删除完整的 `(action, constraintsDigest, exactScopeDigest)` 绑定，尚不证明同一授权记录内部的细粒度 scope 缩小；双向 authorization audit ref 也尚未由正式 approval ledger 背书。

该切片新增 25 项测试，Artifact + manifest + task 定向集合为 `67 passed`；正式 Python 全集为 `1028 passed, 1 skipped`。覆盖 HMAC/受众/scope 篡改、checkpoint 恢复与防回滚、跨协调器 CAS 竞争、operation 冲突、非有限/倒退进度、终态、跨会话重授权、凭据 revision 轮换、范围扩大拒绝和复用产物篡改失败关闭。

第四个内部切片已经实现认证 Project Registry 与 Learning Contract 版本控制。项目创建使用 owner/host/plugin 稳定作用域和调用方 opaque idempotency key 派生不可猜测 projectId；原始幂等键不落盘，session 变化不夺走长期项目，plugin/owner/host 变化则不能读取或复用项目。项目主记录采用 canonical JSON、域隔离 HMAC、no-replace 创建、同目录原子替换、认证 `.bak` 和跨注册表文件锁；当前记录损坏时不会以旧备份静默回滚项目状态。

Project Registry 对 projectRevision 与 contractRevision 同时执行 CAS，只接受冻结的九类语义操作，不接受 JSON Patch 或任意字段路径。operationId 在 revision 检查前提供精确 payload 幂等重放；同 ID 不同 payload 拒绝。失效集合只由真正发生变化的字段决定：发现语义变化使 discovery 及下游 stale，预算变化从 selection 开始，语言变化从 planning 开始；混合 ChangeSet 中的无效 no-op 不会扩大失效范围。公开 project snapshot 不包含认证标签、scope digest、operation ledger、原始幂等键、密钥或绝对路径。30 项新增测试与 Artifact/manifest/task 联合集合 `97 passed`，正式 Python 全集为 `1058 passed, 1 skipped`；覆盖双 revision 冲突、跨注册表唯一写入胜者、幂等重放、最小失效、Unicode 规范化、作用域隔离、HMAC/备份/篡改和秘密/路径拒绝。

第五个内部切片已经实现 model/TTS OperationIntent、OperationApproval 与 InternalAuthorization 核心账本。OperationRequestManifest、project_task/profile_validation 判别 subject、逐目标 DisclosureManifest、CostBudget 和 service binding 全部先严格规范化再计算 JCS 摘要；session/service/host/plugin/OS user 任一变化都使 audienceDigest 变化。创建 intent、批准消费和逐调用消费各有独立幂等摘要，原始 idempotency/consumption/use ID 不落盘。真实决定只接受 Card Service 注入的手势 attestation verifier；未注入时默认失败关闭，普通调用不能仅凭一个摘要写入 approved。

批准只在创建 task 时原子消费一次，并在同一认证记录中签发 task-bound call_model/call_tts 授权；Task AuthorizationBinding 的五个公开字段与 Card Service 内部 authorizationId 分开。授权记录自身使用独立域 HMAC 签名，外层 intent/可变 ledger 再使用域隔离 HMAC；精确 subject、task、action、tagged resource revisions、profile configuration、credentialRevision、egress、disclosure/cost/batch 与 maxUses 均被绑定。逐调用消费同时受单授权 maxUses 与 OperationIntent 共享 remote-call 上限约束，多个 model/TTS authorization 不能放大预算；revocation epoch、过期、配置变化和并发消费均失败关闭。账本限制最长 24 小时和 2048 次远程调用，并在写入前施加 4 MiB 认证记录上限。

该切片新增 23 项测试；Artifact/manifest/task/project/authorization 联合集合为 `120 passed`，正式 Python 全集为 `1081 passed, 1 skipped`。覆盖无批准、缺失手势验签器、受众/服务/会话重放、精确幂等、共享预算、双层 HMAC、内部签名、secret/path、profile validation、非远程动作、过期/撤销、跨实例竞态和 TaskManifest 不泄露内部 authorizationId。

第六个内部切片已经把 `CredentialStore` 升级为认证的 SecretRef/credentialRevision 事务账本。真实秘密仍只保存在 OS credential backend；本地记录只包含 HMAC 派生的 opaque SecretRef、不可逆 material MAC、单调 high-water revision 与事务状态。add/replace/delete/rollback/OAuth material change 均在跨进程文件锁下执行 expectedRevision CAS；崩溃恢复分别比对 intended/previous material，失败尝试烧掉序列但不复用，无法证明的新材料进入 `uncertain` 并禁止解析。元数据使用 canonical JSON、域隔离 HMAC、文件类型/大小/稳定读取检查；旧 V1 记录迁移后立即认证。内部认证密钥也只保存在 credential backend，并按需创建，因此纯 Hermes loopback 继续保持 revision 0 与零 provider secret。

同一切片新增认证 `ServiceProfileVerificationRegistry`。每条结果绑定 capability/profileRef/configurationFingerprint/credentialRevision 与全局单调 sequence；发布时再次从受信 resolver 读取当前绑定，测试期间配置变化的结果只记为 `stale_at_publish`。同一精确绑定按最新 sequence 取结果，所以最新失败覆盖旧成功；成功默认 7 天后 stale，凭据缺失或 uncertain 分别进入 action_required/blocked。幂等 operationId 只保存 HMAC 摘要，聚合计数只用于展示。验证账本损坏时不会用 `.bak` 恢复旧成功，备份只作审计并要求重新验证。

该切片新增 21 项测试，连同 broker 与 Hermes 零凭据合同的定向集合为 `46 passed`；正式 Python 全集为 `1102 passed, 1 skipped`。覆盖 SecretRef canary、跨实例并发、失败写入序列不复用、外部替换、歧义崩溃恢复、rollback/OAuth/delete、Hermes 零凭据、配置/凭据失效、latest-failure、TTL、stale-at-publish、幂等、HMAC 篡改和旧备份不得恢复就绪。

第七个内部切片已经实现持久、非秘密的 `ServiceProfileRegistry`。model/TTS 配置复用固定 Provider Egress allowlist 与规范化 endpoint，Hermes 和 AnkiConnect 仅允许字面 loopback；所有配置使用封闭 schema，configurationFingerprint 为 canonical bytes 的纯 SHA-256。profile 创建/更新/停用使用 expectedRevision CAS 和跨进程锁，operationId 仅以 HMAC 摘要保存；历史结果已被后续 revision 覆盖时明确失败，不能返回错误的“幂等成功”。记录使用 canonical JSON、域隔离 HMAC、no-replace 创建与审计备份，并严格校验字段闭包、身份路径、revision 耗尽、操作历史及保存时凭据绑定。

Registry 的公开 profile 永不返回 SecretRef、秘密或原始 operationId；远程 profile 可先保存为 missing，再由受信设置写入秘密。每次 resolve 都实时读取 `CredentialStore`，所以凭据 add/replace/delete/rollback 或外部材料变化无需重存 profile 即使旧验证 stale；外部替换和删除都保持 `uncertain` 并阻断，不能伪装成普通 missing。Hermes 仍保持 revision 0 且不触碰 credential backend。持久 resolver 已直接接入 `ServiceProfileVerificationRegistry` 的合同测试。

该切片自身新增 34 项测试；正式 Python 全集为 `1136 passed, 1 skipped`。覆盖固定/loopback provider 规范化、secret-bearing/任意 origin 拒绝、配置指纹、CAS/并发、幂等冲突与 superseded、停用/恢复、HMAC 篡改、认证但开放结构、身份移植、revision 与 JSON 安全整数耗尽、SecretRef/operation canary、外部替换/删除 uncertain、旧备份不回滚，以及凭据变化使已通过验证立即 stale。

第八个内部切片已经实现 legacy Project 的非秘密 canonical projection。递归 sanitizer 在任何持久化调用前执行：固定顶层 Project 字段闭包，递归移除 API/TTS 配置和 secret-bearing 字段，以审计 JSON pointer 记录移除位置；http(s)、绝对/盘符相对/上级穿越路径必须逐值匹配 Resource Broker 提供的 path、kind、revision 与原值摘要绑定，替换成唯一 `$resourceSlot`，缺失、类型/值不符或未消费绑定均失败关闭。provider/model/voice 连接配置不进入 Project，只保留 model/TTS profileRef 与 configurationFingerprint 绑定。

投影保留 segments/cards、enabled、relative media name、reliability manifest、learning-point inventory、generation diagnostics 和 export 所需非秘密字段，使用固定 `legacy.project.nonsecret.v1` schema SHA-256 与 JCS Blob；SourceAsset、MediaLedger 及可选 reliability/inventory/diagnostics ArtifactRef 必须同项目、已认证、未撤销并作为父链。内部解析重新验证 Blob 摘要、canonical JSON、closed schema、资源 marker↔pointer 一致性和父引用；公开摘要不返回 Project、BlobRef、profileRef、configurationFingerprint 或 internalResourceBindingId。若最终 Artifact 发布在 Blob 写入后失败，可能留下内容寻址的“已净化孤儿 Blob”，但不会留下 raw Project、路径、URL 或秘密；统一跨 Registry 事务和安全垃圾回收仍是后续工作。

该切片新增 18 项测试，M2 八组安全组件联合回归为 `192 passed`，正式 Python 全集为 `1154 passed, 1 skipped`。覆盖 signed URL/userinfo/query、display origin 的 userinfo/query/非法端口/空白主机拒绝、Windows/相对穿越路径、字段/值 canary、marker 伪造、资源绑定缺失/错型/错值/未消费、跨项目/错 schema/撤销父引用、可选证据不一致、服务绑定闭包、Blob 篡改、深度上限、普通冒号文本不误伤，以及对外摘要不泄露内部投影。

第九个内部切片已经实现 `LocalResourceGrantRegistry`，为 `fileResourceRef`、`directoryResourceRef` 与 `outputResourceRef` 建立认证、短期、精确 audience 绑定的私有资源账本。raw path 只存在于 HMAC 认证的 Card Service 私有记录；公开摘要不返回路径、内部 grantId、attestation 或认证标签，opaque resource ref 本身也不落入记录正文，只保存不可逆引用摘要。引用解析仍要求 owner/host/plugin/session/service instance 全部一致，因此引用不是可跨会话复制的 bearer。

签发在文件快照后要求注入的 trusted gesture verifier 返回精确 audience/request/action 绑定；未注入、拒绝或异常一律在持久化前失败关闭。文件冻结 regular-file 身份、唯一 hardlink、大小、mtime 与流式 SHA-256；输入目录冻结根身份和 mtime，输出目录只冻结稳定目录身份，避免合法写入使授权自我失效。UNC、设备路径、ADS、保留名、相对路径、symlink/junction/reparse 与硬链接全部拒绝。动作和字节/条目/深度/文件数限制采用封闭 schema，消费只能等于或缩小，且有 maxUses、24 小时上限、幂等 useId、过期、显式撤销、revocation epoch、跨进程锁和 current-record 防旧备份回滚。消费后的内部对象只能为完全相同的 legacy path/kind 生成 `LegacyResourceBinding`。

该切片新增 18 项测试，M2 九组件联合回归为 `211 passed`，正式 Python 全集为 `1172 passed, 1 skipped`。覆盖无手势、四项 audience 与 service instance 越界、引用/请求/使用/attestation canary、文件替换、hardlink/symlink、路径语法、权限放大、幂等冲突、使用耗尽、过期重放、撤销、HMAC/绑定篡改、输出目录合法变更和 legacy 精确绑定。

第十个内部切片已经实现 `NetworkResourceGrantRegistry`、`networkResourceRef` 与固定地址 HTTPS fetcher。raw/signed URL 只存在于当前 Service 进程的短期 locator 内存；认证持久记录只保存 HMAC 保护的 request/query digest、脱敏 display origin、封闭策略、次数、期限和撤销状态。YouTube URL 规范化为 video ID，其他 query 保守标记为敏感；userinfo、fragment、反斜杠、畸形转义、非 HTTPS/443 和调用方 header 均在签发前拒绝。

签发、消费与每个同源重定向 hop 都重新解析全部地址，任一非公网结果即 fail closed；传输固定到已验证 IP，同时保留 TLS SNI/hostname 校验，不读取环境代理、Cookie、Authorization 或系统集成凭据。权限只能缩小，request/use 幂等、maxUses、过期、撤销 epoch、响应字节/重定向上限和 HMAC 篡改都有覆盖。raw URL 不落盘，所以 Service 重启后旧记录只能返回 `reauthorization_required`，不能自动恢复网络能力。

该切片新增 33 项测试，M2 十组件联合回归为 `244 passed`，正式 Python 全集为 `1205 passed, 1 skipped`。测试使用可控 DNS resolver 和 fake pinned transport，证明安全合同而不冒充真实公网/YouTube 可用性验收。

第十一个内部切片已经实现 `TaskResourceStager` 与带认证的本地资源 resolution proof。已消费的 file/directory grant 会在再次验证 audience、service、撤销 epoch、资源 revision、约束和当前快照后，以独占句柄、有界流复制进 task-owned workspace；Worker 只收到 workspace-relative locator，不收到原始绝对路径或 staging ref。目录递归冻结有序 manifest，逐项拒绝 symlink/junction/reparse、hardlink、保留名、非 NFC/大小写冲突、深度/条目/总字节越界，并以二次扫描拒绝复制期间变化。

私有 staging receipt 使用域隔离 HMAC 绑定 source ref 摘要、revision、task/audience/service/workspace identity、manifest 和路径；重建时同时复核 receipt、公开 proof、源授权、workspace identity 与暂存字节。生产模式要求正式 hardener，Windows 中 staged payload 对 task SID 仅授予 read/execute，Service/当前用户/SYSTEM/Administrators 保持管理权限；失败或取消不允许留下可消费的 partial。该切片新增 22 项测试，M2 十一组件联合回归为 `266 passed`，正式 Python 全集为 `1227 passed, 1 skipped`。

第十二个内部切片已经把本地资源账本和 stager 组合进 Card Service 唯一的惰性 `ServiceResourceRuntime`。资源认证 key 与 staging receipt key 由 `CredentialStore` 的 OS credential 根材料按 purpose/context 域隔离派生，不写入文件；service instance ID 仅在当前 Service 生命周期内随机生成，重启后旧授权自然失效。能力快照只返回布尔能力，不返回路径、key 或私有引用。packaged runtime 强制绑定正式 `harden_staged_path`，并禁止构造时注入任意 gesture verifier；缺少正式 hardener 时生产 staging 失败关闭。该切片的资源运行时/服务集成回归为 `70 passed`，正式 Python 全集为 `1237 passed, 1 skipped`。

第十三个内部切片已经实现真实 `local_resource_picker` 受信窗口与 Card Service 适配器。用户在独立 Tk 窗口中选择 file/directory/output directory；raw path 以 response key 域隔离派生的 AES-256-GCM 密文写入一次性响应，AAD 精确绑定 sessionRef、requestNonce 和 surface，HMAC 响应认证通过后仅在 Service 内存解密并删除响应文件。公开 session 只返回固定安全标签，绝不返回路径、密文或 attestation。5 分钟 attestation 只接受首次绑定的精确 audience/request digest，成功、过期或取消后清除内存路径；Card Service 状态根、symlink/reparse 和类型变化均失败关闭。packaged Card Service 只使用该正式 verifier，公共 MCP 仍不能注入 verifier 或 raw path。

该切片新增 10 项测试；受信窗口/资源/打包聚类为 `144 passed`，正式 Python 全集为 `1247 passed, 1 skipped`。Computer Use 已捕获真实 Windows 选择器并打开原生文件对话框，确认中文层级、范围说明、按钮、缩放和系统 dialog 正常；由于 Tk owned native dialog 未向自动化返回可操作前台 process id，自动完成文件选择没有 GUI 证据，不能用 31 项加密/Manager/Card Service 集成测试冒充真实点击闭环。

第十四个切片已建立可信 stdio audience 与最小公共资源入口。正式运行必须由已固定安装布局中的原生 `anki-study-agent` 直接启动；launcher 使用 OS CSPRNG 为每次进程生成 256-bit nonce，并把自身 PID 与 nonce 交给子进程。MCP 端消费后立即删除这两个环境值，核对父 PID、父可执行文件精确路径和当前 OS 用户 SID 摘要，再派生只在本进程有效的 host/session binding。MCP 参数不能自报 owner、host、plugin、session 或 audience；直接运行 packaged Python、伪造父 PID/路径或缺失证明均在工具注册前失败关闭。开发态只有同时显式选择 unpackaged runtime 与 trusted MCP session 才能启用同等测试入口。

可信会话现在公开 `system.request_source_grant` 与 `system.request_output_grant`。两个工具使用封闭 schema，只接受调用方幂等 `grantRequestId` 以及 source 的 file/directory 枚举；不接受 path、URL、audience、attestation、权限或 replace。Service 固定授权范围和上限，打开真实本地 picker，并把私有加密响应转换为仅含 opaque resource ref、显示名、资源 revision 摘要、约束和有效期的结果。未建立可信 audience 时，`tools/list` 只返回 `system.get_capabilities`，资源工具调用返回 Unknown tool。公开响应不含 raw path、sessionRef、密文、attestation、私有 receipt 或 staging locator。

该切片的 audience/MCP/资源/无头服务定向回归为 `74 passed`，运行时/安装包/原生 launcher 扩大聚类为 `159 passed, 1 skipped`，正式 Python 全集为 `1265 passed, 1 skipped`；原生 launcher Rust 单测为 `14 passed`。这仍不表示 M2 或 M3 已完成：新 opaque ref 尚未经 `study.register_inputs` 绑定到 StudyTask、Source Adapter 或 Worker 调度，输出 ref 尚未绑定 APKG 发布，宿主 attachment adapter、URL 输入、网络 staging、逐子项公共 ref、Anki ImportApproval 和生成/导出/导入工具仍未开放。跨进程锁仍串行化整个本地复制阶段；picker 等待期间的 stdio 调用也尚未升级为可取消长任务。
随后完成的任务来源绑定切片要求 public InputRef 的 source revision 已存在于 StudyTask input fingerprint，且 task/audience/session/service 与 `read_source` 授权完全一致；绑定只能在任务启动前创建，Worker 读取前会再次复核认证 receipt、grant 与暂存字节，并只获得 workspace-relative locator。该切片新增 11 项专测，正式 Python 全集为 `1276 passed, 1 skipped`。

CURRENT 又新增统一 `StudyRuntime` composition root 与首个项目写工具 `study.create_project`：Project/Artifact/Task/Source Binding 使用同一 service instance、同一 OS 保护主凭据派生的域隔离密钥；工具只在可信 audience 中出现，RequestContext 与 Learning Contract 为封闭 schema，相同 idempotencyKey 精确幂等，无模型、网络、来源读取或 Anki 副作用。

随后完成的 `study.register_inputs` 纵向切片只在可信 audience 中注册封闭 MCP 工具。它接受 1–64 个 file/directory opaque InputRef，把授权绑定到可恢复 StudyTask，形成 task-local snapshot、流式内容寻址 Blob/目录 manifest、认证 `study.source-asset`，再以 expectedRevision 把项目原子推进到 `sources_ready`。Artifact 精确重试会重新签发当前会话 handle；Artifact 已发布但项目尚未提交的崩溃窗口可恢复。公开结果不含原始路径、InputRef、私有 receipt、proof、staging、Worker locator 或 Registry ref；2 GiB 单文件上限在发布前失败关闭。定向扩大聚类为 `117 passed`，正式 `tests` 全集为 `1305 passed, 1 skipped`。这只证明稳定素材快照已登记，尚未证明解析完整性或适合学习。

随后完成的 source inspection 纵向切片公开 `study.start_source_inspection` 与 `study.get_source_inspection`。它在同一可信 audience 中以可恢复 StudyTask 逐来源重验 Blob，确定性解析文本、Markdown、代码、HTML、字幕与目录中的受支持成员，发布认证的 SourceRepresentation、逐来源检查和汇总 Inspection；正文保留在内容寻址 Blob，公开结果和 ContentNode 不内联来源文本。HTML 主动剥离不可见脚本类内容，字幕保留时间定位；未知或尚无安全解析器的 PDF/Office/媒体显式 C 级阻塞，超出同步上限的来源要求未来异步解析，不做无限读取。精确重试、项目提交中断恢复、跨会话隔离、Blob 篡改、Windows CRLF 二进制落盘、目录部分覆盖和公开数据泄漏均有测试。定向扩大聚类为 `95 passed`，正式 `tests` 全集为 `1324 passed, 1 skipped`。

候选质量的首个内部切片现已实现 `candidate-gates-language-v1` 确定性门禁内核。模型提案只允许语言、目标形式/类型、语义功能、路线和有界 spans，不能提交 eligibility、scores、GateResult、用户锁或控制字段。Service 重新验证 node/span 与实际表示文本，派生不含 quote 正文的 EvidenceAnchor、单一评分边界、八类 GateResult、分项分数和最终 eligibility；独立语义复核、重复、冲突与 learner fit 作为受信评审输入，不允许提案自报。span 错位不产生支持证据，Tier B/未知关系进入 needs_review，Tier C、证据/冲突/安全失败 hard block，路线/排除项不符直接 excluded。18 项新增专测和正式 `tests` 全集 `1342 passed, 1 skipped` 已通过。

紧接着的候选 Artifact 切片已经把内部闸门结果发布为 CandidateProposal/安全拒绝记录 → GateEvaluation → Discovery 的单向认证图。发布前会从认证 SourceRepresentation 读取内容寻址正文，逐条回放 node、offset、quote digest 与 evidence ID；调用方篡改 eligibility、GateResult、评分或证据摘要都会失败关闭。安全门禁失败的提案只留下无原文的拒绝摘要，不能借 Artifact/日志持久化秘密、URL 或本机路径。Discovery 只引用候选 EntityRef 和门禁 ArtifactRef，不产生不可变摘要自引用；没有推荐项是完整发现结果上的结构化 issue，不会伪装成不完整解析。该切片 11 项专测和 95 项候选/来源/Artifact/项目联合回归已通过；纳入正式全集后基线将不少于 `1353 passed, 1 skipped`。公共 `study.start_discovery`、模型批准与独立复核接线、候选列表/选择、网络来源、输出/APKG 和 Anki 链路仍未完成。

内部候选发现引擎现已进一步实现两个权限分离的模型角色：高召回提案者只能在已认证、已披露的来源窗口中指出目标形式和精确 span，独立学习复核者只能对安全提案及其有界上下文判断语义支持、冲突与 learner fit；两者都不能提交 eligibility、scores、GateResult、重复判定或用户锁。这里的“独立”指角色、提示词、输入 schema 与输出 schema 分离，尚不强制不同模型供应商。敏感节点在发送给模型前即被剔除，越界 span 失败关闭，安全失败提案只留下摘要；ProposalBatch 与 ReviewBatch 都成为候选图的认证父 Artifact。复核缺失会确定性降级为 `needs_review`，不会伪造成功。新增 10 项专测后正式 `tests` 全集为 `1363 passed, 1 skipped`。该引擎目前仍是 Card Service 内部内核；真实 Service Broker/OperationIntent/Approval 接线、可恢复 StudyTask 与项目提交、公共 `study.start_discovery`/查询/选择工具和质量基准仍未完成。

内部候选任务运行时现已把当前 Inspection、Learning Contract 修订、候选预算、模型 profile/configurationFingerprint/credentialRevision/实现版本、egress、OperationIntent、授权记录/约束/精确 scope/撤销 epoch 和成本预算全部冻结进 WorkReuseManifest、CapabilityBinding、AuthorizationBinding 与 TaskInputFingerprint。发现运行于可恢复 StudyTask，认证结果完成后再把项目从 `sources_ready` 原子推进到 `candidates_ready`；如果模型和 Artifact 已完成但项目提交中断，精确重试只重做项目提交，不重复模型调用。当前检查点粒度仍是整个 discovery 工作单元，失败任务必须显式 resume，提案/复核之间的更细粒度检查点尚未实现。7 项新增运行时测试、109 项扩展聚类以及正式 `tests` 全集 `1370 passed, 1 skipped` 已通过。该入口仍是 Card Service 内部接口：授权证明不能由 MCP 调用方自造，真实 Service Broker/Approval 解析器和公共 `study.start_discovery` 仍须接线。

受控模型接线切片现已新增任务级 `BrokerCandidateDiscoveryModelProvider`：proposer/reviewer 共用同一短期 Broker 授权和模型身份，但使用两个稳定且互异的 workUnitId；OpenAI-compatible、Anthropic 与 Gemini 请求均由 Service 重建，Provider/Base URL/model/credential 不由调用方或模型选择。模型只返回一个严格 JSON 对象；Markdown fence、重复 key、工具块、多候选/多文本段、超限 prompt/response 均失败关闭。Card Service 依据当前可信 Broker 清单、audience、project revision、inspectionHandle 与候选预算派生非秘密 OperationIntent/authorization/constraints/exact-scope/cost/egress 摘要，MCP 调用方不能提交这些字段。51 项候选/Broker/Issuer 组合测试已经通过，正式 Python `tests` 全集为 1388 passed、1 skipped。公共 `study.start_discovery` 仍未注册：当前调用会同步跨越远程模型阶段，必须先补真正的异步 start/poll/cancel/resume 合同，不能为了“看起来可用”而阻塞 stdio。

候选只读公共切片现已开放 `study.list_candidates`、`study.get_candidate` 与 `study.preview_evidence`。三个工具只接受 audience/session 绑定的 Discovery/Candidate/Source opaque handle，不接受 ArtifactRef、路径、BlobRef、模型配置或授权字段。列表提供 eligibility/route/source/query 筛选、三种稳定排序和服务认证的 query-bound cursor，单页最多 100 项；详情返回 Objective、服务端派生门禁/评分和不含正文的证据摘要；证据预览只从认证本地快照重放同一 node 内最多 480 字符上下文，再独立执行敏感披露检查，绝不远程回源。过期 Discovery、跨发现候选、跨 session handle、游标篡改/跨查询复用和相邻敏感上下文均失败关闭。67 项候选/Artifact/MCP 定向测试及正式 Python `tests` 全集 1402 passed、1 skipped 已通过。`study.start_discovery` 仍因缺少异步 start/poll/cancel/resume 而关闭。

候选组合写入切片现已开放 `study.set_selection`。显式 add/remove 与自动 `accept_recommended` 都只接受当前 Discovery 的 audience/session opaque candidate handles；同一候选的别名重复、跨 Discovery、stale revision、hard_blocked/excluded/duplicate 和 evidence/conflict/security hard gate 失败均拒绝。自动模式只纳入 recommended，并用 `portfolio-coverage-v1` 在迁移价值、路线/来源覆盖、饱和、语义重复和复习成本之间做确定性组合，不退化成简单 Top-N。结果发布为认证 `study.portfolio-selection`，项目推进到 `selection_ready`，候选查询的 selectionState 随当前选择投影；上游变化使项目回退后旧选择不再生效。`review-debt-conservative-v1` 给出低置信度复习债务，超过用户日目标产生警告而不静默删卡。该路径不调用模型、TTS、网络或 Anki，也不创建 OperationIntent；CardPlan 和生成仍未开放。该切片新增 14 项正式测试，组合回归 46 项、正式 Python `tests` 全集 1416 passed、1 skipped。

CardPlan 内核切片现已进入内部 CURRENT：`CardPlanRuntime` 从当前认证 SelectionArtifact 重新解析完整候选图与 hard gates，为 `production`、`chunk_collocation`、`reading_recognition` 三条确定性路线发布逐项 `study.card-plan`、汇总 `study.card-plan-set` 和 `study.card-plan-validation`，并将项目从 `selection_ready` 原子推进到 `plans_ready`。规则检查证据覆盖、评分边界、答案泄露、重复、冲突、模板兼容、媒体可生成性和用户锁保留；`needs_review` 计划保留但阻塞，泄露题面保留原文并阻塞，不做静默重写。需要翻译、语用/语法推断或媒体语义的路线返回 `UNSUPPORTED_CARD_PLAN`，不会降级成通用问答。该任务不调用模型、TTS、网络、Anki 或 OperationIntent；幂等结果在上游失效后不能复活。内部服务合同的 6 项 CardPlan 定向测试、31 项 CardPlan/文档组合回归和正式 Python `tests` 全集 1422 passed、1 skipped 已通过。随后可信 MCP 已开放 `study.plan_cards` 与 `study.list_card_plans`：规划输入只保留 RequestContext 与当前 selectionHandle，并将同步上限固定为 100 项，超限返回 `CARD_PLAN_ASYNC_REQUIRED`，不允许调用方注入 route、媒体、模型、授权、ArtifactRef 或路径；列表使用 service/PlanSet 绑定的认证 cursor，返回题面、核心答案、解释、证据数量、媒体策略、复习成本与八项验证状态的脱敏投影。跨 session handle、游标篡改、上游失效和不支持路线均失败关闭。首轮 18 项安全合同、修正后的真实 stdio 清单/MCP 10 项以及正式 Python `tests` 全集 1435 passed、1 skipped 均通过。随后可信 MCP 继续开放 `study.edit_card_plan` 与 `study.validate_card_plans`：四类 Agent edit schema 与 Candidate 操作完全分离，provenance/evidence/user lock 不能由调用方注入；服务保留原证据与锁、记录权威 taskId、发布同 identity 新 revision 并重放八项门禁。语义新增无法由冻结证据确定性证明时为 needs_review，评分边界破坏和未接线媒体为 failed；独立重验发布新的 set/validation revision，并覆盖任务已完成 work unit、尚未 success/commit 的中断恢复以及旧幂等结果失效。该切片完成后的正式 Python `tests` 全集为 1448 passed、1 skipped。随后受限 CardArtifact 切片已开放 `cards.generate` 与 `cards.list`：只接受当前 planSetHandle，要求每张计划八项门禁全通过且为文本/零媒体；服务发布不可变 CardArtifact、ReliabilityManifest、空 MediaLedger、SanitizedLegacyProjectArtifact 与唯一 ProjectArtifact，并把项目推进到 `cards_ready`。公共列表使用 audience/ProjectArtifact 绑定的认证 cursor，只返回学习者可见题面、答案、反馈、评分边界和验证状态。任务成功与项目提交两侧的中断恢复、幂等无重复、非规范 Base64URL/游标篡改、跨会话拒绝和真实 Legacy Worker APKG 导出兼容性均已进入 48 项聚类回归；正式 Python `tests` 全集为 1469 passed、1 skipped。首次全集捕获了 Base64URL 等价非规范末位可解码为同一签名字节的问题，Card/Candidate/CardPlan 三类游标现均执行解码后规范重编码比对，修复后的全集通过。模型/TTS/媒体生成与 Anki 写工具仍未开放。随后 APKG 纵向切片已开放异步 `cards.export_apkg`、`study.get_task` 与 `study.cancel_task`：仅接受当前认证 ProjectArtifact 与受信 outputRef，Worker 在隔离 workspace 导出，Service 独立重验完整包、SQLite note/card、模板/CSS 与身份/媒体合同，发布 PackageArtifact 图并以同盘 `.partial` + no-replace 版本化投递；项目提交窗口未闭合时不公开成功，精确重试不重跑 Worker。任务/MCP/包合同/无头服务/文档定向扩大回归为 83 项通过；正式 Python `tests` 全集为 1480 passed、1 skipped。

`anki.prepare_import` 随后进入 CURRENT：它只接受当前 PackageArtifact opaque handle，流式复核 APKG Blob，固定只读探测本机 loopback AnkiConnect，并发布认证 11 项数据验证合同与 ImportPlan。精确重试保持同一计划句柄，跨插件/旧包/离线目标失败关闭，公开结果不含 profile 名、媒体目录或 deck 名。该切片最初只建立只读计划；后续确认切片已在同一 prepare 结果上追加当前 session 的一次性 `importIntentId`，但仍不写入 Anki。新增 16 项准备契约和 1 条真实 APKG→ImportPlan 重型链已通过。



受信确认切片也已进入 CURRENT：prepare 现在为当前 audience/session 与完整 ImportPlan 创建确定性 `importIntentId`；`anki.request_import_confirmation` 只接受该 locator，并通过 digest-pinned、HMAC 响应认证的本地窗口记录真实点击。专用 ImportApproval ledger 使用服务派生密钥认证记录，精确绑定 ImportPlan/APKG/Anki target，30 分钟过期且只能原子消费一次；跨 session、聊天字段伪批准、错误 attestation、篡改、过期、目标变化和并发双消费均失败关闭。MCP 不返回手势 ref、surface session、执行 token 或内部 ArtifactRef。本切片仍不写 Anki；`anki.import_and_verify`、崩溃后的 recovery intent 和统一撤销管理器仍是下一出口。36 项确认/账本/MCP/组合根快速回归已通过，真实 APKG→ImportPlan 重型链继续单独执行。

Artifact Registry、StudyTask、Project Registry、AuthorizationLedger、CredentialStore、ServiceProfileRegistry、profile verification、legacy projection 与 local/network resource ledger 仍未形成覆盖所有写入的同一事务边界，Learning Contract 尚未发布为 canonical Artifact ref。CURRENT 已将持久 ServiceProfileRegistry 与 verification ledger 接入 Card Service，公开 `system.list_profiles`，并为已存在且需要 secret 的 profile 接入受信凭据窗口；`system.validate_profile` 现可对 exact saved model/TTS/AnkiConnect binding 执行验证，远程诊断使用受信 OperationIntent 确认、一次性批准、task-owned Broker 和单调用硬预算，AnkiConnect 使用有界 loopback 探测。完整非敏感 profile 创建/编辑事务、draft 验证，以及 discovery/generate/resume 的通用 `system.request_operation_confirmation` 接线仍未公开。正式 service key rotation、完整应用数据 ACL、Codex 宿主进程身份证明、精细 scope relation proof、完整 Broker reservation 与授权联合事务和 Anki 运行时证据链仍在后续切片。公共 MCP 在这些边界完成前仍不能接受任意 ArtifactRef 对象或扩大到通用模型/TTS/媒体生成；已经开放的确定性 `cards.generate`、`cards.export_apkg` 与显式 Anki 写入只能通过 audience 绑定 opaque handle、当前项目 revision 和受信授权。

有界 Artifact/审计查询切片现已进入 CURRENT：`study.get_artifact` 与 `study.get_audit` 只接受当前受信会话签发的 opaque ArtifactHandle，先由 Artifact Registry 重验 audience、service 与 envelope，再投影小型白名单摘要。未知 schema 为 metadata-only；来源正文、卡片全文、原始路径、任意文件、内部 ArtifactRef、registryAuthRef 与私有 receipt 都不会返回。审计证书最多投影 256 个父项并报告总数/截断状态；`integrityVerified` 只表示认证本地产物完整性和父链通过，不把数据级 Anki 检查包装成 reviewer 渲染、媒体播放、焦点或重启复习证据。

统一撤销切片现已进入 CURRENT：本地资源授权与 Anki ImportApproval 支持最多 2048 条的认证、按 audience 隔离枚举，管理窗口合并后最多显示 256 项；公开摘要不含 raw path、内部 grant ID、手势引用或账本密钥。`system.revoke_grant` 的空输入只负责打开 digest-pinned 本地授权管理器，Agent 不能提交对象引用或替用户选择。窗口请求只含随机 selectionRef 与脱敏标题/范围，resourceRef、importIntentId 和 broker authorization digest 仅存 Service 内存；真实点击结果以 AES-GCM 绑定 session/nonce/surface，再派生逐项、短期、audience-bound 撤销 attestation。ImportApproval revoke/consume 共享文件锁事务并经过竞态测试；活动 Broker 的 model/TTS/source profile 由 ReservationLedger 单次批量撤销，且先比对窗口打开时的 authorization digest，旧窗口无法撤销新授权。终态逐项报告 revoked/already-consumed/already-revoked/not-found/failed，不伪装跨 Registry 原子事务，也不把既有副作用描述成回滚。

精确 profile 验证切片已进入 CURRENT：可信 stdio 新增 `system.validate_profile` 与 `system.request_operation_confirmation`。model/TTS 首次验证只创建 immutable intent，受信窗口批准后以同一幂等键启动确定性 Task；Broker 只允许一个固定诊断调用，学习正文、来源文件和卡片内容均不在 disclosure 中。配置/凭据变化、批准撤销、并发消费、取消与 Service 重启都失败关闭，latest failed 覆盖旧 passed；AnkiConnect 只允许 Registry 中的字面 loopback 配置并执行有界版本探测。统一授权管理器也纳入同 audience 的未消费 profile-validation OperationApproval。该切片不提供 draft profile 编辑、通用网络授权或 discovery/generate 的通用操作确认。

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
- study.list_candidates、study.get_candidate、study.preview_evidence、study.set_selection（CURRENT）；study.edit_candidate（后续）。
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

### CURRENT 部分进度（2026-07-20）

- TXT/Markdown、HTML 静态快照、字幕文本和受限目录 manifest 已进入认证来源/检查链。
- 文本层 PDF 已以固定 pypdf Worker、页证据和明确遗漏完成 B 级切片。
- 本地或已冻结的音视频仅在存在受支持嵌入字幕时，以固定 FFprobe/FFmpeg Worker 形成 B 级 WebVTT 时间证据；无字幕保持阻塞。
- Podcast 已开放显式 HTTPS feed/小型直链快照，但不会自动追随 enclosure，也没有 ASR。
- DOCX/EPUB、Office、ASR、附件桥、逐适配器 golden 数量门槛和真实 1/20 张 Anki 出口仍未完成，因此 M5 不能标记完成。

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

### 14.1 CURRENT：高级开发安装隔离（2026-07-20）

- 开发安装器已经把被动 Marketplace/Plugin/Skill 与 Card Service runtime 分成两个内容寻址私有快照；Codex 配置只引用用户目录中的精确 digest，不引用可写 Git 工作树。
- Plugin 快照与 runtime 快照都执行规范 manifest、精确文件集合、逐文件 SHA-256、reparse/hardlink 拒绝、受保护 DACL 和 owner 检查；用户目录祖先的 delete-child 替换权限也进入失败关闭门禁。
- 外部开发 CPython 固定使用 `-I -S -B`，安装时扫描启动文件、标准库和所需依赖的 ACL，启动时再次检查根、关键路径和祖先。它仍是同一 OS 用户可信的开发边界，不是原生签名 bootstrap 或发布者证明。
- 安装、升级和卸载持有 Windows 跨进程互斥；同名 Marketplace、Plugin、MCP 在删除或恢复前按私有快照身份复核，失败结果包含 `partial`、`failedStep` 和 `unrecovered`。直接绕过安装器执行 Codex 配置命令不参加该互斥，仍属于显式限制。

### 14.2 提交拆分


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
