# Release Checklist

当前发布目标：`v0.9.2-beta`（package version `0.9.2`）。

目标：确认用户拿到 Windows 桌面端后，不需要源码和开发服务，也能完成素材导入、智能生成、审核、导出和 Anki 验证。

## 发布前

- [ ] `git status` 只包含本次发布相关文件。
- [ ] 没有真实 API Key、OAuth token、私人视频、私人字幕、`.apkg` 或测试缓存。
- [ ] `.gitignore` 已排除 `.playwright-mcp/`、`e2e_regression_*/`、`tmp_*.json`、媒体缓存、构建缓存和虚拟环境。
- [ ] 版本号已同步：`package.json`、`package-lock.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`。
- [ ] `workers/` 已作为 Tauri resources 打包。
- [ ] README、`docs/USER_GUIDE.md`、`docs/TROUBLESHOOTING.md`、`docs/ARCHITECTURE.md`、`docs/BETA_LIMITATIONS.md` 与当前 UI 一致。
- [ ] `docs/screenshots/` 已用当前 UI 重新截图，README 和用户教程引用的截图都能打开。
- [ ] 文档说明当前主流程：素材配置、AI 精筛学习点、用户选择学习点、生成完整卡片、审核导出、学习点诊断、发音透明标记、APKG 导出。
- [ ] 文档说明当前设置页：模型 API 按服务商独立保存、Vertex 使用 gcloud OAuth、TTS 独立保存、本地环境可检测和一键修复。
- [ ] 文档说明 `词霸天下实验 V1` 已有独立导出 Anki 卡面，但仍复用现有字段 schema，仍是实验模板。
- [ ] 开发启动说明可用：`npm run tauri:dev` 能启动当前 workspace，不依赖旧 release/portable 包。

## 自动测试

```powershell
npm run lint
npm run test:unit
npm run build
python -m pytest tests\test_worker_quality.py -q
cargo check --manifest-path src-tauri/Cargo.toml
```

发布包前再跑：

```powershell
npm run test:ui
npm run tauri:build
```

如果 CI 因外部服务、模型接口、YouTube 限流或网络故障失败，release note 需要写明原因和人工复核结果。

## 桌面端 Smoke Test

建议至少跑一次真实桌面端流程：

1. 启动最新 Windows 桌面端。
2. 打开设置，检查模型 API、语音 TTS、本地环境三个页签。
3. 在本地环境页点击检测；缺失项需要能显示“可修复 / 需手动处理”的明确状态。
4. 用短视频或本地视频 + SRT 生成项目。
5. 确认 `抽取学习点` 会调用模型 API，不会把本地规则秒出的候选当正式结果。
6. 确认学习点页面显示推荐、候选和诊断；推荐默认勾选，候选可手动勾选。
7. 选择学习点后生成完整卡片。
8. 确认 Review 页面显示：
   - 生成卡片数
   - 已选卡片数
   - 全部片段
   - 学习点诊断
9. 取消选择几张卡，再重新全选。
10. 打开学习点诊断，确认候选、重复、硬阻断原因可见。
11. 检查至少 5 张卡：原句、答案、发音字段、TTS、原声、视频预览。
12. 导出 APKG。
13. 使用 APKG verify 检查字段、媒体、TTS ledger、PronunciationMeta。
14. 导入 Anki，抽查音频按钮和卡面顺序。

## 干净机器验证

建议用 Windows Sandbox / 虚拟机 / 另一台电脑。

1. 只复制 release 安装包或 zip，不复制源码。
2. 安装或解压。
3. 启动应用。
4. 打开本地环境页并点击“一键修复全部可修复项”。
5. 确认 Python 3.12、Python 依赖、FFmpeg、Anki、AnkiConnect 的状态说明可读。
6. 配置一个模型服务商和一个 TTS 服务商并保存。
7. 用短素材生成卡片。
8. 导出 APKG 并导入 Anki。
9. 删除测试缓存和 APKG，确认 release 目录不包含 API Key、OAuth token 或私人素材。

## GitHub Release 内容

- Windows installer / portable package
- Source archive
- README
- `docs/USER_GUIDE.md`
- `docs/TROUBLESHOOTING.md`
- `docs/BETA_LIMITATIONS.md`
- Release notes

Release note 应明确写出：

- 当前是统一智能筛选，不再暴露“精选 / 不漏 / 全量”策略。
- 当前是先 AI 精筛学习点，再由用户选择学习点生成完整卡。
- 生成出的完整卡默认全选，用户导出前自行勾选。
- 学习点诊断只用于解释为什么有些学习点没有生成完整卡。
- `词霸天下实验 V1` 是实验风格模板，已使用独立导出 Anki 卡面，但仍复用现有字段 schema。
- 多语言发音默认是字幕推测，不是音频实听。
- 第三方模型、TTS 和 YouTube 可能产生费用、限流或版权风险。
