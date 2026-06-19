# Scoring v1.1 预调查报告

> 生成时间: 2026-06-19
> Git: master @ eb9fef3
> 仓库: PtilopsisRadar

## 结论

- **当前是否需要调分数设计**: 需要小调。当前结构存在 cross_layer_raw 权重过小、单源事件容易靠 growth+heat 堆到 alert 的问题。
- **推荐是否做小改**: 是。推荐方案 B（evidence multiplier），改动最小、可解释、可回滚。
- **推荐方案**: 在现有 total_score 后乘 evidence multiplier（单源 0.88，多源 1.10），仅改 `scoring.py` 的 `combine_cr_scores()` 函数。
- **不推荐的大改**: 不推荐引入 event_score/confidence_score/penalty/category_reliability 等复杂体系。当前数据不足以支撑。

## 现有 scoring 逻辑定位

### total_score 计算

- **文件**: `trendradar/cr/scoring.py:697-738`，函数 `combine_cr_scores()`
- **公式**:
  ```
  heat = clamp(growth_raw + current_heat_raw, heat_cap=80)
  cross_evidence = clamp(cross_layer_raw + background_support_raw, cross_evidence_cap=20)
  total = clamp(heat + cross_evidence, total_cap=100)
  ```
- **关键**: 这是一个纯加法结构，heat 占 80% 权重，cross_evidence 仅占 20%。

### growth_raw 计算

- **文件**: `trendradar/cr/scoring.py:425-499`，函数 `score_growth_raw()`
- **Cap**: 60
- **四个子项**（取每项在所有 items 中的最大值后求和）:
  1. `rank_movement` (0–30): 排名变化，需要 hotlist + reliable timeline + current_rank
  2. `new_burst` (0–15): 新标题检测，需要 `is_new=True` + `new_titles_detection` 语义
  3. `recency_momentum` (0–10，合成信号限 3): 时间信号
  4. `weak_persistence` (0–5): 持久性，基于 visible_observation_count 或 count

### current_heat_raw 计算

- **文件**: `trendradar/cr/scoring.py:507-603`，函数 `score_current_heat_raw()`
- **Cap**: 50
- **三个子项**:
  1. `best_rank_heat` (0–30): 当前最佳排名
  2. `source_coverage_heat` (0–12): 不同来源数量
  3. `item_count_heat` (0–8): 聚合条目数

### cross_layer_raw 计算

- **文件**: `trendradar/cr/scoring.py:611-676`，函数 `score_cross_layer_raw()`
- **Cap**: 15
- **三个子项**:
  1. `hotlist_rss_cooccurrence` (0–7): 热榜+RSS 共现，0 或 7
  2. `source_type_diversity` (0–4): 来源类型多样性
  3. `source_count_support` (0–4): 不同来源数量支持

### decision_level 计算

- **文件**: `trendradar/cr/decision.py:101-179`，函数 `apply_cr_decision()`
- **阈值**: `alert_threshold=60.0`, `urgent_threshold=80.0`
- **优先级**: suppress > urgent > alert > watch
- **suppress 逻辑**: 如果 `suppress_labels` 非空且 `suppress_overrides_all=True`（默认），直接强制 suppress

### push_eligible 计算

- **文件**: `trendradar/cr/decision.py:132-144`
- **规则**: alert → push_eligible=True, urgent → True, watch → False, suppress → False

### CSV 输出

- **当前不存在 CSV 输出**。CR 系统输出格式为: Markdown audit、HTML audit、CR-A text、dispatch plan JSON、deploy trace JSON。
- 唯一的 CSV 写入代码在 `scripts/keyword_dryrun.py`（关键词分配 dry-run，与 CR 无关）。

## 现有字段能力

| 字段 | 是否存在 | 当前用途 | 可靠性判断 | 备注 |
|---|---|---|---|---|
| candidate_id | ✅ | 聚类标识，SHA1 截断 | ✅ 可靠 | 不跨 run 稳定，跨 run 用 event_key |
| title / display_title | ✅ | 展示标题 | ✅ 可靠 | |
| run_id / run_label | ✅ | 运行标识 | ✅ 可靠 | |
| run_created_at | ✅ | 仅在 dispatch plan JSON 输出 | ✅ 可靠 | pipeline 内部不传 |
| dispatch_mode | ✅ | dispatch plan JSON 输出 | ✅ 可靠 | |
| source_count | ⚠️ | 仅在 dispatch plan JSON 输出，pipeline 内部用 `_distinct_source_count()` | ✅ 可靠 | dispatch plan 中的 source_count 是 `len(source_items)`，不是 distinct |
| platform_count | ⚠️ | 仅在 dispatch plan JSON 输出 | ✅ 可靠 | `len(source_ids)`，不含 feed_ids |
| item_count | ✅ | `len(candidate.source_items)` | ✅ 可靠 | |
| best_rank | ✅ | `best_current_rank` / `best_normalized_rank` | ✅ 可靠 | |
| best_rank_heat | ✅ | current_heat_raw 子项 | ✅ 可靠 | |
| source_coverage_heat | ✅ | current_heat_raw 子项 | ✅ 可靠 | |
| item_count_heat | ✅ | current_heat_raw 子项 | ✅ 可靠 | |
| rank_movement | ✅ | growth_raw 子项 | ✅ 可靠 | 需要 reliable timeline |
| new_burst | ✅ | growth_raw 子项 | ⚠️ 条件严格 | 需要 new_titles_detection + 非 first_crawl_of_day |
| recency_momentum | ✅ | growth_raw 子项 | ⚠️ 合成信号限 3 | |
| weak_persistence | ✅ | growth_raw 子项 | ✅ 可靠 | |
| hotlist_rss_cooccurrence | ✅ | cross_layer_raw 子项 | ✅ 可靠 | 只有 0 或 7 |
| source_count_support | ✅ | cross_layer_raw 子项 | ✅ 可靠 | 与 source_coverage_heat 用同一计数 |
| growth_raw | ✅ | 组合分数 | ✅ 可靠 | cap=60 |
| current_heat_raw | ✅ | 组合分数 | ✅ 可靠 | cap=50 |
| cross_layer_raw | ✅ | 组合分数 | ✅ 可靠 | cap=15 |
| total_score | ✅ | 最终分数 | ✅ 可靠 | |
| decision_level | ✅ | 决策级别 | ✅ 可靠 | |
| push_eligible | ✅ | 推送资格 | ✅ 可靠 | |
| suppress_reasons | ✅ | suppress 标签 | ✅ 可靠 | 有实际 suppression 逻辑 |

### 关键判断

1. **platform_count 是否存在**: 存在，但仅在 dispatch plan JSON 输出层，pipeline 内部不直接使用。在 `dispatch_plan.py:310` 中计算为 `len(source_ids)`。

2. **source_count vs platform_count 区别**: dispatch plan 中 source_count = `len(source_items)`（可重复），platform_count = `len(source_ids)`（不同平台）。pipeline 内部用 `_distinct_source_count()`，基于 source_id + source_name 命名空间去重。

3. **hotlist_rss_cooccurrence 可靠性**: 可靠。检查 `candidate.has_hotlist and candidate.has_rss`，由 cluster 层设置。

4. **source_count_support vs source_count**: source_count_support 是 cross_layer_raw 的子项分数（0-4），基于 `_distinct_source_count()` 的分桶。两者用同一底层计数。

5. **判断事件是否连续多轮出现**: 可以。通过 `state_snapshot.py` 的 `CREventStateEntry.seen_at` 和 `repeat_preview.py` 的 `CRRepeatPreview.status`（same_level_repeat / meaningful_escalation 等）。

6. **跨日期查询上一轮状态**: 可以。`state_store.py` 持久化 `CREventStateSnapshot` 到文件系统。

7. **识别午夜换日场景**: 部分可以。`CRSourceItem.first_crawl_of_day` 可标识首次抓取，但 pipeline 层没有显式的"午夜 run"标记。

## CSV 行为分析

**注意**: 仓库中不存在真实的 scoring CSV。以下数据基于合成场景回放（`tmp/scoring_replay_v11.py`）。

### 合成场景统计

- 总场景数: 10
- run 数: 2（10:00 和 00:00）
- candidate 数: 10
- 时间范围: 2026-06-19 00:00 ~ 10:00（上海时间）

### decision_level 分布（原始）

| level | 数量 |
|---|---|
| urgent | 2 (S3, S4) |
| alert | 4 (S1, S2, S7, S9) |
| watch | 4 (S5, S6, S8, S10) |
| suppress | 0 |

### push_eligible 分布

| push_eligible | 数量 |
|---|---|
| True | 6（所有 alert + urgent） |
| False | 4（所有 watch） |

### alert/urgent 中 source_count / platform_count 分布

| 场景 | source_count | platform_count | rss_cooc | level | total |
|---|---|---|---|---|---|
| S1: 单源新爆发Top10 | 1 | 1 | 0 | alert | 68.9 |
| S2: 单源排名上升30到5 | 1 | 1 | 0 | alert | 60.0 |
| S3: 双源新爆发Top3 | 2 | 2 | 0 | urgent | 82.0 |
| S4: 多源交叉印证Top2 | 3 | 3 | 1 | urgent | 93.0 |
| S7: 四源+RSS交叉Top4 | 5 | 5 | 1 | alert | 73.0 |
| S9: 双源强排名上升+持久 | 2 | 2 | 0 | alert | 74.0 |

**关键发现**: 6 个 alert/urgent 中，2 个是单源单平台（S1, S2），占比 33%。

### total_score 分布

| 统计量 | 值 |
|---|---|
| min | 8.0 (S10) |
| p25 | 25.0 |
| median | 48.9 |
| p75 | 73.0 |
| p90 | 82.0 |
| max | 93.0 (S4) |

### alert 的分数结构

| 场景 | growth_raw | current_heat_raw | cross_layer_raw | total |
|---|---|---|---|---|
| S1 | 38.9 | 29.0 | 1.0 | 68.9 |
| S2 | 30.0 | 29.0 | 1.0 | 60.0 |
| S7 | 12.0 | 46.0 | 15.0 | 73.0 |
| S9 | 34.0 | 38.0 | 2.0 | 74.0 |

**关键发现**: 单源 alert（S1, S2）的 cross_layer_raw 仅 1.0，占 total 的 1.4%~1.7%。cross_layer_raw 对最终分数几乎无影响。

### cross_layer_raw 分布

| 场景 | cross_layer_raw | 占 total 比例 |
|---|---|---|
| S1, S2, S5, S6, S8, S9, S10 | 1.0 | 1.0%~12.5% |
| S3 | 2.0 | 2.4% |
| S4 | 13.0 | 14.0% |
| S7 | 15.0 | 20.5% |

cross_layer_raw 的理论范围是 0–15，但单源事件始终为 1（仅 source_type_diversity=1 贡献），多源+RSS 共现才能达到 13–15。

### 午夜 run 行为

- S6（午夜首次抓取）: total=48.9，watch，不 alert。`first_crawl_of_day=True` 导致 new_burst=0，有效抑制了午夜误报。
- 午夜场景当前有 `first_crawl_of_day` 保护，不是主要问题。

### 重复 push 行为

合成数据中无跨 run 重复。实际部署中通过 `state_snapshot` + `repeat_preview` 可检测 same_level_repeat，但当前代码中 repeat_preview 仅用于审计，不直接抑制推送。

## 问题假设验证

| 假设 | 结论 | 证据 |
|---|---|---|
| total_score 是简单加法 | **成立** | `scoring.py:729-738`: `heat_raw = growth + heat`, `cross_ev_raw = cl + bg`, `total_raw = heat + cross_ev`。三个 cap 后相加。 |
| cross_layer_raw 权重过小 | **成立** | cross_layer_raw cap=15，cross_evidence_cap=20，而 heat_cap=80。单源事件 cross_layer_raw 恒为 1.0，占 total 的 ~1.4%。即使多源+RSS 共现，cross_layer_raw=15 也仅占 total 的 15.8%~20.5%。 |
| 单源事件可直接 alert | **成立** | S1: 单源单平台，total=68.9 > 60 → alert。S2: 单源单平台，total=60.0 = 60 → alert。仅靠 growth_raw(30-38.9) + current_heat_raw(29) 即可突破 60 阈值。 |
| push_eligible 近似等于 alert | **成立** | `decision.py:132-144`: alert → push_eligible=True, urgent → True, watch → False, suppress → False。默认策略下 push_eligible ≡ (level ∈ {alert, urgent})。 |
| 午夜换日会放大误报 | **部分成立** | `first_crawl_of_day=True` 会导致 new_burst=0（`scoring.py:286-287`），有效抑制了午夜误报。但如果不依赖 new_burst，仅靠 rank_movement + current_heat_raw，单源事件仍可能在午夜达到 alert。午夜场景的真正风险是：旧事件被重新聚合成新 candidate 后，如果没有 suppress_labels，仍可 alert。 |

## 小改方案对比

| 方案 | 改动范围 | replay 效果 | 优点 | 风险 |
|---|---|---|---|---|
| A: cross_layer 加权 (k=1.5) | `combine_cr_scores()` 内部 | alert 6→6，无变化 | 改动最小（1 行） | 对单源事件无效，cross_layer_raw 本身就是 1.0，乘 1.5 也才 1.5 |
| B: evidence multiplier | `combine_cr_scores()` 后处理 | alert 6→5，S2 降级为 watch | 可解释、可配置、不改变子项分数 | 单源 alert S1 仍保持 alert（68.9×0.88=60.6） |
| C: growth 单源衰减 | `score_growth_raw()` 或后处理 | alert 6→5，S2 降级为 watch | 精准压制最容易误报的信号 | 不能奖励多源印证 |

### 方案 A 详细分析

改动: `combine_cr_scores()` 中 `cross_ev_raw = cross_layer_raw_cs.capped_score * k + bg_cs.capped_score`

问题: cross_layer_raw 对单源事件恒为 1.0，乘 k=1.5 后也才 1.5，对 total 影响 0.5 分。**不推荐单独使用**。

### 方案 B 详细分析

改动: 在 `combine_cr_scores()` 返回前，根据 source_count / platform_count / has_rss_cooccurrence 乘以 multiplier。

参数建议:
- 单源单平台无 RSS 共现: ×0.88
- 普通: ×1.00
- 多源(≥3) / 多平台(≥3) / 有 RSS 共现: ×1.10

replay 结果:
- S1: 68.9 × 0.88 = 60.6 → 仍 alert（边界，但合理——top10 新爆发确实有新闻价值）
- S2: 60.0 × 0.88 = 52.8 → 降级为 watch（消除了边界 alert）
- S4: 93.0 × 1.10 = 102.3 → 仍 urgent（多源印证事件被奖励）
- S7: 73.0 × 1.10 = 80.3 → 从 alert 升级为 urgent（多源印证被正确奖励）

### 方案 C 详细分析

改动: 在 `score_growth_raw()` 或后处理中，对单源事件的 growth_raw 乘以衰减系数。

参数建议: `growth_raw *= 0.80`（当 source_count==1 and platform_count==1 and no RSS co-occurrence）

replay 结果:
- S1: growth 38.9→31.1, total 68.9→61.1 → 仍 alert
- S2: growth 30.0→24.0, total 60.0→54.0 → 降级为 watch

## Replay 结果

- **使用的 CSV**: 无真实 CSV，使用合成场景（`tmp/scoring_replay_v11.py`）
- **使用的参数**:
  - Scheme A: cross_layer_raw 权重 k=1.5
  - Scheme B: single_mult=0.88, multi_mult=1.10
  - Scheme C: growth_decay=0.80
- **old alert / new alert**: 6 / 5（Scheme B 和 C 均减少 1 个 alert）
- **old push / new push candidate**: 6 / 5
- **午夜 run 前后对比**: S6 始终为 watch，午夜场景无变化
- **Top changed candidates**:
  - S2（单源排名上升 30→5）: alert → watch（Scheme B 和 C）
  - S7（四源+RSS 交叉 Top4）: alert → urgent（Scheme B，多源奖励）

## 推荐实现方案

### 核心公式

```python
base_score = total_score  # 现有 combine_cr_scores 的输出
evidence_multiplier = _compute_evidence_multiplier(candidate)
final_score = clamp(base_score * evidence_multiplier, 0, 100)
```

### 推荐参数

```python
def _compute_evidence_multiplier(candidate: CRCandidate) -> float:
    source_count = _distinct_source_count(candidate)
    has_cooccurrence = candidate.has_hotlist and candidate.has_rss

    if source_count >= 3 or has_cooccurrence:
        return 1.10  # 多源印证奖励
    if source_count == 1:
        return 0.88  # 单源温和降级
    return 1.00      # 普通
```

### 需要修改的文件

| 文件 | 改动 |
|---|---|
| `trendradar/cr/scoring.py` | 在 `combine_cr_scores()` 末尾添加 evidence multiplier 逻辑 |
| `trendradar/cr/scoring.py` | `CRScoringProfile` 添加 `evidence_multiplier_enabled: bool = False` 和相关参数 |
| `trendradar/cr/scoring.py` | `CRScoreResult.debug` 添加 evidence_multiplier 信息 |
| `tests/test_cr_scoring.py` | 添加 evidence multiplier 测试用例 |

### 需要新增的字段

| 字段 | 位置 | 说明 |
|---|---|---|
| `evidence_multiplier` | `CRScoreResult.debug` | 观察用，记录实际 multiplier |
| `base_score` | `CRScoreResult.debug` | 观察用，记录乘法前的分数 |
| `adjusted_total_score` | `CRScoreResult.debug` 或新字段 | 观察用 |
| `score_adjust_reasons` | `CRScoreResult.debug` | 观察用，记录调整原因 |

### 测试计划

1. **单元测试**: 覆盖单源/多源/RSS 共现三种场景的 multiplier 计算
2. **回归测试**: 现有 `test_cr_scoring.py` 的所有用例必须通过（evidence_multiplier_enabled=False 时行为不变）
3. **边界测试**: total_score=60.0 × 0.88 = 52.8 → watch（验证边界 alert 被消除）
4. **Replay 测试**: 用 `tmp/scoring_replay_v11.py` 验证效果

### 回滚方式

1. **配置回滚**: 设置 `evidence_multiplier_enabled=False`（默认值），恢复原始行为
2. **代码回滚**: `git revert` 单个 commit
3. **无数据迁移**: 不改变数据库 schema，不需要迁移

### 上线后验证

1. 对比上线前后 dispatch plan JSON 的 `candidate_summary` 中 alert 数量
2. 检查 deploy trace 中是否有 evidence_multiplier 相关的 debug 信息
3. 观察单源 alert 的比例是否下降
4. 观察多源+RSS 共现事件是否被正确提升

## 不做的事情

明确不做的事项:

- **不重构 score ontology**: 不引入 event_score / confidence_score / penalty / category_reliability
- **不引入复杂 category reliability**: 当前数据不足以支撑分类可靠性模型
- **不改抓取层**: 不修改 adapter、crawler、RSS fetcher
- **不改数据库 schema**: 不修改 state_store、event_state 的持久化格式
- **不启用真实推送**: 不修改 dispatch / Telegram / notification 逻辑
- **不改变 decision 阈值**: alert_threshold=60.0 和 urgent_threshold=80.0 不变
- **不引入新的 suppress 标签**: 不扩展 suppress_labels 逻辑

## 附录

### 关键命令输出

```fish
# 仓库状态
pwd: /Users/ptilopsis/Projects/PtilopsisRadar
branch: master
commit: eb9fef3
status: ?? docs/deployment/apple-container-preflight.md
```

### 核心公式推导

```
# 单源事件典型分数结构
growth_raw = rank_movement(27) + new_burst(12) + recency(8) + persistence(0) = 47, cap=60
current_heat_raw = best_rank_heat(26) + coverage_heat(2) + item_heat(1) = 29, cap=50
cross_layer_raw = cooccurrence(0) + diversity(1) + count_support(0) = 1, cap=15

heat = clamp(47 + 29, 80) = 76
cross_evidence = clamp(1 + 0, 20) = 1
total = clamp(76 + 1, 100) = 77 → alert

# 多源+RSS 典型分数结构
growth_raw = 41, cap=60
current_heat_raw = 43, cap=50
cross_layer_raw = 7 + 4 + 4 = 15, cap=15

heat = clamp(41 + 43, 80) = 80
cross_evidence = clamp(15 + 0, 20) = 15
total = clamp(80 + 15, 100) = 95 → urgent
```

### Replay 脚本路径

- `tmp/scoring_replay_v11.py` — 合成场景回放脚本
- `tmp/scoring_replay_v11.csv` — 回放结果 CSV

### Git Diff

预调查阶段未修改正式代码。所有产出为临时文件（`tmp/` 和 `docs/scoring/`），不影响业务逻辑。
