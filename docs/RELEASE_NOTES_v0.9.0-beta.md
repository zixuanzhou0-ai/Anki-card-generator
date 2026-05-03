# v0.9.0-beta

这是第一个面向 Windows 内测的 beta 版本。

## 重点变化

- 支持 YouTube URL、本地视频 + SRT、文档三种输入。
- 增加 MIMO 词伙候选评审，默认保留高价值表达。
- 增加自动片段预算，根据视频长度和字幕密度决定候选数量。
- 增加更精确的媒体裁切窗口，导出视频片段更贴近目标词伙。
- 优化 Anki 卡片模板的自适应缩放，减少半屏和全屏下的滚动压力。
- 修复推荐筛选后 `.apkg` 导出时“没有启用卡片”的问题。
- 打包时包含 Python worker 资源，发布包不再依赖源码目录。
- release 运行目录改为用户 AppData，避免安装目录写入权限问题。

## 已知限制

- Windows 便携包不内置 Python、FFmpeg、Anki。
- YouTube 导入依赖 yt-dlp，遇到网站变更时需要更新 yt-dlp。
- 视频裁切基于字幕词序估算；若要逐词级精准裁切，后续需要 Whisper word timestamp 对齐。
- MIMO API Key 需要用户自行配置，release 不包含任何真实密钥。

## 推荐测试

1. 设置页运行环境检查。
2. 本地视频 + SRT 生成并导出。
3. YouTube vlog 生成并导出。
4. 讲解类 YouTube 视频生成并导出。
5. Anki 导入后检查视频、原声、TTS、词伙 TTS。
