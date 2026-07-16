# 宿主界面与交互设计

> 状态：PROPOSED  
> 日期：2026-07-16  
> 固定右侧栏是未来适配偏好，不是当前已确认的 Codex 公共接口；M3 核心为 tools-only。

## 1. 交互第一性原理

用户不应该管理“环境检查、Worker、缓存、批次、媒体账本、APKG、AnkiConnect”这些内部流水线。用户只需要：

1. 交付素材。
2. 表达想达到的学习行为。
3. 选择或修正值得学的目标。
4. 在高影响步骤做明确决定。
5. 获得可以复习、能够解释失败的结果。

正常状态尽量隐形；阻塞、风险、成本和持久写入才打断。

## 2. 对话与控制台的分工

### 对话

适合：

- 自然语言表达学习目标。
- 补齐真正影响路线的信息。
- 解释为什么推荐/排除。
- 请求改变粒度、路线和预算。
- 总结任务结果和恢复建议。

不适合：

- 作为长任务权威状态。
- 展示 100 个候选。
- 保存筛选、选择和批量编辑真相。
- 仅凭文字宣称“已导入/已核验”。

### Work Rail

适合：

- 权威项目、产物、能力和任务状态。
- 候选筛选、证据预览和选择。
- CardPlan 审核。
- 批量进度、取消和恢复。
- Anki ImportPlan 摘要、受信本地确认入口与验证证书；Work Rail 自身不签发批准。

原则：

> conversation = intent；Work Rail = task truth；Card Service = execution truth。

## 3. 官方宿主边界

截至 2026-07-16，Apps SDK 为 ChatGPT Apps 定义的展示模式：

- Inline。
- Fullscreen。
- PiP。

这份 Apps SDK 资料不能证明所有 Codex Desktop、CLI、IDE 或工作区都支持这些界面；同时也没有核验到第三方插件可稳定固定在 Codex 任意右侧栏的公共接口。

设计决定：

- M3 核心采用 tools-only，不使用 DOM 注入、窗口黑客或 Computer Use 控制 Codex。
- M4 先在目标 Codex Desktop/工作区做 App resource 兼容实验；通过后，同一个 WorkRailViewModel 适配宿主实际支持的形态。
- 组件布局允许在窄右栏宽度运行。
- FutureSidebarAdapter 只在官方稳定接口出现后增加。

参考：[UI display modes](https://developers.openai.com/apps-sdk/concepts/ui-guidelines#display-modes)。

## 4. 信息架构

~~~text
项目标题 / Learning Contract 摘要
├── 素材
│   ├── 来源状态与覆盖
│   └── 权限/解析问题
├── 学习目标
│   ├── 推荐
│   ├── 全部
│   ├── 证据/关系
│   └── 组合与复习债务
├── 卡片计划
│   ├── 正面/背面
│   ├── 评分边界
│   └── 媒体策略
├── 生成与交付
│   ├── 长任务
│   ├── 可导出/需复核
│   ├── APKG
│   └── Anki 核验
└── 诊断
    ├── 能力
    ├── 审计
    └── 恢复
~~~

日常路径不展示“诊断”；出现阻塞时才展开相关一项。

## 5. WorkRailViewModel

~~~ts
type TaskView = {
  taskId: string;
  state: Exclude<OperationState, "idle">;
  phaseLabel: string;
  overallPercent: number | null;
  completedItems?: number;
  totalItems?: number;
  elapsedMs: number;
  lastProgressAt: string;
  cancellable: boolean;
  recoverable: boolean;
};

type WorkRailViewModel = {
  project: {
    projectId: string;
    title: string;
    revision: number;
    learningContractSummary: string;
  };
  step: ProductStep;
  artifactStage: ArtifactStage;
  operationState: OperationState;
  heading: string;
  description: string;
  primaryAction: {
    id: WorkflowActionId;
    label: string;
    state: "available" | "blocked" | "running" | "completed";
    blockerCount: number;
  };
  task: TaskView | null;
  issues: IssueView[];
  selection?: SelectionView;
  delivery?: DeliveryView;
  notice?: NoticeView;
};
~~~

ProductStep、ArtifactStage、OperationState 与 WorkflowActionId 使用 [Study IR](STUDY_IR_REFERENCE.md) 的唯一固定枚举。对话、tools-only 分页结果，以及宿主实测支持后的 Inline、PiP、Fullscreen 必须由同一服务快照派生，不能分别计算或从人类文本推断。

严格派生规则：operationState 直接复制 WorkflowSnapshot.operationState；idle 时 currentTaskId 缺省且 task 必须为 null；queued/running/cancelling 时 currentTaskId/task 必须存在且 state 完全一致；succeeded/failed/cancelled/interrupted 在后续写动作被接受前也必须保留同一个 currentTaskId 和对应 TaskView。只读查看、切换页面或渲染结果不能确认终态；后续写动作由 Service 原子记录 lastAcknowledgedTaskId/时间，并替换为新任务，或在同步写动作后转 idle。ArtifactStage 只表示最远可靠产物，绝不能从 task.state 猜测。

## 6. 各宿主形态

### 6.1 Inline

最大信息量：

- 一行项目/阶段。
- 一个核心结果。
- 最多三个阻塞/警告。
- 一个主动作、最多一个次级动作。

示例：

> 找到 28 个候选，推荐 12 个。2 个来源页因扫描图像未读取。  
> 主动作：查看并选择  
> 次级：查看遗漏

Inline 不承载长列表和高级设置。

### 6.2 PiP

用于持续任务：

- 当前阶段。
- 诚实进度/不定进度。
- 已完成条目与批次。
- 已用时间、最后活动。
- 等待/警告。
- 取消。
- 打开详情。

任务完成后 PiP 变成简短结果，不自动抢焦点。

### 6.3 Fullscreen

承担：

- 素材覆盖。
- 候选列表与筛选。
- 证据预览。
- 批量选择和组合。
- CardPlan 对比。
- 需复核项。
- 审计/诊断。

只有一个主纵向滚动容器；固定操作栏不与内容形成竞争滚动。

### 6.4 Future sidebar

布局目标：

- 320–460px 宽度仍可显示任务和候选摘要。
- 列表使用单列卡片。
- 证据详情打开 Fullscreen/对话，不在窄栏硬塞。
- 主动作始终可见。

固定右侧栏不属于任何版本的既定验收；M4 只验收真实宿主已经证明可用的 App UI 形态。

## 7. 主流程

以下四个内部阶段映射到三个 ProductStep：素材 = source；学习目标与卡片计划 = select；生成与交付 = deliver。它们用于主区内容切换，不新增第四个顶层产品步骤。

### 阶段 1：素材

显示：

- 已注册来源。
- 类型、修订、支持级别。
- 完整/部分/阻塞。
- Learning Contract 一行摘要。

主动作：

- 未有素材：添加素材。
- 有阻塞：解决 N 个问题。
- 可分析：发现学习目标。
- 已有有效缓存：查看 N 个候选。

### 阶段 2：学习目标

默认显示推荐且可制卡项。每项：

- 目标表达/知识主张。
- 原句或短上下文。
- 未来行为/路线。
- 推荐理由。
- 证据和风险。

选择状态用一个视觉通道；验证通过不与选中状态竞争。

固定操作栏：

> 已选择 9 个 · 预计首次复习 5 分钟  
> 生成 9 个卡片计划

### 阶段 3：卡片计划

小批量直接预览；50 张以上显示批量检查：

- 数量/批次。
- 路线分布。
- 模型/TTS/媒体调用。
- 预计成本和复习债务。
- 阻塞/需复核。

一张卡的预览必须显示：

- 正面任务。
- 核心答案。
- 评分边界。
- 证据。
- 媒体。
- 用户锁定。

### 阶段 4：生成与交付

生成中显示真实阶段、进度和取消。完成后：

> 生成 10 张草稿 · 9 张可导出 · 1 张需要复核

主动作直接是“导出可用的 9 张”，不再询问是否继续导出。

APKG 后：

> APKG 已生成 · 尚未导入 Anki

主动作：“导入 Anki 并核验”。

该动作先调用 anki.prepare_import；受信本地窗口确认 ImportPlan 后，再以 importIntentId 调用 anki.import_and_verify。任何 Work Rail 自报确认都无效。交付区必须区分：

- “已导入，尚未完成数据核验”。
- “Anki 数据核验通过；实际渲染、播放与复习尚未评估”（data_verified / anki_data_verified）。
- “Anki 数据完整，但实际渲染、播放或重启核验失败”（runtime_failed / anki_data_verified；显示失败检查与仅重试核验）。
- “已在 Anki 中完成运行时核验”（fully_verified / anki_verified，必须有 trusted runtime evidence）。

runtime verifier 不可用时，主动作可以是“稍后进行实际复习核验”，不能把 AnkiConnect 数据查询升级成完整成功。runtime_failed 时主动作是“仅重试实际复习核验”，不得重新导入或重跑模型/TTS。Anki 写边界不明时显示“导入状态待确认”，只提供查看证据/解决冲突，不自动重写。

## 8. 状态和反馈

### 500ms 规则

- 点击后 100ms 内控件进入忙碌态。
- 500ms 内出现任务反馈。
- 3 秒后显示阶段、耗时和取消。
- 15 秒无进度：仍在等待当前服务。
- 30 秒无进度：警告并显示最后活动时间。
- 只有服务超时/退出才能显示失败。

### 进度

- 总体百分比单调。
- 中间批次不显示 100%。
- 不可估算时用不定进度。
- 阶段百分比和总体百分比分开。

### 失败

错误区按顺序说明：

1. 哪一步失败。
2. 已保留什么。
3. 是否产生了费用或 Anki 写入。
4. 唯一推荐动作。
5. 展开后才显示诊断。

失败后焦点移动到错误标题。

## 9. 确认

确认不是通用摩擦，而是高影响边界。

需要确认：

- 新本地目录。
- 新远程服务/数据上传。
- 超预算/超数量。
- 运行期安装或升级组件不在 V1；未来若增加必须使用独立受信流程。
- 覆盖/删除。
- 私网。
- Anki 导入/更新。

高影响确认必须位于 Card Service 提供的受信本地表面，并通过独立认证通道写入内部 approval ledger；对话和普通 MCP App UI 只能发起请求、展示摘要，不能签发或回传执行 bearer。确认面板：

- 具体资源，不用“系统需要权限”。
- 影响和数量。
- 可撤销性。
- 一次性/有效期。
- 主按钮使用动作文案，如“导入 9 张到 English::Podcast”。

Escape 关闭并回到触发按钮；焦点锁定；背景不可操作。

## 10. 候选与证据

- 推荐使用徽标，不用整行绿色。
- 选中只使用主题蓝。
- 风险有图标、文字和颜色。
- 筛选不删除隐藏选择。
- 证据预览显示来源名、定位和上下文。
- 复杂 PDF 显示页码/区域和遗漏。
- 同义、冲突、先修通过关系入口查看。
- 1、49、50、100 个选择都有准确数量和批次说明。

## 11. 学习者编辑

用户说“太简单”“改成产出”“这个证据不对”时：

- 对话将自然语言转换为语义编辑草稿。
- Work Rail 显示具体变化。
- 用户锁定的字段有可见标记。
- 下游失效范围明确，例如“更换证据后需要重新验证 3 个 CardPlan，不会重跑其他 17 张”。

## 12. 能力与设置

简单模式只显示：

~~~text
模型    Hermes Grok 4.5    代理未启动    启动
语音    当前 TTS           需要验证      验证
环境    本地生成运行时      已检查
Anki    AnkiConnect        导入时检查
~~~

设置窗口由 Card Service 本地启动，秘密字段不经过对话、MCP 或 App UI。设置采用 draft：

- 修改不立即污染当前项目。
- 保存并验证后 committed。
- 应用但稍后验证会变 stale。
- 简单/高级切换不清空字段。
- 密钥只显示存在/不存在。

## 13. 视觉系统

沿用温和学习工作台：

- Canvas：#F6F4EF。
- Surface：#FFFFFF。
- Text：#1E252B。
- Secondary：#5F6973。
- Primary：#245B85。
- Success：#2F7D5A。
- Warning：#996117。
- Error：#B23A35。

普通文字对比度至少 4.5:1。状态不只依赖颜色。主控件最小 44px。正文 16px、说明 14px、元数据最低 12px。

动效只用于状态、面板和步骤变化，120–220ms；支持 prefers-reduced-motion。

## 14. 无障碍

- 每个表面只有一个主要 aria-live。
- progressbar 有正确 value；不定进度不伪造。
- 所有主流程支持 Tab、Enter、Space。
- Escape 关闭并恢复焦点。
- 标题切换后聚焦主标题。
- 列表选择有可读状态。
- 长错误、路径别名、中英文和 200% 缩放不截断关键动作。
- PiP 不用持续闪烁吸引注意。

## 15. 文案规范

用用户事实：

- “APKG 已生成，尚未导入 Anki。”
- “Anki 数据核验通过；实际渲染、播放与复习尚未评估。”
- “已保留 24 张，剩余 26 张可以继续。”
- “第 23–27 页没有文本层，本次未用于选卡。”

不用内部术语：

- “运行 export worker command”。
- “缓存 miss”。
- “repair_env”。
- “manifest reconciliation failed”。

诊断区可以显示内部代码，但仍需人类解释。

## 16. UI 验收

- tools-only 对话与所有经兼容验证的 App UI 形态状态一致。
- 每个子状态一个主动作。
- 正常能力不占主界面。
- 阻塞在执行前可见。
- 任务超过 500ms 有反馈。
- 取消不永久卡住。
- 1180×780 到 4K、125–200% 缩放可用。
- 对经宿主验证的界面：Inline 不溢出；PiP 可监控；Fullscreen 无嵌套主滚动。
- 没有任何界面把 APKG 生成、导入成功或 AnkiConnect 数据查询写成完整 Anki 运行时核验。
- 固定右侧栏缺失不影响完整任务。

