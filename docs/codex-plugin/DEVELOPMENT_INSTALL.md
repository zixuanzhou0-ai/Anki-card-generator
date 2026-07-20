# Codex 插件开发安装、升级与卸载

> 状态：CURRENT 高级用户源码路径
> 日期：2026-07-20
> 最低宿主：Codex CLI `0.144.1`
> 运行时：CPython `3.13`
> 发行结论：这不是生产签名安装包

## 1. 这条路径解决什么

仓库现在是一个可被 Codex CLI 识别的本地 Marketplace：

- Marketplace：`anki-study-agent-local`
- Plugin：`anki-study-agent`
- 独立 MCP：`anki-study-card-service`

安装器只调用正式 Codex CLI 管理命令，不手改 `config.toml` 或 Marketplace 注册状态。它会：

1. 验证 Codex 版本、CPython 版本和 Worker 依赖。
2. 把 Card Service、Worker、启动器及可选媒体工具复制到 `%USERPROFILE%\.anki-study-agent\codex-dev-runtime\<manifest-sha256>`；快照由规范 manifest、资源角色、大小与逐文件 SHA-256 完整寻址。
3. 把 Marketplace、Plugin manifest、Skill、Agent metadata 与参考合同独立复制到 `%USERPROFILE%\.anki-study-agent\codex-dev-plugin\<manifest-sha256>`；Codex 以该只读快照为安装输入，再把 Skill 摄取到自己的托管插件缓存，因此不会从 Git 工作区加载已安装 Skill。
4. 在任何 Codex 配置写入前为应用根、运行时、插件、状态根、安装身份和每个快照文件应用受保护的精确 Windows DACL，只允许当前用户、SYSTEM 和 Administrators 管理；同时检查用户目录祖先的替换权限。
5. 通过 `codex plugin marketplace add` 登记私有插件 digest 快照，而不是当前仓库。
6. 通过 `codex mcp add` 注册一个直接指向具体 digest 快照、固定参数且不含环境变量/cwd 的 stdio Card Service。
7. 最后通过 `codex plugin add` 安装 Skill 插件，并只读复核 Marketplace、Plugin 版本和 MCP。
8. 要求新建 Codex 任务，使新的 Skill 与 MCP 工具目录生效。

开发启动器只接受 AnkiConnect 端口。它固定使用快照内 Worker、安装时验真的 CPython、私有状态目录和字面 loopback AnkiConnect URL；不会从 Git 工作区回退，也不接受任意 Worker、模型端点、Provider、密钥、Shell、环境变量或输出目录参数。启动时会先用标准库复核 manifest、快照目录名、完整文件集、逐文件哈希和 Python 身份，然后才导入快照内 Card Service。

## 2. 前置条件

在仓库根目录执行：

```powershell
python -m pip install -r workers/requirements.txt
codex --version
```

必须满足：

- `codex-cli 0.144.1` 或更新版本。
- 当前 `python` 为 CPython 3.13。
- `genanki`、`yt-dlp`、`pypdf`、`cryptography` 可以从该 Python 导入。
- Python 安装根、启动 DLL、标准库及实际使用的第三方依赖必须位于 Windows 受保护路径，其他普通或沙箱主体不能修改；安装器会逐项检查并失败关闭，不接受工作区虚拟环境作为可信 MCP Python。MCP 固定使用 `-I -S -B`，禁用自动 `site`、`.pth` 和 `sitecustomize` 后才显式加入已检查的依赖目录。
- 若需要媒体能力，PATH 中存在稳定的 `ffmpeg.exe`、`ffprobe.exe` 和 `yt-dlp.exe`。
- 若需要直接导入，Anki 与 AnkiConnect 已启动。

## 3. 安装

通常直接运行：

```powershell
python scripts/install_codex_study_plugin_dev.py install
```

安装器会只读探测 `8765` 和 `8785`。恰好一个端口返回合法 AnkiConnect `version` 响应时使用该端口；都不可用时保守登记官方默认 `8765`，但不会伪称 Anki 已就绪。可显式指定：

```powershell
python scripts/install_codex_study_plugin_dev.py install --anki-connect-port 8785
```

如果只需要文本流程，可跳过开发媒体工具复制：

```powershell
python scripts/install_codex_study_plugin_dev.py install --skip-tool-staging
```

成功输出固定包含：

- `mode=development_private_snapshot`
- `productionSigned=false`
- Codex/Python 版本
- Marketplace、Plugin 和 MCP 状态
- AnkiConnect 端口及其选择依据
- 内容寻址运行时根与插件根、两份 manifest SHA-256、资源数量，以及已复制/缺失的媒体工具名称；不返回工具原始发现路径
- `newThreadRequired=true`

## 4. 升级

拉取或切换到已经验证的新代码后执行：

```powershell
python scripts/install_codex_study_plugin_dev.py upgrade
```

升级会：

- 确认 Marketplace 名称仍指向一个完整、未篡改的旧私有插件快照。
- 调用 Plugin Creator 官方 `update_plugin_cachebuster.py` 生成新的 `+codex.<token>` 版本，并验证版本确实变化。
- 分别创建新的不可变 Plugin 与 runtime digest 快照；Marketplace 和 MCP 直接切换到具体快照，不使用 `current` symlink/junction。
- 只在现有 MCP 的 Python、参数、私有快照、manifest、DACL、env 和 cwd 全部严格匹配时替换它。
- 在 Plugin 写入失败时恢复旧 MCP/Marketplace；升级验证失败时原子恢复旧 manifest 并重新安装旧 Plugin 版本。
- 不触碰项目、APKG、Anki 牌组或 Card Service 状态目录。

若同名 MCP 来自其他程序、参数有任何额外项，或旧私有快照已损坏，安装器停止且不覆盖。没有“强制替换陌生 MCP”开关；必须先独立审计并处理冲突。

## 5. 卸载

移除 Plugin 与 MCP，但保留 Marketplace：

```powershell
python scripts/install_codex_study_plugin_dev.py uninstall
```

同时移除 Marketplace 登记：

```powershell
python scripts/install_codex_study_plugin_dev.py uninstall --remove-marketplace
```

卸载不会删除：

- 已生成的 APKG。
- Anki 牌组或媒体。
- Card Service 任务、项目和恢复检查点。
- 私有运行时快照、稳定安装身份和快照内媒体工具副本。

这些内容必须由用户单独审计后清理，避免卸载动作误删学习资料或恢复证据。

## 6. 验证

安装后可以只读检查：

```powershell
codex plugin list --json
codex mcp get anki-study-card-service --json
```

必须看到：

- `anki-study-agent@anki-study-agent-local` 已安装且启用。
- MCP transport 为 `stdio`。
- 命令是当前 CPython。
- Marketplace root 位于 `%USERPROFILE%\.anki-study-agent\codex-dev-plugin\<digest>`，Plugin source 位于其 `plugins\anki-study-agent`，两者都通过插件快照 manifest 与精确 DACL 复核。
- 参数固定为 `-I -S -B %USERPROFILE%\.anki-study-agent\codex-dev-runtime\<digest>\launcher.py --anki-connect-port <port>`。
- `cwd` 为空、`env` 为空，launcher 的父目录名等于 manifest SHA-256。
- 修改或重命名仓库不会改变已安装 MCP 的代码来源。

随后新建 Codex 任务，先调用 `system.get_capabilities`。可信开发会话应枚举当前 38 个公共工具，且 `audienceBinding.available=true`、`mode=development_explicit`。能力快照只代表工具注册和当前本地能力，不代表 Hermes 公网、TTS、Anki 或真实制卡已经成功。

## 7. 安全与发行边界

这条源码路径面向项目作者和高级贡献者：

- 安装时仍信任当前 Git 工作副本提供的源码字节；安装完成后 MCP 直接读取私有、内容寻址且受精确 DACL 保护的 runtime 快照，Codex 则从私有插件快照摄取 Skill 到自己的托管缓存。安装器验证输入快照、安装版本与 Codex 报告的来源，不宣称托管缓存继承了相同的逐文件 DACL/哈希保证。
- 安装、升级与卸载持有同一 Windows 跨进程互斥，并在每次按名称删除前复核精确来源。该保证只覆盖使用本安装器的协作进程；用户在事务期间直接运行绕过安装器的 `codex plugin/mcp` 修改既不持有此锁，也无法由当前 Codex CLI 以 compare-and-swap 原子删除，因此属于不支持的并发管理方式。安装器会对可观察到的状态变化停止并报告部分恢复状态，但不宣称能消除最后一次检查与原生 CLI 写入之间的所有竞态。
- 开发 audience 以受保护的随机安装身份、当前 Windows 用户 SID 和 Plugin ID 派生稳定 host scope；升级快照不会让旧项目失去作用域，每次进程启动仍使用新的 session nonce。
- 这仍是“同一 OS 用户可信”的高级开发边界：同一用户或本机管理员可以重写私有安装，不能把它表述为正式发布者证明。
- 它没有 Authenticode 发布者身份、正式 Ed25519 发布密钥、可信时间戳或生产安装 anti-rollback 证明。
- 它不会生成 `.mcp.json` 到被动源码 Plugin，也不会把测试签名改称生产签名。
- 它不能作为普通 GitHub 用户“一键可信安装”的证据。

正式安装包继续要求：外部发布密钥管理、受信代码签名证书、证书 pin/revocation policy、签名 launcher、finalizer 三重复核和独立复制后的真实 Codex 安装验收。缺失任一项都保持 fail closed。
