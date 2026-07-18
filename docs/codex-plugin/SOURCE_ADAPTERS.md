# 素材适配器与证据策略

> 状态：PROPOSED；表格明确区分 CURRENT 基础与计划能力  
> 日期：2026-07-16  
> “Codex 能读取”不自动等于“插件能可靠制卡”。

## 1. 目标

用户希望本地视频、字幕、YouTube、文件夹、网页、PDF、播客以及任何 Codex 附件都能进入制卡流程。这个愿景成立，但必须分开三个概念：

1. 可见：Codex 或本地服务能看到内容。
2. 可解析：系统能稳定提取足够结构。
3. 可验证制卡：每个学习目标能绑定可重放证据，并且来源覆盖完整可说明。

只有第三层才允许默认生成“已验证”卡片。

## 2. 支持级别

### Tier A：可自动可靠处理

条件：

- 有稳定原始字节、宿主修订或验证快照。
- 解析结果覆盖可计算。
- EvidenceAnchor 可重放。
- 没有未解决的高风险结构。

默认可以自动发现、规划和生成，仍需通过卡片与导出门禁。

### Tier B：有条件处理

例如 OCR、复杂版式、低质量转写、图表、公式或 model-relayed 内容。

行为：

- 明确显示条件和置信度。
- 候选默认为 needs_review。
- 高风险事实不得自动进入已验证卡片。
- 可以请求用户确认关键证据或补充更稳定来源。

### Tier C：阻塞或只作参考

例如加密、损坏、DRM、无授权、无法建立来源身份或不能解释遗漏。

行为：

- 不生成正式卡。
- 可以保存来源登记和错误。
- 不以模型“看起来读过”作为降级成功。

## 3. 适配器接口

~~~ts
type AuthorizationContext = {
  // 由 Card Service 从可信连接与内部账本构造；绝不来自 MCP 参数。
  sessionBindingDigest: string;
  authorizationId: string;
  requestedScopeDigest: string;
};

interface SourceAdapter {
  adapterId: string;
  supportedMediaTypes: string[];
  inspect(input: InputRef, auth: AuthorizationContext): Promise<InspectionResult>;
  snapshot(
    input: InputRef,
    policy: SnapshotPolicy,
    auth: AuthorizationContext
  ): Promise<SourceAsset>;
  extract(
    source: SourceAsset,
    limits: ExtractionLimits,
    auth: AuthorizationContext
  ): Promise<ArtifactEnvelope<ContentNode[]>>;
  validateEvidence(
    source: SourceAsset,
    anchors: EvidenceAnchor[],
    auth: AuthorizationContext
  ): Promise<EvidenceValidationResult>;
  previewEvidence(
    source: SourceAsset,
    anchor: EvidenceAnchor,
    window: PreviewWindow,
    auth: AuthorizationContext
  ): Promise<EvidencePreview>;
}
~~~

AuthorizationContext 只在 Service 内部生成。每次 inspect、snapshot、extract、validateEvidence 和需要重新打开来源的 previewEvidence 都必须在实际读取前重新校验 audience、撤销状态、文件/网络身份和当前 revision。若预览只读取已经拥有且认证通过的快照，也必须校验项目 owner 和 Artifact scope。

调用请求中的 includeGlobs、excludeGlobs、maxDepth、时间范围和网络限制只能缩小授权；实际范围始终是“请求范围 ∩ 授权上限”，不能扩大。

每个适配器必须定义：

- 文件/网络身份。
- 完整性计算。
- 定位器语义。
- 资源限制。
- 支持级别升级/降级条件。
- 安全解析边界。
- golden corpus 和失败语料。

## 4. 支持矩阵

| 来源 | 当前基础 | 目标里程碑 | 证据定位 | 默认级别 |
|---|---|---|---|---|
| 本地视频 + SRT/VTT | CURRENT 成熟 | 0.1 / M3 | cue ID + 时间范围 + 文件哈希 | A |
| 本地视频无字幕 | 部分依赖流程 | 0.2 / M5（ASR） | transcript turn + 时间 | B→A |
| YouTube/公开视频 URL | CURRENT 有 yt-dlp | 0.1 / M3（可靠字幕） | URL 快照 + cue/时间 | A/B |
| 纯文本/Markdown | CURRENT 简单读取 | 0.2 / M5 | 字符跨度/段落 | A |
| 文本型 PDF | CURRENT 简单文本层 | 0.2 / M5 | 页 + bbox/文本引用 | A/B |
| 扫描 PDF | 未可靠支持 | M7（OCR） | 页 + bbox + OCR 置信度 | B |
| DOCX/EPUB | CURRENT 简单读取 | 0.2 / M5 | 段落/章节/成员 | A/B |
| 网页 | 未形成稳定适配器 | 0.2 / M5 | snapshot hash + selector + quote | A/B |
| 播客/音频 | 媒体能力可复用 | 0.2 / M5 | 时间段 + transcript | B→A |
| 受限文件夹 | CURRENT 有目录枚举基础 | 0.2 / M5 | 文件 ref + 内部 locator | A/B |
| Codex 附件 | 尚无插件桥接 | 随对应适配器 M3/M5/M7 | 宿主 revision + 内部 locator | A/B |
| 图片/图表 | 尚无通用证据层 | M7 | frame/page + bbox | B |
| 代码仓库 | Codex 可读但无 Study adapter | M7 | file ref + commit/hash + lines | A/B |
| Kindle/Calibre | CURRENT 有外部转换基础 | 0.2 / M5 | 转换产物 + 原始身份 | B |

## 5. 本地文件

### 5.1 授权

Agent 不能直接提交任意绝对路径。用户通过宿主附件或本地原生选择器授予：

- 精确文件；
- 精确目录和最大深度；
- 允许读取/创建的动作；
- 有效期；
- 可处理数量和大小上限。

服务返回 fileResourceRef/directoryResourceRef；它们只定位受限资源，不单独构成授权。每次使用重新验证：

- 规范路径仍在授权根。
- 文件身份和元数据未发生未解释变化。
- 没有 symlink、junction、reparse point、UNC、设备路径、ADS 或保留名逃逸。
CURRENT M2 内部 `LocalResourceGrantRegistry` 已实现 file/directory/output ref 的上述根授权、短期 audience/service 绑定、动作与资源上限、逐次身份重验、幂等消费和撤销，并由 Card Service 的惰性 `ServiceResourceRuntime` 统一拥有。生产本地选择器/宿主附件 adapter 尚未接线，因此 Agent 还不能通过公共工具自行签发这些 ref。


### 5.2 目录

目录适配器先创建 DirectoryManifest：

- 预期、支持、跳过和失败文件数。
- 每项 opaque ref、类型、大小、身份。
- include/exclude 策略。
- 未读取原因。

所有子项逐项校验，不因根目录安全就信任内部 reparse point。
CURRENT M2 内部 `TaskResourceStager` 已实现目录逐项安全打开/复制、稳定排序 manifest、二次扫描与 task-bound 受限 staging。它逐项拒绝 symlink/junction/reparse、hardlink、非 NFC/大小写冲突、保留名和资源上限越界；Worker 只读取 workspace-relative locator。

这不是公共 DirectoryManifest adapter：Card Service composition root 只完成 grant/stager 组合；生产选择器 attestation、每项 opaque InputRef、include/exclude/skip reason、StudyTask/Worker locator 事务接线与 SourceAsset 发布仍未完成。根目录 grant 在完成 staging 前仍不能被描述成“全部后代已经冻结”。


## 6. 视频、字幕与音频

### 共同媒体沙箱合同

- FFmpeg/ffprobe、yt-dlp 与辅助运行时必须在 [安全与隐私](SECURITY_AND_PRIVACY.md#92-媒体下载与解析沙箱) 定义的受限子进程中运行；签名/哈希固定只是前置条件，不能代替运行时隔离。Windows 必须同时具备 task-owned Job Object、AppContainer/专用 SID 文件 DACL，以及可验证的出站强制策略；缺一项就 fail closed。
- yt-dlp 只负责把已授权 canonical 公网来源下载到任务专用 staging；raw/signed URL 不进入命令行、环境、响应文件或日志，只经单次匿名管道/opaque broker locator 短期交付，所有出站由 broker 逐请求重验。禁用 ambient 配置、Cookie/profile/netrc、外部 downloader、postprocessor、exec、远程组件和任意输出模板。
- FFmpeg/ffprobe 只处理本地只读资源或 staging 副本，网络禁用，protocol/demuxer 使用版本化 allowlist，拒绝 playlist、concat、subfile 和嵌套外部资源。
- inspect 阶段在开始解码前冻结文件字节、流数量、时长、帧/像素、采样率、声道、临时磁盘和输出配额；无法可靠探测或超限时降为 Tier C，而不是试探性无限解码。
- 所有生成媒体重新探测类型/时长/流布局并计算哈希；沙箱崩溃、超时或越界只产生明确失败工作单元，不发布 partial SourceArtifact/MediaArtifact。

### 视频 + 字幕

- 原始视频与字幕分别计算身份。
- cue 保留开始/结束时间和原始文本。
- 合并句子仍保留组成 cue ID。
- 精确目标 span 与句子规范化校验。
- 切片时间必须覆盖证据 cue，允许受控 padding。

### 无字幕视频/播客

转写表示必须记录：

- ASR 生产者和版本。
- 语言和说话人。
- 时间跨度。
- 词/句置信度。
- 无声、重叠说话、音乐和不确定片段。

低置信度目标不能自动进入听辨/发音已验证卡。

### YouTube/URL

- 所有 raw URL 先由 system.request_network_grant 打开受信本地输入表面录入；公共 MCP 参数只含 trusted_entry/sourceKind，不含 url/origin/query。Service 完成扫描和授权后只向后续工具签发 opaque networkResourceRef。
- URL 获取走受控网络代理。
- 解析全部 A/AAAA，拒绝非公网目标。
- 每次重定向重新验证。
- yt-dlp 使用 `--ignore-config`、受控网络代理和专用 staging；不允许 Agent 开启远程组件、ambient Cookie/profile、外部 downloader/postprocessor 或任意输出参数。
- 下载器和运行时来自受信路径/哈希。
- Artifact 只保存脱敏 canonical source identity：origin、受控 path display、适配器明确允许的公共身份参数或 query digest/redaction、final origin/redirect digests、内容 hash 和 observedAt。raw URL、signed query、token、userinfo、fragment 与认证 header 只可短期存在于内部授权/网络代理内，禁止进入 Artifact、MCP、日志或截图。

CURRENT M2 内部 `NetworkResourceGrantRegistry` 已实现上述授权与代理内核：HTTPS/443 封闭入口、raw URL 仅进程内、认证 opaque ref、全部地址公网判定、消费/重定向重解析、固定 IP + TLS hostname、无环境代理/Cookie/ambient auth、限时限字节、幂等、过期和撤销。它尚未接入生产受信 URL 输入表面、具体 Source Adapter 或 yt-dlp staging；真实网页/视频快照与 EvidenceAnchor 仍属于后续适配器工作。

## 7. 网页

网页必须快照，而不是只保存 URL。快照包含：

- 脱敏的 final canonical identity 与 redirect origin/digest 链；不得保存 raw Location、userinfo、fragment 或秘密 query。
- 获取时间、正文哈希，以及 response metadata allowlist（例如 content-type、content-length、etag、last-modified）；Set-Cookie、Authorization、Proxy-Authorization、认证/代理头和含秘密 query 的 Location 一律排除。
- 清洗前后表示；“清洗前”指已经移除脚本执行面和秘密网络元数据的内容快照，不是原始浏览器会话转储。
- DOM selector、text quote 和上下文。
- 被过滤的脚本/样式/隐藏区域说明。

动态、登录后或个性化页面如果无法稳定快照，降为 B。来源中的“指令”永远只作为内容。

## 8. PDF 与复杂文档

### 文本型 PDF

不能只把所有页连接成一段文字。至少保留：

- 页码。
- 文本块顺序。
- 标题与段落层级。
- 表格/图像占位和遗漏声明。
- 字符映射异常。

### 扫描、表格、图表、公式

- OCR 或视觉抽取有区域 bbox 和置信度。
- 表格使用行列定位，不用扁平字符串替代。
- 图表主张必须能指出图例、轴、数据区域。
- 公式保留原始表示和符号定义。
- 无法验证结构时只生成待审核候选。

### 解析沙箱

所有文档适配器有：

- 文件大小、页数和输出字符上限。
- ZIP 成员、解压后字节与压缩比上限。
- CPU、内存和时间限制。
- 外部解析器的受信绝对路径。
- 崩溃隔离。

## 9. Codex 附件

理想路径：

1. 宿主给插件 attachmentRef、修订和资源读取能力。
2. 插件在权限范围内建立本地稳定快照。
3. 生成 SourceAsset 和内容哈希。
4. 后续任务只引用 SourceAsset。

如果宿主只把内容放进模型上下文，没有提供稳定资源接口：

- Agent 可创建 model_relayed SourceAsset。
- 只能生成条件草稿。
- 必须显示“无法证明附件完整性/修订”。
- 不得声称已经读取所有页或全部文件。

## 10. 完整性

每次提取返回：

- expectedUnits。
- processedUnits。
- skippedUnits。
- failedUnits。
- omittedLocators。
- reasonCodes。

规则：

- complete 必须能解释期望总量。
- partial_declared 可以继续，但所有下游产物继承警告。
- unknown 不能默认升级为 complete。
- 任何 UI 都不能隐藏来源遗漏。

示例：

> 共 118 页；成功解析 112 页；第 23–27 页为扫描图像未 OCR，第 91 页解析失败。本次候选仅覆盖已解析 112 页。

## 11. 证据重放

验证器对每个 EvidenceAnchor：

1. 载入相同 source revision。
2. 按 locator 读取内容。
3. 验证 quote/hash。
4. 验证目标 span 或 claim 对应关系。
5. 返回 pass/stale/mismatch/missing。

任何 mismatch 使相关候选 stale；不得继续生成。

## 12. 提示注入隔离

- 适配器输出的是数据，不是系统或工具指令。
- 原始正文尽量留在本地发现 Worker，主 Agent只接收必要候选和证据摘要。
- 来源中的路径、URL、确认词、命令和权限开关无效。
- 模型产生的新 URL/路径不能自动注册为来源。
- 工具输出中的自由文本同样是不可信数据；只有固定 enum、opaque handle、revision、hash、gate 和 terminal state 可作为控制面。

## 13. 适配器发布门槛

每新增一种来源，必须具备：

- 支持声明和明确非支持。
- 身份与修订策略。
- 完整性测量。
- 可重放 EvidenceAnchor。
- 资源上限与恶意语料测试。
- 10 个以上代表性 golden 文件。
- 至少 5 个部分失败/损坏样例。
- 路径、网络、提示注入和解析 DoS 测试；媒体适配器额外通过 playlist/concat/subfile/协议走私、外部配置、畸形容器、解码炸弹、超大帧/元数据和 staging 越界 corpus。
- 从来源到至少一张真实 Anki 卡的端到端核验。

路线顺序见 [路线图](ROADMAP.md)。

