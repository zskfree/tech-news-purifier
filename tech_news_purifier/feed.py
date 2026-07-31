from __future__ import annotations

import copy
import html
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlsplit

from .models import KeptArticle

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "podcast": "https://podcastindex.org/namespace/1.0",
    "atom": "http://www.w3.org/2005/Atom",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def safe_url(url: str, *, require_https: bool = True) -> str:
    value = url.strip()
    parsed = urlsplit(value)
    allowed = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in allowed or not parsed.netloc:
        raise ValueError(f"不安全的 URL: {url!r}")
    return value


def format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def write_chapters(path: Path, chapters: list[dict[str, object]]) -> None:
    if not chapters or chapters[0].get("startTime") != 0:
        raise ValueError("章节必须从 0 秒开始")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": "1.2.0", "chapters": chapters}
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2).encode())


def _text(parent: ET.Element, tag: str, value: str, **attrs: str) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs)
    node.text = value
    return node


def _old_items(feed_path: Path, current_guid: str) -> list[ET.Element]:
    if not feed_path.exists():
        return []
    try:
        channel = ET.parse(feed_path).getroot().find("channel")
    except ET.ParseError:
        return []
    if channel is None:
        return []
    items: list[ET.Element] = []
    for item in channel.findall("item"):
        guid = item.findtext("guid", default="")
        if guid != current_guid:
            items.append(copy.deepcopy(item))
    return items[:29]


def feed_has_guid(feed_path: Path, guid: str) -> bool:
    if not feed_path.exists():
        return False
    try:
        channel = ET.parse(feed_path).getroot().find("channel")
    except (ET.ParseError, OSError):
        return False
    return channel is not None and any(
        item.findtext("guid", default="") == guid for item in channel.findall("item")
    )


def build_feed(
    output_path: Path,
    *,
    previous_feed_path: Path,
    server_base_url: str,
    date_str: str,
    audio_filename: str,
    audio_size: int,
    duration_seconds: float,
    chapter_filename: str,
    articles: list[KeptArticle],
    script_text: str,
) -> None:
    base = safe_url(server_base_url.rstrip("/"), require_https=False)
    audio_url = safe_url(f"{base}/audio/{audio_filename}", require_https=False)
    chapters_url = safe_url(f"{base}/chapters/{chapter_filename}", require_https=False)
    cover_url = safe_url(f"{base}/cover.png", require_https=False)
    feed_url = safe_url(f"{base}/feed.xml", require_https=False)
    guid = f"geek-news-{date_str}"

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    _text(channel, "title", "极客早报 | AI 自动精选技术播客")
    _text(channel, "link", base)
    _text(channel, "description", "每日 20 分钟硬核技术资讯、开源项目与架构突破听报。")
    _text(channel, "language", "zh-cn")
    _text(channel, "copyright", "Copyright 2026 Tech News Purifier")
    _text(channel, f"{{{NS['itunes']}}}author", "Tech News Purifier Engine")
    _text(channel, f"{{{NS['itunes']}}}explicit", "false")
    ET.SubElement(channel, f"{{{NS['itunes']}}}image", {"href": cover_url})
    ET.SubElement(
        channel,
        f"{{{NS['atom']}}}link",
        {"href": feed_url, "rel": "self", "type": "application/rss+xml"},
    )
    category = ET.SubElement(channel, f"{{{NS['itunes']}}}category", {"text": "Technology"})
    ET.SubElement(category, f"{{{NS['itunes']}}}category", {"text": "Tech News"})

    item = ET.SubElement(channel, "item")
    _text(item, "title", f"极客早报 | {date_str} 20分钟硬核技术深度精选")
    short_description = f"本期精选 {len(articles)} 篇技术资讯，覆盖 AI、开源与系统架构。"
    _text(item, "description", short_description)
    _text(item, "pubDate", format_datetime(datetime.now(UTC), usegmt=True))
    _text(item, "guid", guid, isPermaLink="false")
    ET.SubElement(
        item,
        "enclosure",
        {"url": audio_url, "length": str(audio_size), "type": "audio/mpeg"},
    )
    _text(item, f"{{{NS['itunes']}}}duration", format_duration(duration_seconds))
    _text(item, f"{{{NS['itunes']}}}explicit", "false")
    ET.SubElement(item, f"{{{NS['itunes']}}}image", {"href": cover_url})
    ET.SubElement(
        item,
        f"{{{NS['podcast']}}}chapters",
        {"url": chapters_url, "type": "application/json+chapters"},
    )

    sections = [
        f"<h2>{html.escape(date_str)} 极客早报</h2>",
        f"<p>{html.escape(script_text[:400])}…</p>",
        "<h3>本期资讯</h3><ul>",
    ]
    for article in articles:
        link = safe_url(article.link, require_https=False)
        sections.append(
            "<li><strong>"
            + html.escape(f"[{article.source}] {article.title}")
            + "</strong><br>"
            + html.escape(article.summary)
            + f'<br><a href="{html.escape(link, quote=True)}">阅读原文</a></li>'
        )
    sections.append("</ul>")
    _text(item, f"{{{NS['content']}}}encoded", "".join(sections))

    for old_item in _old_items(previous_feed_path, guid):
        channel.append(old_item)

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    with tempfile.NamedTemporaryFile("wb", dir=output_path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        tree.write(handle, encoding="utf-8", xml_declaration=True)
    try:
        ET.parse(temp_path)
        os.chmod(temp_path, 0o640)
        os.replace(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temp_path, 0o640)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def migrate_feed_base(feed_path: Path, server_base_url: str) -> None:
    """Rewrite all locally hosted Feed URLs to a new validated HTTP(S) base."""
    base = safe_url(server_base_url.rstrip("/"), require_https=False)
    root = ET.parse(feed_path).getroot()
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Feed 缺少 channel")

    def local_url(value: str) -> str:
        parsed = urlsplit(value)
        path = parsed.path
        if path == "/feed.xml" or path == "/cover.png" or path.startswith(
            ("/audio/", "/chapters/")
        ):
            return f"{base}{path}"
        return value

    link = channel.find("link")
    if link is not None:
        link.text = base
    for node in root.iter():
        if node.text and (
            node.tag in {"link", "url"} or node.tag.endswith(("}link", "}url"))
        ):
            node.text = local_url(node.text)
        for attribute in ("url", "href"):
            if attribute in node.attrib:
                node.attrib[attribute] = local_url(node.attrib[attribute])

    # Validate every rewritten hosted URL before replacing the live Feed.
    for node in root.iter():
        for attribute in ("url", "href"):
            value = node.attrib.get(attribute)
            if value:
                safe_url(value, require_https=False)
    ET.indent(root, space="  ")
    with tempfile.NamedTemporaryFile("wb", dir=feed_path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        ET.ElementTree(root).write(handle, encoding="utf-8", xml_declaration=True)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        ET.parse(temp_path)
        os.chmod(temp_path, 0o640)
        os.replace(temp_path, feed_path)
    finally:
        temp_path.unlink(missing_ok=True)
