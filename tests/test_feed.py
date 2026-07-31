import json
import xml.etree.ElementTree as ET

import pytest

from tech_news_purifier.feed import (
    NS,
    build_feed,
    feed_has_guid,
    format_duration,
    migrate_feed_base,
    safe_url,
    write_chapters,
)
from tech_news_purifier.models import KeptArticle


def sample_article(link: str = "https://example.com/a") -> KeptArticle:
    return KeptArticle(
        source="RSS <source>",
        title='Title <script>alert("x")</script>',
        link=link,
        summary="Summary <b>not markup</b>",
        reason="reason",
        category="systems",
        quality_score=8,
        created_at="2026-07-30 00:00:00",
    )


def test_feed_is_valid_safe_xml_with_chapters(tmp_path) -> None:
    output = tmp_path / "feed.xml"
    build_feed(
        output,
        previous_feed_path=output,
        server_base_url="http://47.115.165.231:23654",
        date_str="2026-07-30",
        audio_filename="2026-07-30-12345678.mp3",
        audio_size=123,
        duration_seconds=1200,
        chapter_filename="2026-07-30-12345678.json",
        articles=[sample_article()],
        script_text="script <unsafe>",
    )
    root = ET.parse(output).getroot()
    item = root.find("./channel/item")
    assert item is not None
    chapters = item.find(f"{{{NS['podcast']}}}chapters")
    assert chapters is not None
    assert chapters.attrib["type"] == "application/json+chapters"
    assert chapters.attrib["url"].startswith("http://47.115.165.231:23654/")
    assert feed_has_guid(output, "geek-news-2026-07-30")
    assert not feed_has_guid(output, "geek-news-2026-07-29")
    encoded = item.findtext(f"{{{NS['content']}}}encoded", default="")
    assert "<script>" not in encoded
    assert format_duration(1200) == "20:00"


def test_chapters_must_begin_at_zero(tmp_path) -> None:
    path = tmp_path / "chapters.json"
    write_chapters(path, [{"startTime": 0, "title": "开始"}])
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == "1.2.0"
    with pytest.raises(ValueError):
        write_chapters(path, [{"startTime": 1, "title": "错误"}])


def test_feed_rejects_non_https_article_url(tmp_path) -> None:
    with pytest.raises(ValueError):
        build_feed(
            tmp_path / "feed.xml",
            previous_feed_path=tmp_path / "missing.xml",
            server_base_url="http://47.115.165.231:23654",
            date_str="2026-07-30",
            audio_filename="a.mp3",
            audio_size=1,
            duration_seconds=1200,
            chapter_filename="a.json",
            articles=[sample_article("javascript:alert(1)")],
            script_text="script",
        )


def test_safe_url_requires_https() -> None:
    with pytest.raises(ValueError):
        safe_url("http://example.com")
    assert safe_url("http://example.com", require_https=False) == "http://example.com"


def test_migrate_existing_feed_to_new_port(tmp_path) -> None:
    path = tmp_path / "feed.xml"
    path.write_text(
        """<?xml version="1.0"?><rss><channel>
        <link>http://47.115.165.231/feed.xml</link>
        <image><url>http://47.115.165.231/cover.png</url>
        <link>http://47.115.165.231/feed.xml</link></image>
        <item><enclosure url="http://47.115.165.231/audio/old.mp3"/></item>
        </channel></rss>""",
        encoding="utf-8",
    )
    migrate_feed_base(path, "http://47.115.165.231:23654")
    xml = path.read_text(encoding="utf-8")
    assert "http://47.115.165.231:23654/audio/old.mp3" in xml
    assert "http://47.115.165.231:23654/cover.png" in xml
    assert "http://47.115.165.231/feed.xml" not in xml
