# coding=utf-8
"""
Canonical CR HTML audit renderer (PR9i).

Renders all presented candidates into a single self-contained HTML document
string.  Includes every decision level (urgent / alert / watch / suppress)
without filtering.  Purely internal — does NOT use the existing dashboard /
report generator, does NOT write files, does NOT call runtime, and does NOT
send messages.  No external CSS/JS assets.

Design reference: PR9i.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Mapping

from trendradar.cr.decision import (
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.cooldown_policy import (
    CRCooldownDecision,
    CRCooldownPolicy,
)
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.repeat_preview import (
    CRRepeatPreview,
    CRSeenEventState,
)
from trendradar.cr.render_model import (
    CRAuditRenderModel,
    CRCandidateRenderView,
    build_cr_audit_render_model,
)
from trendradar.cr.scoring import CRScoreResult
from trendradar.cr.state_transition_preview import (
    CREventStateTransitionPreview,
)
from trendradar.cr.input_health import CRInputHealth


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRHTMLRenderConfig:
    """Configuration for CR HTML audit rendering."""

    title: str = "Ptilopsis Radar｜CR HTML Audit"
    include_debug: bool = True
    include_source_items: bool = True
    include_score_components: bool = True
    include_event_identity: bool = True
    include_repeat_preview: bool = False
    seen_event_states: Mapping[str, CRSeenEventState] | None = None
    include_cooldown_decision: bool = False
    cooldown_policy: CRCooldownPolicy | None = None
    include_state_transition_preview: bool = False
    state_transition_preview: CREventStateTransitionPreview | None = None
    input_health: CRInputHealth | None = None
    collapse_suppress: bool = True
    collapse_watch: bool = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECTION_ORDER: list[str] = [
    DECISION_URGENT,
    DECISION_ALERT,
    DECISION_WATCH,
    DECISION_SUPPRESS,
]

_COMPONENT_ORDER: list[str] = [
    "growth_raw",
    "current_heat_raw",
    "heat",
    "cross_layer_raw",
    "background_support_raw",
    "cross_evidence",
]

_COMPONENT_DISPLAY: dict[str, str] = {
    "growth_raw": "Growth Raw",
    "current_heat_raw": "Current Heat Raw",
    "heat": "Heat",
    "cross_layer_raw": "Cross Layer Raw",
    "background_support_raw": "Background Support Raw",
    "cross_evidence": "Cross Evidence",
}

_SOURCE_ITEM_FIELDS: list[tuple[str, str]] = [
    ("source_type", "Source Type"),
    ("source_name", "Source Name"),
    ("source_id", "Source ID"),
    ("feed_id", "Feed ID"),
    ("current_rank", "Current Rank"),
    ("normalized_rank", "Normalized Rank"),
    ("is_new", "Is New"),
    ("is_new_semantics", "Is New Semantics"),
    ("observed_in_current_run", "Observed In Current Run"),
    ("observed_after_ingest_gap", "Observed After Ingest Gap"),
    ("first_time", "First Time"),
    ("last_time", "Last Time"),
    ("published_at", "Published At"),
]

# Minimal inline stylesheet — no external assets, no JavaScript.
_STYLE = (
    "body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
    "margin:0;padding:1.5rem;color:#1a1a1a;background:#fafafa;line-height:1.5}"
    "main{max-width:880px;margin:0 auto}"
    "h1{font-size:1.5rem}h2{font-size:1.2rem;text-transform:uppercase;"
    "letter-spacing:0.04em}"
    ".run-meta p{margin:0.1rem 0}"
    ".decision-section{margin:1.25rem 0;padding:0.5rem 0;border-top:1px solid #ddd}"
    ".candidate-card{border:1px solid #ddd;border-radius:6px;padding:0.75rem 1rem;"
    "margin:0.75rem 0;background:#fff}"
    ".candidate-card h3{margin:0 0 0.5rem 0;font-size:1.05rem}"
    "dl{display:grid;grid-template-columns:max-content 1fr;gap:0.15rem 0.75rem;margin:0.5rem 0}"
    "dt{font-weight:600;color:#555}dd{margin:0}"
    "table.score-components{border-collapse:collapse;margin:0.5rem 0;width:100%}"
    "table.score-components th,table.score-components td{border:1px solid #ddd;"
    "padding:0.2rem 0.5rem;text-align:right}"
    "table.score-components th:first-child,table.score-components td:first-child{text-align:left}"
    ".source-items ol{margin:0.3rem 0;padding-left:1.4rem}"
    ".debug pre{background:#f0f0f0;padding:0.5rem;overflow:auto;font-size:0.85rem}"
    ".decision-urgent>h2{color:#b00020}.decision-alert>h2{color:#c25e00}"
    ".decision-watch>h2{color:#1a6b1a}.decision-suppress>h2{color:#666}"
)


# ---------------------------------------------------------------------------
# Escaping / formatting helpers
# ---------------------------------------------------------------------------


def _escape_html_text(value: object) -> str:
    """Escape *value* for safe HTML text content (no quote escaping)."""
    return escape(str(value), quote=False)


def _escape_html_attr(value: object) -> str:
    """Escape *value* for safe HTML attribute content (quotes escaped)."""
    return escape(str(value), quote=True)


def _is_safe_href(url: str) -> bool:
    """Return True when *url* is safe to use as an anchor href.

    Only ``http://`` and ``https://`` schemes are allowed.  Anything else
    (``javascript:``, ``data:``, scheme-relative, ...) must NOT be rendered
    as a link — render the text alone instead so the audit trail is kept.
    """
    normalized = url.strip().lower()
    return normalized.startswith("http://") or normalized.startswith("https://")


def _format_score(v: float) -> str:
    """Format a score value to one decimal place (stable, no float noise)."""
    return f"{v:.1f}"


# ---------------------------------------------------------------------------
# Fragment renderers
# ---------------------------------------------------------------------------


def _render_score_components_table(sr: CRScoreResult) -> list[str]:
    """Render the score components table for one candidate."""
    lines: list[str] = []
    lines.append('      <table class="score-components">')
    lines.append("        <thead>")
    lines.append(
        "          <tr><th>Component</th><th>Raw</th><th>Capped</th><th>Cap</th></tr>"
    )
    lines.append("        </thead>")
    lines.append("        <tbody>")
    for name in _COMPONENT_ORDER:
        cs = getattr(sr, name, None)
        if cs is None:
            continue
        display = _COMPONENT_DISPLAY.get(name, name)
        lines.append(
            f"          <tr><td>{_escape_html_text(display)}</td>"
            f"<td>{_format_score(cs.raw_score)}</td>"
            f"<td>{_format_score(cs.capped_score)}</td>"
            f"<td>{_format_score(cs.cap)}</td></tr>"
        )
    lines.append("        </tbody>")
    lines.append("      </table>")
    return lines


def _render_source_item(item) -> list[str]:
    """Render one source item as an ``<li>`` entry with a metadata ``<dl>``."""
    lines: list[str] = []

    title = item.title or "(untitled)"
    if item.url and _is_safe_href(item.url):
        href = _escape_html_attr(item.url)
        lines.append(
            f'        <li><a href="{href}">{_escape_html_text(title)}</a>'
        )
    elif item.url:
        # Unsafe scheme — keep title and URL as plain escaped text for audit.
        lines.append(
            f"        <li>{_escape_html_text(title)} "
            f"({_escape_html_text(item.url)})"
        )
    else:
        lines.append(f"        <li>{_escape_html_text(title)}")

    meta_parts: list[str] = []
    for attr, label in _SOURCE_ITEM_FIELDS:
        value = getattr(item, attr, None)
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        meta_parts.append(
            f"<dt>{_escape_html_text(label)}</dt>"
            f"<dd>{_escape_html_text(value)}</dd>"
        )
    if meta_parts:
        lines.append("          <dl>" + "".join(meta_parts) + "</dl>")
    lines.append("        </li>")
    return lines


def _render_source_items(items) -> list[str]:
    """Render the source-item section for one candidate."""
    lines: list[str] = []
    lines.append('      <section class="source-items">')
    lines.append("        <h4>Source Items</h4>")
    lines.append("        <ol>")
    for item in items:
        lines.extend(_render_source_item(item))
    lines.append("        </ol>")
    lines.append("      </section>")
    return lines


def _render_debug(pc: CRPresentedCandidate) -> list[str]:
    """Render a minimal collapsible debug block (top-level primitives only)."""
    debug_lines: list[str] = []

    sr_debug = pc.score_result.debug
    if sr_debug:
        for k, v in sr_debug.items():
            if isinstance(v, (str, int, float, bool)):
                debug_lines.append(f"score.{k}: {v}")

    dec_debug = pc.decision.debug
    if dec_debug:
        for k, v in dec_debug.items():
            if isinstance(v, (str, int, float, bool)):
                debug_lines.append(f"decision.{k}: {v}")

    lines: list[str] = []
    lines.append('      <details class="debug">')
    lines.append("        <summary>Debug</summary>")
    lines.append(f"        <pre>{_escape_html_text(chr(10).join(debug_lines))}</pre>")
    lines.append("      </details>")
    return lines


def _render_event_identity(identity) -> list[str]:
    """Render audit-only event identity evidence for one candidate.

    Observability only — no dedupe/cooldown enforcement, no dispatch effect.
    Every value is HTML-escaped text content; no anchors/hrefs are added and
    the raw verbose ``cluster_key`` is never emitted (only its fingerprint).
    """
    rows: list[tuple[str, str | None]] = [
        ("Event Key", identity.event_key),
        ("Key Basis", identity.key_basis),
        ("Normalized Title", identity.normalized_title),
        ("Candidate ID (evidence)", identity.candidate_id),
        ("Cluster Key Fingerprint (evidence)", identity.cluster_key_fingerprint),
        ("Title Fingerprint", identity.title_fingerprint),
        ("Platform Fingerprint", identity.platform_fingerprint),
        ("Source Fingerprint", identity.source_fingerprint),
    ]

    lines: list[str] = []
    lines.append('      <section class="event-identity">')
    lines.append("        <h4>Event Identity</h4>")
    lines.append(
        '        <p><em>Identity evidence for future dedupe/cooldown '
        "(PR10b/c); not enforced here.</em></p>"
    )
    lines.append("        <dl>")
    for label, value in rows:
        if value is None:
            continue
        lines.append(
            f"          <dt>{_escape_html_text(label)}</dt>"
            f"<dd>{_escape_html_text(value)}</dd>"
        )
    lines.append("        </dl>")
    lines.append("      </section>")
    return lines


def _render_repeat_preview(preview: CRRepeatPreview) -> list[str]:
    """Render audit-only repeat preview evidence for one candidate."""
    has_prior_level = preview.previous_decision_level is not None
    has_prior_score = preview.previous_score is not None
    rows: list[tuple[str, str | None]] = [
        ("Status", preview.status),
        ("Reason", preview.reason),
        ("Previous Level", preview.previous_decision_level),
        (
            "Current Level",
            preview.current_decision_level if has_prior_level else None,
        ),
        (
            "Previous Score",
            _format_score(preview.previous_score)
            if has_prior_score
            else None,
        ),
        (
            "Current Score",
            _format_score(preview.current_score)
            if has_prior_score and preview.current_score is not None
            else None,
        ),
        ("Previous Seen At", preview.previous_seen_at),
    ]

    lines: list[str] = []
    lines.append('      <section class="repeat-preview">')
    lines.append("        <h4>Repeat Preview</h4>")
    lines.append("        <dl>")
    for label, value in rows:
        if value is None or value == "":
            continue
        lines.append(
            f"          <dt>{_escape_html_text(label)}</dt>"
            f"<dd>{_escape_html_text(value)}</dd>"
        )
    lines.append("        </dl>")
    lines.append("      </section>")
    return lines


def _render_cooldown_decision(decision: CRCooldownDecision) -> list[str]:
    """Render audit-only cooldown policy preview for one candidate.

    Preview of what a cooldown policy *would* decide. No enforcement, no
    dispatch change, no anchors/hrefs; every value is HTML-escaped text.
    """
    rows: list[tuple[str, str | None]] = [
        ("Action", decision.action),
        ("Reason", decision.reason),
        ("Repeat Status", decision.repeat_status),
        (
            "Cooldown Minutes",
            str(decision.cooldown_minutes)
            if decision.cooldown_minutes is not None
            else None,
        ),
    ]

    lines: list[str] = []
    lines.append('      <section class="cooldown-decision">')
    lines.append("        <h4>Cooldown Policy Preview</h4>")
    lines.append("        <dl>")
    for label, value in rows:
        if value is None or value == "":
            continue
        lines.append(
            f"          <dt>{_escape_html_text(label)}</dt>"
            f"<dd>{_escape_html_text(value)}</dd>"
        )
    lines.append("        </dl>")
    lines.append("      </section>")
    return lines


def _format_prior_source_status(
    preview: CREventStateTransitionPreview,
) -> str:
    if preview.prior_snapshot_error is not None:
        return "error"
    if preview.prior_snapshot_loaded is True:
        return "loaded"
    if preview.prior_snapshot_loaded is False:
        return "missing"
    if preview.prior_snapshot_available:
        return "supplied"
    return "not_supplied"


def _render_state_transition_preview(
    preview: CREventStateTransitionPreview,
) -> list[str]:
    """Render run-level state transition preview metadata."""
    next_snapshot_status = (
        "available" if preview.next_snapshot is not None else "suppressed"
    )
    next_entry_count = (
        str(len(preview.next_snapshot.entries))
        if preview.next_snapshot is not None
        else None
    )
    rows: list[tuple[str, str | None]] = [
        ("Prior Source", _format_prior_source_status(preview)),
        (
            "Prior Loaded",
            str(preview.prior_snapshot_loaded)
            if preview.prior_snapshot_loaded is not None
            else None,
        ),
        ("Prior Error", preview.prior_snapshot_error),
        ("Update Count", str(preview.update_count)),
        ("Next Snapshot Preview", next_snapshot_status),
        ("Next Snapshot Entry Count", next_entry_count),
        ("Reason", preview.reason),
    ]

    lines: list[str] = []
    lines.append('    <section class="state-transition-preview">')
    lines.append("      <h4>State Transition Preview</h4>")
    lines.append("      <dl>")
    for label, value in rows:
        if value is None or value == "":
            continue
        lines.append(
            f"        <dt>{_escape_html_text(label)}</dt>"
            f"<dd>{_escape_html_text(value)}</dd>"
        )
    lines.append("      </dl>")
    lines.append("    </section>")

    return lines


def _render_candidate_card(
    view: CRCandidateRenderView,
    config: CRHTMLRenderConfig,
) -> list[str]:
    """Render a single candidate card."""
    pc = view.presented
    lines: list[str] = []
    level = pc.decision_level

    lines.append(
        f'    <article class="candidate-card decision-{_escape_html_attr(level)}" '
        f'id="candidate-{_escape_html_attr(pc.candidate_id)}">'
    )
    lines.append(f"      <h3>{_escape_html_text(pc.display_title)}</h3>")
    lines.append("      <dl>")
    lines.append(
        f"        <dt>Candidate ID</dt><dd>{_escape_html_text(pc.candidate_id)}</dd>"
    )
    lines.append(
        f"        <dt>Cluster Key</dt><dd>{_escape_html_text(pc.cluster_key)}</dd>"
    )
    lines.append(f"        <dt>Decision</dt><dd>{_escape_html_text(level)}</dd>")
    lines.append(
        f"        <dt>Total Score</dt><dd>{_format_score(pc.total_score)}</dd>"
    )

    # Triggers.
    if pc.trigger_reasons:
        triggers = "; ".join(_escape_html_text(r) for r in pc.trigger_reasons)
    else:
        triggers = "score threshold"
    lines.append(f"        <dt>Triggers</dt><dd>{triggers}</dd>")

    # Suppress labels — only when present.
    if pc.suppress_labels:
        labels = "; ".join(_escape_html_text(l) for l in pc.suppress_labels)
        lines.append(f"        <dt>Suppress Labels</dt><dd>{labels}</dd>")

    # Link — only when present.  Unsafe schemes (javascript:, data:, ...)
    # are rendered as plain escaped text without an anchor so the audit
    # trail is preserved.
    if pc.representative_url:
        text = _escape_html_text(pc.representative_url)
        if _is_safe_href(pc.representative_url):
            href = _escape_html_attr(pc.representative_url)
            lines.append(
                f'        <dt>Link</dt><dd><a href="{href}">{text}</a></dd>'
            )
        else:
            lines.append(f"        <dt>Link</dt><dd>{text}</dd>")

    lines.append("      </dl>")

    if config.include_event_identity and view.identity is not None:
        lines.extend(_render_event_identity(view.identity))

    if (
        config.include_repeat_preview
        and view.repeat_preview is not None
    ):
        lines.extend(_render_repeat_preview(view.repeat_preview))

        # Cooldown policy preview (audit-only; no enforcement). Gated on
        # repeat preview being enabled so a preview already exists.
        if (
            config.include_cooldown_decision
            and view.cooldown_decision is not None
        ):
            lines.extend(
                _render_cooldown_decision(view.cooldown_decision)
            )

    if config.include_score_components:
        lines.extend(_render_score_components_table(pc.score_result))

    if config.include_source_items and pc.candidate.source_items:
        lines.extend(_render_source_items(pc.candidate.source_items))

    if config.include_debug:
        lines.extend(_render_debug(pc))

    lines.append("    </article>")
    return lines


def _render_section_body(
    candidates: tuple[CRCandidateRenderView, ...],
    config: CRHTMLRenderConfig,
) -> list[str]:
    """Render the body of a decision section (cards or empty notice)."""
    if not candidates:
        return ["      <p><em>No candidates.</em></p>"]
    lines: list[str] = []
    for view in candidates:
        lines.extend(_render_candidate_card(view, config))
    return lines


def _render_section(
    level: str,
    candidates: tuple[CRCandidateRenderView, ...],
    config: CRHTMLRenderConfig,
) -> list[str]:
    """Render one decision section, optionally collapsing its contents."""
    lines: list[str] = []
    lines.append(
        f'    <section class="decision-section decision-{_escape_html_attr(level)}">'
    )
    lines.append(f"      <h2>{_escape_html_text(level)}</h2>")

    collapse = (level == DECISION_SUPPRESS and config.collapse_suppress) or (
        level == DECISION_WATCH and config.collapse_watch
    )

    if collapse:
        lines.append('      <details class="section-collapse">')
        lines.append(
            f"        <summary>{_escape_html_text(level)} "
            f"({len(candidates)})</summary>"
        )
        lines.extend(_render_section_body(candidates, config))
        lines.append("      </details>")
    else:
        lines.extend(_render_section_body(candidates, config))

    lines.append("    </section>")
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_cr_html_model(
    model: CRAuditRenderModel,
    *,
    config: CRHTMLRenderConfig | None = None,
) -> str:
    """Purely format a precomputed CR audit model as HTML.

    All identity, repeat, cooldown, health, sorting, and grouping work must
    already be represented by ``model``.
    """
    if config is None:
        config = CRHTMLRenderConfig()

    by_level = {
        section.level: section.candidates
        for section in model.sections
    }

    title_text = _escape_html_text(config.title)

    lines: list[str] = []
    lines.append("<!doctype html>")
    lines.append('<html lang="en">')
    lines.append("<head>")
    lines.append('  <meta charset="utf-8">')
    lines.append('  <meta name="viewport" content="width=device-width, initial-scale=1">')
    lines.append(f"  <title>{title_text}</title>")
    lines.append(f"  <style>{_STYLE}</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append("  <main>")
    lines.append(f"    <h1>{title_text}</h1>")
    lines.append('    <section class="run-meta">')
    lines.append(
        f"      <p><strong>Run:</strong> "
        f"{_escape_html_text(model.run_label)}</p>"
    )
    lines.append(
        f"      <p><strong>Candidates:</strong> "
        f"{len(model.candidates)}</p>"
    )
    lines.append(
        "      <p><strong>High-score suppressed candidates:</strong> "
        f"{model.high_score_suppressed_count}</p>"
    )
    lines.append("    </section>")

    if model.input_health is not None:
        health = model.input_health
        snapshot = health["snapshot"]
        reasons = ", ".join(health["reasons"]) or "none"
        warnings = ", ".join(health["warnings"]) or "none"
        generated_at = snapshot["generated_at"] or "unknown"
        age_minutes = (
            snapshot["age_minutes"]
            if snapshot["age_minutes"] is not None
            else "unknown"
        )
        lines.append('    <section class="input-health">')
        lines.append("      <h2>Input Health</h2>")
        lines.append(f"      <p><strong>Status:</strong> {_escape_html_text(health['status'])}</p>")
        lines.append(f"      <p><strong>Reasons:</strong> {_escape_html_text(reasons)}</p>")
        lines.append(
            "      <p><strong>Snapshot:</strong> "
            f"{_escape_html_text(generated_at)}; "
            f"age={_escape_html_text(age_minutes)} minutes; "
            f"historical={_escape_html_text(snapshot['historical_data_reused'])}</p>"
        )
        hotlist_ratio = health["hotlist"]["success_ratio"]
        rss_ratio = health["rss"]["success_ratio"]
        lines.append(
            "      <p><strong>Source ratios:</strong> hotlist="
            f"{_escape_html_text(hotlist_ratio if hotlist_ratio is not None else 'unknown')}; rss="
            f"{_escape_html_text(rss_ratio if rss_ratio is not None else 'unknown')}</p>"
        )
        recovery = health["recovery"]
        recovered_hotlist = ", ".join(health["hotlist"]["recovered_ids"]) or "none"
        recovered_rss = ", ".join(health["rss"]["recovered_ids"]) or "none"
        lines.append(
            "      <p><strong>Recovery:</strong> state="
            f"{_escape_html_text(recovery['state_status'])}; "
            f"hotlist={_escape_html_text(recovered_hotlist)}; "
            f"rss={_escape_html_text(recovered_rss)}</p>"
        )
        lines.append(f"      <p><strong>Warnings:</strong> {_escape_html_text(warnings)}</p>")
        lines.append("    </section>")

    if (
        config.include_state_transition_preview
        and model.state_transition_preview is not None
    ):
        lines.extend(
            _render_state_transition_preview(
                model.state_transition_preview
            )
        )

    for level in _SECTION_ORDER:
        lines.extend(_render_section(level, by_level[level], config))

    lines.append("  </main>")
    lines.append("</body>")
    lines.append("</html>")

    return "\n".join(lines)


def render_cr_html_audit(
    candidates: list[CRPresentedCandidate],
    *,
    run_label: str,
    config: CRHTMLRenderConfig | None = None,
    urgent_threshold: float = 80.0,
) -> str:
    """Compatibility façade that prepares evidence before pure rendering."""
    if config is None:
        config = CRHTMLRenderConfig()
    model = build_cr_audit_render_model(
        candidates,
        run_label=run_label,
        urgent_threshold=urgent_threshold,
        include_event_identity=config.include_event_identity,
        include_repeat_preview=config.include_repeat_preview,
        seen_event_states=config.seen_event_states,
        include_cooldown_decision=config.include_cooldown_decision,
        cooldown_policy=config.cooldown_policy,
        input_health=config.input_health,
        state_transition_preview=config.state_transition_preview,
    )
    return render_cr_html_model(model, config=config)
