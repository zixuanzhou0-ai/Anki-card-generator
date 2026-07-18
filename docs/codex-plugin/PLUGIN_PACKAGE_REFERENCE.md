# 插件包、安装与分发参考

> 状态：CURRENT IMPLEMENTING；被动插件、签名 packaged runtime、原生 pinned launcher 和非安装型离线候选包已通过真实 Codex 宿主探针，但尚未声明可安装 MCP/App
> 日期：2026-07-18
> 实施时必须重新用当时的官方验证器核验清单字段。

## 1. 0.1 / M3 核心包形态

V1 采用一个仓库内插件包：

~~~text
plugins/
  anki-study-agent/
    .codex-plugin/
      plugin.json
    skills/
      anki-study-agent/
        SKILL.md
        agents/
          openai.yaml
        references/
    server/
      launcher/
      card-service/
        model-tts-broker/
      anki-runtime-verifier/
      local-settings/
      consent-ui/
      schemas/
    app/                    # M4 条件组件；M3 核心包可省略
      resources/
      components/
    assets/
      icon.png
      logo.png
      screenshots/
    .mcp.json
    .app.json              # M4 条件组件；M3 核心包可省略
    THIRD_PARTY_NOTICES.md
    SBOM.spdx.json
~~~

这是目标布局。当前已在 `plugins/anki-study-agent` 创建不声明 MCP/App 的被动 manifest、Skill、Agent metadata 和学习/工作流/安全参考合同；官方 plugin/Skill 验证器、仓库合同测试和一次独立前向测试均通过。前向测试在 Card Service 工具缺席时明确停止，没有使用 Shell 绕过或伪造 APKG/Anki 核验。最小 MCP stdio 桥已经通过真实 Codex `0.144.1` app-server 的开发态、签名 packaged runtime、独立复制的 pinned launcher 和完整被动候选包四类注册与调用，只公开 `system.get_capabilities`；候选包探针验证了内层签名、双层 SPDX、完整 Python lock、外层/运行时精确 DACL，以及启动前的全部资源哈希/精确文件集合。当前仍使用不落盘私钥的短期本地探针签名，launcher 也尚未获得正式 Authenticode/等价外层签名；只有正式发布公钥/私钥管理、外层签名和可安装插件宿主验证全部通过，才增加 `.mcp.json` 和 manifest 的 `mcpServers`。禁止用开发工作区路径、临时探针信任策略或空 MCP 占位文件伪造可安装状态。

职责：

- plugin.json：插件元数据和组件路径。
- skills：Agent 行为与工具编排。
- .mcp.json：本地 stdio Card Service 启动配置。
- .app.json：App/connector 映射，只有真实映射和目标宿主兼容验证完成时才写入 manifest；UI bundle 由对应 MCP App resource 提供。
- server：本地服务与共享 schema；model-tts-broker 是 Card Service 内部模块，不是公共 HTTP/MCP 工具；anki-runtime-verifier 是版本化受信 add-on/GUI protocol 适配器。
- assets：Marketplace 展示资源。
- SBOM/Notices：供应链透明。

V1 不使用 hooks。当前生成规范与验证器对 hooks 字段存在差异，实施时以实际官方 schema/validator 为准。

## 2. 建议 manifest

以下为设计示例，不可直接当作已验证发行文件：

~~~json
{
  "name": "anki-study-agent",
  "version": "0.1.0",
  "description": "Turn authorized sources into evidence-backed, verified Anki study tasks.",
  "author": {
    "name": "Project maintainer",
    "url": "https://github.com/zixuanzhou0-ai"
  },
  "homepage": "https://github.com/zixuanzhou0-ai/Anki-card-generator",
  "repository": "https://github.com/zixuanzhou0-ai/Anki-card-generator",
  "license": "SEE-LICENSE-IN-REPOSITORY",
  "keywords": ["anki", "learning", "flashcards", "codex"],
  "skills": "./skills/",
  "mcpServers": "./.mcp.json",

  "interface": {
    "displayName": "Anki Study Agent",
    "shortDescription": "Create evidence-backed Anki cards from your sources.",
    "longDescription": "Discover learning objectives, generate media-rich cards, export APKG, and verify them in Anki.",
    "developerName": "Project maintainer",
    "category": "Productivity",
    "capabilities": ["Read", "Write"],
    "websiteURL": "https://github.com/zixuanzhou0-ai/Anki-card-generator",
    "privacyPolicyURL": "https://example.invalid/privacy",
    "termsOfServiceURL": "https://example.invalid/terms",
    "defaultPrompt": [
      "把这个附件中值得长期记住的内容做成卡片。",
      "从这个视频选出 10 个值得主动表达的英语词块。",
      "继续上次中断的制卡任务。"
    ],
    "brandColor": "#245B85",
    "composerIcon": "./assets/icon.png",
    "logo": "./assets/logo.png"
  }
}
~~~

注意：

- example.invalid 是占位提醒；正式包必须替换为真实 HTTPS 隐私与条款页面。
- license 必须在开源发布前明确，不能长期保留模糊值。
- assets 引用必须真实存在。
- 本项目首版最多提供三条简短 default prompt；实施时以官方 validator 的实际限制为准。
- M3 核心示例故意不声明 apps。只有 .app.json、MCP App resource 和目标 Codex 宿主兼容实验全部通过后，M4 manifest 才增加 apps 字段。

## 3. 本地 MCP

建议 .mcp.json 使用 stdio：

~~~json
{
  "mcpServers": {
    "anki-study-agent": {
      "command": "./server/launcher/anki-study-agent.exe",
      "args": ["--stdio"],
      "env": {
        "ANKI_STUDY_PLUGIN_ROOT": "<PLUGIN_ROOT>"
      }
    }
  }
}
~~~

这是概念示例；环境变量替换语法必须以实施时官方运行器为准。

启动器要求：

- 从插件根解析资源，不依赖当前工作目录。
- 启动前先由宿主/安装器验证外层 Authenticode/等价包签名和固定发布者信任根签发的 canonical manifest。
- canonical manifest 覆盖 plugin manifest、Skill、MCP/App 映射、Card Service、model/TTS broker、Anki runtime verifier/add-on、Worker、FFmpeg、yt-dlp、schemas、SBOM 与所有资源哈希，并包含 keyId、有效期、撤销和最低允许版本。
- launcher 再按已认证 manifest 校验受管资源；仅把哈希表内嵌在 launcher 中不足以自证。
- 不从不受信 PATH 解析同名程序。
- stdout 只输出 MCP 协议；日志走受控 stderr/文件并脱敏。
- 退出前保存任务安全状态。
- 不监听 LAN。

当前原生 launcher 实现位于 `runtime-tools/anki-study-launcher`，只直接依赖锁定的 `serde_json` 与 `sha2`：

- `scripts/build_anki_study_launcher.py` 先用 Card Service 的正式验证器检查运行包 detached signature、发布者策略、SBOM 和资源，再把精确 runtime manifest SHA-256 与 trust-policy SHA-256 编入 launcher；构建固定 `--locked --offline`、禁用增量、固定 `SOURCE_DATE_EPOCH`，Windows 链接使用 `/Brepro`，不接收或读取发布私钥。
- launcher 只接受固定 `--stdio`，从自己的 `server/launcher` 位置解析插件根、`server/runtime` 与发布者策略，不读取 cwd/PATH；拒绝 symlink/junction/reparse、路径逃逸、大小写碰撞、Windows 保留名、缺失/额外文件、size/SHA-256 不符和错误的策略摘要。
- launcher 在启动 Python 前流式复核 manifest 固定的全部 4380 项资源与精确文件集合，缓冲区位于堆上；随后只启动已验证的包内 Python，固定 `-E -s -B -m card_service.mcp_stdio`，移除 Python 路径覆盖变量并继承 stdio，不监听端口。
- 受限宿主可能移除 `PROCESSOR_ARCHITECTURE`，便携 Python 的 `platform.machine()` 会因此返回空值。未来运行包从 Python 自身的 `sysconfig` 构建标签判定平台；当前已签名运行包由受信 x64 launcher 固定设置 `PROCESSOR_ARCHITECTURE=AMD64` 并清除 WOW64 覆盖，避免把受限环境误判为 `windows-`。
- 平台修复后的两个全新隔离 target release 构建均为 308,736 bytes、SHA-256 `c11b912b0590c406aef361400820e776ae7d009b85c8b7019f2e912d9caed3c3`。替换 trust policy 或首个运行资源均在 Python 启动前以退出码 125 拒绝；独立复制目录通过官方 plugin validator，并在全新 `CODEX_HOME` 中由真实 Codex `0.144.1` 完成只读工具调用。
- 这些证据证明 launcher 代码、离线构建和独立副本路径成立，不证明发行者身份。正式 Authenticode/等价安装包签名、发布私钥保管、撤销与最终安装器验证仍是启用 `.mcp.json` 前的硬门槛。

`scripts/build_plugin_release_candidate.py` 是当前外层候选包的唯一装配入口：

- 输入只允许通过官方验证的被动插件根、原生 launcher、已签名 runtime 和独立 trust policy；检测到 `.mcp.json`、`.app.json`、`mcpServers`、`apps` 或源插件自带 `server/` 时立即拒绝。
- 输出固定生成 canonical `release-package-v1.json` 和根级 SPDX 2.3，逐文件覆盖插件、launcher、runtime manifest/signature、trust policy 和全部运行资源；拒绝路径逃逸、reparse、Windows 保留名、大小写碰撞、缺失/额外文件、源文件复制中变化和已有输出覆盖。
- 外层插件树使用当前用户、SYSTEM、Administrators 的受保护精确 DACL；`server/runtime` 再使用固定 runtime AppContainer SID 的只读执行 DACL。装配前后逐项读回验证，防止普通复制破坏 sandbox 边界。
- 实物候选包含 4391 个资源、289,210,657 bytes；外层 manifest SHA-256 为 `9ab03b75dc2a0c2197e280fdd47a9f9a83c2fe25fc786459822cfcbf23f262d6`。它在普通权限下通过官方 plugin validator，并由真实 Codex `0.144.1` 从候选目录完成唯一只读工具调用。
- 候选 manifest 与 CLI 固定报告 `installable=false`、`mcpDeclared=false`、`outerSignatureVerified=false`、`publisherKeyManaged=false`；构建不接收私钥、不联网、不生成 MCP/App 映射。它是发行结构证据，不是可安装发布物。

M1 托管运行包的内层合同已经固定为：

- `workers/requirements-win-cp313.lock` 固定 CPython 3.13 / cp313 / win_amd64 的 25 个直接和传递 wheel 版本与 SHA-256。`scripts/generate_python_runtime_lock.py` 从 wheel METADATA/WHEEL 生成锁并拒绝 sdist、非 wheel、重复包、根版本不符、平台不兼容和哈希变化；锁本身是必需的签名运行资源。
- `scripts/assemble_managed_python.py` 只从该锁和精确 wheelhouse 以 `--no-index --require-hashes --only-binary` 组装便携 CPython；排除 ambient site-packages、Scripts、FFmpeg 和缓存，禁用并拒绝 pyc。组装元数据 `python-runtime-build-v1.json` 以有界 canonical JSON 记录 Python identity、lock digest、wheel 数和无网络事实，不记录构建机路径；发布前会再次验证该元数据与实际锁的 SHA-256/条目数以及便携目录结构。
- `scripts/build_managed_runtime.py` 是当前唯一正式 staging 入口：要求显式 output/version/UTC build time/repository root/预装配 Python root/Python lock/FFmpeg/ffprobe/yt-dlp，先拒绝与锁不匹配、含 Scripts/pyvenv/pyc 或缺少 build metadata 的 Python root，再离线收集并原子发布一个**未签名**目录。`python-runtime-build-v1.json` 使用固定资源 ID `managed-python:build-metadata` 纳入 SBOM 和签名 manifest；运行包加载器还会把其中的 lock digest/wheel 数与 `metadata:python-runtime-lock` 交叉验证。Card Service 与 Worker 固定打包为顶层 `card_service/` 和 `workers/`，正式启动不依赖 `PYTHONPATH`。构建器拒绝已有输出、reparse 源、路径逃逸、大小写碰撞、Windows 保留名、缺失资源和超限 manifest/SBOM；同一输入生成稳定的 namespace、资源排序和摘要。
- 构建阶段故意不接受私钥。发布流水线必须在仓库外对 canonical manifest 完成 detached 签名，再由外层受信 launcher 提供独立 trust policy；测试私钥不得用于正式包。
- `runtime-package-v1.json` 是 canonical JSON，绑定 package identity/version、Card Service 最低兼容版本、目标平台、SPDX 2.3 SBOM 声明和全部运行资源的 size/SHA-256。
- `runtime-package-v1.sig.json` 是 detached Ed25519 签名；签名覆盖 authority、keyId/keyEpoch、签发/过期时间和 manifest digest，并使用 `study.runtime-package-manifest.v1` 域隔离。
- 发布者 trust policy 不得放进运行包自证；它必须由已经受信的 launcher/外层发布物单独提供。正式 `--runtime-package` 模式缺少 `--runtime-trust-policy` 时 fail closed。
- trust policy 固定 authority、单调 sequence、精确 32-byte 公钥及其 SHA-256、active/revoked 状态、最低运行包版本和撤销版本。相同 sequence 不同 digest、较低 sequence、低版本和同版本不同内容均被拒绝。
- `metadata/SBOM.spdx.json` 必须是 canonical SPDX 2.3，并逐文件覆盖 manifest 中除 SBOM 自身外的全部资源；SBOM 与 manifest 任一不一致都拒绝启动。
- manifest、SBOM、detached signature、trust policy 和本地 anti-rollback floor 均在解析前执行 stat + 有界读取；仅在读取后判断长度不满足该边界。
- `scripts/create_ephemeral_runtime_probe_signature.py` 只用于本地宿主探针：每次生成随机 Ed25519 密钥，最长有效 24 小时，只写公钥策略和 detached signature，绝不写私钥；它不能进入发布包或替代真实发布密钥。
- 当前最新实物 packaged 探针包含 4380 项、286,759,977 bytes，manifest SHA-256 为 `3ba6c9ea3cdb8c2c945df22aff817d5872bee1f1627f0931315e65ba915ca0b2`；真实 Codex `0.144.1` 在隔离且禁用无关 plugin/remote-plugin 同步的宿主中成功调用唯一只读工具，并确认 `signatureVerified=true`、`runtimePackageDacl=true`。该证据只证明内层包及 Python-lock 组合可启动；在外层插件安装包签名、真实发布密钥保管和独立复制后的可安装插件验证完成前，能力摘要继续报告 `complete: false`。

M1 媒体运行时在该签名包内进一步要求：

- manifest 必须包含 Worker 的 `acg/media_tool_policy.py` 以及精确 `managed-tool:ffmpeg`、`managed-tool:ffprobe`、`managed-tool:yt-dlp` 资源；Card Service 只把这三条已验证绝对路径交给受限 Worker，正式模式不回退到 PATH。`managed-tool:yt-dlp` 是无第三方 Rust 依赖的相对定位启动器，只执行同一包内 `python.exe -I -B -m yt_dlp`，拒绝 build machine 上由 pip console script 写死的系统 Python。
- FFmpeg/ffprobe 命令由 Worker 内部策略构造：只允许本地普通文件输入、固定 `file` protocol、固定 demuxer allowlist、禁止 playlist/concat/subfile/网络协议与策略覆盖，且无 Shell、无交互 stdin、超时有界。工具、输入和输出路径逐级拒绝 symlink/junction/reparse ancestor，并拒绝 UNC、NT 设备与 ADS 路径形式。
- 托管 FFmpeg 在启动前以受限 FFprobe 证据冻结输入总字节、流数、时长、码率、分辨率、像素、帧率/帧数、采样率、声道和逻辑解码量；原始 PCM 根据显式格式/采样率/声道及文件大小计算，不允许用缺失容器元数据绕过。输入探测中变化或证据未知即拒绝；输出固定 512 MiB `-fs` 上限，触顶半成品删除。命令合同严格限制为一个本地普通文件输入和一个新的最终输出；多输入/多输出、循环/实时参数、未知选项、任意滤镜和显式输出格式在启动前拒绝，滤镜只允许产品固定缩放与音量表达式。非零退出、超时、空输出或成功但未产出文件都会清理本次创建的普通文件并 fail closed。每个任务另有独立 cwd；Service 对其实施不跟随 link/reparse 的总逻辑字节和条目预算，默认 2 GiB/20,000 项、硬上限 8 GiB/100,000 项，最终成功前再次复核。Service 级准入在同一进程内原子计算 retained actual + active worst-case headroom + proposed task，默认总上限 8 GiB/100,000 项；准入、运行中每秒复核和成功接纳使用 4 GiB 卷剩余空间缓冲，容量证据不足或跌破缓冲线时 fail closed。能力摘要固定报告 `aggregateWorkspaceBudgetScope=service_process`、`volumeFreeSpaceReserveEnforcement=admission_and_periodic` 与 `externalWriterHardQuota=false`；它不声称跨多个 Service 进程原子，也不声称限制任意外部写入者。正式 packaged DACL 模式将该目录同时作为唯一受权写边界；开发模式的目录预算不等同于文件系统隔离。终态工作区在 M2 Artifact 引用/保留合同完成前不会自动递归删除，因此真实占用持续计入总预算。小于 1 MiB 的真实极宽、高帧率、稀疏超长时轴、逻辑解码量大于 16 TiB 和 33 流容器已经证明预检在解码前拒绝；其中两类真实探测在 AppContainer + Job + DACL 内完成。命令语法不接受循环/playlist/concat，后续仍需更广泛的 codec parser 崩溃/fuzz corpus、跨进程协调与 M2 输入 staging。
- yt-dlp 强制 `--ignore-config`、禁用插件目录、exec、playlist 和 playlist 元数据，并固定受信 FFmpeg 目录；正式托管模式即使请求显式要求也拒绝 remote components。
- Service 已增加窄范围 `source.youtube_subtitles`：正式启动授权按方法绑定该能力，Worker 只提交任务已授权的 YouTube video ID、字幕语言和 VTT 格式；Service 固定 watch/timedtext host/path，解析全部 DNS 地址并拒绝非公网答案，连接固定公网 IP并保留 TLS hostname 校验，不跟随重定向，限制响应字节/超时，且不把 signed caption query 交给 Worker 或持久化账本。
- 托管 Worker 直接运行联网 yt-dlp 会在子进程启动前 fail closed。当前只交付无视频/原声音频的字幕-only 学习点抽取；完整 URL 视频/音频 acquisition、M2 opaque networkResourceRef 和逐操作批准账本仍未交付，不能把插件视频 URL 制卡描述为已完成。

M1 Provider Egress 的当前内层边界为：

- Worker 的认证 task-owned IPC 只接受固定 operation 与 `{workUnitId, request}`；profile、origin、endpoint、model/voice、credential revision、operation intent、预算和每调用预留成本全部来自 Service 内部授权闭包。
- Service 对 OpenAI/xAI/Anthropic/Gemini、项目已知 gateways 和 Hermes 分别重建固定请求；禁止 tools、任意 Header、任意 endpoint、流式响应和重定向，禁用 ambient proxy，并对请求字段、prompt/TTS 长度、超时和响应字节设上限。
- 生产 TTS 与 `test_tts` 已进入同一 task-owned broker。Worker 只提交规范化文本、BCP47 语言、目标 MP3、采样率和码率，不得提交 provider、origin、model、voice、Header、credential 或预算。Service 端分别固定 OpenAI Speech、xAI TTS、MIMO audio chat、Qwen multimodal TTS 与 Gemini inline PCM 适配器；返回音频必须通过 Base64、长度、SHA-256、MIME 与 PCM 采样率校验。
- Qwen 只有内联音频可进入任务结果；provider 返回二次 URL 时以 `TTS_SECONDARY_URL_BLOCKED` 失败，Worker 不再自行下载。受管 Vertex TTS 在 Service OAuth egress 完成前继续 fail closed。
- Hermes 只允许字面 `127.0.0.1`/`::1` 的显式 HTTP origin，使用 credential revision 0；远程服务必须 HTTPS。任意自定义 OpenAI-compatible origin 在 M2 的受信 origin authorization 和连接时 IP 约束完成前 fail closed。
- Legacy Worker 的 OpenAI-compatible、Anthropic 和 Gemini 模型入口已接入该通道；受管请求递归拒绝 URL/Header/secret/profile/credential/intent/budget，批次和内部重试使用确定性的独立 work unit。Gemini Vertex 在 Service-owned OAuth egress 完成前 fail closed。
- 正式 stdio 支持 `--broker-authorization-manifest`，但只接受固定 Card Service state dir 下 `trusted-surfaces/authorizations` 的稳定普通文件，不接受工作区或调用方任意路径。清单必须是 canonical `study.card-service.broker-authorization` V1，短期有效并绑定方法、能力、profile configuration fingerprint、credential revision、intent ref 和硬预算；任何未知字段、过期/超长期限、能力错配、陈旧凭据或任务自报授权字段都 fail closed。Service 能力摘要只公开清单 digest/期限/计数。正常 tools-only 路径不要求调用方提供该内部路径：`system.open_broker_authorization` 启动受信确认窗口，真实点击通过 HMAC 验证后由 Service 在固定目录签发并热加载，调用方只收到脱敏摘要。
- 真实受限 Legacy Worker 已通过认证 stdio 完成无 Worker API Key/Base URL 的卡片生成，以及无 Worker API Key/Base URL/model/voice 的 TTS 测试；Service 重建模型或声音请求、注入认证、验证音频证据并结算 ledger。当前默认传输仍只对临时 Hermes-style loopback 做过真实 POST；公网 provider 未使用真实用户凭据验证，M2 逐操作批准/撤销/消费账本尚未完成，因此 `modelTtsBroker.complete` 仍为 false。

## 3.1 受信本地设置与确认表面

server/local-settings 是最小本地凭据配置窗口；server/consent-ui 是文件/目录、网络、输出、模型/TTS 数据出域、成本/批量 OperationIntent 和 Anki 写入的受信确认窗口。它们不是完整桌面制卡应用，但必须：

- 由 Card Service 从受信绝对路径启动。
- 绑定 OS 用户、plugin instance、session 和 request ref。
- 直接与本地 Service/OS 凭据存储通信，秘密不经过 MCP/模型。
- 将真实用户手势写入服务端 approval ledger。文件/目录/网络/输出可返回受会话约束的资源 handle；模型/TTS/成本/批量确认只返回 operationIntentId 的 approvalState；Anki 确认只返回 importIntentId 的 approvalState，均不返回执行 token/ref。
- consent-ui 同时提供受信授权管理器：直接从 Service 读取脱敏的资源授权、OperationApproval 和 ImportApproval，允许用户在消费前逐项撤销；撤销/消费原子互斥，MCP 只收到结果摘要，不接触内部 authorization/ledger ID。
- 能从 tools-only 宿主启动；若宿主/系统阻止启动，对应高影响操作 fail closed。

当前 M1 受信窗口启动器已经固定 Python/UI 绝对路径和 UI SHA-256，并把响应改为每会话一次性 HMAC：响应密钥只经私有 stdin 交付 digest-pinned 子进程，不落盘、不进入调用结果；Service 在接受 user gesture 前验证域隔离 MAC 与 session/nonce，并拒绝重复启动。短期 broker authorization 现由同一受信窗口展示规范化 profile/origin/model/voice、方法、来源、期限和预算，批准后由 Service canonical 签发并内部热加载；远程 credential revision 从 OS 凭据元数据冻结，公开结果不含路径或 secret。正式 profile 注册目录及 M2 approval ledger 仍是后续边界。

M1 实现窗口与启动器，M2 实现授权账本、过期/撤销/重放保护；M3 首次使用旅程以此为前提。
## 4. Skill 包

SKILL.md 必须包含：

- 用户意图到高层工具的决策树。
- Learning Contract 的推断与最小询问规则。
- 权限、成本和 Anki 导入确认规则。
- 不可信来源和提示注入规则。
- 部分失败、取消、中断和恢复措辞。
- 严禁宣称未经服务证明的“已生成/已核验”。

Skill 不包含：

- API Key。
- 内部绝对路径。
- 通用 Shell 指令。
- 可以绕过 MCP 服务的备用写路径。
- 卡片可靠性算法的唯一实现。

Skill 详细行为将在实现阶段从 [产品规格](PRODUCT_SPEC.md)、[学习设计](LEARNING_DESIGN.md) 和 [MCP 工具参考](MCP_TOOL_REFERENCE.md) 生成合同测试。

## 5. App UI 包

PROPOSED App UI 采用 MCP Apps resource 和宿主桥接；在 M4 前必须先证明目标 Codex 宿主能把插件内 stdio MCP 与 App resource 连接。

- Inline：摘要和主动作。
- Fullscreen：候选、证据、卡片计划和诊断。
- PiP：长任务进度和恢复。

UI bundle 由 MCP App resource 提供，.app.json 仅承担经官方 schema 验证的映射。兼容实验通过前 manifest 不写 apps；失败时保持 tools-only，或另行评审独立 App/托管 MCP。UI 使用 structuredContent，不解析模型自然语言，也不能假设固定右侧栏存在。

官方参考：

- [Apps SDK UI guidelines](https://developers.openai.com/apps-sdk/concepts/ui-guidelines#display-modes)
- [MCP Apps host bridge](https://developers.openai.com/apps-sdk/mcp-apps-in-chatgpt#host-bridge)

## 6. 版本轴

必须分开：

| 版本 | 作用 |
|---|---|
| plugin semver | 插件包、Skill、MCP/App 兼容 |
| MCP protocol | 工具 schema 和错误语义 |
| Study IR schema | 领域产物格式 |
| Card Service | 本地运行时实现 |
| Worker protocol | 现有 Python 子进程协议 |
| card template family | 产品卡片家族，如 immersive_v11 |
| template schema | 当前模板实现版本，如 V15 |
| Anki Note Model ID | Anki 中稳定模型身份 |

不能再用“卡片 V11”同时指代 family、schema 和 Note Model。

## 7. 操作系统和依赖

### V1 支持承诺

- Windows 首发。
- Codex Desktop 为首要宿主；CLI/IDE 的无 UI 工具体验按实际验证声明。
- Anki 与 AnkiConnect 的精确版本范围在发布前由兼容矩阵确定。
- Python、FFmpeg、yt-dlp 等优先受管/捆绑，不要求用户随意修复 PATH。

### 不承诺

- macOS/Linux 完整媒体与 Anki 闭环。
- 没有本地运行时仍能生成视频/TTS/APKG。
- 插件自动继承所有桌面端凭据。
- 自动安装依赖。

## 8. 安装与首次使用

首版 Git/个人 Marketplace 路径：

1. 用户从可信仓库/Marketplace 安装插件。
2. 用户或发布脚本按项目发布说明验证包 SHA-256、发布者签名、manifest 和兼容范围；只有未来实现受信安装器后，才宣称自动验证。
3. 新任务/重启 Codex 以刷新 Skill 和工具目录。
4. 首次调用只读 capability check。
5. 缺依赖时展示精确组件和受信来源；V1 插件不自动安装或修复，用户在插件外完成后重新运行只读检查。
6. 模型/TTS 凭据在本地受信流程配置，Codex 只得到 profile ref 和 secret_exists。
7. 生成第一张卡，分别取得 Anki 数据完整性证书与受信 runtime verifier 的真实渲染/播放/重启复习证据。

实际命令以发布时 Codex 官方文档为准，不在设计文档中冻结可能变化的 CLI 语法。

## 9. 升级与回退

- 升级前保存插件版本、Service 版本、Study IR 版本和当前任务检查点。
- 安装新版本后先运行只读迁移预检。
- 产物迁移采用 copy-on-write；旧产物保留到验证通过。
- 运行中任务不原地跨版本继续，标记 interrupted 并由兼容适配器恢复。
- 失败时恢复旧插件和 Service；不回滚用户生成的 APKG/Anki 牌组。
- Note Model 迁移是独立高影响操作，V1 不自动执行。

## 10. 卸载

卸载默认：

- 移除插件代码和注册。
- 不删除 APKG、来源、Anki 牌组或项目数据。
- 提供可选的本地数据清理说明和预览。
- 凭据删除为独立、明确确认动作。

## 11. 分发阶段

### 阶段 A：开发者本地

- repo 内 plugin 目录。
- 本地 Marketplace。
- 固定构建输入和开发签名。

### 阶段 B：Git 仓库分发

- tag/commit 固定来源。
- 发布 SHA-256、SBOM、签名和变更日志。
- 高级用户手动安装。

### 阶段 C：公开插件提交门户/公开插件目录

公开提交前需要重新核验官方要求。当前官方资料显示，含 App/MCP 的公开提交通常要求生产 MCP；skills-only 插件不应被错误套用同一要求。含 App/MCP 的提交通常还要求：

- 可公开访问的生产 MCP URL。
- 域名验证。
- 隐私、支持和服务条款。
- 正确工具注解。
- 五个正向和三个负向测试案例。

V1 本地 stdio 设计不应为了公开目录而过早引入云服务。先证明本地产品闭环，再设计配对的本地执行器与托管控制面。

参考：[Submit plugins](https://learn.chatgpt.com/docs/submit-plugins)。

## 12. 供应链发布清单

- 插件包可复现构建。
- 固定发布者 trust root 签署 RFC 8785/JCS 规范化 release manifest；外层安装资产使用 Authenticode/等价包签名。
- manifest 覆盖 plugin.json、Skill、MCP 配置、App 映射、Service、Worker、FFmpeg、yt-dlp、schemas、SBOM、许可和全部资源哈希。
- manifest 记录 plugin/service/worker/schema 版本、keyId、签名时间、有效期、撤销信息、最低允许版本和兼容范围。
- Service/Worker/外部二进制固定版本与 SHA-256；Python 依赖锁定版本和哈希。
- launcher 只能在外层与 manifest 验证通过后启动，并按 manifest 校验资源；launcher 与内嵌 hash 表一起被替换也必须失败。
- 禁止发布时或运行时动态下载可执行远程组件。
- 回退只允许仍在签名允许清单中的版本，拒绝撤销密钥和版本降级。
- CI 进行秘密扫描、依赖审计、launcher+payload+hash 表联合替换、撤销密钥和降级包测试。
- 不使用 curl-pipe-shell 或 repair_env。

## 13. CURRENT M0 合同状态与打包边界

历史 V1 + `startswith` 宽前缀会同时接受合法版本与伪造 V199。M0 已将其替换为精确 family/schema/Note Model ID、字段/模板/CSS 与 compatibility contract，并将生产 V15/V14、明确兼容的 V10、V15 模型作用域 GUID、固定 `genanki==0.13.1` serializer、完整 APKG 包合同、10 个生产生成变体、原子发布、伪版本/篡改负例、强制 release verifier 和 Anki 写入前整包 preflight 纳入门禁。该固定不等于第 12 节要求的全依赖版本+哈希锁定已经完成。

最终自动化为 Vitest 830、正式 `pytest` 603、独立 `unittest discover` 576（有重叠，不相加）、Rust 31 项通过与 1 项忽略、UI smoke 3、V15/V10 release smoke、`check:full` 与 Tauri build 通过。V15 20 卡包为 20/20/52；真实隔离 Anki 核验覆盖单卡、V15 20 卡重复/重启、V14/V15 同字段并存，Computer Use 覆盖 Anki 26.05 的 20 张连续复习和四类媒体。合成视频与静音 TTS 不是真人语义、听感或长期学习效果证据。内部 raw `ExportResult` 仍不认证来源；正式插件包必须等 M2 认证 Artifact 注册表、不透明引用和受控文件句柄建立后，才能把导入工具暴露给 MCP。

这个完成项不能外推为插件包已经可用：

- 当前已有仓库内被动插件/Skill 包，以及经过真实 Codex app-server 注册与调用验证的开发态只读 stdio MCP；仍没有离开仓库可启动、经过安装与宿主验证的正式插件包，也没有 App resource。
- M1 Headless Card Service 已完成受限任务、AppContainer/DACL、认证 broker IPC、签名运行包及本地媒体策略的若干切片，但完整 M1 出口尚未满足；M2 Artifact/授权边界和插件侧通用 Anki runtime evidence 适配器仍未实现。M0 交付的仍只是受精确合同约束的 Anki 26.05 媒体快捷键桥。
- 非 NFC、Windows 保留设备名（含 `CLOCK$`）、规范化冲突与 APKG archive 资源上限已通过；有界流式读取覆盖 APKG archive/package/verifier 与标准 Windows Anki direct-first 媒体路径。非标准/portable profile 的 AnkiConnect inline 兼容路径仍整文件/Base64，但原始单文件上限为 8 MiB；8 MiB 不是进程峰值。
- M0 的 Computer Use、GUI 翻面/媒体播放和 20 张连续复习出口已经通过；完整边界见 [M0 验证报告](M0_VERIFICATION_REPORT_2026-07-17.md)。
- 被动 Skill 不等于运行时可用；M1–M3 的 Headless Service 出口、认证 Artifact/授权边界、stdio MCP、宿主注册和可安装包出口满足前，不得声明 Codex 插件已经复用完整 APKG → 真实 Anki 发布闭环。

## 14. 包验收

- 官方 validator 通过，无占位 URL/字段。
- M3：新任务能发现 Skill 和全部 MCP tools，manifest 不声明 apps。
- M4 条件验收：只有目标 Codex 宿主兼容实验通过后，才要求发现与工具映射正确的 App resources。
- 卸载后不会删除用户学习数据。
- 插件启动不依赖开发工作区。
- 无受信二进制从 PATH 被劫持。
- 离线时本地功能按能力矩阵工作。
- 版本不兼容时 fail closed 并提供回退。
- 首次和升级安装均通过真实 Windows、Codex、Anki 测试。
