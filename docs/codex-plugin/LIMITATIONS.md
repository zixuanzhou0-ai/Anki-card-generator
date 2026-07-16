# 限制与已知风险

> 状态：设计基线的诚实边界  
> 日期：2026-07-16  
> 这里的“计划”不能在产品页面写成“当前支持”。

## 1. 当前仓库状态

- 当前产品是 Windows Tauri 桌面应用。
- 当前仓库没有插件 manifest、SKILL.md、MCP Server 或 App UI 包。
- 当前 Worker 是 stdin/stdout 一次性 JSON 协议，不是 MCP。
- 当前文档/知识卡能力是局部基础，不是通用 Study IR。
- 当前真实强项是语言视频、媒体、APKG 和 Anki 数据一致性核验；完整运行时渲染/播放/重启复习仍需独立版本化 verifier 证明。

## 2. 已知 P0

当前 immersive_v11 卡片 family 实际生成 template schema V14；发布版 workers/verify_apkg.py 使用 startswith 且包含宽前缀 Anki Card Generator V1，所以 V14 与 V199 等非法近似名称都会命中。当前问题是 verifier 版本边界 fail-open。

后果：

- verifier 不能证明正在核验精确的 family/schema/Note Model 兼容关系。
- 在修复前不能宣称完整复用最新 APKG verifier。
- 插件 M0 必须先统一版本轴、移除宽前缀匹配，并增加真实 V14 正例及 V13/V15/V199/近似前缀负例。

## 3. Codex 宿主

- Apps SDK 为 ChatGPT Apps 定义 Inline、Fullscreen、PiP；目标 Codex 宿主是否支持尚需逐版本实测。
- 固定右侧栏尚无本次核验到的公开稳定接口。
- V1 不能保证 UI 永久固定在右侧。
- Codex Desktop、CLI、IDE 和不同工作区的 App UI 可用性可能不同；CLI/IDE 默认按 tools-only。
- 插件更新后可能需要新任务/重启才能刷新能力。
- M3 仍必须实测目标宿主的 manifest 加载、stdio Service 启动/重连和工具注册；不能因为官方支持 stdio 就推断每个具体 Codex 版本与工作区都可用。
- 受信本地选择/确认表面若被宿主或系统策略阻止，插件只能 APKG-only，不能完成新的授权或 Anki 写入。

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

## 9. Anki

- 导入是持久写入，必须由用户明确触发。
- 不自动安装或更新 AnkiConnect。
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
