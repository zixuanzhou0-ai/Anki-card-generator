# Anki Card Generator

面向中文学习者的 Windows 桌面端 Anki 卡片生成器。它把视频、字幕、YouTube 链接和文档资料变成可以审核、选择并导出的 Anki `.apkg` 卡包。

当前仓库版本已经切到新的主流程：

```text
素材配置 -> 智能生成学习点 -> 审核可用卡片/学习点诊断 -> 导出已选 APKG
```

不再让用户在“精选优先 / 不漏优先 / 全量发现”之间纠结，也不再把“推荐 / 待审 / 拒绝”作为主要操作心智。系统内部仍然保留质量 gate、重复过滤、硬阻断和诊断统计，但 Review UI 面向用户展示的是：

- `可用卡片`：已经生成完整卡片，默认全选，用户可取消。
- `学习点诊断`：展示未制卡、重复折叠或硬阻断的学习点与原因。
- `导出已选`：只导出用户当前勾选的完整卡片。

## 主要能力

- 本地视频 + SRT：从剧集、课程或电影片段生成语言学习卡。
- YouTube / URL：下载视频和字幕，失败时可降级到字幕-only。
- 文档资料：支持知识吸收和语言精读两种路径。
- 统一智能筛选：同一句里可以同时抽取词伙、语境生词、语法框架、听力难点和语气风险点。
- 自动难度：学习水平默认自动判断，每张卡带 `estimated_level` / `difficulty`。
- 多语言发音标注：支持 `en / fr / es / ja / ru`，不强行把所有语言塞进英语 IPA。
- 发音透明追踪：`PronunciationMeta` 记录语言、口音 profile、生成依据、字段置信度和 validator issues。
- TTS 与媒体账本：整句 TTS、表达 TTS、原视频音频、视频切片都会记录 hash 和 ledger，方便核验。
- AnkiConnect 核验：可导入后检查 note/card、媒体引用、TTS ledger 和隐藏 JSON 字段。
- 本地环境一键修复：设置页可以检测 Python、FFmpeg、Deno/Node、Anki、AnkiConnect，并尝试自动修复可自动处理的项。

## 界面预览

### 素材配置

![素材配置](docs/screenshots/workflow-start.png)

### 审核导出

![审核导出](docs/screenshots/workflow-generated.png)

### 模型 API 设置

Vertex 模式使用本机 `gcloud` OAuth，不需要粘贴 API Key。其它服务商的 Key 可以分别保存到“我的模型”。

![模型 API 设置](docs/screenshots/settings-model-api.png)

### 语音 TTS 设置

TTS 服务商、音色和 Key 与文本模型分开保存。导出 TTS 默认降低音量，避免比原视频声音刺耳。

![语音 TTS 设置](docs/screenshots/settings-tts.png)

### 本地环境检测与修复

环境页会分开检测 Anki 桌面端、Anki 是否运行、AnkiConnect 是否可用。缺少 Python 时，Tauri 原生层会先尝试安装推荐 Python 3.12，再继续安装 worker 依赖。

![本地环境设置](docs/screenshots/settings-environment.png)

## 快速开始

推荐普通用户直接使用 Windows 桌面端：

1. 下载或构建桌面端。
2. 打开 `Anki Card Generator.exe`。
3. 进入 `设置 -> 本地环境`，点击 `检查环境`。
4. 如果有缺失项，点击 `一键修复全部可修复项`。
5. 进入 `模型 API`，选择模型方案，测试连接并保存。
6. 进入 `语音 TTS`，选择 TTS 方案，测试连接并保存。
7. 选择素材：本地视频 + SRT、视频链接，或文档资料。
8. 点击 `生成卡片`。
9. 在 `审核导出` 里检查卡片，取消不想学的卡。
10. 点击 `导出已选`，导入 Anki。

完整图文教程见 [用户指南](docs/USER_GUIDE.md)。

## 本地环境说明

应用尽量把环境问题做成“检测 + 修复”，而不是只提示错误。

| 项目 | 当前处理方式 |
| --- | --- |
| Python 运行环境 | 原生层检测；缺失时尝试通过 winget 安装推荐 Python 3.12 |
| Python worker 依赖 | 创建 `.venv`，安装/更新 `genanki`、`yt-dlp`、`pypdf` |
| FFmpeg | 缺失时尝试通过 winget 安装 |
| Deno / Node | 缺失时尝试通过 winget 安装 Deno |
| Anki 桌面端 | 缺失时尝试通过 winget 安装 |
| AnkiConnect | 不能静默安装；应用会打开 Anki 并提示插件代码 `2055492159` |

为什么不是“最新 Python”：当前推荐安装 Python 3.12，因为它更稳，避免最新版本带来依赖兼容波动。

## 模型与 TTS

当前设置页支持：

- Gemini Vertex：文本模型默认 `gemini-3.1-pro-preview`，使用本机 `gcloud` OAuth。
- Gemini Vertex TTS：默认 `gemini-3.1-flash-tts-preview`，使用本机 `gcloud` OAuth。
- MIMO / OpenAI-compatible。
- Qwen / DashScope。
- DeepSeek。
- 可扩展的自定义服务商配置。

每个模型方案和 TTS 方案都可以单独保存到“我的模型”或“我的 TTS”。Vertex 方案不显示 API Key 输入框，因为它不使用本地保存的 API Key。

## 多语言发音逻辑

内部语言使用稳定 code：

```ts
en | fr | es | ja | ru
```

默认 profile：

| 语言 | 读法体系 |
| --- | --- |
| English | IPA + weak forms/linking/stress |
| Français | API/IPA + liaison/e caduc |
| Español | 拉美通用读法，音节 + 重音，可选 IPA |
| 日本語 | 假名 + 可靠时标音高 |
| Русский | 带重音西里尔，可选 IPA |

V1 不做真实 ASR 或 forced alignment。没有音频实听时，`generation_basis` 默认是 `subtitle_inferred`，UI 和 Anki 卡面会标为推测口语读法或低置信度，不会把字幕推测包装成“剧中实听”。

## 质量与诊断

生成时会先召回学习点，再决定哪些生成完整卡片：

- 合法且高价值：生成完整可用卡片。
- 合法但未制卡：进入学习点诊断。
- 训练动作重复：折叠为重复诊断。
- `exact_span` 不在原句、`answer_core` 混入中文/IPA/解释：硬阻断。

默认不会为了数量硬凑低价值卡。用户想多导出时，可以直接在可用卡片里选择更多卡片；后续可继续扩展“从候选库一键生成更多完整卡”。

## 开发运行

```powershell
npm install
npm run tauri:dev
```

## 验证

常用检查：

```powershell
npm run lint
npm run test:unit
npm run build
python -m pytest tests\test_worker_quality.py -q -k "check_env or repair_env"
cargo check --manifest-path src-tauri/Cargo.toml
```

完整发布前检查：

```powershell
npm run check:full
npm run tauri:build
```

## 隐私与版权

- 不要把真实 API Key 写进源码、README、issue、日志或截图。
- 用户勾选保存时，密钥优先保存到 Windows Credential Manager；不可用时使用本机 DPAPI 加密文件。
- 使用第三方模型或 TTS 时，字幕、文档片段和生成字段会发送给对应服务商。
- 生成的视频片段、音频、字幕、`.apkg` 和项目缓存默认不提交到 Git。
- 第三方视频、字幕、文档和合成音频默认仅供个人学习使用。

## 更多文档

- [用户指南](docs/USER_GUIDE.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [架构说明](docs/ARCHITECTURE.md)
- [发布清单](docs/RELEASE_CHECKLIST.md)
