# 公开 Telegram / X 账号采集

支持 `telegram_html` 和 `x_public_html`，直接解析公开页面，不需要账号密码或 API Token，不执行网页脚本，也不借用第三方镜像站。消息复用现有条目存储、来源健康记录、新鲜度过滤和下游处理；`rss.feeds` 是兼容配置入口，不表示经过 RSS 转换。

## 配置和候选

默认启用用户选择的两个来源，其余媒体候选默认关闭。关闭的候选可参与只读试采，不会因此修改配置或参与生产任务。

| 配置 ID | 账号/入口 | 默认 | 来源层级 |
|---|---|---|---|
| lilaoshi-telegram | https://t.me/s/lilaoshibushinilaoshi | 开 | D，社交线索 |
| lilaoshi-x | https://x.com/whyyoutouzhele | 开 | D，社交线索 |
| zaobao-telegram | https://t.me/s/zaobaosg | 关 | B，媒体 |
| zaobao-x | https://x.com/zaobaosg | 关 | B，媒体 |
| thepaper-x | https://x.com/thepapercn | 关 | C，媒体 |
| ecns-x | https://x.com/Echinanews | 关 | C，媒体 |
| peoples-daily-zh-x | https://x.com/PDChinese | 关 | C，媒体 |
| xinhua-x | https://x.com/XHNews | 关 | C，媒体 |
| bbc-chinese-x | https://x.com/bbcchinese | 关 | B，媒体 |
| dw-chinese-x | https://x.com/dw_chinese | 关 | B，媒体 |

共 10 个入口、8 个发布方。媒体官方账号身份与某条报道是否核实是两个问题，不能因为账号是媒体就把事件自动标为已证实。早报官网列出其 Telegram/X：https://www.zaobao.com.sg/products ；中新网英文官网列出 Echinanews：https://www.ecns.cn/ 。接入其他候选前仍应核对发布方官网、简介及账号身份。

## 采集边界

- Telegram：提取消息编号、原始时间、正文与 X 原帖链接；同页相册按消息编号去重。`max_pages` 控制最近页面的历史回看，默认 1、允许 1–10；李老师配置为 3 页。只允许同频道、数字 `before` 游标，游标不后退则失败。固定回看不等于已经补齐任意长度的停机缺口。
- X：解析公开账号页当前返回的结构化帖子，不执行 JavaScript，不使用内部 GraphQL 请求。仅保留该账号的主时间线帖子，引用帖保留为上下文；长帖取完整文本，旧置顶帖按原始时间排序。当前实测通常只返回 5 条，因此它是近期快照，不能当完整账号历史流。
- 页面出现登录、挑战、改版或没有可解析消息时，记录为来源失败，不报告健康的“0 条”。HTTP 429/5xx 和连接超时沿用现有有界重试；不做验证码绕过、换 IP 或登录态轮换。
- 正文最长保留为现有 500 字摘要，标题取原文首个非空行（上限 200 字）。图片/视频无文字时只保存中性的媒体消息占位及原帖地址，不推断画面内容；OCR/语音转写尚未接入。
- 发布日期不是事发日期。今天发布的旧案跟进不能计作今天发生的新案件；大陆范围也应按事发地核实，不能按平台语言或账号所在地判断。
- 李老师 Telegram/X 是同一发布方，早报两端也是如此；不能把跨平台转发视作独立核实。现有来源分层与核验约束继续生效，这次没有增加严重度强制升级或放宽发送门槛。

## 只读试采

在仓库根目录运行：

```sh
python scripts/probe_public_sources.py --rounds 3 --interval-seconds 30 --output /tmp/public-sources.json
python scripts/probe_public_sources.py --include-disabled --rounds 3 --output /tmp/public-candidates.json
python scripts/probe_public_sources.py --match-pattern '徽剑|伤医|持刀' --output /tmp/public-topic.json
```

工具只请求公开账号并生成诊断报告，不写生产数据库、不调用模型、不发送通知。报告记录每轮成功/失败、条目编号、最新/最旧时间、24 小时内条数与诊断主题命中。诊断命中不是已核实事件数量，`--match-pattern` 也不会改变运行时准入或推送策略。

2026-10-28 的三轮短时试采，10 个入口均为 3/3 可解析，共 105 个不同入口条目地址。李老师 Telegram 3 页得到 26 条，X 5 条（含一条较早置顶）；早报 Telegram 2 页得到 39 条，其余 X 各 5 条。该结果仅证明短时可用性，不能替代持续运行的可靠性观察。X 返回窗口随发帖频率变化，高频账号的 5 条快照可能短于定时任务间隔，应监测窗口和采集间隔，并用官网时间流等独立入口补充。

## 部署

新解析代码和配置应在同一版本部署，不能只向旧镜像复制含新 `source_type` 的配置。安装依赖没有变化；需重建包含新模块的镜像。关键词扩充见 PR #201，建议先合并该词表修改以覆盖殴打、纵火、伤医等表述。当前 PR 只完成公开来源接入，未执行生产部署或触发推送。
