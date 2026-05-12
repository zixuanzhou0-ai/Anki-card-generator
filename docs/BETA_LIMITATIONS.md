# Beta 限制说明

`v0.9.2-beta` 是 Windows 内测版本，目标是验证本地视频 / SRT / YouTube / 文档制卡主流程。它还不是“开箱即稳”的大众发行版。

## YouTube 导入

YouTube URL 导入依赖 yt-dlp。失败原因可能包括：

- YouTube 返回 HTTP 429 或临时限流；
- 字幕接口不可用；
- n challenge / EJS 规则变化；
- 区域限制、登录限制或网络代理问题；
- 本机缺少 Deno / Node.js，导致 yt-dlp 不能执行 JavaScript challenge solver。

如果 URL 导入失败，建议先下载视频和 SRT，再走“本地视频 + SRT”。

## 模型和 TTS

- MIMO / DeepSeek / OpenRouter / Claude / Gemini / xAI / 自定义兼容接口都属于第三方服务。
- 使用模型评审或 TTS 时，字幕、文档片段和 TTS 文本会发送给对应服务商。
- TTS 可能产生费用，且不同服务商的 voice、model、format 支持不完全一致。

## 本地依赖

便携包不内置 Python、FFmpeg、Anki、Deno / Node.js。`scripts/setup_runtime.ps1` 会创建项目本地 `.venv` 并安装 Python worker 依赖，但仍需要系统能找到 Python 和 FFmpeg。

## 媒体裁切精度

视频片段裁切基于字幕时间和词序估算。没有逐词级时间戳时，片段可能略早或略晚。后续如果接入 Whisper word timestamp，对齐会更精确。

## 文档导入

TXT / Markdown / DOCX / EPUB / PDF 的文本抽取质量取决于文件格式。扫描版 PDF、复杂排版、图片文字和多栏布局可能无法完整解析。

## 版权和分享

生成的 `.apkg` 可能包含视频片段、字幕和文档摘录。默认用途是个人学习。公开分享 deck 前，请确认你有权分发这些素材。
