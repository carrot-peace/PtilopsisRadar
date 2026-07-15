# DR 运行与验收指南

DR（Daily Report）是一条独立的日报产品链路。它共享抓取数据，但不复用 CR 的评分、决策或发送语义。

## 生产链路

```text
daily 数据
→ 关键词组仅作为候选容器
→ evidence_id 级证据
→ 模型分批生成事件文字
→ 事件证据重新分桶并生成事实边界
→ 同一事件 schema 与语义
   ├─ daily 运行：Daily HTML + DR Telegram 摘要
   └─ current/incremental 运行：Dashboard + state.json
```

面向读者的基本单位必须是事件，不是关键词组。各运行模式不会复用同一个内存中的 `AIAnalysisResult`，但必须共用同一事件 schema 和规则。所有渠道直接使用事件已有的标题、摘要、`verification_status`、`factual_boundary` 和证据子集，不得重新分桶；渲染器只能按三端共用的规则，将 C+D 等证据组合细化为面向读者的展示标签。

## Gemini 容量配置

`config/config.yaml` 的 `ai_analysis` 段提供 DR 专用预算：

```yaml
ai_analysis:
  max_output_tokens: 16000
  max_events: 30
  batch_max_evidence: 12
```

Gemini 3.x 请求会自动使用 `reasoning_effort=low` 并省略显式 temperature；其他 Provider 不会被自动注入 Gemini 专用推理参数。

`max_events` 是历史配置名，当前表示单期最多送入 AI 的 evidence 候选数，不是读者最终看到的事件硬上限。程序为保证证据不丢失，确定性降级可以保留更多事件。

环境变量覆盖项：

- `AI_ANALYSIS_MAX_OUTPUT_TOKENS`
- `AI_ANALYSIS_MAX_EVENTS`
- `AI_ANALYSIS_BATCH_MAX_EVIDENCE`

这些参数只作用于信息环境日报，不改变翻译或其他 AI 任务。达到输出上限时，程序必须依据 `finish_reason` 缩小批次重试；不可拆分的截断必须使本轮 AI 分析失败，不能由 `json_repair` 修成部分成功。

每次调用应记录模型、结束原因、输入/输出/thought token 用量。AI prose 需要 Provider 支持 JSON Schema Structured Output；不支持或返回不合规响应时，本轮按失败处理并输出确定性事件。有效响应必须符合 `environment-events-v1` schema；Prompt、解析器和 schema 必须作为同一版本部署。

## DR 发送门控

DR 默认不发送。只有同时满足以下条件才进入 Telegram live 发送：

```text
PTILOPSIS_DR_DISPATCH_MODE=live
PTILOPSIS_DR_TELEGRAM_SEND=1
PTILOPSIS_DR_TELEGRAM_BOT_TOKEN 已配置
PTILOPSIS_DR_TELEGRAM_CHAT_ID 已配置
```

`artifact` 只写 dispatch plan / receipt，不产生网络发送；`off` 完全跳过 DR dispatch。调度表中的 legacy `push` 开关不替代上述 DR 独立门控。

可选 Telegram 参数：`PTILOPSIS_DR_TELEGRAM_ATTACH_HTML`、`PTILOPSIS_DR_TELEGRAM_API_BASE_URL`、`PTILOPSIS_DR_TELEGRAM_TIMEOUT_SECONDS`、`PTILOPSIS_DR_TELEGRAM_PARSE_MODE`。未设置或传入空值时，附件开关、API 地址和超时时间分别回退为开启、官方 API 地址和 10 秒。通过 Docker 或 GitHub Actions 部署且未配置 `PARSE_MODE` 时默认为 HTML；若在直接调用中显式传入空值，则视为不启用 parse mode。

日报与 current 运行产物：

- `output/public/daily/full.html`
- `output/public/current/index.html`
- `output/public/current/state.json`

仅当 dispatch mode 为 `artifact` 或 `live` 时，另外生成：

- `output/dr/dispatch/latest/dispatch_plan.json`
- `output/dr/dispatch/latest/dispatch_receipts.json`

## 部署要求

Docker compose 将 `config` 与 `output` 挂载到容器，其中 Prompt 来自宿主机的只读 `config`，Python、事件 schema、解析器和渲染器来自镜像，测试不进入生产镜像。因此镜像代码与宿主配置必须来自同一 revision，不能只更新 Prompt 或只更新镜像。`docker/docker-compose.yml` 是纯 image 运行配置，不会自动构建本地代码；本地发布前先确认 worktree 干净，再在仓库根目录执行：

```bash
scripts/docker/build-image.sh wantcat/trendradar:latest
cd docker
cp .env.example .env  # 首次部署
docker compose up -d --force-recreate
```

部署后至少核对：

1. 镜像中的 `PTILOPSIS_BUILD_COMMIT` 与验收 commit 相同，且没有 `-dirty` 后缀。
2. 宿主 `config` 来自同一 commit，Prompt 和 parser 都声明 `environment-events-v1`。
3. 日报日志能看到批次数、结束原因和 token 用量。
4. `full.html` 不出现“本组”“该类目”等内部组织语言。
5. 同一次 daily 运行生成的 HTML 与 Telegram 使用相同的事件标题和验证状态；独立的 current/incremental 运行与 daily 共用相同 schema、证据绑定和状态规则。

## 本地验收

```bash
.venv/bin/python -m unittest \
  tests.test_analyzer_environment \
  tests.test_config_and_prompt_files \
  tests.test_daily_report_v2_artifact \
  tests.test_dr_dispatch \
  tests.test_dashboard \
  tests.test_context_daily_renderer_routing

git diff --check
```

视觉模板以 Newsletter 文章流为准：无表格、无卡片堆叠、少分隔线；正文与阅读向操作保持统一字号，通过字重建立层级；仅日报大标题、标题周边元数据、来源与核验元数据和页脚使用例外字号。折叠入口不显示三角符号。
