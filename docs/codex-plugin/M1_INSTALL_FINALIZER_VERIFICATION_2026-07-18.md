# M1 安装最终化验证报告：2026-07-18

> 状态：CURRENT；M1 安装发布闭环切片已实现并通过验证，完整 M1 仍在进行中
> 日期：2026-07-18
> 范围：Codex 插件安装候选、独立签名请求、Windows Authenticode 闸门、原生 install-only 预检、原子发布与失败关闭
> 不包含：生产发布证书、HSM 私钥操作、正式 marketplace 安装、用户 Codex 配置写入、M2 Artifact 注册表

## 1. 结论

仓库现在具备一条不读取私钥、不联网、不修改用户 Codex 配置的安装发布闭环：构建 MCP-wired 候选、生成 public-key-only 待签请求、接收仓库外 detached signature，并在隔离 staging 中完成 Ed25519 域验签、Windows Authenticode 与外部证书 pin、精确资源/DACL、原生 `--verify-install-only` 和原子发布。发布后还会再次执行 Python、Authenticode 与原生三重复核。

这不等于正式插件已经可安装。当前真实 launcher 的 Windows 签名状态仍为 `NotSigned`，仓库也没有生产发布策略或 HSM 返回签名，因此正式 builder/finalizer 必须失败关闭。测试中的内存证书、临时 Ed25519 key 和伪原生回调只证明合同与故障语义，不能建立发布身份。

## 2. 新增合同

- 安装 manifest 使用独立 `study.plugin-install-manifest.v1` 域；被动发布签名不能跨域复用。
- `.mcp.json` 固定只启动包内 `./server/launcher/anki-study-agent.exe --stdio`，cwd 固定为插件根，工具超时固定为 900 秒。
- install candidate 精确绑定插件 manifest、MCP 配置、外层 SPDX、launcher、外部发布策略摘要，以及委托 runtime manifest/trust digest。
- 正式 Python API 与 CLI 不接受私钥、测试 Authenticode verifier、伪原生 verifier 或调用方提供的验证时间。
- finalizer 失败时不会产生最终目录，不会修改候选，不会推进本机回滚地板。
- 原生 `--verify-install-only` 会完整验证外层安装授权与委托 runtime 后退出，不启动 Python；被动 launcher 固定拒绝该模式。
- 正常 `--stdio` 仍只在全部资源验证后推进单调回滚地板。

## 3. 实物证据

| 实物 | 结果 |
|---|---|
| 两个隔离 `/Brepro` launcher 构建 | 均为 315,392 bytes |
| launcher SHA-256 | `b73d06c4739d9db5d76184c0261ba53220f2f2dc1abffe2bb4d1327b4ae16619` |
| 被动候选资源 | 4,391 项 |
| 被动候选总字节 | 289,217,313 bytes |
| 候选 manifest SHA-256 | `66a5ebaa23529415c5d3e9117302d8c79ff8dc2bee5e99a47846ae180b87bdc1` |
| 官方 plugin validator | 通过 |
| 真实 Codex 宿主 | Codex `0.144.1` 在隔离环境连续两次完成唯一只读工具调用 |
| 被动 install-only 负例 | Python 启动前退出 125 |
| 真实 Authenticode 负例 | `NotSigned`，正式候选 CLI 拒绝且不创建输出 |

第一次隔离宿主探针曾出现一次连接提前关闭；直接 launcher 跟踪确认 MCP 进程和 4,380 项 runtime 验证正常。随后带跟踪和不带跟踪各重跑一次均通过，因此只把第一次记录为瞬态，不把它改写成正向证据。

## 4. 自动化结果

| 门禁 | 结果 |
|---|---|
| 安装发布合同 | 6 项通过 |
| Python 正式 `pytest tests` | 949 项通过；2 个预期重复 ZIP 条目警告 |
| 前端 Vitest | 90 个文件、830 项通过 |
| Worker `unittest discover` | 598 项通过 |
| 文档合同 | 4 项通过 |
| 官方 plugin validator | 通过 |
| 原生插件 launcher | 13 项通过；`cargo fmt --check`、严格 clippy、release build 通过 |
| 托管 yt-dlp launcher | 2 项通过 |
| Tauri | 31 项通过，1 项按设计忽略 |
| UI smoke | 3 项通过 |
| `npm run check:full` | 通过 |
| V15/V10 release smoke | 通过 |

这些集合存在重叠，不能相加为独立测试总数。

安装合同覆盖：确定性候选、固定 MCP 接线、public-key-only 请求、独立签名域、原子 finalizer、跨域签名、资源篡改、未签名 launcher、原生拒绝，以及生产 API 不暴露测试 verifier/时钟注入。

## 5. 当前阻断与下一步

完整 M1 尚未完成，以下项目继续阻断正式可安装声明：

1. 仓库外建立生产发布 key/HSM 流程，并返回真实安装域 detached signature。
2. 使用可信 Windows Code Signing 证书和时间戳签署 launcher，冻结生产 Authenticode policy pin。
3. 在独立安装目录执行真实 finalizer、Codex 宿主注册与卸载/升级/回滚验收。
4. 完成桌面与 Headless Card Service 的等价矩阵及插件侧通用 Anki runtime verifier。
5. M2 再引入认证 Artifact 注册表、不透明引用和受控文件句柄；在此之前不得公开 raw `ExportResult` 写工具。

在上述门槛满足前，不向仓库被动插件写入正式 `.mcp.json`，不安装插件，不修改用户配置，也不声明插件已经交付。
