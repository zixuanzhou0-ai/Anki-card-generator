# M0 验证报告：2026-07-17

> 状态：CURRENT 验证快照；M0 仍为进行中
> 日期：2026-07-17
> 范围：当前桌面仓库的 Worker、APKG、Anki 数据级验证与发布构建
> 不包含：Codex 插件、MCP、Headless Card Service 或完整 Anki GUI/学习体验验收

## 1. 结论

当前可靠性内核已经通过最终自动化回归、生产 V14/V10 发布 smoke、20 卡媒体包合同，以及隔离真实 Anki 的单卡和 20 卡数据级导入验证。结果证明包结构、卡片与媒体归属、跨盘媒体持久化、重复导入幂等和重启后的数据完整性达到本轮冻结要求。

这些证据不证明真实 Anki GUI 中的卡面视觉、翻面、滚动、键盘焦点、媒体实际播放、真人语音语义与听感或连续复习体验。当前执行环境没有 Computer Use，因此 M0 仍为进行中。

## 2. 证据等级

| 等级 | 本轮状态 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 自动化合同 | 通过 | schema、状态、Worker、Rust、包合同和发布构建没有已知回归 | 真实 GUI 和真人听感 |
| 离线 APKG 包 | 通过 | note/card/deck、媒体清单、账本、归属、哈希和字幕对齐闭合 | 实际导入、播放和复习 |
| 真实 Anki 数据级 | 通过 | AnkiConnect 导入、collection 数据、媒体文件、重复导入和重启持久化 | 卡面渲染、交互、媒体播放和连续复习 |
| 真实 Anki GUI/学习体验 | 未执行 | 无 | Computer Use 当前不可用，不能用静态截图或数据库检查替代 |

## 3. 最终自动化结果

| 门禁 | 结果 |
|---|---|
| 前端 Vitest | 830 项通过 |
| Python 正式 `pytest` | 561 项通过 |
| 独立 `unittest discover` | 551 项通过 |
| Rust | 31 项通过，1 项按设计忽略 |
| UI smoke | 3 项通过 |
| V14/V10 release smoke | 通过；使用生产 verifier |
| `npm run check:full` | 通过 |
| `npm run tauri:build` | 通过 |

`pytest` 与 `unittest discover` 会覆盖部分相同测试，不能把 561 和 551 相加后宣称为独立测试总数。

## 4. 已关闭的 M0 安全与包合同问题

- Note Model 使用精确 family、template schema、ID、字段、模板、CSS 与兼容合同，不再依赖 V1 名称前缀。
- V14 与明确支持的 V10 由 release smoke 真实生成；V13、V15、V199、近似名称和篡改合同必须失败。
- APKG 候选先写同目录唯一 `.partial`，完整验证后再以 no-replace 语义原子发布；目标已存在时拒绝覆盖。
- 受信跨盘 Anki 媒体恢复也使用同目录临时文件加 no-replace 发布；发布瞬间若并发出现同内容文件则按幂等成功处理，若内容不同则拒绝覆盖并保留对方文件。
- 前端只有在 full 与 compact 两份导出结果都具备完整写入证据，且规范化 APKG/media 路径、哈希、大小、mtime、牌组、模型、模板、合同、标签、来源、内容指纹和核心媒体摘要一致时才允许导入；任一缺失或错配均 fail closed，不再回退到可能陈旧的结果。
- 非 NFC 文件名、Windows 保留设备名（含 `CLOCK$`）、大小写与规范化碰撞均按 fail-closed 处理。
- APKG archive/package/verifier 路径对包内媒体哈希与提取使用有界流式读取，并执行单条目、条目数和解压后总量上限。

流式结论只适用于 APKG archive/package/verifier。AnkiConnect 缺失媒体恢复仍会把单个最多 256 MiB 的源媒体整体读入内存，构造约为原始体积 4/3 的 base64 文本，并在写后再次整文件取回和解码；受信跨盘 fallback 也仍接收整块字节。因此不能宣称所有媒体路径都已流式化，峰值内存可能显著高于媒体文件本身。

## 5. 20 卡生产 V14 离线包

| 项目 | 结果 |
|---|---|
| APKG SHA-256 | `35fc97d4889a8a4a4ba55a47da05c1e84cac706c5c2a52c113a9c9569fabae01` |
| notes / cards | 20 / 20 |
| 业务牌组 | 1；collection 另含默认牌组，合同摘要 `decks=2` |
| 唯一媒体 | 52 |
| 媒体角色 | sentence TTS 20、phrase TTS 20、video 6、original audio 3、poster 3 |
| 逐卡媒体引用 | 20/20 卡各 6 个引用，共 120 个 card-media ownership bindings |
| manifest / ledger | 52 / 52，完全闭合 |
| 字幕对齐 | 20/20 匹配 |
| 失败项 | missing、invalid、unreferenced、compatibility conflict、package issue、verifier failed check、display warning 均为 0 |

该包使用 release-smoke 合成视频与 SRT。TTS 和原声音频为静音 smoke fixture，TTS semantic 状态为 `not_applicable`。它证明生产媒体链和数据合同，不证明真人语音语义、听感或播放体验。

## 6. 隔离真实 Anki 数据级验证

### 6.1 单卡跨盘

单卡生产 V14 APKG 的大小为 212,361 bytes，SHA-256 为 `1115ac480f7dfac12d84c465e37e0e2cc122f999991ece4d1ec7a6d04b28dd7a`。APKG 与媒体源位于一个磁盘卷，隔离 Anki profile 和 `collection.media` 位于另一个磁盘卷。

| 检查 | 结果 |
|---|---|
| 首次导入 | 1 note / 1 card；目标 deck、model、tag、CardId 匹配 |
| 媒体 | 6/6：sentence TTS、phrase TTS、WebM、MP4、original audio、poster |
| 跨盘一致性 | 源与目标逐文件 bytes 和 SHA-256 相同 |
| 缺失/不匹配/不可访问 | 0 / 0 / 0 |
| 重复导入 | 以 CardId + content SHA-256 命中并跳过；`duplicates=0` |
| 重启后 | 仍为 1 note / 1 card，6/6 媒体再次通过 bytes + SHA-256 |

隐藏 Anki 的正常退出请求没有在等待窗口内完成，测试最终终止了该隔离进程；重新启动后数据仍完整。这个结果不能写成正常 GUI 退出体验已通过。

### 6.2 20 卡批量

同一 20 卡生产 V14 媒体包随后进入全新隔离 Anki profile：

| 检查 | 结果 |
|---|---|
| 首次导入 | 20 notes / 20 cards |
| 唯一媒体 | 52/52 均存在，逐文件 bytes 与 SHA-256 一致 |
| 媒体归属 | 120 个 card-media ownership bindings 全部闭合 |
| 重复导入 | 完整命中并跳过；没有新增重复卡片 |
| 重启后 | 仍为 20 notes / 20 cards / 52 media，哈希复核通过 |

这是“真实 Anki 进程 + AnkiConnect + collection/filesystem”的数据级证据。由于素材仍是合成视频和静音音频，且没有通过 GUI 翻面、播放或连续复习，它不是完整运行时或学习体验证据。

## 7. 仍未完成的出口

- Computer Use 当前不可用，尚未验证真实 Windows Anki/Tauri 的布局、翻面、滚动、焦点、键盘和媒体交互。
- 尚未在真实 GUI 中逐卡播放原声、慢读、表达 TTS、WebM/MP4，也未完成至少 20 张连续复习。
- 合成视频与静音 TTS 不提供真人语义、音质、口型、时间感或学习有效性证据。
- 当前 raw `ExportResult` 只做内部一致性检查，不认证来源；M2 仍需认证 Artifact 注册表、不透明引用和受控文件句柄解决同权限篡改与剩余 TOCTOU。
- AnkiConnect 整文件/base64 媒体恢复仍存在峰值内存放大。
- 插件 manifest、Skill、stdio MCP、目标 Codex 宿主注册、M1 Headless Card Service 和版本化 Anki runtime verifier 尚未实现。
- 当前只固定关键 `genanki` serializer；Python、Node、Rust 和外部二进制尚未全部完成版本加哈希的供应链固定。

## 8. 发布判定

M0 保持“进行中”。允许声明自动化、APKG 包合同和隔离 Anki 数据级验证通过，不允许声明插件已交付、真实 Anki GUI/播放/连续复习已通过或全部媒体处理均已流式化。

后续只有在 Computer Use 可用的真实桌面环境完成 GUI 与媒体交互验收，并由版本化 runtime verifier 形成固定检查集证据后，才能把数据级状态提升为完整运行时验证状态。
