# Anki Card Generator v0.9.6-beta 测试与交付记录

## 1. 本轮范围

本轮只验收 Windows 桌面端 Anki Card Generator，不包含网页端 / Local Helper，不提交 `docs/web-helper/`，不把安装包、APKG、视频、音频、缓存或 smoke 原始证据加入 Git。

目标版本：`v0.9.6-beta`。

核心改动：

- 默认统一为一种 `学习卡`：一个选中的 learning point 只生成一张卡。
- 推荐质量收口：低迁移、不可定位、过泛或训练动作不清楚的学习点降为候选/待审。
- 设置页新增 `关于 / 版权`，包含版本、版权声明、Anki 独立声明、隐私边界和 GitHub 仓库入口。
- Vertex AI 模型目录新增 `gemini-3.5-flash`。
- 保留 v0.9.5 的无终端弹窗策略和左侧栏紧凑布局修复。

## 2. 交付物路径

本地工作区交付目录：

`E:\ANKI\.local-delivery-v0.9.6-beta`

桌面交付目录：

`C:\Users\Administrator\Desktop\Anki卡片生成器_v0.9.6-beta`

桌面目录结构：

- `安装包\Anki卡片生成器_v0.9.6-beta_安装程序.exe`
- `安装包\Anki卡片生成器_v0.9.6-beta_MSI安装包.msi`
- `安装包\Anki卡片生成器_v0.9.6-beta_便携版.zip`
- `安装包\SHA256校验值_v0.9.6-beta.txt`
- `说明文档\Anki卡片生成器_中文使用手册_v0.9.6-beta.md`
- `说明文档\Anki卡片生成器_中文使用手册_v0.9.6-beta.docx`
- `说明文档\Anki卡片生成器_产品介绍与使用方法_v0.9.6-beta.pptx`
- `截图\*.png`

## 3. 已完成自动化验证

已通过：

- `npm.cmd run check:versions`
- `npm.cmd run lint`
- `npm.cmd run test:unit`：62 files / 465 tests passed
- `npm.cmd run test:ui`：3 Playwright smoke tests passed
- `npm.cmd run test:worker`：440 Python worker tests passed
- `cargo check --manifest-path src-tauri/Cargo.toml`
- `npm.cmd run build`
- `npm.cmd run tauri:build`
- `npm.cmd run smoke:release`：生成 1 张可用卡，导出 APKG，写入 verify report

安装包构建输出：

- NSIS setup exe 构建成功
- MSI 构建成功
- 便携 zip 已生成
- 桌面交付目录 SHA256 校验通过
当前桌面交付安装包 SHA256：

- `Anki卡片生成器_v0.9.6-beta_安装程序.exe`：`5be884d991cef3bba7799a640dd971fcc7f12280a842b7d6bad5e6e02d3045a1`
- `Anki卡片生成器_v0.9.6-beta_MSI安装包.msi`：`b58dad3166659b5f334fa8836f07dd9b04450c2db8ecac59d90f3cb5b53afa8d`
- `Anki卡片生成器_v0.9.6-beta_便携版.zip`：`2deb87b069441378608f65515e7a19b0a6b7918961388d2892536ce75366b00f`

## 4. 无终端弹窗检查

已检查：

- `scripts/start_desktop_dev.ps1` 默认 `WindowStyle Hidden`，调试入口才显示控制台。
- Rust/Tauri `Command::new` 普通探测和 worker 启动路径调用 `hide_console_window`。
- Python worker 的 `subprocess.run/Popen` 静态 AST 检查通过，扫描范围内所有外部工具调用都包含隐藏窗口 flags。

安装版实测：

- 已卸载旧程序本体，保留 `C:\Users\Administrator\AppData\Local\com.ankicard.generator` 配置目录。
- 初次 silent install 发现旧注册表 `InstallLocation` 指向历史桌面测试目录，导致安装登记为 0.9.6 但 exe 文件仍为旧路径/旧版本；该问题已定位并作为本机污染处理。
- 已删除旧程序目录，不删除配置目录；使用 NSIS `/S /D=C:\Users\Administrator\AppData\Local\Anki Card Generator` 显式安装。
- 重装后 `winget list --name "Anki Card Generator"` 显示 `0.9.6`。
- 已安装 exe `ProductVersion=0.9.6`、`FileVersion=0.9.6`，注册表 `InstallLocation` 指向标准用户安装目录。
- 从安装目录启动后窗口标题为 `Anki 卡片生成器`；进程树只有主程序和 `msedgewebview2.exe`，`cmd.exe` / `conhost.exe` / `powershell.exe` / `python.exe` 计数为 0；WebView2 命令行显示 `--webview-exe-version=0.9.6`。

## 5. 文档 QA

Markdown：已生成中文使用手册。

Word：已生成并执行隐私元数据清理；DOCX 结构检查通过，包含 4 张截图，无 comments/revisions。由于本机未安装 LibreOffice/`soffice`，无法执行 DOCX 页面 PNG 渲染 QA。

PPT：已使用 `@oai/artifact-tool` 生成；导出 11 页 PNG 和 montage；基础 QA 通过：页面数量 11、尺寸 1280x720、非空、元素未越界。

## 6. 安全扫描

已通过：

- Git diff 高置信密钥扫描
- staged diff 高置信密钥扫描
- 最终交付目录扫描
- DOCX/PPTX 解包 XML/rels 扫描
- 桌面安装包 SHA256 与校验文件逐项匹配

未提交/不得提交：

- `.local-delivery-v0.9.6-beta/`
- `release/smoke/`
- `docs/web-helper/`
- 安装包、APKG、视频、音频、缓存、日志、test_runs、target、node_modules、`.venv`

## 7. 下一步人工验收

建议你从桌面交付目录开始：

1. 关闭正在运行的 Anki 卡片生成器。
2. 使用 `安装包\Anki卡片生成器_v0.9.6-beta_安装程序.exe` 安装。
3. 从开始菜单或安装目录启动，确认没有黑色终端弹窗。
4. 打开 `设置 -> 模型 API`，确认 Vertex 可见 `gemini-3.5-flash`。
5. 打开 `设置 -> 关于 / 版权`，确认版权声明和 GitHub 仓库按钮可见。
6. 用小视频 + SRT 跑素材输入、抽取学习点、生成统一学习卡、导出 APKG。
7. 如本机 Anki/AnkiConnect 可用，执行导入/verify。

## 8. GitHub 发布前边界

如继续推送 GitHub，应使用白名单 staging，只加入源码、公开文档、release notes 和必要测试文件。桌面交付目录与本地构建产物只用于交付和人工验收，不提交到仓库。