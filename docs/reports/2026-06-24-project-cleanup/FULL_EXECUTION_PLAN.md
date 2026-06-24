# Anki Card Generator 清洗后完整执行计划

## Summary

目标是把 Anki Card Generator Windows 桌面端收尾到一个干净、可信、可发起 PR 的状态：项目中不再出现 错误项目名串线；开发启动避开 Windows 保留端口；测试、启动、APKG smoke 全部可复现；本次 PR 不提交本地暂存的其它产品线资料。

## Key Changes

### 1. 命名清洗

- 全仓库扫描 错误项目名的多种拼写。
- 清理所有误命名报告、脚本路径和 Office 产物。
- 重新生成或重命名所有用户可见文档为 Anki Card Generator。
- Office 文件内部 XML 也必须无旧项目名。

### 2. 启动修复

- 当前机器 Windows 会动态保留端口范围，旧 dev port `1420` 和后来的 `1450` 都可能不可用。
- 启动脚本自动选择可监听端口；静态 fallback 统一为 `5173`。
- 同步更新：
  - `package.json`
  - `src-tauri/tauri.conf.json`
  - `scripts/start_desktop_dev.ps1`
  - `docs/TROUBLESHOOTING.md`
- 所有 JSON 必须 UTF-8 no BOM。

### 3. 验证链路

- 项目启动必须使用：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_desktop_dev.ps1 -TimeoutSeconds 180`
- 启动成功标准：
  - Vite ready at 自动选择的 `http://127.0.0.1:<selected-dev-port>/`
  - Tauri debug exe 运行。
  - 窗口标题为 `Anki 卡片生成器`。
  - startup JSON 中 `visible=true`。

### 4. GitHub 上传边界

允许提交：

- 产品源码。
- 启动脚本修复。
- 公开 Windows 桌面端 docs。
- 清洗报告。
- 必要测试与配置。

禁止提交：

- API key、`.env`、token、secret。
- `release/smoke/`。
- APKG、视频、音频。
- `src-tauri/target/`。
- `.venv/`、`node_modules/`。
- `test_runs/`、`projects/`。
- 临时 scratch、日志、缓存。
- `src-tauri/Cargo.toml` 的无内容换行符状态。
- 本地暂停资料目录不纳入本次 PR。

## Test Plan

必须通过：

```powershell
npm.cmd run check:versions
npm.cmd run test:ui
npm.cmd run smoke:release
npm.cmd run build
cargo check --manifest-path src-tauri/Cargo.toml
```

清洗检查：

```powershell
# 使用实际错误项目名的大小写/空格变体进行扫描；公开文档中只保留占位说明。
rg -uuu -n -i "<wrong-project-name-pattern>" .
```

结果必须为无命中，允许排除：

- `.git/`
- `node_modules/`
- `src-tauri/target/`
- `.venv/`
- `release/smoke/`
- `test_runs/`

安全检查：

- 文本 secret scan。
- Office 包内 secret scan。
- `git diff` / `git diff --cached` secret scan。
- 人工确认没有本机私密路径、API key、APKG、媒体文件。

## Acceptance Criteria

- 本地项目中没有 错误项目名残留。
- 当前开发版能从项目启动。
- UI smoke 通过。
- Release smoke 能生成并 verify APKG。
- Production build 通过。
- Cargo check 通过。
- GitHub 文档只称 Anki Card Generator / Anki 卡片生成器。
- 提交使用白名单 staging，不使用 `git add .`。

## Assumptions

- 当前产品名是 Anki Card Generator / Anki 卡片生成器。
- 当前可发布产品是 Windows 桌面端。
- 不删除用户配置、API key、本地缓存项目或历史素材。
- 不清空 release evidence，只通过 `.gitignore` 和白名单 staging 保持 GitHub 干净。

