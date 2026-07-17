# 插件包、安装与分发参考

> 状态：PROPOSED 打包设计，当前仓库还没有 Codex 插件包
> 日期：2026-07-17
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

这是目标布局。M0 完成后先创建不声明 MCP/App 的被动插件与 Skill 骨架；只有真实 stdio 服务至少提供 system.get_capabilities、通过宿主注册测试后，才增加 .mcp.json 和 manifest 的 mcpServers。禁止用空 MCP 占位文件伪造可用状态。

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

M1 托管运行包的内层合同已经固定为：

- `runtime-package-v1.json` 是 canonical JSON，绑定 package identity/version、Card Service 最低兼容版本、目标平台、SPDX 2.3 SBOM 声明和全部运行资源的 size/SHA-256。
- `runtime-package-v1.sig.json` 是 detached Ed25519 签名；签名覆盖 authority、keyId/keyEpoch、签发/过期时间和 manifest digest，并使用 `study.runtime-package-manifest.v1` 域隔离。
- 发布者 trust policy 不得放进运行包自证；它必须由已经受信的 launcher/外层发布物单独提供。正式 `--runtime-package` 模式缺少 `--runtime-trust-policy` 时 fail closed。
- trust policy 固定 authority、单调 sequence、精确 32-byte 公钥及其 SHA-256、active/revoked 状态、最低运行包版本和撤销版本。相同 sequence 不同 digest、较低 sequence、低版本和同版本不同内容均被拒绝。
- `metadata/SBOM.spdx.json` 必须是 canonical SPDX 2.3，并逐文件覆盖 manifest 中除 SBOM 自身外的全部资源；SBOM 与 manifest 任一不一致都拒绝启动。
- 运行包签名只完成内层资源认证；在外层插件安装包签名、真实发布密钥保管、完整传递依赖哈希锁和可复现构建完成前，能力摘要继续报告 `complete: false`。

## 3.1 受信本地设置与确认表面

server/local-settings 是最小本地凭据配置窗口；server/consent-ui 是文件/目录、网络、输出、模型/TTS 数据出域、成本/批量 OperationIntent 和 Anki 写入的受信确认窗口。它们不是完整桌面制卡应用，但必须：

- 由 Card Service 从受信绝对路径启动。
- 绑定 OS 用户、plugin instance、session 和 request ref。
- 直接与本地 Service/OS 凭据存储通信，秘密不经过 MCP/模型。
- 将真实用户手势写入服务端 approval ledger。文件/目录/网络/输出可返回受会话约束的资源 handle；模型/TTS/成本/批量确认只返回 operationIntentId 的 approvalState；Anki 确认只返回 importIntentId 的 approvalState，均不返回执行 token/ref。
- consent-ui 同时提供受信授权管理器：直接从 Service 读取脱敏的资源授权、OperationApproval 和 ImportApproval，允许用户在消费前逐项撤销；撤销/消费原子互斥，MCP 只收到结果摘要，不接触内部 authorization/ledger ID。
- 能从 tools-only 宿主启动；若宿主/系统阻止启动，对应高影响操作 fail closed。

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

- 当前仍没有经过安装与宿主注册验证的正式插件包、stdio MCP 或 App resource。
- M1 Headless Card Service、M2 Artifact/授权边界，以及插件侧的通用 Anki runtime evidence 适配器仍未实现；M0 只交付了受精确合同约束的 Anki 26.05 媒体快捷键桥。
- 非 NFC、Windows 保留设备名（含 `CLOCK$`）、规范化冲突与 APKG archive 资源上限已通过；有界流式读取覆盖 APKG archive/package/verifier 与标准 Windows Anki direct-first 媒体路径。非标准/portable profile 的 AnkiConnect inline 兼容路径仍整文件/Base64，但原始单文件上限为 8 MiB；8 MiB 不是进程峰值。
- M0 的 Computer Use、GUI 翻面/媒体播放和 20 张连续复习出口已经通过；完整边界见 [M0 验证报告](M0_VERIFICATION_REPORT_2026-07-17.md)。
- M1–M3 的 Headless Service、认证 Artifact/授权边界、stdio MCP、Skill、宿主注册和可安装包出口满足前，不得声明 Codex 插件已经复用完整 APKG → 真实 Anki 发布闭环。

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
