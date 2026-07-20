# Codex 插件开发安装验证报告

> 状态：CURRENT 开发安装切片证据
> 日期：2026-07-20
> 结论：开发态 Plugin/Skill 与本地 stdio MCP 可以安全安装、升级、发现和卸载；这不是正式签名发布，也不证明完整富媒体制卡目标已经完成。

## 1. 本轮验证对象

- 被动 Skill 插件：`anki-study-agent`
- Marketplace：`anki-study-agent-local`
- Card Service MCP：`anki-study-card-service`
- Codex CLI：`0.144.1`
- Python：`3.13.12`
- AnkiConnect：字面 loopback `127.0.0.1:8785`

开发安装器先把 Marketplace/Plugin/Skill 输入源和 Card Service runtime 分别发布为内容寻址私有快照，再通过 Codex CLI 注册。MCP 使用 `python.exe -I -S -B <digest>/launcher.py`，不设置 `cwd` 或环境变量。Codex 会把 Skill 从私有源快照摄取到自己的托管插件缓存；本轮安装器验证源快照、Codex 返回的版本/来源和 MCP runtime，不把该托管缓存声明为同一逐文件 DACL 信任根。

## 2. 真实安装、升级与卸载

隔离 `CODEX_HOME` 中完成：

1. 初次安装成功，Plugin、Marketplace 与 MCP 均指向 `%USERPROFILE%\.anki-study-agent` 下的具体 digest。
2. 使用 Plugin Creator 官方 cachebuster 执行升级，Plugin 版本和私有插件 digest 同时变化，旧 Plugin/runtime 快照保留。
3. 卸载成功移除 Plugin、MCP 与 Marketplace；用户状态和不可变快照保留。
4. 再安装后，Codex 托管缓存中存在与当前版本对应的 `SKILL.md`。

当前用户环境最终安装证据：

- Plugin version：`0.1.0+codex.20260720065818`
- Plugin snapshot digest：`a0b1dd2eb5b9a4f37c97aa0db118ededc2d8a0b1b18c9a15818fa7cf77a61f42`
- Runtime snapshot digest：`7a96cdcc506e51a8a5fe72903c378aee0ae3551fde7fb6ea82dabc2a34c5473a`
- Runtime resources：173
- 固定媒体工具：`ffmpeg.exe`、`ffprobe.exe`、`yt-dlp.exe`

同一安装器的协作进程使用全局 Windows 命名互斥串行化。原生 Codex CLI 没有为按名称删除公开 compare-and-swap 接口，因此绕过安装器的并发 `codex plugin/mcp` 修改属于明确不支持边界；不能宣称已消除所有外部 TOCTOU 竞态。

## 3. MCP 与新 Codex 会话

直接 stdio 握手验证：

- 初始化协议：`2025-06-18`
- Server：`anki-study-card-service 0.1.0`
- 公共工具：38
- `audienceBinding.available=true`
- `mode=development_explicit`
- `identifiersDisclosed=false`
- `toolArgumentsCanDeclareAudience=false`

随后启动新的临时 Codex CLI 会话，只允许调用 `system.get_capabilities`。会话真实记录到：

~~~text
mcp: anki-study-card-service/system.get_capabilities started
mcp: anki-study-card-service/system.get_capabilities (completed)
~~~

返回的五项能力与直接 stdio 探针完全一致。这证明新任务能够发现安装后的 Skill/MCP；当前已打开的旧任务仍需新任务边界才能刷新插件目录。

该 Codex 会话启动期间还出现本机模型缓存旧 schema 警告和 WebSocket 503/超时，随后回退到 HTTPS 并完成 MCP 调用。它没有改变 Card Service 结果，但属于 Codex 宿主网络/缓存环境信号，不应掩盖。

## 4. 安全复核结果

- Plugin 与 runtime 快照使用 canonical manifest、精确文件集、大小和逐文件 SHA-256。
- 私有快照、状态根与安装身份使用受保护精确 DACL。
- Python 信任链只接受当前用户、SYSTEM、Administrators 与精确 TrustedInstaller SID；任意其他 `S-1-5-80-*` Service SID 不再被信任。
- 启动前复核 Python 前缀、解释器、DLL、标准库、实际第三方依赖和祖先替换权限。
- 安装事务保留底层失败步骤、部分状态和未恢复组件，不把失败回滚报告为成功。
- 同名陌生 Plugin、Marketplace 或 MCP 在可观察到时停止，不提供强制覆盖开关。
- 文档已明确区分私有安装输入快照与 Codex 托管 Skill 缓存。

真实素材选择复测额外发现并关闭了一个重启级缺陷：旧版受信窗口子进程会在不可变 runtime 中写入 `__pycache__`，导致下一次启动按完整性规则失败。当前子进程使用隔离模式、`-B` 和最小受控环境，真实选择文件后 runtime 中 `.pyc` 数量保持为 0，随后再次启动仍返回全部 38 个工具。升级器还允许把“仅多出 CPython bytecode cache、其余 manifest 资源逐字节完整”的旧注册识别为本安装器所有并安全替换；任何其他额外文件、缺失文件或资源哈希变化仍按陌生/损坏注册拒绝覆盖。

## 5. 自动化证据

本轮最终结果：

- Plugin Creator validator：通过。
- Codex 文档 validator：22 份权威设计文档通过；本验证报告作为附加证据同时参与通用敏感信息扫描。
- 插件/安装/ACL/来源定向聚类：先前 115 项通过；重启缺陷修复后的定向复测为 105 项通过，另有受信窗口 17 项和损坏快照恢复 3 项通过。
- 正式 Python `tests`：1755 项通过，1 项按环境设计跳过；两个 ZIP 重复条目警告来自故意的失败关闭语料。
- Vitest：830 项通过。
- Worker `unittest discover`：602 项通过。
- Rust：31 项通过，1 项密钥环写入测试按设计忽略。
- UI smoke：`source-selector`、`compact-workbench`、`settings-and-workflow` 通过。
- `npm run check:full`：通过，包括 V15/V10 APKG release smoke。
- `npm run tauri:build`：通过，生成 MSI 与 NSIS 两种安装包。

## 6. 尚未被本报告证明的目标

本报告只关闭“高级用户开发安装与发现”切片，不关闭以下目标：

- Hermes Grok 4.5 的真实 xAI 候选发现仍需在上游可达时重新跑通；此前真实验证在 xAI 连接处超时并正确失败关闭。
- 当前 Card Service 公共生成仍是英语确定性文本/零媒体切片，不等于桌面端 V15 的中英双语解释、例句、TTS、原声、视频和高亮卡。
- Codex 宿主 attachment bridge、Office、扫描 PDF/OCR、无字幕媒体 ASR、完整远程媒体 acquisition 和通用知识卡仍未交付。
- Anki 最高公共证据仍是 `anki_data_verified`；渲染、翻面、播放、焦点、复习交互和重启持久性的插件 runtime verifier 尚未实现。
- 正式发布者签名、内嵌 `.mcp.json`、正式安装包与 Codex App/右侧栏 UI 尚未完成。

因此，正确结论是“开发插件已可安装并被新 Codex 任务发现”，不是“用户设想的全部 Codex 制卡产品已经完成”。
