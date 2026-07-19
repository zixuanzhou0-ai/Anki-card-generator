# CURRENT：M1 真实服务与端口恢复验证报告

> 验证日期：2026-07-20
> 范围：开发态可信 stdio Card Service、Hermes Grok 4.5 预检、Windows AnkiConnect 端口恢复
> 结论：本地授权与恢复逻辑通过；xAI 公网上游仍被真实环境阻断，因此完整真实模型→APKG→Anki 链未宣称通过。

## 1. 本轮修复

- 将固定 Hermes endpoint 从错误的 `127.0.0.1:8317/v1` 对齐到 Hermes 官方代理端口 `127.0.0.1:8645/v1`。
- 新增 Service-owned Hermes preflight：校验固定 `/health`、xAI/Grok upstream 和 OAuth 状态；代理未运行时只使用固定 `provider=xai`、`host=127.0.0.1`、`port=8645` 启动。
- `system.authorize_candidate_discovery` 只有在真实用户批准且本地代理通过 preflight 后才返回 `capabilityAvailable=true`。
- 初次 discovery、异步 discovery 与恢复 discovery 都重新执行 preflight，避免历史授权或旧健康状态绕过当前能力检查。
- Provider 连接、HTTP、凭据或授权过期故障统一映射为可恢复的 `MODEL_STALE`，不再误报 `INTERNAL_UNCLASSIFIED`。
- AnkiConnect endpoint 改为 launcher 固定的显式 IPv4 loopback 地址；默认 8765，允许受控改为其他本机端口，但 MCP 调用方不能提交或覆盖。
- APKG 输出目录与 Anki profile 保持解耦；跨磁盘不再被解释为必须把 APKG 放进 Anki 文件夹。

## 2. 自动化证据

定向集合：

```text
tests/test_candidate_discovery_broker.py
tests/test_hermes_proxy.py
tests/test_mcp_system_tools.py
tests/test_anki_target_probe.py
tests/test_anki_import_execution_materialization.py
```

结果：`53 passed in 1.57s`。

覆盖包括：

- 8645 固定 endpoint、健康响应闭包、OAuth 未就绪、端口冲突、启动失败、启动超时和进程清理。
- 授权批准后才启动代理；本地能力不可用时 `capabilityAvailable=false`。
- discovery 首次运行和恢复运行都执行 Hermes preflight。
- provider infrastructure failure 归类为 `MODEL_STALE`。
- 仅允许 `http://127.0.0.1:<1..65535>`；拒绝 hostname、非 loopback、userinfo、query、fragment、错误 path 和非法端口。
- 配置的 AnkiConnect 端口同时进入只读目标探测与真实导入 Worker 请求。

## 3. Computer Use 真实桌面证据

通过 Computer Use 操作真实 Windows 原生窗口完成：

1. 启动可信 stdio Card Service 端到端脚本。
2. 在真实文件选择器中选中 `source.txt` 并返回授权。
3. 创建项目、注册来源并完成来源检查。
4. 打开 digest-pinned Hermes 授权窗口；窗口明确显示固定方法、模型、8645 endpoint、时限与预算。
5. 真实点击“授权并继续”。
6. Card Service 自动启动/复用 Hermes 8645 代理并得到：`status=ok`、`upstream=xAI Grok OAuth`、`authenticated=true`。

这关闭了此前“只打开对话框、没有选中返回”的 GUI 证据缺口。

## 4. 真实公网负例与失败边界

候选发现没有成功。证据不是插件 schema 不兼容：

- 对 8645 发送最小 OpenAI-compatible JSON 请求，约 20 秒后得到 HTTP 502，稳定错误类型为 `upstream_unreachable`，原因是 Hermes 到 `https://api.x.ai/v1/chat/completions` 连接超时。
- 使用 Hermes 官方 one-shot 命令绕过插件进行相同最小 Grok 4.5 调用，184 秒仍未得到结果并由测试超时终止。
- xAI OAuth 状态仍为 ready，本地 `/health` 仍为 authenticated。
- Windows WinHTTP 已配置本机代理；xAI 官方域名经该代理可快速到达，但本次 Hermes proxy 的上游连接仍超时。因此“系统代理已配置”不能推导“Hermes 公网推理已就绪”。

系统按设计：

- discovery task 终止为可重试 `MODEL_STALE`；
- 没有 CandidateArtifact、CardArtifact、APKG 或 Anki 写入；
- 已完成的来源授权、注册和检查保留；
- 后续可以在网络/Hermes 路由恢复后通过 recovery 工具重新执行候选发现，而不伪造成功。

## 5. AnkiConnect 端口证据

本机 Windows 排除 TCP 端口范围覆盖默认 8765，导致 AnkiConnect 不能绑定默认端口。隔离 Anki profile 与 Card Service 改为 `127.0.0.1:8785` 后：

- AnkiConnect `version` 返回 6；
- Service 只读 target probe 能使用 8785；
- 导入 Worker materialization 保持同一 8785 endpoint；
- endpoint 仍是禁用环境代理的字面 IPv4 loopback；
- 不要求 APKG 与 `collection.media` 位于同一磁盘。

本轮真实 Hermes 链在 discovery 阶段按设计停止，因此没有把这次运行伪装成新的完整 Anki 导入正例。完整数据级导入证据继续以既有隔离 Anki 报告为准；本报告只关闭端口配置与 preflight 缺口。

## 6. 未关闭项

- 恢复 xAI/Hermes 的真实公网推理路由后，必须从真实 discovery 重新运行到 APKG 与隔离 Anki；当前不能宣称真实 Grok 端到端通过。
- 正式插件安装仍受发布者签名、Authenticode/HSM 与独立安装验收阻断。
- 固定 Codex 右侧栏仍无已验证的公共宿主接口。
- 通用 runtime verifier、视频/YouTube/PDF/Office/网页/播客适配、TTS 与媒体生成仍未完成。

本报告的负例是发布门禁证据：它证明系统在真实外部服务不可达时停止并保留可恢复状态，不证明插件已经正式交付。
