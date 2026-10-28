"""Parse public Telegram previews and X profiles without login or JavaScript execution.

An empty/login/challenge page is an error, not a healthy zero-item crawl.
Only the requested account's posts are emitted; quoted posts stay in context.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

from .parser import ParsedRSSItem


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def find(self, *, tag=None, cls=None):
        for child in self.children:
            if not isinstance(child, _Node):
                continue
            if (tag is None or child.tag == tag) and (
                cls is None or cls in child.attrs.get("class", "").split()
            ):
                yield child
            yield from child.find(tag=tag, cls=cls)

    def text(self):
        if self.tag in {"script", "style"}:
            return ""
        if self.tag == "br":
            return "\n"
        return "".join(c.text() if isinstance(c, _Node) else c for c in self.children)


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def account_name(url, source_type):
    """Validate the origin before any request, including bounded pagination."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("Public source requires a canonical HTTPS account URL")
    path = parsed.path.rstrip("/")
    if source_type == "telegram_html":
        valid_host = parsed.hostname == "t.me"
        match = re.fullmatch(r"/s/([A-Za-z][A-Za-z0-9_]{3,31})", path)
    else:
        valid_host = parsed.hostname in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}
        match = re.fullmatch(r"/([A-Za-z0-9_]{1,15})", path)
    if not valid_host or not match or parsed.query or parsed.fragment:
        raise ValueError("Public source requires a canonical account URL without query parameters")
    return match[1]


def _clean(text):
    return re.sub(r"[ \t\r\f\v]+", " ", unescape(text)).strip()


def _item(body, url, author, published_at, references=()):
    body = _clean(body)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    title = (lines[0] if lines else "图片或视频消息")[:200]
    refs = list(dict.fromkeys(references))[:2]
    suffix = "\n关联原文：" + " ".join(refs) if refs else ""
    return ParsedRSSItem(
        title=title, url=url, guid=url, author=author,
        published_at=published_at,
        summary=body[:max(0, 500 - len(suffix))] + suffix,
    )


def parse_telegram_html(content, url):
    channel = account_name(url, "telegram_html")
    doc = _Document(); doc.feed(content)
    items = {}
    for message in doc.root.find(cls="tgme_widget_message"):
        post = message.attrs.get("data-post", "")
        if not re.fullmatch(re.escape(channel) + r"/\d+", post, re.I):
            continue
        dates = list(message.find(cls="tgme_widget_message_date"))
        times = list(dates[0].find(tag="time")) if dates else []
        timestamp = times[0].attrs.get("datetime", "") if times else ""
        try:
            stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError
        except ValueError:
            raise ValueError("Telegram message is missing a valid timezone-aware timestamp") from None
        texts = list(message.find(cls="tgme_widget_message_text"))
        text = texts[0].text() if texts else ""
        references = []
        for anchor in texts[0].find(tag="a") if texts else ():
            href = anchor.attrs.get("href", "")
            if re.fullmatch(r"https://(?:x\.com|twitter\.com)/[A-Za-z0-9_]+/status/\d+", href):
                references.append(href.replace("https://twitter.com/", "https://x.com/"))
        canonical = "https://t.me/" + post
        item = _item(text, canonical, channel, stamp.astimezone(timezone.utc).isoformat(), references)
        # Albums can repeat an ID; retain the caption-bearing version.
        if canonical not in items or len(item.summary) > len(items[canonical].summary):
            items[canonical] = item
    if not items:
        raise ValueError("Telegram public preview contained no valid messages (unavailable channel or changed markup)")
    cursors = [int(n.attrs["data-before"]) for n in doc.root.find(tag="a") if n.attrs.get("data-before", "").isdigit()]
    cursor = min(cursors) if cursors else None
    return sorted(items.values(), key=lambda item: item.published_at, reverse=True), cursor


def _tweet_results(value):
    """Walk timeline containers without promoting quoted/retweeted posts."""
    if isinstance(value, dict):
        if isinstance(value.get("tweet_results"), dict):
            yield value["tweet_results"].get("result", {})
        for key, child in value.items():
            if key not in {"tweet_results", "quoted_tweet_results", "retweeted_status_result"}:
                yield from _tweet_results(child)
    elif isinstance(value, list):
        for child in value:
            yield from _tweet_results(child)


def parse_x_public_html(content, url):
    handle = account_name(url, "x_public_html")
    doc = _Document(); doc.feed(content)
    decoder = json.JSONDecoder(); items = {}
    for script in doc.root.find(tag="script"):
        text = "".join(c for c in script.children if isinstance(c, str))
        if "GraphQLRequestStream.Completed" not in text:
            continue
        # Decode JSON string literals only. Never eval the site's JavaScript.
        for match in re.finditer(r"\bvalue\s*:\s*", text):
            try:
                encoded, _ = decoder.raw_decode(text, match.end())
                payload = json.loads(encoded) if isinstance(encoded, str) else None
            except (ValueError, TypeError):
                continue
            for result in _tweet_results(payload):
                if not isinstance(result, dict):
                    continue
                result = result.get("tweet", result)
                if not isinstance(result, dict):
                    continue
                user = result.get("core", {}).get("user_results", {}).get("result", {})
                owner = user.get("core", {}).get("screen_name") or user.get("legacy", {}).get("screen_name", "")
                if owner.lower() != handle.lower():
                    continue
                post_id = result.get("rest_id", "")
                details = result.get("details") or result.get("legacy") or {}
                note = result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
                body = note.get("text") or details.get("full_text", "")
                if not str(post_id).isdigit() or not body:
                    continue
                millis = details.get("created_at_ms")
                try:
                    stamp = datetime.fromtimestamp(int(millis) / 1000, timezone.utc)
                except (ValueError, TypeError, OverflowError, OSError):
                    continue
                canonical = f"https://x.com/{handle}/status/{post_id}"
                items[canonical] = _item(body, canonical, handle, stamp.isoformat())
    if not items:
        raise ValueError("X public profile contained no parseable posts (login/challenge page or changed markup)")
    # An old pinned post must not displace current posts when max_items is applied.
    return sorted(items.values(), key=lambda item: item.published_at, reverse=True)
