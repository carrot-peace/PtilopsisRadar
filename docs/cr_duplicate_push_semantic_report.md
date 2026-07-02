# CR 同事件重复推送与语义聚类失灵调查报告

生成时间：2026-07-01  
调查范围：`output/cr/archive/dispatch_plan/current-*.json`、`output/cr/archive/dispatch_receipts/current-*.json`、`output/cr/state/cr_dispatch_state.json`  
报告性质：事实调查与证据分析。

## 1. 调查摘要

本次调查确认：CR-A 在 2026-06-20 至 2026-07-01 的归档数据中，存在同一语义事件被多次纳入实际发送批次的现象。该现象并非单一模式，而是由两类重复构成：

1. **同一 `event_key` 重复发送**  
   这类记录的事件身份键一致，说明系统已经识别为同一事件。重复出现的直接原因来自 cooldown 状态：有些是等级升级后被放行，有些是冷却时间经过后再次进入发送批次。

2. **语义同一事件但 `event_key` 分裂**  
   这类记录的标题表达不同，但事件语义、来源证据、聚类标题集合高度重合。系统给它们生成了不同 `event_key`，于是 cooldown 状态无法互相命中。这是本报告重点关注的“语义聚类/身份识别失灵”现象。

在以“receipt 中存在 `accepted=true` 且候选未被 `suppressed_by_cooldown=true` 标记”为实际发送口径重建候选流后，得到以下统计：

| 指标 | 数值 |
|---|---:|
| 实际发送候选记录 | 274 |
| 覆盖日期 | 2026-06-20 至 2026-07-01 |
| 语义近似重复候选组 | 14 组 |
| 同 `event_key` 重复发送组 | 22 组 |
| 同 `event_key` 重复发送记录 | 65 条 |

本报告中的“实际发送候选记录”指候选进入了被接收的发送批次，并且该候选没有被 cooldown 明确抑制。CR-A 可以在一个批次中包含多个候选，因此候选记录数不等同于 Telegram 消息条数。

## 2. 调查口径

### 2.1 数据文件

使用的归档数据来自以下位置：

| 数据 | 路径 |
|---|---|
| 调度计划 | `output/cr/archive/dispatch_plan/current-*.json` |
| 调度回执 | `output/cr/archive/dispatch_receipts/current-*.json` |
| 当前事件状态 | `output/cr/state/cr_dispatch_state.json` |

核心字段：

| 字段 | 含义 |
|---|---|
| `run_id` | 本次 CR-A 运行标识 |
| `created_at` | 本次运行时间，原始值为 UTC |
| `candidate_id` | 候选 ID |
| `event_key` | cooldown 使用的事件身份键 |
| `current_level` | 当前候选级别 |
| `decision` | cooldown/enforcement 结果 |
| `suppressed_by_cooldown` | 是否被 cooldown 抑制 |
| `score` | 候选分数 |
| `source_count` | 候选包含的 source item 数量 |
| `platform_count` | 候选覆盖的平台/source_id 数量 |
| `cluster_key` | 候选聚类证据，由标题与 URL 等信息构成 |

### 2.2 纳入标准

候选被纳入“实际发送候选记录”需要同时满足：

1. 对应 `dispatch_receipts` 中存在 `accepted=true`。
2. 候选级别为 `alert` 或 `urgent`。
3. `suppressed_by_cooldown` 不是 `true`。
4. `decision` 不是 `skipped_cooldown` 或 `not_evaluated`。

调查中发现，`decision="cooldown"` 并不必然表示该候选被拦截。部分记录中 `decision="cooldown"`，但 `suppressed_by_cooldown=false` 且 receipt 已 accepted，说明 cooldown 已经过期后该候选进入发送批次。

### 2.3 语义重复识别

语义重复筛查采用离线分析，主要依据：

- 标题规范化后的 CJK 2/3/4-gram 重合。
- 英文、数字、机构名、地点名 token 重合。
- 标题包含率与 Jaccard 相似度。
- 72 小时时间窗。
- 对高相似候选组进行人工复核。

该分析只用于调查归类，不参与系统运行。

## 3. 总体统计

### 3.1 发送候选按日期分布

| 日期 | 发送候选记录数 |
|---|---:|
| 2026-06-20 | 23 |
| 2026-06-21 | 13 |
| 2026-06-22 | 16 |
| 2026-06-23 | 44 |
| 2026-06-24 | 22 |
| 2026-06-25 | 15 |
| 2026-06-26 | 22 |
| 2026-06-27 | 19 |
| 2026-06-28 | 29 |
| 2026-06-29 | 38 |
| 2026-06-30 | 21 |
| 2026-07-01 | 12 |

2026-06-23、2026-06-29 是重复候选较密集的日期。前者集中在高考分数线、娱乐事件、国际/区域事件；后者集中在地震、出口管制、娱乐舆情与公司辟谣后续。

### 3.2 enforcement 结果分布

在实际发送候选记录中，候选 outcome 分布如下：

| outcome | suppressed_by_cooldown | 数量 |
|---|---|---:|
| `allow_new` | false | 230 |
| `cooldown` | false | 33 |
| `allow_escalation` | false | 11 |

另有被排除的相关记录：

| outcome | suppressed_by_cooldown | 数量 |
|---|---|---:|
| `skipped_cooldown` | true | 14 |
| `not_evaluated` | false | 2 |

`cooldown=false` 的 33 条记录说明：同一 `event_key` 在冷却状态存在时，仍可能因为冷却时间到期进入发送批次。

## 4. 现象分型

### 4.1 同一 event_key 重复发送

此类现象表明事件身份识别本身命中，但 cooldown 状态没有持续阻止后续曝光。

典型表现：

- 同标题、同 `event_key` 在多个小时内多次出现。
- alert 后变 urgent，以 `allow_escalation` 进入发送批次。
- 同级事件在 60 分钟冷却后以 `decision="cooldown"`、`suppressed_by_cooldown=false` 再次发送。

代表事件：

- `上海高考分数线公布`
- `2名中国公民在委内瑞拉地震中遇难`
- `中方将20家日本实体列入管控名单`
- `美股半导体指数暴跌早报`

### 4.2 语义同一事件但 event_key 分裂

此类现象是本报告中的核心语义身份问题。

典型表现：

- 标题短写/长写变化。
- 标题中增加数字、机构前缀、后续状态。
- 同一候选的 `cluster_key` 已包含多个标题变体，但 `event_key` 仍随展示标题变化。
- 相同 `candidate_id` 下出现多个 `event_key`。

代表事件：

- `上海高考分数线公布` vs `上海高考分数线公布：本科403分`
- `2名中国公民在委内瑞拉地震中遇难` vs `2名中国公民在委地震中遇难`
- `中方将20家日本实体列入出口管制名单` vs `商务部：将20家日本实体列入出口管制管控名单`
- `东鹏饮料辟谣“创始人不喝自家饮料”` vs `东鹏饮料辟谣董事长饭局拒喝自家饮料`
- `伊朗锡里克地区传出爆炸声，美军称再对伊实施打击` vs `伊朗锡里克地区传出爆炸声 美军称再对伊实施打击`

### 4.3 聚类证据存在但推送身份未继承

多组案例显示，候选 `cluster_key` 已经包含多个标题变体和多个 URL，说明候选聚类层已经将这些 source item 合并到了同一候选中。但 cooldown 使用的 `event_key` 来自展示标题，因此当展示标题变化时，推送身份依然分裂。

最典型的证据来自：

- 东鹏饮料案例：相同 `candidate_id=c7722570d4cc`，两个不同 `event_key`。
- 伊朗锡里克案例：相同 `candidate_id=caf186287635`，两个不同 `event_key`。
- 中方 20 家日本实体案例：`cluster_key` 同时包含多个同义标题，但产生三段不同 `event_key`。

## 5. 代码路径证据

### 5.1 event_key 的生成基础

事件身份生成位于：

`trendradar/cr/event_identity.py`

核心行为：

- `normalize_cr_event_title` 对标题做 NFKC、空白折叠和 lowercase。
- 该函数保留标点和语义差异。
- `build_cr_event_identity_from_input` 使用 `CR_EVENT_IDENTITY_KEY_VERSION + normalized_title` 生成 sha256。

这意味着展示标题中的以下差异会进入 hash：

- 中文标点差异。
- 短标题与长标题差异。
- 数字说明差异。
- 机构前缀差异。
- 地名/简称差异。

### 5.2 cooldown 使用 stable_event_key_for_candidate

cooldown enforcement 位于：

`trendradar/cr/cooldown_enforce.py`

关键路径：

- `enforce_cr_cooldown_for_candidates`
- 对每个候选调用 `stable_event_key_for_candidate(pc)`
- `stable_event_key_for_candidate` 最终读取候选对象的 `display_title`

因此 cooldown 的主身份键来自候选展示标题，而不是完整的 `cluster_key`、标题集合或 URL 集合。

### 5.3 cluster_key 与 event_key 的职责差异

聚类层位于：

`trendradar/cr/cluster.py`

候选构建会生成：

- `display_title`
- `source_items`
- `keyword_groups`
- `source_names`
- `source_ids`
- `feed_ids`
- `cluster_key`
- `candidate_id`

其中 `cluster_key` 能包含多个标题和 URL。调查案例显示，多个重复事件的 `cluster_key` 中已经出现了同义标题集合，但 event identity 的主 hash 没有直接使用这些集合。

## 6. 案例一：上海高考分数线公布

### 6.1 发送序列

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 分数 | source/platform | 标题 |
|---|---|---|---|---|---:|---|---|
| 2026-06-23 18:03:07 | `4b8290bde34f` | `cr-event-v1:e176b371de94` | alert | allow_new | 60.002 | 1/1 | 上海高考分数线公布 |
| 2026-06-23 18:32:01 | `364420183137` | `cr-event-v1:e176b371de94` | urgent | allow_escalation | 89.25 | 6/5 | 上海高考分数线公布 |
| 2026-06-23 19:32:04 | `2c09635a526a` | `cr-event-v1:e176b371de94` | alert | cooldown | 69.45 | 5/5 | 上海高考分数线公布 |
| 2026-06-23 20:32:24 | `2c09635a526a` | `cr-event-v1:e176b371de94` | alert | cooldown | 69.45 | 5/5 | 上海高考分数线公布 |
| 2026-06-23 21:02:32 | `2c09635a526a` | `cr-event-v1:9eca883df0c6` | alert | allow_new | 69.45 | 5/5 | 上海高考分数线公布：本科403分 |
| 2026-06-23 22:02:16 | `30229262e883` | `cr-event-v1:e176b371de94` | alert | cooldown | 69.45 | 5/5 | 上海高考分数线公布 |
| 2026-06-23 23:32:47 | `d0beab1181e0` | `cr-event-v1:e176b371de94` | urgent | allow_escalation | 89.25 | 4/4 | 上海高考分数线公布 |
| 2026-06-24 01:02:22 | `4a91ea9a17b4` | `cr-event-v1:e176b371de94` | urgent | cooldown | 88.75 | 3/3 | 上海高考分数线公布 |
| 2026-06-24 04:32:07 | `4a91ea9a17b4` | `cr-event-v1:e176b371de94` | urgent | cooldown | 83.25 | 3/3 | 上海高考分数线公布 |
| 2026-06-24 06:02:06 | `4a91ea9a17b4` | `cr-event-v1:e176b371de94` | urgent | cooldown | 83.25 | 3/3 | 上海高考分数线公布 |
| 2026-06-24 10:02:17 | `2dbf3b1d21a4` | `cr-event-v1:e176b371de94` | alert | cooldown | 77.6 | 2/2 | 上海高考分数线公布 |

### 6.2 聚类证据

在 2026-06-23 18:32:01 的记录中，候选已覆盖 6 个 source item、5 个平台，`cluster_titles` 包含：

- `上海2026高考分数线公布`
- `上海高考分数线公布`
- `上海高考分数线公布 本科403分`
- `上海高考查分`

在 2026-06-23 21:02:32 的记录中，候选 `candidate_id=2c09635a526a`，标题展示为 `上海高考分数线公布：本科403分`，`event_key` 从 `e176...` 变为 `9eca...`。

### 6.3 现象分析

本案同时体现两种重复：

1. `e176...` 同一 event_key 在多个时刻重复进入发送批次。
2. `上海高考分数线公布：本科403分` 与 `上海高考分数线公布` 同属 cluster titles，但生成了新的 `event_key=9eca...`，并被判定为 `allow_new`。

聚类层对“上海高考分数线公布”和“本科403分”的关系已有捕捉，推送身份层没有保持同一身份。

## 7. 案例二：委内瑞拉地震与中国公民遇难

### 7.1 发送序列

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 分数 | source/platform | 标题 |
|---|---|---|---|---|---:|---|---|
| 2026-06-25 19:02:42 | `a2d80a34046a` | `cr-event-v1:95ac680eac80` | urgent | allow_new | 88.75 | 3/3 | 委内瑞拉强震遇难人数升至164人 |
| 2026-06-26 07:31:59 | `f3e8b0629783` | `cr-event-v1:2ca94baafafc` | urgent | allow_new | 88.75 | 3/3 | 2名中国公民在委内瑞拉地震中遇难 |
| 2026-06-26 08:02:35 | `ac63ca5e0bb9` | `cr-event-v1:2ca94baafafc` | urgent | allow_escalation | 89.25 | 4/4 | 2名中国公民在委内瑞拉地震中遇难 |
| 2026-06-26 09:02:35 | `ac63ca5e0bb9` | `cr-event-v1:2ca94baafafc` | alert | cooldown | 69.45 | 4/4 | 2名中国公民在委内瑞拉地震中遇难 |
| 2026-06-26 09:32:05 | `9917f9cfacc7` | `cr-event-v1:2ca94baafafc` | urgent | allow_escalation | 89.25 | 5/5 | 2名中国公民在委内瑞拉地震中遇难 |
| 2026-06-26 10:32:22 | `709dd141164f` | `cr-event-v1:8d76fd08d270` | alert | allow_new | 69.45 | 4/4 | 2名中国公民在委地震中遇难 |
| 2026-06-26 11:02:33 | `b23aec8437a2` | `cr-event-v1:8d76fd08d270` | urgent | allow_escalation | 89.25 | 5/5 | 2名中国公民在委地震中遇难 |
| 2026-06-26 12:32:04 | `709dd141164f` | `cr-event-v1:2ca94baafafc` | alert | cooldown | 69.45 | 4/4 | 2名中国公民在委内瑞拉地震中遇难 |
| 2026-06-26 13:32:11 | `709dd141164f` | `cr-event-v1:2ca94baafafc` | alert | cooldown | 69.45 | 4/4 | 2名中国公民在委内瑞拉地震中遇难 |
| 2026-06-26 15:02:50 | `5c34c02eed41` | `cr-event-v1:2ca94baafafc` | alert | cooldown | 67.85 | 3/3 | 2名中国公民在委内瑞拉地震中遇难 |
| 2026-06-27 09:02:28 | `04ef5567a6ad` | `cr-event-v1:740a54dde1e6` | alert | allow_new | 78.4 | 2/2 | 委内瑞拉地震中国公民遇难人数升至7人 |
| 2026-06-27 10:32:07 | `70cd9ed26a65` | `cr-event-v1:b1f8aef77c7d` | urgent | allow_new | 88.75 | 3/3 | 委内瑞拉地震7名中国公民遇难 |
| 2026-06-27 10:32:07 | `c7b4919f5914` | `cr-event-v1:b04c29882bfe` | alert | allow_new | 60.002 | 1/1 | 委内瑞拉强震已致920人遇难 |
| 2026-06-27 13:02:35 | `ef3f597f3f63` | `cr-event-v1:8b1a21bbde37` | urgent | allow_new | 88.75 | 4/3 | 遇难中国公民升至7人，委内瑞拉强震已致920死 |

### 7.2 聚类证据

`2名中国公民在委内瑞拉地震中遇难` 阶段，cluster titles 包含：

- `2名中国公民在委内瑞拉地震中遇难`
- `2名中国公民在委地震中遇难`
- `委内瑞拉地震2名中国公民遇难`

但系统生成了至少两个身份键：

- `cr-event-v1:2ca94baafafc...`
- `cr-event-v1:8d76fd08d270...`

`7名中国公民遇难` 阶段，cluster titles 包含：

- `委内瑞拉地震7名中国公民遇难`
- `委内瑞拉地震中国公民遇难人数升至7人`
- `遇难中国公民升至7人 委内瑞拉强震已致920死`

对应身份键进一步分裂：

- `cr-event-v1:740a54dde1e6...`
- `cr-event-v1:b1f8aef77c7d...`
- `cr-event-v1:8b1a21bbde37...`

### 7.3 现象分析

本案表现为“事件家族”型重复：

- 主事件：委内瑞拉强震。
- 状态更新：遇难人数升至 164、920、1430 等。
- 涉中国公民更新：2 名遇难、7 名遇难、8 名遇难。

系统把多个标题角度拆成多个 `event_key`。其中一部分在同一 cluster titles 内已经显示出语义关系，但 event identity 仍按展示标题分裂。

## 8. 案例三：中方将20家日本实体列入出口管制名单

### 8.1 发送序列

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 分数 | source/platform | 标题 |
|---|---|---|---|---|---:|---|---|
| 2026-06-29 11:32:12 | `591d663b34dd` | `cr-event-v1:c75c22babf36` | alert | allow_new | 61.0 | 2/2 | 中方将20家日本实体列入出口管制名单 |
| 2026-06-29 12:02:50 | `8a30d89b7e72` | `cr-event-v1:c75c22babf36` | urgent | allow_escalation | 88.75 | 3/3 | 中方将20家日本实体列入出口管制名单 |
| 2026-06-29 12:32:08 | `44ddf837d7a6` | `cr-event-v1:329c6bc22f77` | urgent | allow_new | 89.25 | 4/4 | 中方将20家日本实体列入管控名单 |
| 2026-06-29 13:32:27 | `44ddf837d7a6` | `cr-event-v1:329c6bc22f77` | alert | cooldown | 69.45 | 4/4 | 中方将20家日本实体列入管控名单 |
| 2026-06-29 14:32:29 | `44ddf837d7a6` | `cr-event-v1:329c6bc22f77` | alert | cooldown | 69.45 | 4/4 | 中方将20家日本实体列入管控名单 |
| 2026-06-29 15:32:31 | `dc6b1ff963e8` | `cr-event-v1:329c6bc22f77` | alert | cooldown | 69.45 | 4/4 | 中方将20家日本实体列入管控名单 |
| 2026-06-29 16:33:01 | `dc6b1ff963e8` | `cr-event-v1:728bd2b431b0` | alert | allow_new | 69.45 | 4/4 | 商务部：将20家日本实体列入出口管制管控名单 |
| 2026-06-29 17:05:54 | `78a98536e7fc` | `cr-event-v1:329c6bc22f77` | alert | cooldown | 61.25 | 3/3 | 中方将20家日本实体列入管控名单 |

### 8.2 聚类证据

2026-06-29 12:32:08 的 cluster titles：

- `中方将20家日本实体列入出口管制名单`
- `中方将20家日本实体列入管控名单`
- `商务部 将20家日本实体列入出口管制管控名单`

2026-06-29 16:33:01 的 cluster titles：

- `中方将20家日本实体列入出口管制名单`
- `中方将20家日本实体列入管控名单`
- `商务部 将20家日本实体列入出口管制管控名单`
- `商务部宣布 20 家日本实体列入出口管制管控名单 20 家日本实体列入关注名单 有哪些信息值得关注`

### 8.3 现象分析

本案中，`cluster_key` 已经把“中方”“商务部”“出口管制名单”“管控名单”多种表达聚合到同一候选证据内，但 event_key 分裂为：

- `cr-event-v1:c75c22babf36...`
- `cr-event-v1:329c6bc22f77...`
- `cr-event-v1:728bd2b431b0...`

其中 16:33 的 `商务部：将20家日本实体列入出口管制管控名单` 被判定为 `allow_new`，尽管同一候选的 cluster titles 中已经包含此前推送过的标题表达。

## 9. 案例四：四川宜宾地震

### 9.1 发送序列

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 分数 | source/platform | 标题 |
|---|---|---|---|---|---:|---|---|
| 2026-06-29 08:02:41 | `6b8bcea518e1` | `cr-event-v1:05945c1548b9` | urgent | allow_escalation | 80.5 | 2/2 | 四川宜宾地震 |
| 2026-06-29 11:32:12 | `d3fc2a16514a` | `cr-event-v1:faf222c80df1` | alert | allow_new | 61.25 | 3/3 | 四川宜宾地震瞬间鱼群乱跳 |
| 2026-06-29 12:02:50 | `a9ff2a76b391` | `cr-event-v1:faf222c80df1` | urgent | allow_escalation | 83.25 | 3/3 | 四川宜宾地震瞬间鱼群乱跳 |

### 9.2 聚类证据

11:32 与 12:02 的 cluster titles 均包含：

- `四川宜宾发生5 5级地震`
- `四川宜宾地震`
- `四川宜宾地震瞬间鱼群乱跳`

### 9.3 现象分析

`四川宜宾地震` 与 `四川宜宾地震瞬间鱼群乱跳` 在聚类标题集合中已共现。系统仍生成两个 event_key：

- `cr-event-v1:05945c1548b9...`
- `cr-event-v1:faf222c80df1...`

从语义上看，后者是前者的现场画面/衍生报道标题。推送身份层将其视为新事件。

## 10. 案例五：东鹏饮料辟谣

### 10.1 发送序列

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 分数 | source/platform | 标题 |
|---|---|---|---|---|---:|---|---|
| 2026-06-28 00:04:46 | `c7722570d4cc` | `cr-event-v1:bb0d96d34323` | alert | allow_new | 73.4 | 2/2 | 东鹏饮料辟谣“创始人不喝自家饮料” |
| 2026-06-28 08:02:29 | `c7722570d4cc` | `cr-event-v1:2734b510147f` | alert | allow_new | 66.5 | 2/2 | 东鹏饮料辟谣董事长饭局拒喝自家饮料 |
| 2026-06-29 16:33:01 | `b1937b7562de` | `cr-event-v1:ee86d6930c32` | alert | allow_new | 60.002 | 1/1 | 深圳警方：男子造谣“东鹏特饮创始人不喝自家品牌饮料”被刑拘 |
| 2026-06-30 00:03:44 | `7f411a672610` | `cr-event-v1:421d60726dca` | urgent | allow_new | 80.5 | 2/2 | 警方通报「东鹏特饮创始人不喝自家饮料」，造谣者被刑拘，涉及哪些法律问题？谣言为啥能让其市值蒸发 70 亿？ |

### 10.2 聚类证据

前两条的 `candidate_id` 完全相同：

`c7722570d4cc`

cluster titles 包含：

- `东鹏饮料辟谣 创始人不喝自家饮料`
- `东鹏饮料辟谣董事长饭局拒喝自家饮料`

但 event_key 分别是：

- `cr-event-v1:bb0d96d34323...`
- `cr-event-v1:2734b510147f...`

### 10.3 现象分析

这是非常明确的“同一候选、不同事件身份”案例。候选聚类层给出了相同 `candidate_id`，表示这两个标题已经被识别为同一候选。但推送身份层仍因展示标题不同而生成两个 event_key。

后两条属于同一舆情链条的执法后续，标题中加入“警方通报”“被刑拘”“市值蒸发 70 亿”等新角度，系统将其作为新 event_key 处理。

## 11. 案例六：伊朗锡里克地区爆炸

### 11.1 发送序列

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 分数 | source/platform | 标题 |
|---|---|---|---|---|---:|---|---|
| 2026-06-28 10:02:38 | `caf186287635` | `cr-event-v1:565776ed2355` | alert | allow_new | 69.6 | 2/2 | 伊朗锡里克地区传出爆炸声，美军称再对伊实施打击 |
| 2026-06-29 00:02:37 | `caf186287635` | `cr-event-v1:7c1903147d2e` | alert | allow_new | 73.4 | 2/2 | 伊朗锡里克地区传出爆炸声 美军称再对伊实施打击 |

### 11.2 聚类证据

两条记录的 `candidate_id` 相同：

`caf186287635`

两条记录的 cluster title 均为：

`伊朗锡里克地区传出爆炸声 美军称再对伊实施打击`

差异主要来自展示标题中的中文逗号。

### 11.3 现象分析

该案例显示，标点差异足以造成 event_key 分裂。由于 `normalize_cr_event_title` 保留标点和语义内容，`爆炸声，美军称` 与 `爆炸声 美军称` 产生了不同 hash。候选层已经保持相同 `candidate_id`，但推送身份层生成了不同 `event_key`。

## 12. 其他高置信重复案例

### 12.1 湖南泸溪民房火灾

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 标题 |
|---|---|---|---|---|---|
| 2026-06-21 11:32:05 | `81716502629b` | `湖南泸溪一民房火灾致6死...` | urgent | allow_new | 湖南泸溪一民房火灾致6死 |
| 2026-06-21 13:37:10 | `b09c791f5366` | `湖南一民房发生火灾 已致6死...` | alert | cooldown | 湖南泸溪一民房火灾致6死 |
| 2026-06-21 15:31:59 | `5a0588b588f7` | `cr-event-v1:4ce5c91d83...` | alert | allow_new | 湖南泸溪一民房火灾致6死 |

该组包含早期非 `cr-event-v1` 格式 identity 与新版 title-derived identity 的混用痕迹。

### 12.2 韩红为冯小刚新片站台

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 标题 |
|---|---|---|---|---|---|
| 2026-06-23 09:32:10 | `001c45cd01b6` | `cr-event-v1:210359ca40...` | alert | allow_new | 韩红为冯小刚新片站台喊话引争议 |
| 2026-06-23 11:02:18 | `f425ddc0aa86` | `cr-event-v1:210359ca40...` | alert | cooldown | 韩红为冯小刚新片站台喊话引争议 |
| 2026-06-23 14:32:22 | `82c0851a47c4` | `cr-event-v1:beabac7301...` | alert | allow_new | 韩红为冯小刚新片站台发言引争议 |

“喊话”与“发言”造成标题身份分裂。

### 12.3 LGD.NBW vs 上海EDG.M KPL

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 标题 |
|---|---|---|---|---|---|
| 2026-06-28 14:32:17 | `a2b33c4cf368` | `cr-event-v1:ab450e03fc...` | alert | allow_new | 杭州LGD.NBW vs 上海EDG.M KPL |
| 2026-06-28 15:32:21 | `839e76acfd77` | `cr-event-v1:a99163273a...` | alert | allow_new | LGD.NBW vs 上海EDG.M KPL |

两条标题的队伍、赛事完全重合，差异是队伍名前缀地名。

### 12.4 杨紫白玉兰视后争议

| 时间 UTC+8 | candidate_id | event_key 前缀 | 等级 | decision | 标题 |
|---|---|---|---|---|---|
| 2026-06-30 00:03:44 | `af976b493ad7` | `cr-event-v1:c04dec3251...` | alert | allow_new | 杨紫获白玉兰视后为何争议难平 |
| 2026-06-30 10:02:47 | `34ec5a235cd6` | `cr-event-v1:183ae41c97...` | alert | allow_new | 杨紫获白玉兰视后争议不止 |

“为何争议难平”与“争议不止”为同一舆论话题的不同表达。

## 13. 事实归纳

### 13.1 聚类层并非完全失效

多个案例中，`cluster_key` 已包含多个标题变体和 URL：

- 上海高考案例包含 `上海2026高考分数线公布`、`上海高考分数线公布`、`本科403分`。
- 中方 20 家日本实体案例包含 `出口管制名单`、`管控名单`、`商务部...管控名单`。
- 东鹏饮料案例中同一 `candidate_id` 包含两个辟谣标题。
- 伊朗锡里克案例中同一 `candidate_id` 横跨两个展示标题。

因此，问题并非简单表现为“source item 没有合并成候选”。在不少高置信案例中，候选层已经形成合并证据。

### 13.2 推送身份层比候选聚类层更脆弱

当前 `event_key` 主要由展示标题生成。展示标题是面向用户展示的字段，会受以下因素影响：

- 平台标题差异。
- 热榜标题长度差异。
- 标点差异。
- 数字更新。
- 机构名前缀。
- 具体后续信息。
- display title 选择规则变化。

这些变化不一定代表新事件，但会影响 `event_key`。

### 13.3 同一 candidate_id 下 event_key 变化是强证据

调查中发现至少两组明确案例：

| candidate_id | 标题 A | event_key A | 标题 B | event_key B |
|---|---|---|---|---|
| `c7722570d4cc` | 东鹏饮料辟谣“创始人不喝自家饮料” | `bb0d96d34323...` | 东鹏饮料辟谣董事长饭局拒喝自家饮料 | `2734b510147f...` |
| `caf186287635` | 伊朗锡里克地区传出爆炸声，美军称再对伊实施打击 | `565776ed2355...` | 伊朗锡里克地区传出爆炸声 美军称再对伊实施打击 | `7c1903147d2e...` |

同一 `candidate_id` 表明候选身份稳定，但不同 `event_key` 表明推送身份不稳定。

### 13.4 灾害与后续报道最容易形成重复

委内瑞拉地震案例覆盖：

- 主灾害报道。
- 总遇难人数更新。
- 中国公民遇难人数更新。
- 救援/灾后状态更新。
- 更高死亡数字再更新。

这些标题共享地点和灾害实体，但系统将它们拆成多个 `event_key`。在用户感知中，这类记录最容易表现为“同一件灾害一直推”。

## 14. 结论

本次调查显示，CR-A 的同事件重复推送主要由两种机制共同造成：

1. **已识别为同一事件，但 cooldown 到期或升级后继续发送。**
2. **语义上同一事件，但展示标题变化导致 `event_key` 分裂。**

第二类现象在案例数据中非常明确。尤其是东鹏饮料与伊朗锡里克两组，同一 `candidate_id` 下出现多个 `event_key`，说明候选聚类身份与推送 cooldown 身份存在不一致。

综合所有案例，当前系统的候选聚类层能够在不少场景下合并标题变体，但推送身份层仍以展示标题为主要依据。展示标题的短写、长写、标点、数字、机构前缀、后续状态变化，会导致 event identity 断裂。由此产生的重复，在 dispatch receipts 中表现为 `allow_new`、`allow_escalation` 或 cooldown 到期后的 `cooldown=false` 发送记录。

这份调查只陈述归档数据中已发生的行为与证据链。
