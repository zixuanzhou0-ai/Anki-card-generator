# Anki Card Generator 项目说明

## 1. 产品定位

Anki Card Generator 当前的可交付产品是 Windows 桌面端。它面向需要从真实视频、字幕和语言材料中快速生成 Anki 卡片的学习者、教师和内容整理者。

当前桌面端能力已经覆盖一条完整路径：

1. 输入本地视频 + SRT，或输入视频链接。
2. 选择学习水平、卡片模式和内容偏好。
3. 让 AI 抽取值得学习的表达、句子和语境。
4. 用户审核学习点。
5. 生成带视频、音频、TTS、解释和练习字段的 Anki 卡。
6. 导出 APKG。
7. 通过 Anki/APKG verify 检查媒体、字段和模板是否完整。

这不是单纯的“字幕转卡片”工具，而是一个视频语言学习材料生产台。

## 2. 当前 Windows 桌面端能力

### 2.1 素材输入

支持：

- 本地视频。
- SRT 字幕。
- 批量视频文件夹。
- 视频链接模式。

当前公开版本聚焦视频制卡，不再把文档制卡作为 README 的主叙事，以免用户误解产品重点。

### 2.2 学习点抽取

系统会基于字幕和上下文抽取学习点。用户可以在生成 APKG 前审核、选择或调整学习点，避免自动把所有候选内容直接变成卡片。

### 2.3 卡片模式

当前用户可见重点：

- 完整复读：适合精听、复述、上下文沉浸。
- 快速复读：适合快速刷句、短时间复习。

### 2.4 TTS 和媒体

支持 TTS 设置和导出。APKG 内可以包含：

- 视频 MP4。
- 视频 WebM。
- poster 图片。
- 原始音频。
- TTS 音频。
- phrase 音频。

Release smoke 已验证这些媒体能被 APKG 正确引用。

### 2.5 Anki 导出与核验

导出后会进行 APKG 结构校验。当前 smoke 证明：

- 卡片数量正确。
- 模板存在。
- 视频字段存在。
- MP4/WebM source 存在。
- poster 字段存在。
- 音频字段存在。
- 媒体无缺失、无无效、无未引用。

## 3. GitHub 上用户如何理解项目

GitHub 当前应让用户清楚看到三件事：

1. 当前 Release 是 Windows 桌面端。
2. Windows 用户下载 NSIS installer、MSI 或 portable zip。
3. macOS/Linux 用户暂时不能直接使用 Windows 桌面端，但可以关注下一阶段 Browser + Local Helper 规划。

建议 README 顶部未来增加一个“Choose your build”区域：

| 用户类型 | 应选择 |
|---|---|
| Windows 普通用户 | GitHub Release 的 Windows installer |
| Windows 高级用户 | MSI 或 portable zip |
| macOS/Linux 用户 | 等待 Browser + Local Helper 版本 |
| 开发者 | 阅读 `docs/web-helper/` 与架构文档 |

## 4. 截图与用户告知

当前已有截图覆盖：

- 主工作台。
- 流程开始。
- 生成结果。
- 设置页。
- 模型/API 设置。
- TTS 设置。
- 本地环境设置。
- Anki 成品卡正面/中间/背面状态。

这些截图对用户非常重要，因为它们直接回答：

- 这个工具长什么样。
- 生成流程是不是完整。
- 设置入口在哪里。
- 最后进 Anki 的卡片是什么样。

后续建议继续补充：

- 安装版最小窗口 compact 模式截图。
- “素材面板”打开后的截图。
- 批量文件夹选择入口截图。
- APKG 导出完成页截图。

## 5. Windows 桌面端与浏览器端分离规划

用户提出的关键要求是：Windows 端和浏览器端必须完全分开，不能混成一个文件夹。

推荐仓库结构：

```text
apps/
  desktop-windows/
    README.md
    src/
    src-tauri/
    workers/
    scripts/
  browser-web/
    README.md
    src/
    public/
    tests/
  local-helper/
    README.md
    src/
    api/
    installers/
packages/
  shared-types/
  shared-card-model/
  shared-ui-tokens/
docs/
  desktop/
  web-helper/
  reports/
```

原则：

- Windows 桌面端继续使用 Tauri 和原生 worker 能力。
- 浏览器端只负责 UI、项目编排、本地设置和调用 helper。
- Local helper 负责浏览器不能直接做的本地能力：读写本地文件、视频处理、ffmpeg、APKG 导出、AnkiConnect、缓存和本地安全边界。
- 共享层只放类型、卡片 schema、非敏感 UI token，不放平台专用逻辑。

## 6. 为什么浏览器端需要 local helper

Tauri 前端看起来像浏览器，但它背后有原生后端能力。纯静态网页不能直接获得这些能力：

- 不能任意读写本地路径。
- 不能直接执行 ffmpeg。
- 不能自由启动 Python worker。
- 不能像桌面应用一样打包本地二进制。
- 不能直接访问 AnkiConnect 以外的本地服务。
- 不能稳定保存大型媒体缓存。

因此浏览器端要想达到桌面端能力，需要一个用户主动安装/启动的 local helper。浏览器 UI 通过 localhost 与 helper 通信。这样用户体验接近桌面端，但安全边界更清楚。

## 7. 插件和工具调用计划

### GitHub / gh CLI

用途：

- 检查 Release。
- 下载资产。
- 核对 tag、asset digest、README 和 About。
- 后续创建 PR 和更新公开文档。

### Playwright

用途：

- UI smoke。
- 最小窗口布局测试。
- 素材面板、批量入口、CTA 可达性。
- 后续浏览器端 E2E。

### documents:documents

用途：

- 生成 Word 报告。
- 使用固定设计预设。
- 渲染 DOCX 为 PNG。
- 检查每页是否有重叠、裁切、表格溢出。

### presentations:Presentations

用途：

- 生成 PowerPoint 演示稿。
- 使用 `@oai/artifact-tool`。
- 渲染 slide previews 和 montage。
- 检查标题、截图、排版、层级和重叠。

### codex-security 或本地 secret regex

用途：

- 扫描 API key、token、secret。
- 检查 diff、报告文档和准备上传内容。
- 防止截图或文档泄露本地私密信息。

### PowerShell / winget

用途：

- 检查本机安装登记。
- 启动/关闭安装版。
- 计算 SHA256。
- 检查进程和安装路径。

## 8. 当前验收结论

Anki Card Generator 当前 Windows 桌面端已经进入高度可用的 beta 阶段。它不是完美的最终版，但已经具备公开 Release、用户下载测试、生成真实 APKG、验证媒体完整性的能力。

下一阶段真正重要的不是继续把更多东西塞进当前 Tauri 文件夹，而是把 Windows 桌面端、浏览器端和 local helper 拆成清晰产品线。这样用户不会困惑，开源贡献者也能知道自己应该改哪一部分。

## 9. 推荐下一阶段目标

1. 将 `docs/web-helper/` 推进为正式公开路线图。
2. 在 README 中增加 Windows Desktop 与 Browser + Helper 的选择说明。
3. 新建 `apps/browser-web/` 和 `apps/local-helper/`，先放最小可运行骨架。
4. 定义 helper API：health、settings、project、media、generate、export、verify。
5. 做一个浏览器端最小闭环：选择素材、连接 helper、生成 demo APKG。
6. 做跨平台安装说明：Windows/macOS/Linux helper 如何启动，端口如何授权。


