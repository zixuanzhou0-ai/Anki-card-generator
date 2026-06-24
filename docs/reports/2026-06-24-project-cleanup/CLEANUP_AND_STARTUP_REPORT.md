# Anki Card Generator 项目清洗与启动验证报告

日期：2026-06-24  
对象：`E:\ANKI` 本地 Anki Card Generator 项目  
目的：清除误混入的 错误项目名 项目命名或冗余产物，确认项目能正常启动和测试，并为 Windows 桌面端 PR 收口提供干净证据。

## 1. 清洗结论

本次清洗后，`E:\ANKI` 项目中未再发现 错误项目名的多种拼写 命名残留。

已清理或修正：

- 修正报告目录中曾经错误出现的项目名。
- 修正 PPT QA 脚本里的旧 scratch 路径。
- 删除外部临时目录：`C:\tmp\codex-presentations\manual-20260624\old-wrong-project-verification`
- 删除生成缓存：`E:\ANKI\.pytest_cache`
- 将报告产物统一为 Anki Card Generator 命名。

保留：

- 本地暂停资料目录不纳入本次 PR，也不作为 GitHub 用户可见路线展示。
- `docs/reports/2026-06-24-cross-platform-verification/`，但其中项目名已修正为 Anki Card Generator。
- `release/smoke/` 本地 smoke 证据，不提交到 GitHub。

## 2. 全局扫描

执行范围：

- 仓库文本内容。
- 文件名和目录名。
- Word/PPTX Office 包内部 XML。
- 外部 PPT scratch 目录。

结果：

- 文本扫描：无 错误项目名命中。
- 文件名扫描：无 错误项目名命中。
- Office 包扫描：无 错误项目名命中。
- 外部错误 scratch：已删除。

说明：

- 历史日志和旧 handoff 中的端口记录不作为项目命名污染处理。
- 本次清洗不删除用户数据、API key、本地配置和可复用验收文档。

## 3. 启动问题与修复

最初从项目启动失败，原因不是 Anki Card Generator 代码坏了，而是本机 Windows 将 TCP `1344-1443` 端口段保留，旧开发端口 `1420` 正好落在保留段内，Vite 报错：

```text
Error: listen EACCES: permission denied 127.0.0.1:1420
```

修复：

- 将开发端口从 Windows 保留范围内的旧端口改为自动探测；静态 fallback 为 `5173`。
- 更新 `package.json` 的 `dev` script。
- 更新 `src-tauri/tauri.conf.json` 的 `build.devUrl`。
- 更新 `scripts/start_desktop_dev.ps1` 里的端口检测、ready 检查、错误文案。
- 更新 `docs/TROUBLESHOOTING.md`。
- 修复 Windows PowerShell 写 JSON 产生 BOM 的问题，将关键 JSON 文件重写为 UTF-8 no BOM。

## 4. 启动验证

命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_desktop_dev.ps1 -TimeoutSeconds 180
```

结果：通过。

证据：

- 当前项目开发版进程已启动：
  - `E:\ANKI\src-tauri\target\debug\anki-card-generator.exe`
- 窗口标题：
  - `Anki 卡片生成器`
- startup JSON：
  - `visible=true`
  - `show ok`
  - `set_focus ok`
  - `set_min_size ok`
- Vite：
  - 自动选择的 `http://127.0.0.1:<selected-dev-port>/`

## 5. 测试结果

已通过：

```powershell
npm.cmd run check:versions
npm.cmd run test:ui
npm.cmd run smoke:release
npm.cmd run build
cargo check --manifest-path src-tauri/Cargo.toml
```

摘要：

- 版本检查：`v0.9.4-beta` 通过。
- UI smoke：3/3 passed。
- Release smoke：生成 APKG 并 verify 通过。
- Production build：通过，仅保留 Vite chunk size 非阻塞警告。
- Cargo check：通过。

## 6. 当前注意事项

- `src-tauri/Cargo.toml` 仍显示换行符状态，但无内容 diff，不要误提交。
- `release/smoke/`、APKG、媒体文件、`src-tauri/target/` 不应提交到 GitHub。
- PowerShell profile 仍会在普通 `powershell` 命令下输出 oh-my-posh / PSReadLine 噪声；启动脚本验证应使用 `-NoProfile`。
- 启动脚本已改为自动探测 dev port；如果全部候选端口都不可用，需要扩展候选列表。

## 7. 最终判断

项目命名污染已经清理干净。Anki Card Generator 当前项目能正常启动、正常测试、正常 build、正常 smoke 导出 APKG。当前最重要的后续工作是：用白名单方式提交这些清洗和端口修复；本次 PR 只面向 Windows 桌面端，不发布或承诺其它产品线。

