# M0 验证报告：2026-07-17

> 状态：CURRENT；M0 已完成
> 日期：2026-07-17
> 范围：桌面仓库可靠性内核、V15 Note Model、Anki 媒体快捷键桥、APKG、真实 Anki GUI 与发布门禁
> 不包含：Codex 插件清单、stdio MCP、M1 Headless Card Service 或真人 TTS 学习效果实验

## 1. 结论

M0 的出口已经全部通过。当前可靠性内核不仅通过自动化、APKG 包合同和 AnkiConnect 数据核验，还在真实 Windows Anki 26.05 中完成了 V14/V15 并存、20 张连续复习、正反面布局、四类媒体播放、Space/Enter 键盘路由、媒体互斥、重复导入和重启持久性验证。

本轮新增 V15，而不是修改既有 V14 卡片。V15 使用模型作用域 GUID，避免字段完全相同的 V14 与 V15 note 在 Anki 中错误合并；V10/V12/V14 的历史 GUID 规则保持不变。媒体快捷键能力由一个最小 Anki add-on 提供，并以版本化 runtime contract 将 Anki 版本、Note Model ID、模板摘要、路由键和权限边界绑定在一起。

M0 完成只表示可靠性基线已经冻结，可以进入 M1。它不表示 Codex 插件、MCP 控制台或 Headless Card Service 已经交付。

## 2. 证据等级

| 等级 | 结果 | 主要证据 |
|---|---|---|
| 自动化合同 | 通过 | 前端、Worker、Rust、包合同、快捷键桥和发布 smoke |
| 离线 APKG | 通过 | V15 20 notes / 20 cards / 52 media、模型作用域 GUID、完整媒体哈希 |
| 真实 Anki 数据级 | 通过 | note/card/model/deck/media 计数、重复导入、重启、V14/V15 并存 |
| 真实 Anki GUI/学习体验 | 通过 | Computer Use 操作真实 Anki，连续复习 20 张并逐项操作媒体 |
| 真人语义与学习效果 | 未声称 | 本轮媒体为合成 smoke fixture，不能证明真人听感或长期记忆增益 |

## 3. 最终自动化结果

| 门禁 | 结果 |
|---|---|
| 前端 Vitest | 90 个文件、830 项通过 |
| Python 正式 `pytest` | 603 项通过；2 个预期 ZIP 重复条目警告 |
| 独立 `unittest discover` | 576 项通过 |
| 包合同与快捷键定向集 | 58 项通过 |
| Rust | 31 项通过，1 项按设计忽略 |
| UI smoke | 3 项通过 |
| V15 20 卡包 | 20 notes / 20 cards / 52 media，通过完整包合同 |
| V15/V10 release smoke | 通过；使用生产 verifier |
| `npm run check` | 通过 |
| `npm run check:full` | 通过 |
| `npm run tauri:build` | 通过；MSI 与 NSIS 安装包均生成 |
| `cargo test --locked` | 通过 |

`pytest` 与 `unittest discover` 覆盖大量相同测试，不能把 603 和 576 相加后宣称为独立测试总数。

## 4. V15 Note Model 与包合同

### 4.1 当前合同

| 模板 | Note Model ID | schema | contract digest |
|---|---:|---|---|
| 沉浸复读 V11 | 1028904201 | V15 | `966edeadbcbe64511e93343d854007f23ad851c17d81e79a672dbad4b4d74e4c` |
| 沉浸复读 V11 Fast | 5074019806 | V15 | `79bebf769f73d97e55f34c36c8a028f9e77bb12079b11102bce0f6d4544c8578` |

V15 验证必须同时满足：

- 精确 template family、schema、Note Model ID、字段顺序、模板、CSS 和合同摘要。
- 唯一 `anki_card_generator_v15` 标签，不能混入其他版本标签。
- note GUID 必须由 Note Model ID 与 50 个原始字段共同计算。
- 展示 HTML、媒体 manifest、card-media ledger、ZIP 条目和资源上限继续使用完整 APKG verifier。

### 4.2 V14/V15 同字段兼容性

| 项目 | V14 | V15 |
|---|---|---|
| APKG SHA-256 | `5fcc2ad7c1e1875460f0330d1a1b4db03982dcdd13674631b1968f0f083f5997` | `7f309e457e8bd56d342aa24050046aef71357b3dd331a466a481bfb34415b7e3` |
| Note Model ID | 3157735470 | 1028904201 |
| GUID | `D6E19B4SSJ` | `emn>>\`s@fj` |
| 字段数 | 50 | 50 |
| 字段值摘要 | `df4262a51d9d7965aa0a6506046171937646c2dc28e654ad3c3db1b740d4901c` | 相同 |

真实 Anki 中两张 note 同时存在，字段名和值完全相同，但 note ID、model name 与 GUID 均不同。V15 重复导入时显示 1 条已经在集合中；重启前后结构化 JSON 完全一致。

## 5. 最终 V15 20 卡 APKG

| 项目 | 结果 |
|---|---|
| APKG SHA-256 | `54da28686dbc35b04175ba06ad3a0ea090c2d6eb793f806fd05dcf5dfd3cae2b` |
| Note Model | `Anki Card Generator V15 - 沉浸复读 V11` |
| notes / cards | 20 / 20 |
| 唯一媒体 | 52 |
| 媒体角色 | sentence TTS 20、phrase TTS 20、video 6、original audio 3、poster 3 |
| 字幕对齐 | 20/20 matched |
| GUID 合同错误 | 0 |
| 包合同错误 | 0 |

导入并重启真实 Anki 后，结构化取证仍为 20 notes、20 cards、52 media；52 个实际媒体 SHA-256 与导出 manifest 全部一致，missing、unexpected 和 hash mismatch 均为 0。同一 APKG 再导入时，Anki 明确显示 20 条笔记已经存在，没有新增重复卡片。

## 6. Anki 媒体快捷键桥

### 6.1 交付物

- 源码目录：`anki-addon/anki_card_generator_media_shortcut_bridge/`
- 版本：`1.0.0-m0`
- 构建包：`anki_card_generator_media_shortcut_bridge-1.0.0-m0.ankiaddon`
- 最终构建包 SHA-256：`e022a2ebb8793c28e96133569497bd4ad7a346670b1d5a2c93a9983de0f5f674`
- 当前支持的 Anki point version：260500（Anki 26.05）

### 6.2 安全边界

runtime contract 明确声明：

- 只处理 review 状态的 question/answer 两面。
- 只路由 Space、Return、Enter。
- 只允许 original、slow、phrase、video 四个角色。
- 两阶段 DOM token 激活、单飞、拒绝旧卡/旧面、1500ms 超时并 fail closed。
- 不请求网络、collection read/write 或 media write 权限。

### 6.3 真实测试发现并关闭的问题

1. Anki 26.05 的 `state_shortcuts_will_change` hook 不可迭代，原先的“包含判断”会在启动时抛错；改为模块级幂等安装哨兵。
2. token 直接拼入 CSS attribute selector 会产生无效或不可靠选择器；改为枚举白名单属性节点并做精确字符串比较。
3. 媒体刚调用 `play()` 后立刻按空格，迟到的 Promise 回调可能把暂停态覆盖成失败或播放态；改为同步乐观状态和仅在当前仍为 playing 时处理失败。
4. 初版运行时只检查 Note Model ID，弱于文档声明的精确模板合同；现已同时验证精确 model name、template name、qfmt、afmt 与 CSS 摘要。同 ID 但模板被改写时 fail closed，不翻面、不评分。

四个问题均增加回归断言；最终 add-on 又在真实 Anki 中复测背景 Space 翻面和表达按钮 Space 暂停。

## 7. Computer Use 真实 Anki 验收

测试使用全新隔离 Anki 数据目录，不触碰正式 profile。

### 7.1 卡面与学习顺序

- 正面不泄露答案。
- 背面第一屏先看到 Answer、中文含义和高亮原句，视频位于音频之后。
- 目标表达在原句、怎么用、别误用和例句迁移中使用主题蓝、加粗和放大；没有蓝色下划线。
- 表达发音按钮紧跟 Answer，不掉到下一行独立区域。
- 长内容可自然滚动，没有固定高度截断。

### 7.2 媒体交互

- 表达发音：点击后 100ms 立即按 Space，卡 1 与卡 20 均进入“继续表达发音”，没有播放失败。
- 原声：Space 可暂停为“继续原声”，同时停止视频和其他音频。
- 慢读：Return 可暂停为“继续慢读”。
- 视频：Space 可暂停为“视频已暂停”，Return 可继续为“视频播放中”。
- 点击新媒体会把旧媒体恢复到初始状态。
- 媒体按键不会误触发翻面或评分；卡片背景上的 Space 仍按 Anki 默认行为翻面。

### 7.3 20 张连续复习

检查点依次为：

- 15 + 5 + 0
- 10 + 10 + 0
- 5 + 15 + 0
- 1 + 19 + 0
- 0 + 20 + 0

每次进入下一张卡，原声、慢读和视频均回到初始文案，没有上一张的 playing/paused/error 状态串入。第 20 张再次执行快速表达发音暂停仍通过。

### 7.4 重启与并存

- 20 卡牌组重启后仍显示 20 张学习中卡片。
- V14/V15 同字段隔离集合重启后仍各 1 note / 1 card。
- 重启前后并存证据 JSON 无差异。

## 8. 仍然存在的边界

- 合成视频与静音/fixture TTS 只能证明协议、渲染、可播放性和状态机，不能证明真人语义、音质或长期学习效果。
- add-on 当前只声明支持 Anki 26.05；其他版本必须先扩展并验证 runtime contract，不能静默放宽。
- 非标准/portable profile 仍使用受 8 MiB 原始媒体上限约束的 AnkiConnect inline 兼容路径；它仍会整文件 Base64，不能宣称全部媒体路径都流式化。
- raw `ExportResult` 仍是内部一致性证据，不是认证来源。M2 仍需 Artifact 注册表、不透明引用和受控文件句柄。
- Codex 插件 manifest、Skill、stdio MCP、目标宿主注册和 M1 Headless Card Service 尚未实现。

## 9. 发布判定

M0 判定为完成。允许声明：

- V15 Note Model、模型作用域 GUID、完整 APKG 合同和媒体快捷键桥已经实现并验证。
- 真实 Anki 26.05 的 20 张连续复习、四类媒体交互、重复导入、重启和 V14/V15 并存已经通过。
- 当前桌面与发布自动化没有已知回归。

不允许声明：

- Codex 插件或 MCP 已经可安装使用。
- 其他 Anki 版本已经兼容。
- 真人 TTS 语义、听感或学习效果已经验证。
- M1/M2 的权限、Artifact 和 Headless Runtime 已经完成。

下一实施阶段是 M1：Headless Legacy Runtime。
