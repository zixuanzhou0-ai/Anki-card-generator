# 用户指南

这份指南按普通用户的实际操作顺序写：先让本地环境跑起来，再配置模型和 TTS，最后生成、审核、导出 Anki 卡包。

## 1. 第一次打开

打开桌面端后，主界面分为三段：

1. `素材配置`：选择本地视频或视频链接。
2. `学习设置`：选择学习语言、自动/手动难度、预览速度和卡片模式。
3. `确认抽取`：调用模型 AI 精筛学习点，用户选择要制卡的学习点。
4. `审核导出`：检查可用卡片、学习点诊断，选择要导出的卡。

![素材配置](screenshots/workflow-start.png)

生成完成并导入 Anki 后，卡片会保留视频片段、表达、语境义、原句、原声和慢读 TTS：

![Anki 成品卡](screenshots/anki-card-stress-start.jpg)

顶部右侧有常用操作：

- `设置`：模型 API、语音 TTS、本地环境。
- `抽取学习点`：先让 AI 从字幕里精筛词伙、口语、单词用法、语法和听力点。
- `导出`：生成完成后导出已选且通过质量闸的可用卡片。
- `收起面板`：收起左侧流程台，留出更多审核空间。

## 2. 检查和修复本地环境

进入 `设置 -> 本地环境`。

![本地环境设置](screenshots/settings-environment.png)

点击 `检查环境`，应用会检测：

| 项目 | 用途 |
| --- | --- |
| Python 运行环境 | 启动制卡 worker |
| 项目 `.venv` | 隔离 Python 依赖 |
| genanki | 生成 `.apkg` |
| yt-dlp | 下载 YouTube 视频/字幕 |
| FFmpeg | 视频切片、转音频、生成封面 |
| Deno / Node | 解决 YouTube n challenge |
| Anki 桌面端 | 打开或导入 APKG |
| AnkiConnect | 导入后核验卡片和媒体 |

如果缺少依赖，点击 `一键修复全部可修复项`。

当前自动修复能力：

- 缺少 Python 时，原生层会尝试通过 `winget` 安装推荐 Python 3.12。
- Python 可用后，会创建 `.venv` 并安装/更新 `genanki`、`yt-dlp`、`pypdf`。
- 缺少 FFmpeg 时，会尝试通过 `winget` 安装 `Gyan.FFmpeg`。
- 缺少 Deno/Node 时，会尝试通过 `winget` 安装 Deno。
- 缺少 Anki 时，会尝试通过 `winget` 安装 Anki。
- AnkiConnect 需要在 Anki 内确认安装，应用会提示插件代码 `2055492159`。

如果电脑没有 `winget`，对应项目会显示手动安装步骤。

## 3. 配置模型 API

进入 `设置 -> 模型 API`。

![模型 API 设置](screenshots/settings-model-api.png)

推荐流程：

1. 在快速切换区选择模型方案。
2. 如果该方案需要 API Key，填写 Key。
3. 点击 `保存模型方案`，保存到“我的模型”。
4. 点击 `测试连接`。

注意：

- Gemini Vertex 使用本机 `gcloud` OAuth，不需要在应用里填 API Key。
- Vertex 文本模型默认使用 `gemini-3.1-pro-preview`。
- 每个模型方案的 Key 单独保存，不再所有服务商共用同一个 Key。
- Key 不会写入仓库；用户选择保存时，优先写入 Windows Credential Manager。

常见模型选择：

| 场景 | 建议 |
| --- | --- |
| 高质量英语/多语言卡 | Gemini Vertex / Qwen / DeepSeek / MIMO 中选择稳定方案 |
| 快速试流程 | 选择响应更快、成本更低的模型 |
| 长视频深度理解 | 使用支持 reasoning/thinking 且 JSON 稳定的模型 |
| Vertex | 先确认 `gcloud auth login` 和 `gcloud config set project <project-id>` |

## 4. 配置语音 TTS

进入 `设置 -> 语音 TTS`。

![语音 TTS 设置](screenshots/settings-tts.png)

TTS 和文本模型分开配置：

- `TtsAudio`：整句 AI 朗读。
- `PhraseTtsAudio`：核心表达/答案朗读。
- 原视频音频不会被 TTS 替代。

当前设计：

- TTS 服务商、模型、音色、Key 可以单独保存。
- Gemini Vertex TTS 使用本机 `gcloud` OAuth，不需要填写 TTS API Key。
- 导出时默认把 AI TTS 音量降到 65%，避免比原视频声音刺耳。
- 预览播放速度只影响应用内试听，不改变导出的 Anki 音频。

英语 TTS 建议：

- 能听清原视频时，优先用原声。
- 额外整句朗读和表达朗读再用 AI TTS。
- Vertex TTS 可从 `Kore / Aoede / Puck / Charon` 等 voice 里试。
- Qwen 英语可优先试 `Jennifer` 或 `Aiden`。

## 5. 选择素材

### 本地视频 + SRT

适合自己已有视频和字幕。

1. 选择 `本地视频`。
2. 选择视频文件。
3. 选择 SRT 字幕；如果留空，应用会尝试同目录自动匹配 SRT/VTT，也会尝试读取 MKV/MP4 内嵌字幕。
4. 导出时会生成视频片段、原声和 TTS；如果切片失败，请先修复 FFmpeg 或素材路径后再重试。

如果没有 SRT：

- 有内嵌字幕时，应用会尝试提取。
- 没有字幕时，当前版本不会自动 ASR；建议先用 Whisper、本地 ASR 或线上 ASR 转成 SRT，再导入。

### 视频链接 / YouTube

1. 选择 `视频链接`。
2. 粘贴 URL。
3. 默认尝试下载视频 + 字幕。
4. 如果视频下载失败，请先处理 yt-dlp、网络、权限或区域限制后再重试；当前发布版不生成缺视频的卡包。

URL 失败常见原因是 YouTube 429、区域限制、字幕不可用或 n challenge。先看 [故障排查](TROUBLESHOOTING.md)。

### 文档资料

当前发布版不开放文档资料制卡入口。主流程只保留本地视频和视频链接，优先把视频语言学习卡片的稳定性、媒体完整性和 Anki 导入质量做好。

## 6. 生成设置

### 学习语言

支持：

- English
- Francais
- Espanol
- 日本語
- Русский

内部使用稳定 code：`en / fr / es / ja / ru`。

不同语言使用不同读法体系：

| 语言 | 读法体系 |
| --- | --- |
| English | IPA + weak forms/linking/stress |
| French | API/IPA + liaison/e caduc |
| Spanish | 拉美通用读法，音节 + 重音，可选 IPA |
| Japanese | 假名 + 可靠时才标音高 |
| Russian | 带重音西里尔，可选 IPA |

### 学习水平

默认是 `自动判断`。

推荐保持自动。生成后每张卡会带：

- estimated level
- difficulty
- difficulty reason

如果手动选择 A1-C2，它只作为软偏好，影响解释深度和筛选倾向，不作为硬门槛。

### 预览播放速度

左侧统一设置预览播放速度：

- 0.75x
- 1x
- 1.25x

它只影响应用内预览，不影响导出的 Anki 音频。

### 卡片模式

视频/字幕主流程只显示 `沉浸复读 V11` 这一套稳定模板。用户不需要选择实验模板、解析精度或学习点类型，系统会默认智能处理。

| 模式 | 说明 |
| --- | --- |
| 完整复读 | 默认模式。正面用于视频复读，背面保留完整释义、用法、误用提醒、发音和练习提示。 |
| 快速复读 | 轻量模式。正面同完整复读，背面只保留原句、中文意思、视频、原声、慢读 TTS 和表达 TTS。 |

实验模板代码仍可能保留在仓库里用于回归研究，但普通用户界面不再展示它们。

## 7. 抽取学习点并生成卡片

点击顶部 `抽取学习点`。

桌面端会真实调用 worker 和模型 API，不再把本地规则秒出的候选当作正式结果。API 未配置或未测试通过时，正式抽取会被阻止。

流程大致是：

```mermaid
flowchart TB
  A["视频素材"] --> B["字幕解析"]
  B --> C["本地高召回候选"]
  C --> D["Gemini/Vertex AI 精筛和补漏"]
  D --> E["推荐/候选/诊断"]
  E --> F["用户勾选学习点"]
  F --> G["AI 生成完整可用卡片"]
  G --> H["审核导出"]
```

学习点页面会显示：

- `推荐`：默认勾选。
- `候选`：可手动勾选。
- `诊断`：AI 拒绝、重复折叠、硬阻断或模型失败记录。

只有用户勾选的学习点才会进入完整制卡。点击某条学习点只是查看它，不代表只生成这一条。生成按钮会明确显示 `生成已勾选的 N 张`；如果只想生成一张，先点 `全不选`，再勾选那一条。

## 8. 审核导出

生成完成后进入 `审核导出`。

![审核导出](screenshots/workflow-generated.png)

顶部统计含义：

| 指标 | 含义 |
| --- | --- |
| 生成卡片数 | 已经生成完整内容的可用卡片 |
| 可导出卡 | 当前通过质量闸、可以写入 APKG 的卡片 |
| 需修复卡 | 含草稿、内部提示、待人工确认或字段不完整，不能导出的卡片 |
| 已选卡片数 | 当前已勾选且会导出的可用卡片 |
| 发现学习点 | 系统从素材中找到的学习点总数 |
| 更多学习点 | 可在诊断中查看的候选、拒绝、重复或硬阻断项 |
| 重复 / 硬阻断 | 被折叠或不能制卡的学习点 |

可用卡片默认全部选中。你可以：

- 全选
- 全不选
- 反选
- 只看已选
- 只看未选
- 按片段启用/停用
- 单卡勾选/取消

导出只导出当前选中且通过质量闸的完整卡片。当前公开版不要求本机 ASR/Whisper，也不会因为 ASR 误听阻止导出。视频卡如果出现视频、原声、整句 TTS、表达 TTS 缺失，或 ledger/hash 不一致，会被质量闸拦住，不会静默写入 APKG。

## 9. 学习点诊断

`学习点诊断` 用来解释“为什么某些学习点没有变成卡”。

常见状态：

| 状态 | 含义 |
| --- | --- |
| card_generated | 已生成完整卡 |
| candidate_only | 合法、有价值，但默认未勾选或暂未生成完整卡 |
| hidden_duplicate | 训练动作重复，被折叠 |
| hard_blocked | 不能制卡，例如跨度不存在、答案混入中文/IPA/解释 |

候选库 V1 先保证可见、可筛选、可解释。后续可以继续加“一键把候选生成完整卡”。

## 10. 发音字段

视频语言卡会包含：

- 标准读法
- 推测口语读法 / 剧中读法
- 原句听感
- 发音说明
- PronunciationMeta 隐藏 JSON

当前 V1 不把 ASR 或 forced alignment 作为公开主流程，所以默认：

```text
generation_basis = subtitle_inferred
```

也就是说，没有音频实听时，应用不会把字幕推测包装成“剧中实际读法”。如果某个发音字段被隐藏、清空或降级，`PronunciationMeta.field_changes` 会记录原因。

## 11. 导出 APKG

确认卡片后点击 `导出可用的 N 张`。`N` 是当前已选且通过质量闸的卡片数。

如果已选学习点的 AI 字段不完整，应用会尽量用原学习点、字幕和时间点补齐保底卡，并把缺失字段记录到高级诊断。只有视频、原声、整句 TTS、表达 TTS、ledger/hash 等硬失败才会阻止导出；应用不应该静默移除用户已选的卡。

导出内容包括：

- Anki notes/cards
- 视频切片
- 原声片段
- 整句 TTS
- 表达 TTS
- PronunciationMeta
- media manifest
- TTS ledger

导出后可以：

- 手动在 Anki 导入 `.apkg`。
- 让应用打开 Anki 导入。
- 使用 AnkiConnect 做导入核验。

当前发布版的导出结果面板服务于视频制卡路径：APKG 成功后显示路径、`打开 Anki` 和 `核验媒体`；视频卡必须通过媒体和 TTS 取证检查。

## 12. AnkiConnect

AnkiConnect 插件用于导入后自动核验。

安装步骤：

1. 打开 Anki。
2. 工具 -> 插件 -> 获取插件。
3. 输入插件代码：`2055492159`。
4. 重启 Anki。
5. 回到应用设置页，点击 `检查环境`。

环境页会区分：

- Anki 没安装。
- Anki 已安装但没打开。
- Anki 已打开但 AnkiConnect 未连接。
- AnkiConnect 正常。

## 13. 推荐的端到端测试

每次发布前建议跑：

```powershell
npm.cmd run lint
npm.cmd run test:unit
npm.cmd run build
python -m pytest tests\test_worker_quality.py -q -k "check_env or repair_env"
cargo check --manifest-path src-tauri/Cargo.toml
```

完整桌面端回归：

1. 打开桌面端。
2. 检查本地环境。
3. 测试模型 API。
4. 测试 TTS。
5. 用本地视频 + SRT 生成。
6. 检查可用卡片和学习点诊断。
7. 导出 APKG。
8. 运行 APKG verify。
9. 导入 Anki，抽查音频、视频、发音字段和隐藏 JSON。

## 14. 常见理解误区

### 一键修复是不是完全无人值守？

不是。能自动安装的会自动安装，但 AnkiConnect 必须在 Anki 内确认安装。没有 winget 时，系统级依赖也需要手动安装。

### 能不能把所有学习点都导出？

当前能导出的是“已经生成完整卡片”的可用卡。学习点诊断里能看到更多候选，但 V1 不默认为所有候选生成 TTS、媒体和完整 Anki 字段。

### 为什么不用最新版 Python？

应用推荐 Python 3.12，因为它比“最新版”更稳定。最新版可能带来依赖兼容波动。

### 为什么没有 SRT 不能直接听懂视频？

当前 V1 不内置 ASR。没有字幕时，建议先用本地 Whisper 或线上 ASR 转 SRT，再导入。

### 为什么发音字段会显示“推测”？

因为没有真实音频对齐时，读法来自字幕和常见口语规律推断。应用宁愿标低置信度，也不误导学习者。
