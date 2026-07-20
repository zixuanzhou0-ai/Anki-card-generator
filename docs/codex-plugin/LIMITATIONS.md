# 限制与已知风险

> 基线日期：2026-07-20

## CURRENT 能力边界速查（2026-07-20）

- 当前可信开发态 stdio runtime 已公开 38 个工具，能够完成：脱敏 profile 列表与现有 profile 的受信本地凭据管理、精确 model/TTS/AnkiConnect profile 验证、远程诊断前的受信操作确认、受信本地授权查看/撤销、项目分页找回与权威工作流快照、版本化 Learning Contract 语义更新与精确下游失效、本地/网络受支持文本授权与检查、固定 Hermes Grok 4.5 候选发现、候选发现安全恢复、候选选择、确定性文本 CardPlan 与卡片生成、APKG 导出、受信确认、真实 Anki 导入和数据级核验，以及对当前会话 ArtifactHandle 的有界产物摘要和完整性审计查询。
- 当前统一授权管理器覆盖同一受信会话的本地文件/目录/输出 grant、network grant、未消费 Anki ImportApproval、未消费 profile-validation OperationApproval 和当前 Broker model/TTS/source 授权。当前 OperationApproval 公共生产者只有 model/TTS profile 诊断，不能当作 discovery/generate 的通用授权。管理器是逐账本的明确结果集合，不宣称跨多个 Registry 的全局原子事务，也不会删除已生成产物或回滚既有远程/Anki 副作用。
- 当前来源包括本地文本、Markdown、代码、HTML、字幕文本及目录中的受支持成员，也包括匿名静态 HTTPS 网页快照、YouTube 字幕快照，以及仅在能力摘要明确可用时开放的文本层 PDF。PDF 解析是 B 级有损表示，不保留完整布局、图片或公式；源码开发态缺少签名沙箱 runtime 时会主动阻塞。视频解码/下载、任意公开视频、扫描 PDF/OCR、Office、动态或登录网页、音频/播客转写和附件桥仍未实现。
- 当前不生成模型扩写卡片、TTS 或媒体切片；CardPlan 只允许冻结证据足以确定性支持的文本/零媒体路线。
- Anki 导入最高状态为 `anki_data_verified`。实际渲染、音视频播放、复习按键和重启持久性均为 `not_assessed`，不能写成“已在 Anki 完整核验”。
- 仓库内 manifest/Skill 是被动插件源；正式发布签名、MCP 声明、安装包和 App UI 尚未交付，不能宣称插件已正式可安装或可发布。

下文历史里程碑快照中的“尚未开放”若与本节冲突，只说明当时状态，不代表当前代码。

> 状态：CURRENT 与 PROPOSED 的诚实边界
> 日期：2026-07-20
> 这里的“计划”不能在产品页面写成“当前支持”。

## 1. 当前仓库状态

- 当前产品是 Windows Tauri 桌面应用。
- 当前仓库已有 Card Service、最小 stdio MCP、原生固定 launcher、被动插件 manifest/SKILL.md、候选插件装配与完整设计文档，但尚无带正式发行签名、可安装 MCP 声明或 App UI 的发布包。
- 当前 Worker 仍是一次性 JSON 协议；Agent 不能直连 Worker。可信 Card Service MCP 已公开受限项目/来源/候选/计划、固定 Hermes 候选发现、确定性文本生成、异步 APKG 导出、任务查询/取消和受信确认后的 Anki 数据级导入核验；仍不公开 raw Worker、Shell、通用模型/TTS/媒体生成或 runtime verifier。
- source/output/network grant 已绑定 StudyTask、受支持来源快照/检查与认证 APKG 发布；异步 discovery、ImportPlan、确认和 Anki 数据写入/核验已经接线。完整媒体 acquisition、模型扩写/TTS/媒体生成、R8b runtime verifier 和正式插件安装仍缺失。
- 当前文档/知识卡能力是局部基础，不是通用 Study IR。
- 当前真实强项是语言视频、媒体、APKG 和 Anki 数据一致性核验；完整运行时渲染/播放/重启复习仍需独立版本化 verifier 证明。

## 2. CURRENT：已关闭的 APKG P0 与尚未关闭的 M0

历史问题是：immersive_v11 family 实际生成 template schema V14，而旧 verifier 用 `startswith("Anki Card Generator V1")` 判定，导致合法 V14 与伪造 V199 都会命中。当前 M0 工作分支已经移除该宽前缀路径，并完成：

- 生产 V15、V14 与明确保留的 V10 兼容模型使用精确 family/schema/Note Model ID、字段/模板/CSS 哈希和 compatibility contract；V15 额外使用模型作用域 GUID，历史 V10/V12/V14 GUID 保持不变；Note Model serializer 固定为 `genanki==0.13.1`。
- 生成、独立 `verify_apkg.py` 与生产 Anki 导入 preflight 复用同一合同注册表；完整 APKG 包合同还验证 ZIP/JSON 唯一性与限额、模型/牌组/note/card 关系、CardId/纯内容 SHA、媒体 manifest/ledger/card-media ledger 和安全展示 HTML。
- 10 个生产生成变体均以真实导出产物通过整包合同；导出采用“同目录唯一 `.partial` → 完整校验 → no-replace 原子发布最终 APKG”，目标已存在时拒绝覆盖，失败时不留下新可交付包或伪 done 状态。
- V13、V199、近似名称、非规范 ID/整数、完整字段/模板/model extras/CSS 篡改、registry 偏差、双 collection/重复关键条目与解压限额超限必须失败。
- release smoke 强制生成并核验 V14 与 V10；`verify_apkg.py` 缺失不再被跳过。
- Anki 写入路径先核对应用内部、证据完整的 raw `ExportResult`、payload 覆盖、绝对路径、实际 APKG 哈希/大小与完整包合同；失败不能进入媒体预置或 `importPackage`。这个兼容入口不认证 `ExportResult` 来源，无法抵抗能同时篡改 APKG 与 `ExportResult` 的同权限本机攻击者。媒体准备后还会在 `importPackage` 前再次 stat + SHA；这与原子发布都只缩小而不能消除 TOCTOU。M2 的认证 Artifact 注册表、不透明句柄和受控文件句柄才是公共插件写路径的信任根。
- 最终自动化回归已通过：Vitest 830、正式 `pytest` 603、独立 `unittest discover` 576、Rust 31 项通过与 1 项按设计忽略、UI smoke 3、V15/V10 release smoke、`npm run check:full` 和 `npm run tauri:build`。`pytest` 与 `unittest` 有重叠，不能相加。
- 20 卡生产 V15 离线完整合同为 20 notes / 20 cards / 52 个唯一媒体，manifest、逐媒体哈希、字幕对齐和模型作用域 GUID 闭合。它使用合成视频和静音 TTS，不是语义、听感或长期学习效果证据。
- 真实隔离 Anki 数据级验证覆盖 E→C 单卡 1/1/6、最终 V15 20 卡 20/20/52，以及 V14/V15 同字段并存；重复导入跳过，真实重启后计数、GUID、model 与逐媒体哈希不变。Computer Use 又在 Anki 26.05 中完成 20 张连续复习、翻面、焦点、滚动和四类媒体播放。正式 profile/牌组未触碰；此前合同不一致尝试仍作为 fail-closed 0 写入负例保留。
- 非 NFC、Windows 保留设备名（含 `CLOCK$`）、大小写/规范化冲突与 APKG archive 资源上限已经通过。
- 标准 Windows Anki profile 的缺失媒体恢复现在 direct-first：同一源句柄和 `mkstemp` 原句柄以 1 MiB 分块复制/计数/哈希，flush/fsync、identity 复核后 same-dir no-replace 发布；64 MiB 样本在禁用整文件读取、Base64 与 AnkiConnect 媒体 API 时通过，Python `tracemalloc` 峰值增量低于 32 MiB。
- 非标准/portable profile 与非 Windows 仍依赖整文件 Base64 的 AnkiConnect inline 兼容路径，但原始单文件上限收紧到 8 MiB；8 MiB+1 会在任何媒体 API 调用前停止。8 MiB 是协议原始媒体上限，不代表 Worker/Anki 进程峰值。
- timeout、意外后缀孤儿、部分预置和清理失败都会进入 ownership ledger；最终媒体 barrier 未闭合时禁止 `importPackage`，导入后补救失败也不能返回成功。

M0 基线、Card Service、可信 MCP、认证 Artifact/opaque handles 和 Anki 数据导入链已有实现与回归，但这些证据不等于插件已经发布。公共 APKG 路线使用认证 PackageArtifact 和内容寻址 Blob；ImportPlan、受信批准与 `anki.import_and_verify` 已闭合当前数据写入边界。仍缺少跨会话完整恢复、runtime rendering/playback/restart verifier、正式发布密钥/Authenticode 正例、生产安装包和 App UI。媒体快捷键 add-on 的历史 Anki 26.05 证据及非标准 AnkiConnect 的 8 MiB inline 限制也不能外推为通用插件 runtime 能力。

## 3. Codex 宿主

- Apps SDK 为 ChatGPT Apps 定义 Inline、Fullscreen、PiP；目标 Codex 宿主是否支持尚需逐版本实测。
- 固定右侧栏尚无本次核验到的公开稳定接口。
- V1 不能保证 UI 永久固定在右侧。
- Codex Desktop、CLI、IDE 和不同工作区的 App UI 可用性可能不同；CLI/IDE 默认按 tools-only。
- 插件更新后可能需要新任务/重启才能刷新能力。
- M3 仍必须实测目标宿主的 manifest 加载、stdio Service 启动/重连和工具注册；不能因为官方支持 stdio 就推断每个具体 Codex 版本与工作区都可用。
- 受信本地选择/确认表面若被宿主或系统策略阻止，插件只能 APKG-only，不能完成新的授权或 Anki 写入。
- 当前 stdio audience 证明固定原生 launcher 的直接子进程与当前 OS 用户，不证明 launcher 的父进程一定是某个 Codex 发行版本；正式宿主 attestation 仍是发布门槛。
- picker 工具在等待用户时占用当前 stdio 请求；超时后可用同一 `grantRequestId` 继续轮询，但 MCP 通知尚不能把该同步等待立即取消。2026-07-20 的 Computer Use 真机回归已在真实原生文件对话框中选中 `source.txt` 并返回授权；这只证明当前 Windows/Python 受信窗口路径，不替代其他 Codex 宿主和安装版验收。

## 4. 操作系统

- V1 计划 Windows-first。
- macOS/Linux 的 FFmpeg、Anki、凭据、路径和安装没有承诺。
- CLI/IDE 可能只有工具能力，没有完整 App UI。
- Codex 关闭后 V1 不保证任务继续运行，只保证安全检查点恢复。

## 5. 来源

- “Codex 可读”不等于插件可取得完整稳定附件。
- model-relayed 内容只能作为条件草稿。
- 扫描 PDF、图表、公式、复杂表格、图片和代码语义需要后续适配。
- OCR/ASR 会产生错误，低置信内容需要审核。
- 加密、DRM、损坏或无授权来源会阻塞。
- 动态/登录网页可能无法稳定快照。
- 为保证 raw URL 不进入 MCP，所有 URL（包括普通公开链接）都必须在受信本地表面重新输入；对话里粘贴的值不会被工具复制。含 signed/token/auth query 的值若已进入对话，应撤销/重新签发。
- 目录部分失败必须显式，不能保证每个文件都能处理。

## 6. 学习选择

- 模型推荐不是客观真理。
- Learning Contract 不完整会影响选择。
- 学习者模型在首版有限，无法完全知道用户已掌握内容。
- ReviewDebtEstimate 是估计。
- 自动选卡优于手动选卡是 EXPERIMENT，必须通过真实对照验证。
- 一些技能更适合 PracticeTask，不适合 Anki 卡。

## 7. 事实正确性

- 来源一致性不等于来源本身正确。
- 单一来源可能过时、偏见或错误。
- 插件首版不能承诺通用事实核查。
- external_corroboration 必须有独立来源；没有时不能被标为外部佐证。
- 冲突检测可能漏报，关键高风险资料仍需专家审核。

## 8. 模型和 TTS

- 远程服务可用性、费用、速率和政策会变化。
- 历史测试通过不代表当前 OAuth/代理可用；其他 profile 的 ready 或聚合状态不能替代当前所选 profile 的最新验证。
- 模型输出可能无效或偏离目标。
- TTS 音质和发音随服务/语音变化。
- 本地 Hermes Grok 4.5 的具体可用性依赖本地代理/OAuth，不是插件永久保证。
- `/health` 的 authenticated 只证明 Hermes 找到了 xAI OAuth，不证明 `api.x.ai` 当时可达。2026-07-20 的真实回归中，本地 8645 代理健康且 OAuth ready，但插件调用与 Hermes 官方 one-shot 都在 xAI 上游连接处超时；插件按设计返回可重试的 `MODEL_STALE`，没有生成候选或伪造成功。Hermes 当前代理实现是否遵循 Windows WinHTTP/环境代理由 Hermes 版本决定；仅配置系统代理不能被本插件当作已验证的公网连通性。

## 9. Anki

- 导入是持久写入，必须由用户明确触发。
- 不自动安装或更新 AnkiConnect。
- AnkiConnect 默认端口 8765 可能落入 Windows 动态排除端口范围；开发态 Card Service 支持由 launcher 固定其他字面 IPv4 loopback 端口（真实隔离回归使用 8785）。这不是把 APKG 限制在 Anki 文件夹或同一磁盘，输出目录与 Anki profile 可以位于不同磁盘。
- 不自动迁移已有 Note Model。
- 重复/冲突策略只能在已知 CardId/hash 边界内确定。
- 第三方 Anki 插件、定制模板或未来 Anki 版本可能影响行为。
- AnkiConnect 只能证明结构/数据，不能单独证明正背面渲染、媒体实际播放和重启复习；runtime verifier 不可用时必须停在 anki_data_verified。runtime verifier 必须使用隔离 profile 且证明调度/复习历史零写入；当前该实现尚不存在。
- 完整核验通过也只表示列明的数据与运行时检查成立，不表示学习者一定掌握。

## 10. 资源

- 大视频、长播客、批量 PDF 和 100+ 卡会占用时间、磁盘和模型额度。
- V1 可能保持单 Worker，吞吐量有限。
- 中断恢复按工作单元/批次，不能保证从模型响应中间继续。
- 资源上限会拒绝 ZIP bomb、超大文档，也可能拒绝真实极端文件。

## 11. 安全

- 插件化扩大提示注入攻击面。
- 当前桌面 UI 布尔确认不能直接用于 Agent。
- 原始路径、任意 Base URL、repair_env、load_secret、raw AnkiConnect 必须完全不暴露。
- 在内部授权记录、network/model/TTS broker、Windows 解析沙箱、逐 profile 验证和可信导入注册表完成前，插件不可发布。

## 12. 分发

- Git/个人 Marketplace 适合 V1 高级用户。
- 公开 Marketplace 可能要求生产 HTTP MCP、域名和法务页面。
- 本地 stdio 与公开目录要求存在架构张力，不能用虚假云入口绕过。
- 隐私政策、条款、许可证和支持渠道尚需在发布前确定。

## 13. 桌面端与 Web Helper

- Codex Plugin 被确定为未来主入口。
- 桌面端继续作为兼容/验证入口，不立即删除。
- docs/web-helper 是未实现的旧规划；其 file ref/job/security 概念可吸收，但“Universal UI entry”定位冻结。
- 不同时维护两套独立本地安全/任务实现；未来应共享 Card Service。

## 14. 对外措辞

可以说：

- “从经过授权且可定位的素材生成证据化卡片。”
- “验证 APKG 和真实 Anki 中的字段/媒体数据一致性；具备受信 runtime verifier 时再验证渲染、播放与重启复习。”

不能说：

- “任何文件都能百分之百正确做卡。”
- “所有事实都已验证为真。”
- “完全自动且无需任何确认。”
- “固定显示在 Codex 右侧栏。”
- “Codex 关闭后继续后台运行。”
- “支持所有操作系统和所有 Anki 版本。”
