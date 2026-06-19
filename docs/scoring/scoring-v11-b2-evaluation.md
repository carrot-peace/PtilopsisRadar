# Scoring v1.1 B2 追加评估：cross evidence 乘法化

> 生成时间: 2026-06-19
> 基于: docs/scoring/scoring-v11-preflight.md
> Git: master @ eb9fef3

## 结论

- **是否存在双算问题**: 是。方案 B 确实存在 double-counting。对于 S4（多源交叉印证 Top2），B 给出 100.0（cross_ev=13 加分 + 10% boost），而 B2 给出 88.0（仅 10% boost on heat=80）。B 把 cross_evidence 算了两次：一次加法，一次乘法。
- **B2 是否可实现**: 是。只需改 `combine_cr_scores()` 最后 5 行，不触及子项计算。
- **是否推荐 B2**: 推荐 B2-lite，不推荐纯 B2。
- **是否推荐 B2-lite**: 是。B2-lite 是最平衡的选择。
- **推荐最终方案**: **B2-lite-v1**（`heat × multiplier + min(cross_ev × 0.25, 5.0)`）

## 现有公式复核

### heat_score

```python
heat_raw = growth_raw.capped_score + current_heat_raw.capped_score
heat_score = clamp(heat_raw, heat_cap=80.0)
```

位置: `scoring.py:729-730`

### cross_evidence_score

```python
cross_ev_raw = cross_layer_raw.capped_score + background_support_raw.capped_score
cross_evidence_score = clamp(cross_ev_raw, cross_evidence_cap=20.0)
```

位置: `scoring.py:733-734`

### total_score

```python
total_raw = heat_score + cross_evidence_score
total_score = clamp(total_raw, total_cap=100.0)
```

位置: `scoring.py:737-738`

### cap 关系

| 组件 | cap | 理论最大值（实际） |
|---|---|---|
| growth_raw | 60 | ~51（rank_movement 30 + new_burst 15 + recency 10 + persistence 5 = 60，但实际很少同时满分） |
| current_heat_raw | 50 | 50（rank 30 + coverage 12 + item_count 8） |
| heat | 80 | 80（growth + heat 超过 80 被截断） |
| cross_layer_raw | 15 | 15（cooccurrence 7 + diversity 4 + count_support 4） |
| background_support_raw | 10 | 0（当前 disabled） |
| cross_evidence | 20 | 15（当前 bg=0） |
| total | 100 | 95（heat 80 + cross 15） |

### debug / profile 可扩展性

- `CRScoreResult.debug` 是 `dict[str, object]`，可自由添加字段 ✅
- `CRScoringProfile` 是 frozen dataclass，新增字段需要新参数 ✅（向后兼容）
- `combine_cr_scores()` 已有 `profile` 参数，可传递新配置 ✅

## 方案定义

### 原始方案（当前）

```
total = clamp(heat + cross_evidence, 0, 100)
```

cross_evidence 作为加法项，最多贡献 20 分。

### 方案 B

```
total = clamp((heat + cross_evidence) * evidence_multiplier, 0, 100)
```

问题: cross_evidence 已在加法中贡献了分数，又通过 multiplier（基于 source_count/has_rss）再算一次。对多源事件双重奖励。

### 方案 B2

```
heat = clamp(growth_raw + current_heat_raw, 0, 80)
evidence_multiplier = f(candidate)
total = clamp(heat * evidence_multiplier, 0, 100)
```

cross_evidence 不再加分，仅通过 multiplier 间接影响。解决了双算问题，但可能过度压低有交叉证据但 heat 不高的事件。

### 方案 B2-lite

```
heat = clamp(growth_raw + current_heat_raw, 0, 80)
cross_evidence = clamp(cross_layer_raw + bg, 0, 20)
small_cross_bonus = min(cross_evidence * 0.25, 5.0)
evidence_multiplier = f(candidate)
total = clamp(heat * evidence_multiplier + small_cross_bonus, 0, 100)
```

主逻辑是乘法，但保留 0–5 分的小补偿，避免有交叉证据但 heat 略低的事件被过度压低。

## Replay 对比

### 分数对比

| 场景 | src | rss | heat | cross_ev | old | B | B2v1 | B2v2 | B2Lv1 | B2Lv2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S1: 单源新爆发Top10 | 1 | 0 | 67.9 | 1.0 | 68.9 | 60.6 | 59.8 | 61.1 | 60.0 | 61.4 |
| S2: 单源排名30到5 | 1 | 0 | 59.0 | 1.0 | 60.0 | 52.8 | 51.9 | 53.1 | 52.2 | 53.4 |
| S3: 双源新爆发Top3 | 2 | 0 | 80.0 | 2.0 | 82.0 | 82.0 | 80.0 | 78.4 | 80.5 | 78.9 |
| S4: 多源交叉印证Top2 | 3 | 1 | 80.0 | 13.0 | 93.0 | **100.0** | 88.0 | 86.4 | 91.2 | 89.7 |
| S5: 单源弱Rank80 | 1 | 0 | 24.0 | 1.0 | 25.0 | 22.0 | 21.1 | 21.6 | 21.4 | 21.9 |
| S6: 午夜首次抓取 | 1 | 0 | 47.9 | 1.0 | 48.9 | 43.0 | 42.2 | 43.1 | 42.4 | 43.4 |
| S7: 四源+RSS Top4 | 5 | 1 | 58.0 | 15.0 | 73.0 | **80.3** | 63.8 | 62.6 | 67.6 | 66.4 |
| S8: 单源Rank150 | 1 | 0 | 8.3 | 1.0 | 9.3 | 8.2 | 7.3 | 7.5 | 7.6 | 7.7 |
| S9: 双源强改善 | 2 | 0 | 72.0 | 2.0 | 74.0 | 74.0 | 72.0 | 70.6 | 72.5 | 71.1 |
| S10: 纯RSS | 1 | 0 | 7.0 | 1.0 | 8.0 | 7.0 | 6.2 | 6.3 | 6.4 | 6.5 |
| S11: 双源中等边界 | 2 | 0 | 52.0 | 2.0 | 54.0 | 54.0 | 52.0 | 51.0 | 52.5 | 51.5 |
| S12: 热榜+RSS低热 | 2 | 1 | 29.0 | 12.0 | 41.0 | 45.1 | 31.9 | 31.3 | 34.9 | 34.3 |
| S13: 三源热榜强 | 3 | 0 | 79.0 | 3.0 | 82.0 | **90.2** | 86.9 | 85.3 | 87.7 | 86.1 |
| S14: 单源边界60 | 1 | 0 | 59.0 | 1.0 | 60.0 | 52.8 | 51.9 | 53.1 | 52.2 | 53.4 |
| S15: 单源高热Top3 | 1 | 0 | 80.0 | 1.0 | 81.0 | 71.3 | 70.4 | 72.0 | 70.7 | 72.2 |

**加粗** = B 方案存在明显双算的场景。

### 级别变化对比

| 场景 | old | B | B2v1 | B2v2 | B2Lv1 | B2Lv2 |
|---|---|---|---|---|---|---|
| S1: 单源新爆发Top10 | alert | alert | **watch** | alert | alert | alert |
| S2: 单源排名30到5 | alert | watch | watch | watch | watch | watch |
| S3: 双源新爆发Top3 | urgent | urgent | urgent | **alert** | urgent | **alert** |
| S7: 四源+RSS Top4 | alert | **urgent** | alert | alert | alert | alert |
| S14: 单源边界60 | alert | watch | watch | watch | watch | watch |
| S15: 单源高热Top3 | urgent | **alert** | **alert** | **alert** | **alert** | **alert** |

### 汇总统计

| 方案 | alert+urgent | urgent | 单源alert | 多源alert | 单源urgent | 多源urgent |
|---|---:|---:|---:|---:|---:|---:|
| old | 9 | 4 | 4 | 5 | 1 | 3 |
| B | 7 | 4 | 2 | 5 | 1 | 3 |
| B2v1 | 6 | 3 | 1 | 5 | 0 | 3 |
| B2v2 | 7 | 2 | 2 | 5 | 0 | 2 |
| B2Lv1 | 7 | 3 | 2 | 5 | 0 | 3 |
| B2Lv2 | 7 | 2 | 2 | 5 | 0 | 2 |

## 分层变化

### alert 数量变化

- old→B2v1: 9→6（减少 3），其中单源 alert 4→1
- old→B2Lv1: 9→7（减少 2），其中单源 alert 4→2
- B2-lite 比纯 B2 多保留 1 个 alert（S1: 单源新爆发 Top10）

### urgent 数量变化

- old→B2v1: 4→3（S15 从 urgent 降为 alert）
- old→B2Lv1: 4→3（同上）
- S15 降级合理：单源事件不应该 urgent（81 分 → 70.4 分）

### 单源 alert 变化

- old: S1(alert), S2(alert), S14(alert), S15(urgent) = 4 个单源 alert+
- B2v1: S15(alert) = 1 个单源 alert+
- B2Lv1: S1(alert), S15(alert) = 2 个单源 alert+
- B2-lite 保留了 S1（top10 新爆发有新闻价值），消除了 S2/S14（边界 alert）

### 多源/RSS 事件变化

- S4（多源交叉印证 Top2）: 所有方案保持 urgent，B2-lite 给出 91.2（合理，原始 93.0）
- S7（四源+RSS Top4）: B 升至 urgent（80.3，双算），B2/B2-lite 保持 alert（63.8~67.6）
- S13（三源热榜强）: 所有方案保持 urgent
- **B2-lite 对多源事件的奖励足够**：通过 multiplier 1.10 + 小 bonus（最多 5 分），总效果比纯 B2 好

### 边界事件变化

- S1（68.9→60.0）: B2-lite-v1 正好 60.0，仍 alert。纯 B2-v1 是 59.8，差 0.2 跌出 alert。
- S14（60.0→52.2）: 所有方案都降为 watch，消除了边界 false positive。
- **B2-lite 的小 bonus 在边界事件上起了关键作用**。

## 风险分析

### B2 可能过度压低的场景

**S7（四源+RSS Top4）**: heat=58.0, cross_ev=15.0
- 原始: 73.0 (alert) — cross_evidence 贡献了 15 分
- B2v1: 63.8 (alert) — 丢失了 9.2 分
- B2Lv1: 67.6 (alert) — 丢失了 5.4 分，其中 small_bonus 补回了 min(15×0.25, 5)=3.75

**S12（热榜+RSS 低热）**: heat=29.0, cross_ev=12.0
- 原始: 41.0 (watch)
- B2v1: 31.9 (watch) — 丢失 9.1 分，但仍是 watch
- B2Lv1: 34.9 (watch) — 丢失 6.1 分

这两个场景中 B2 都没有导致错误降级。S7 保持 alert，S12 保持 watch。B2-lite 在 S7 上多保留了 3.8 分，更接近原始分数。

### B2-lite 的折中价值

B2-lite 的 `small_cross_bonus = min(cross_ev × 0.25, 5.0)` 的效果：

| cross_ev | bonus | 占 cross_ev 比例 |
|---:|---:|---:|
| 1.0 | 0.25 | 25% |
| 2.0 | 0.50 | 25% |
| 5.0 | 1.25 | 25% |
| 10.0 | 2.50 | 25% |
| 15.0 | 3.75 | 25% |
| 20.0 | 5.00 | 25%（cap） |

- 最大 bonus 5 分，远小于原始的 20 分加法
- 保留了 cross_evidence 的可解释性（"有交叉证据 → 小加分"）
- 避免了纯 B2 对高 cross_ev 低 heat 事件的过度压低

### 是否需要调阈值

**不需要。**
- B2-lite-v1 下 alert 数量从 9 降到 7，是合理的收紧
- 单源 alert 从 4 降到 2，消除了边界 false positive
- 多源 alert 保持 5 个不变
- 如果觉得太紧，可以调 multiplier 参数（如 single_mult 从 0.88 调到 0.92），而不是调 threshold

### 是否影响 push_eligible

- push_eligible 由 decision_level 决定（alert/urgent → True）
- B2-lite 改变了部分事件的 decision_level，因此间接改变了 push_eligible
- S2/S14 从 alert→watch，push_eligible 从 True→False（符合预期）
- S15 从 urgent→alert，push_eligible 仍为 True（只是级别降了）

## 推荐实现方式

### 核心公式

```python
heat_score = clamp(growth_raw + current_heat_raw, 0, heat_cap)
cross_ev_score = clamp(cross_layer_raw + bg, 0, cross_evidence_cap)
small_cross_bonus = min(cross_ev_score * 0.25, 5.0)
evidence_multiplier = compute_evidence_multiplier(candidate)
total_score = clamp(heat_score * evidence_multiplier + small_cross_bonus, 0, total_cap)
```

### multiplier 参数

```python
def compute_evidence_multiplier(candidate):
    ds = _distinct_source_count(candidate)
    has_cooc = candidate.has_hotlist and candidate.has_rss
    if has_cooc or ds >= 3:
        return 1.10   # strong cross evidence
    if ds >= 2:
        return 1.00   # moderate
    return 0.88        # single source, no cross
```

### 修改文件

| 文件 | 改动 |
|---|---|
| `trendradar/cr/scoring.py` | `CRScoringProfile` 新增 3 个配置字段 |
| `trendradar/cr/scoring.py` | `combine_cr_scores()` 最后 5 行改为 B2-lite 公式 |
| `trendradar/cr/scoring.py` | 新增 `_compute_evidence_multiplier()` 辅助函数 |
| `trendradar/cr/scoring.py` | `CRScoreResult.debug` 记录 evidence_multiplier、small_cross_bonus、base_score |
| `tests/test_cr_scoring.py` | 新增 B2-lite 测试用例 |

### 新增 profile 字段

```python
@dataclass(frozen=True)
class CRScoringProfile:
    # ... existing fields ...
    evidence_multiplier_enabled: bool = True  # 默认启用，合并即生效
    evidence_multiplier_single: float = 0.88
    evidence_multiplier_moderate: float = 1.00
    evidence_multiplier_strong: float = 1.10
    cross_evidence_bonus_factor: float = 0.25
    cross_evidence_bonus_cap: float = 5.0
```

### 新增 debug 字段

```python
merged_debug["evidence_multiplier"] = {
    "enabled": True,
    "multiplier": mult,
    "reason": reason,
    "base_score": heat_score,
    "small_cross_bonus": small_cross_bonus,
    "adjusted_total": total_score,
}
```

### 新增测试

1. `test_b2_lite_single_source_decayed`: 单源事件 total 被 multiplier 压低
2. `test_b2_lite_multi_source_rewarded`: 多源事件 total 被 multiplier 抬高
3. `test_b2_lite_cross_bonus_applied`: cross_evidence 贡献小 bonus
4. `test_b2_lite_cross_bonus_capped`: bonus 不超过 5.0
5. `test_b2_lite_disabled_preserves_original`: `evidence_multiplier_enabled=False` 时行为不变
6. `test_b2_lite_boundary_alert`: S1 边界场景（60.0）仍为 alert

### 默认启用策略

`evidence_multiplier_enabled: bool = True`

合并即切换到 B2-lite 公式，无需额外配置。当 `enabled=False` 时，`combine_cr_scores()` 走原始的 `heat + cross_evidence` 路径，行为完全不变。

### 回滚方式

1. **配置回滚**: 传入 `CRScoringProfile(evidence_multiplier_enabled=False)`
2. **代码回滚**: `git revert` 单个 commit
3. **无需数据迁移**: 不改 schema

## 不做的事情

- 不改抓取层（adapter、crawler、RSS fetcher）
- 不改聚类（cluster.py、event_identity.py）
- 不改数据库 schema（state_store、event_state）
- 不改 dispatch/push（dispatch_plan、Telegram、notification）
- 不改 Docker / Apple container
- 不引入 event_score / confidence_score / penalty / category_reliability
- 不改 alert_threshold / urgent_threshold（60 / 80 不变）
- 不引入新的 suppress 标签

## 附录

### Replay 脚本路径

- `tmp/scoring_replay_b2.py` — B2 评估 replay 脚本
- `tmp/scoring_replay_b2.csv` — B2 评估结果 CSV

### 前一轮 replay

- `tmp/scoring_replay_v11.py` — 原始 v1.1 replay 脚本
- `tmp/scoring_replay_v11.csv` — 原始 v1.1 结果 CSV

### Git 状态

```fish
git status --short:
?? docs/deployment/apple-container-preflight.md
?? docs/scoring/
?? tmp/
```

无正式代码修改。

### B2 双算问题的数值证据

S4（多源交叉印证 Top2）:
```
heat = 80.0, cross_ev = 13.0
原始: 80 + 13 = 93.0
B:    (80 + 13) × 1.10 = 102.3 → cap 100.0   ← cross_ev 被算了两次
B2:   80 × 1.10 = 88.0                         ← cross_ev 仅通过 multiplier
B2L:  80 × 1.10 + min(13×0.25, 5) = 88+3.25=91.25  ← 保留小 bonus
```

B 方案中 cross_evidence 贡献了 +13（加法）+ 9.3（乘法放大）= 22.3 分，远超其 cap(20)。
B2-lite 中 cross_evidence 贡献了 0（加法）+ 8.0（乘法放大）+ 3.25（小 bonus）= 11.25 分，更合理。

### S7（四源+RSS Top4）的 B 双算证据

```
heat = 58.0, cross_ev = 15.0
原始: 58 + 15 = 73.0
B:    (58 + 15) × 1.10 = 80.3 → urgent  ← cross_ev(15) 加法 + 10% boost = 升级 urgent
B2:   58 × 1.10 = 63.8 → alert          ← 合理
B2L:  58 × 1.10 + 3.75 = 67.55 → alert  ← 合理
```

B 方案中 S7 从 alert 升级为 urgent，这是 cross_evidence 双算导致的过度奖励。B2/B2-lite 保持 alert，更合理。
