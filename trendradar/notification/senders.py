# coding=utf-8
"""
消息发送器模块

将报告数据发送到 Telegram 通知渠道，支持分批发送、异常提醒、每日简报及 HTML 附件。
"""

import time
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

from .batch import add_batch_headers, get_max_batch_header_size, truncate_at_line_boundary


# ════════════════════════════════════════════════════════════════
# 实时异常提醒 gate 的作用域规则（唯一来源，勿在别处复制这些条件）
# ════════════════════════════════════════════════════════════════

# realtime alert gate 只作用于「自动实时推送」的报告模式。
REALTIME_ALERT_MODES = ("current", "incremental")
TELEGRAM_BRAND_NAME = "Ptilopsis Radar"


def _replace_telegram_brand_text(text: str) -> str:
    """Replace visible Telegram brand text without rewriting HTML tag attributes."""
    if not text:
        return text
    parts = re.split(r"(<[^>]*>)", text)
    for idx, part in enumerate(parts):
        if part.startswith("<") and part.endswith(">"):
            continue
        parts[idx] = re.sub(r"trendradar", TELEGRAM_BRAND_NAME, part, flags=re.IGNORECASE)
    return "".join(parts)


def should_apply_realtime_alert_gate(
    report_style: str, mode: str, manual_trigger: bool = False
) -> bool:
    """是否对本次 Telegram 推送应用 realtime alert gate（候选筛选 + cooldown/去重/升级）。

    规则（确定、唯一来源——所有分流判断都必须经由本函数，禁止在别处内联同等条件）：
      1. 仅 environment 报告风格适用；
      2. 仅自动实时推送适用：mode ∈ {current, incremental}；
      3. daily（含 daily_brief 预设）一律不适用——每日推送不被候选 gate 静默，
         也不读写 alert_state；daily digest 由专门 renderer 负责；
      4. 未来手动 /now 拉取（manual_trigger=True）一律不适用——直接复用 renderer 绕过 gate。

    默认从严：任何不在白名单内的情形（未知 mode、缺省、手动触发）都返回 False，
    即"不施加 gate"，避免误将非实时推送静默掉。
    """
    if manual_trigger:
        return False
    if report_style != "environment":
        return False
    return mode in REALTIME_ALERT_MODES


def _extract_ai_stats(ai_analysis) -> Optional[Dict]:
    """从 AI 分析结果中提取统计数据"""
    if not ai_analysis or not getattr(ai_analysis, "success", False):
        return None
    return {
        "total_news": getattr(ai_analysis, "total_news", 0),
        "analyzed_news": getattr(ai_analysis, "analyzed_news", 0),
        "max_news_limit": getattr(ai_analysis, "max_news_limit", 0),
        "hotlist_count": getattr(ai_analysis, "hotlist_count", 0),
        "rss_count": getattr(ai_analysis, "rss_count", 0),
        "hotlist_analyzed": getattr(ai_analysis, "hotlist_analyzed", 0),
        "rss_analyzed": getattr(ai_analysis, "rss_analyzed", 0),
        "standalone_analyzed": getattr(ai_analysis, "standalone_analyzed", 0),
        "ai_mode": getattr(ai_analysis, "ai_mode", ""),
        "include_rss": getattr(ai_analysis, "include_rss", True),
        "include_standalone": getattr(ai_analysis, "include_standalone", False),
    }


def _render_ai_analysis(ai_analysis: Any, channel: str) -> str:
    """渲染 AI 分析内容为指定渠道格式"""
    if not ai_analysis:
        return ""

    try:
        from trendradar.ai.formatter import get_ai_analysis_renderer
        renderer = get_ai_analysis_renderer(channel)
        return renderer(ai_analysis)
    except ImportError:
        return ""


def send_to_telegram(
    bot_token: str,
    chat_id: str,
    report_data: Dict,
    report_type: str,
    update_info: Optional[Dict] = None,
    proxy_url: Optional[str] = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 4000,
    batch_interval: float = 1.0,
    split_content_func: Callable = None,
    rss_items: Optional[list] = None,
    rss_new_items: Optional[list] = None,
    ai_analysis: Any = None,
    display_regions: Optional[Dict] = None,
    standalone_data: Optional[Dict] = None,
    html_file_path: Optional[str] = None,
    get_time_func: Optional[Callable] = None,
    alert_state_store: Any = None,
    alert_config: Optional[Dict] = None,
    manual_trigger: bool = False,
) -> bool:
    """
    发送到 Telegram（支持分批发送，支持热榜+RSS合并+独立展示区）

    Args:
        bot_token: Telegram Bot Token
        chat_id: Telegram Chat ID
        report_data: 报告数据
        report_type: 报告类型
        update_info: 更新信息（可选）
        proxy_url: 代理 URL（可选）
        mode: 报告模式 (daily/current)
        account_label: 账号标签（多账号时显示）
        batch_size: 批次大小（字节）
        batch_interval: 批次发送间隔（秒）
        split_content_func: 内容分批函数
        rss_items: RSS 统计条目列表（可选，用于合并推送）
        rss_new_items: RSS 新增条目列表（可选，用于新增区块）
        html_file_path: HTML 报告路径（environment alert brief 用于"完整报告"链接）
        get_time_func: 获取当前时间的函数（environment alert brief 时间戳，统一时区）
        alert_state_store: 实时提醒 cooldown 状态存储（AlertStateStore，可选）；
            为 None 时不做冷却/去重/升级过滤（行为同未启用）
        alert_config: 实时提醒门控配置（ALERT 段，大写键），驱动 cooldown / heat gate
        manual_trigger: 是否为手动触发（未来 /now 拉取实时报告）；True 时绕过 realtime alert gate，
            直接走完整渲染（不做候选筛选 / cooldown）

    Returns:
        bool: 发送是否成功
    """
    headers = {"Content-Type": "application/json"}
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    # 日志前缀
    log_prefix = f"Telegram{account_label}" if account_label else "Telegram"

    # === realtime alert gate：environment + 自动实时模式 → 走异常提醒 alert brief 单条路径 ===
    # 作用域规则统一由 should_apply_realtime_alert_gate 决定（current/incremental 自动推送）：
    #   - daily（含 daily_brief）与手动 /now 不在此分支，落到下方完整报告 split 路径；
    #   - 仅本分支做候选筛选 + cooldown/去重/升级，并读写 alert_state；
    #   - cooldown / alert gate 不影响 daily digest（daily 由专门 renderer 负责，不读写 alert_state）；
    #   - HTML 报告始终负责完整阅读与证据展开。classic 风格保持下方原逻辑。
    report_style = getattr(ai_analysis, "report_style", "classic") if ai_analysis else "classic"
    if (
        ai_analysis
        and getattr(ai_analysis, "success", False)
        and should_apply_realtime_alert_gate(report_style, mode, manual_trigger)
    ):
        from trendradar.ai.formatter import (
            render_environment_telegram_alert_brief,
            select_environment_alert_items,
        )

        alert_cfg = alert_config or {}
        max_items = alert_cfg.get("MAX_ITEMS", 3)
        notify_labels = alert_cfg.get("NOTIFY_LABELS")
        # 语义：先按 notify_labels 限定允许的桶，再按优先级选满 max_items；
        # 不是「先选 3 条再过滤」——那会在窄白名单时误丢候选。
        items = select_environment_alert_items(
            ai_analysis, max_items=max_items, allowed_labels=notify_labels,
        )
        # 防御性兜底：selector 已按 allowed_labels 过滤，此处再过滤一次仅为容错
        if notify_labels:
            items = [(label, it) for (label, it) in items if label in notify_labels]

        now = get_time_func() if get_time_func else datetime.now()

        # cooldown / 去重 / 升级再推 + high_heat heat gate（仅在注入 store 时生效；
        # store=None（未启用 / 无存储后端）→ 跳过，行为同上一阶段）
        if alert_state_store is not None:
            from trendradar.ai.alert_state import apply_alert_cooldown

            cooldown_cfg = {
                "cooldown_minutes": alert_cfg.get("COOLDOWN_MINUTES", 180),
                "max_items": max_items,
                "allow_upgrade_break_cooldown": alert_cfg.get("ALLOW_UPGRADE_BREAK_COOLDOWN", True),
                "high_heat_min_rank": alert_cfg.get("HIGH_HEAT_MIN_RANK", 10),
                "high_heat_min_platforms": alert_cfg.get("HIGH_HEAT_MIN_PLATFORMS", 2),
            }
            items = apply_alert_cooldown(items, alert_state_store, now, cooldown_cfg)

        if not items:
            # 无候选 / 全部处于冷却或未达门槛：静默成功，不打断用户（留给每日简报或未来手动 /now）
            print(f"{log_prefix}本轮无可推送的异常提醒候选（冷却/门槛/无候选），跳过推送 [{report_type}]")
            return True

        text = render_environment_telegram_alert_brief(
            ai_analysis,
            items,
            report_type=report_type,
            mode=mode,
            html_file_path=html_file_path,
            now=now,
        )
        text = _replace_telegram_brand_text(text)
        # 单条消息：接近 Telegram 限制时按行截断，绝不调用通用分批器拆成多批
        # 上限取 min(batch_size, 3900)，留出余量避免逼近 Telegram 单条 4096 上限
        text = truncate_at_line_boundary(text, min(batch_size, 3900))

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = requests.post(
                url, headers=headers, json=payload, proxies=proxies, timeout=30
            )
            if response.status_code == 200 and response.json().get("ok"):
                print(f"{log_prefix}异常提醒发送成功（{len(items)} 个信号）[{report_type}]")
                # 仅在 POST 成功后落盘冷却状态：失败/未推不写，保证下轮可补推
                if alert_state_store is not None:
                    alert_state_store.commit(items, now)
                return True
            description = ""
            try:
                description = response.json().get("description", "")
            except Exception:
                description = f"状态码：{response.status_code}"
            print(f"{log_prefix}异常提醒发送失败 [{report_type}]，错误：{description}")
            return False
        except Exception as e:
            print(f"{log_prefix}异常提醒发送出错 [{report_type}]：{e}")
            return False

    # === daily digest：environment + daily → Telegram 单条每日简报 ===
    # 与 realtime alert gate 完全分离：不做候选 gate / cooldown / heat gate，
    # 不读写 alert_state；若 digest 构造失败，发送最小 fallback 消息并返回，不走 split 路径。
    if (
        ai_analysis
        and getattr(ai_analysis, "success", False)
        and report_style == "environment"
        and mode == "daily"
    ):
        try:
            from trendradar.ai.formatter import render_environment_telegram_daily_digest

            now = get_time_func() if get_time_func else datetime.now()
            text = render_environment_telegram_daily_digest(
                ai_analysis,
                html_file_path=html_file_path,
                now=now,
            )
            text = _replace_telegram_brand_text(text)
            text = truncate_at_line_boundary(text, min(batch_size, 3900))
        except Exception as e:
            print(f"{log_prefix}每日简报渲染失败，发送最小 fallback [{report_type}]：{e}")
            fallback_text = "每日简报正文暂不可用；完整 HTML 报告已生成，可查看网页或附件。"
            fallback_text = _replace_telegram_brand_text(fallback_text)
            fallback_text = truncate_at_line_boundary(fallback_text, min(batch_size, 3900))
            payload = {
                "chat_id": chat_id,
                "text": fallback_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                response = requests.post(
                    url, headers=headers, json=payload, proxies=proxies, timeout=30
                )
                if response.status_code == 200 and response.json().get("ok"):
                    print(f"{log_prefix}每日简报 fallback 发送成功 [{report_type}]")
                    return True
                description = ""
                try:
                    description = response.json().get("description", "")
                except Exception:
                    description = f"状态码：{response.status_code}"
                print(f"{log_prefix}每日简报 fallback 发送失败 [{report_type}]，错误：{description}")
                return False
            except Exception as send_error:
                print(f"{log_prefix}每日简报 fallback 发送出错 [{report_type}]：{send_error}")
                return False
        else:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                response = requests.post(
                    url, headers=headers, json=payload, proxies=proxies, timeout=30
                )
                if response.status_code == 200 and response.json().get("ok"):
                    print(f"{log_prefix}每日简报发送成功 [{report_type}]")
                    return True
                description = ""
                try:
                    description = response.json().get("description", "")
                except Exception:
                    description = f"状态码：{response.status_code}"
                print(f"{log_prefix}每日简报发送失败 [{report_type}]，错误：{description}")
                return False
            except Exception as e:
                print(f"{log_prefix}每日简报发送出错 [{report_type}]：{e}")
                return False

    # 渲染 AI 分析内容并提取统计数据
    ai_content = _render_ai_analysis(ai_analysis, "telegram") if ai_analysis else None
    ai_stats = _extract_ai_stats(ai_analysis)

    # 获取分批内容，预留批次头部空间
    header_reserve = get_max_batch_header_size("telegram")
    batches = split_content_func(
        report_data, "telegram", update_info, max_bytes=batch_size - header_reserve, mode=mode,
        rss_items=rss_items,
        rss_new_items=rss_new_items,
        ai_content=ai_content,
        standalone_data=standalone_data,
        ai_stats=ai_stats,
        report_type=report_type,
    )

    # 统一添加批次头部（已预留空间，不会超限）
    batches = add_batch_headers(batches, "telegram", batch_size)

    print(f"{log_prefix}消息分为 {len(batches)} 批次发送 [{report_type}]")

    # 逐批发送
    for i, batch_content in enumerate(batches, 1):
        batch_content = truncate_at_line_boundary(
            _replace_telegram_brand_text(batch_content), batch_size
        )
        content_size = len(batch_content.encode("utf-8"))
        print(
            f"发送{log_prefix}第 {i}/{len(batches)} 批次，大小：{content_size} 字节 [{report_type}]"
        )

        payload = {
            "chat_id": chat_id,
            "text": batch_content,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(
                url, headers=headers, json=payload, proxies=proxies, timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    print(f"{log_prefix}第 {i}/{len(batches)} 批次发送成功 [{report_type}]")
                    # 批次间间隔
                    if i < len(batches):
                        time.sleep(batch_interval)
                else:
                    print(
                        f"{log_prefix}第 {i}/{len(batches)} 批次发送失败 [{report_type}]，错误：{result.get('description')}"
                    )
                    return False
            else:
                print(
                    f"{log_prefix}第 {i}/{len(batches)} 批次发送失败 [{report_type}]，状态码：{response.status_code}"
                )
                return False
        except Exception as e:
            print(f"{log_prefix}第 {i}/{len(batches)} 批次发送出错 [{report_type}]：{e}")
            return False

    print(f"{log_prefix}所有 {len(batches)} 批次发送完成 [{report_type}]")

    return True


ATTACHMENT_EVENT_DEFAULTS = {
    "realtime_alert": "dashboard",
    "daily_digest": "full",
}
ATTACHMENT_REPORT_KINDS = {"dashboard", "full"}


def _normalize_attachment_report_kind(value: Any) -> Optional[str]:
    kind = str(value or "").strip().lower()
    return kind if kind in ATTACHMENT_REPORT_KINDS else None


def resolve_attachment_kind_for_event(cfg: Dict[str, Any], event_name: str) -> str:
    """Resolve Telegram HTML attachment kind from event-level policy.

    Known event defaults are intentionally event-specific:
      - realtime_alert -> dashboard
      - daily_digest   -> full

    Legacy REPORT_KIND is retained only as a compatibility fallback for unknown
    events. It does not override the built-in defaults for known events.
    """
    event = str(event_name or "").strip()
    default = ATTACHMENT_EVENT_DEFAULTS.get(event)

    policy = cfg.get("REPORT_KIND_BY_EVENT") or cfg.get("report_kind_by_event") or {}
    if isinstance(policy, dict) and event in policy:
        kind = _normalize_attachment_report_kind(policy.get(event))
        if kind:
            return kind
        if default:
            return default

    if default:
        return default

    legacy = _normalize_attachment_report_kind(
        cfg.get("REPORT_KIND", cfg.get("report_kind", "full"))
    )
    return legacy or "full"


def resolve_report_attachment_path(
    output_dir: str, mode: str, report_kind: str = "full"
) -> str:
    """解析要作为 Telegram 附件发送的报告文件路径。

    支持发布根下的两类单文件 HTML：
      - full      → public/{group}/full.html
      - dashboard → public/{group}/index.html

    group 映射与 generator.py / dashboard.py 完全一致：
      - current / incremental → current
      - daily                 → daily

    本函数只会拼出 public/{group}/full.html 或 public/{group}/index.html，
    绝不指向 state.json / db / log / alert_state / secrets。
    """
    group = "daily" if mode == "daily" else "current"
    kind = _normalize_attachment_report_kind(report_kind) or "full"
    filename = "index.html" if kind == "dashboard" else "full.html"
    return str(Path(output_dir) / "public" / group / filename)


def send_telegram_document(
    bot_token: str,
    chat_id: str,
    document_path: str,
    *,
    filename: Optional[str] = None,
    caption: Optional[str] = None,
    proxy_url: Optional[str] = None,
    max_file_mb: float = 8,
    timeout: int = 60,
    log_prefix: str = "Telegram",
) -> bool:
    """发送单个 document 附件到一个 chat（sendDocument）。

    仅负责附件投递：不渲染文本、不分批、不读写 alert_state、不改文案。
    所有失败（文件缺失 / 过大 / API / 网络）都返回 False 并打印日志，绝不抛出，
    以保证调用方可以「附件失败不影响文本推送结果」。

    Args:
        bot_token: Telegram Bot Token
        chat_id: 目标 chat id
        document_path: 本地文件路径
        filename: 展示给用户的文件名（如 trendradar-current.html）；None 时用真实文件名
        caption: 可选说明文字（v1 不传，避免改文案）
        proxy_url: 代理 URL（可选）
        max_file_mb: 大小上限（MB）；<=0 表示不检查（仍受 Telegram 物理上限约束）
        timeout: 请求超时（秒）
        log_prefix: 日志前缀

    Returns:
        bool: 仅当 Telegram 确认 ok 时返回 True
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    path = Path(document_path)
    if not path.is_file():
        print(f"{log_prefix}附件文件不存在，跳过附件发送：{document_path}")
        return False

    try:
        size = path.stat().st_size
    except OSError as e:
        print(f"{log_prefix}附件无法读取大小，跳过附件发送：{document_path}：{e}")
        return False

    if max_file_mb and max_file_mb > 0:
        limit = int(max_file_mb * 1024 * 1024)
        if size > limit:
            print(
                f"{log_prefix}附件过大（{size} 字节 > {max_file_mb}MB），跳过附件发送：{document_path}"
            )
            return False

    send_name = filename or path.name
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption

    try:
        with open(path, "rb") as f:
            files = {"document": (send_name, f, "text/html")}
            response = requests.post(
                url, data=data, files=files, proxies=proxies, timeout=timeout
            )
        if response.status_code == 200 and response.json().get("ok"):
            print(f"{log_prefix}附件发送成功（{send_name}，{size} 字节）")
            return True
        description = ""
        try:
            description = response.json().get("description", "")
        except Exception:
            description = f"状态码：{response.status_code}"
        print(f"{log_prefix}附件发送失败，错误：{description}")
        return False
    except Exception as e:
        print(f"{log_prefix}附件发送出错：{e}")
        return False
