# 实施路线图

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

- 已创建仓库内 `plugins/anki-study-agent` 被动插件包：manifest、Skill、Agent metadata 和学习/工作流/安全参考合同均通过官方 plugin/Skill 验证器与 3 项仓库合同测试。manifest 明确不声明尚未注册的 MCP/App；独立前向测试证明工具缺席时 Skill 会诚实停止，不会用 Shell 绕过或伪造 APKG/Anki 核验。该结果不等于插件已安装或 Card Service 已通过 Codex 宿主注册。
- 已实现最小真实 MCP stdio 协议桥，支持 `initialize`、`ping`、`tools/list` 和 `tools/call`，当前仅公开只读、零参数的 `system.get_capabilities`。Card Service 错误只返回限长错误码和可重试性，不回显本机路径、凭据或 Worker 细节；生成、导出、Anki 写入、凭据与通用 Worker 命令均未暴露。
- 已使用真实 Codex `0.144.1` app-server 在隔离 `CODEX_HOME` 中完成可重复宿主探针：宿主成功注册并调用上述唯一工具，确认 stdio MCP 协议版本 `2025-11-25`、`genericShell=false`、`secretBearingRequests=false`。探针不修改用户 MCP 配置，也不安装插件。仓库插件 manifest 仍保持被动，因为离开工作区可启动的外层受信 launcher、离线运行包与发布签名尚未完成；在此之前不写入会失效的 `.mcp.json`。
- 已完成受限 Card Service API、任务快照/恢复、进度/取消/超时、无通用 Shell、Worker 运行时清单、受信本地设置与授权入口、Broker 账本与 task-owned HMAC IPC。
- 已完成 Windows task-owned Job、restricted primary token、AppContainer、每任务 capability SID、runtime/task workspace 精确 DACL 和无网络 capability 的真实负面测试。
- 已完成托管运行包内层供应链边界：canonical `runtime-package-v1.json`、detached Ed25519 签名、由受信 launcher 单独提供的发布者策略、签名有效期/密钥撤销/最低版本、同 sequence 分叉与本机版本回退拒绝，以及覆盖全部运行资源的 canonical SPDX 2.3 SBOM。
- 正式 packaged mode 现在必须同时提供运行包和受信策略；运行包不能通过自带公钥建立信任。测试私钥只存在于测试代码内，仓库和运行包均不包含发布私钥。
- Python 直接依赖已改为精确版本；最终发布仍需生成带哈希的完整传递依赖锁、真实离线签名密钥流程和外层 Authenticode/等价安装包签名。
- 已把 FFmpeg、ffprobe 和 yt-dlp 绑定到签名运行包中的精确资源。托管 FFmpeg/ffprobe 只接受绝对本地普通文件，固定 `file` protocol 与显式 demuxer allowlist，拒绝 playlist、concat/subfile、网络协议、策略覆盖、reparse 输入、Shell/stdin 覆盖，并施加 300 秒上限；托管 yt-dlp 忽略外部配置和插件，禁止 exec、playlist 与 remote components，并锁定受信 FFmpeg 目录。
- 真实畸形 MP4 已在 Windows AppContainer + task-owned Job + 专用 DACL 中 fail closed；正常 WAV→MP3 和 H.264/AAC 切片仍通过。受限子进程现在真实以自己的 task workspace 为工作目录，不再以只读运行包目录为 cwd；Service 对该目录按不跟随 link/reparse 的逻辑字节与条目数实施持续预算，默认 2 GiB/20,000 项、硬上限 8 GiB/100,000 项，超限会终止任务并拒绝结果。开发模式也使用独立工作目录和预算，但只有正式 packaged DACL 模式能把它作为文件系统写边界。
- 托管 FFmpeg 现增加执行前资源证据闸门：同一命令输入合计最多 8 GiB、32 个流、12 小时，视频限制单轴 8192、每帧最多 8192×4320 像素、240 fps、300 万帧及 16 TiB 逻辑解码量，音频限制 192 kHz、8 声道及 64 GiB 逻辑解码量；FFprobe 输出、探测耗时和码率也有限。输入在探测期间变化会拒绝，所有输出统一施加 512 MiB `-fs` 硬上限，达到上限的半成品会删除。FFmpeg 参数现只允许产品实际使用的单本地输入、单最终输出语法；第二输入/输出、循环/实时参数、任意滤镜、显式输出格式和未知选项在进程启动前拒绝，`-vf`/`-af` 只接受固定缩放与音量表达式。目标必须是新文件，失败、超时、空输出和假成功不会留下可消费的半成品。
- 真实正常 WAV/MP4、真实 FFmpeg 多输出/循环参数负例、伪造极端媒体证据以及会真实写超限文件的受限 Worker 负例均通过。新增小于 1 MiB 的实物容器语料覆盖 9000 像素单轴、300 fps、超过 50000 秒的稀疏 PTS、8192×4320/240 fps/超过 1200 秒且逻辑解码量大于 16 TiB，以及 33 流扇出；五类输入都在正式 `run_ffmpeg` 解码前 fail closed 且不留下输出。逻辑解码炸弹和稀疏超长时轴的真实 FFprobe 还在 Windows AppContainer + task-owned Job + 专用 DACL 内完成探测，网络/文件系统隔离证明成立且旁侧文件未变。命令级循环、playlist 和 concat 不属于可接受语法，因此没有可进入解码器的循环命令路径；更广泛的 codec parser 崩溃/fuzz corpus 仍留在 M3。
- 同一 Card Service 进程现在原子预留全部并发任务的最坏增长，将已终止任务留下的真实占用计入默认 8 GiB/100,000 项总预算；准入、每秒运行复核和成功接纳使用 4 GiB 卷剩余空间缓冲，跌破时终止活动任务并拒绝结果。这是 process-scoped admission/periodic 闸门，不是跨 Service 进程或约束任意外部写入者的 OS 硬配额。尚未完成的边界是 M2 Artifact 注册表完成前的安全保留清理、跨进程单实例/卷级协调，以及本地输入的受控 staging/opaque file ref。
- 已实现 Service-owned Provider Egress 和任务授权闭包：Worker 只能提交 `{workUnitId, request}`，不能提交 URL、Header、profile、credential revision、operation intent 或预算；Service 重建 endpoint、模型/voice 和认证头。当前固定 OpenAI、xAI、Anthropic、Gemini、已知项目 gateway host，以及字面 loopback Hermes；任意自定义 OpenAI-compatible origin 在 M2 受信 origin 授权与连接时地址约束完成前拒绝。
- 受限 fake Worker 已通过认证 stdio 调用真实 task handler；默认传输已对临时 Hermes-style loopback 完成真实 POST 并拒绝 redirect。provider secret canary 只在 Service 传输闭包内出现，未进入任务、Broker ledger 或其他 JSON。未知真实费用按预留上限结算；发送后异常立即进入 `possible_incurred`。
- Legacy Worker 的 OpenAI-compatible、Anthropic 和 Gemini 生产模型入口已迁到受管 broker；受管模式不再因为缺少 Worker 内 API Key 而误判模型不可用。内部重试和批次重试使用确定性的独立 work unit，Worker 请求会递归拒绝 URL、Header、secret、profile、credential revision、intent 和 budget 等 Service-owned 字段。Gemini Vertex 在 Service-owned OAuth egress 完成前明确 fail closed，不允许退回 Worker 调用 `gcloud`。
- 真实受限 Legacy Worker 已通过认证 stdio 完成一次“选中学习点 → Service Provider Egress → 完整卡片项目”闭环：Worker 请求不含 API Key/Base URL，Service 覆盖 Worker model hint、注入 Service-owned credential，Broker ledger 正常 settle 且持久 JSON 无 secret canary。
- 生产 TTS 与 TTS 测试现已迁入同一 task-owned broker：Worker 只提交文本/语言/音频格式意图，Service 固定 provider、origin、model、voice、认证和预算；MIMO/Qwen/Gemini JSON 音频与 OpenAI/xAI binary 音频均返回统一的长度、SHA-256、MIME 证据，Qwen 二次媒体 URL fail closed。真实受限 Legacy Worker 已通过认证 stdio 完成一次无 Worker secret/origin/model/voice 的 TTS 测试并结算 ledger。
- 正式 stdio 启动器现已装配 Service-owned profile/intent resolver。启动清单必须是 canonical JSON、短期有效、位于固定 state dir 的 `trusted-surfaces/authorizations` 受信目录；它绑定方法→能力→profile、固定 provider/origin/model/voice、configuration fingerprint、credential revision、调用/请求/响应/成本预算与 intent ref。Card Service 在任务创建和每次 Broker 调用前复核过期及凭据版本，且拒绝任务自报 profile、revision、intent、budget、预留成本或 broker descriptor。能力摘要只暴露清单 digest/期限/计数，不暴露路径或秘密。
- 受信本地设置/确认窗口的响应通道已从“请求文件中的可读 nonce”加固为每会话一次性 HMAC：256-bit 响应密钥只经启动后的私有 stdin 交付窗口，不写 session/response 文件、不返回调用方；响应必须通过域隔离 MAC，读取 nonce 后伪造批准、篡改响应或重复启动同一会话都会被拒绝。Worker/UI 任意 details 不进入控制面。
- 已完成 M1 短期 Broker 启动授权的受信签发闭环：`system.open_broker_authorization` 只接受固定 schema 的 provider/profile、方法绑定、来源能力、有效期和硬预算；Service 解析并规范化 provider origin/model/voice，远程 profile 的 credential revision 直接从 OS 凭据元数据冻结，Hermes 固定 revision 0。可信窗口以可滚动正文展示全部授权范围，HMAC 验证真实点击后才在固定 authorizations 目录签发 canonical manifest；公开结果仅返回 digest、期限和数量，不返回路径、secret 或执行 token。调用/请求/响应/成本预算按 operation intent 在所有消费任务间合计，不能通过创建多个 task 放大。运行中的 Card Service 随后内部热加载该清单，排队任务则继续使用创建时冻结的 Broker factory，不会借用后批准的新授权。
- 已交付首个受控来源切片：正式授权清单可按方法绑定 `source.youtube_subtitles`；旧 V1 清单不含来源策略时保持兼容并默认关闭该能力。Service 只接受任务已授权的 YouTube video ID、字幕语言和 VTT 格式，固定访问 YouTube watch/timedtext 端点，解析全部 DNS 地址并拒绝任一非公网答案，连接固定公网 IP 且保留 TLS hostname 校验，不跟随重定向，并限制 watch/subtitle 响应字节和超时。signed caption query 只存在于 Service 短期内存，不进入 Worker、结果或 ledger；Worker 仅接收含有效时间 cue、长度和 SHA-256 的规范化 VTT。托管 Worker 直接运行联网 yt-dlp 会在创建子进程前 fail closed。
- 真实受限 Legacy Worker 已完成“受控 YouTube 字幕 → 本地候选 → Service 模型 Broker → 学习点结果”认证 stdio 闭环；source/model 两类 reservation 均结算，持久 JSON 不含 provider secret 或 signed caption query canary。该证明使用确定性 fake transport，不是一次真实 YouTube 公网可用性测试。
- 已增加首条桌面/Headless 语义等价合同：同一个冻结的单学习点请求分别由桌面 Legacy Worker 直调与 Headless Card Service 执行，核心 Project/segments/生成学习点一致；两边随后独立导出，Note Model 合同、media manifest、card-media ledger 和 audio audit 一致，任务终态均为 100%。同一“未选择学习点”请求的 code/message/retryable/stage 也一致；Card Service 现在保留经过 allowlist/限长的 Worker stage/fallbacks，但不持久化任意 details。该样本关闭 TTS 且不含视频，Headless 导出为隔离调度等价测试而显式关闭 restricted launcher；它不能替代受限视频/TTS、真实 Anki verify 和完整取消矩阵。
- 本里程碑仍未完成：M2 的逐 OperationIntent approval ledger、撤销/原子消费和正式 profile 注册尚未实现；公网 provider 也未做真实用户凭据调用，Vertex TTS OAuth egress 仍 fail closed。完整 YouTube 视频/音频获取仍未开放，托管模式不会静默退回直接 yt-dlp；更广泛的 codec parser 崩溃/fuzz corpus、安全 Artifact 保留清理、更多桌面/Headless 语义等价证据和正式外层插件 launcher/离线可安装包仍在后续切片。真实宿主探针只证明开发态 MCP 注册与只读调用，不等于已安装插件或正式供应链出口。
- 当前回归证据包括正式 Python 全集 870 项、正式 Worker `unittest discover` 598 项、Vitest 830 项，以及 lint、类型检查和生产构建，以及真实受限 Legacy Worker 的模型、TTS、字幕→模型三条认证 stdio 闭环和一条桌面/Headless 单卡语义等价合同；这些集合有重叠且不是 M1 完成判定。

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
