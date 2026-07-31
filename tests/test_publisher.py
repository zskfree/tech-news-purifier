import json
import os
import time
import xml.etree.ElementTree as ET

import pytest

from tech_news_purifier.feed import NS
from tech_news_purifier.publisher import cleanup_orphans, publish_episode


def staged_episode(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    audio = staging / "2026-07-31-12345678.mp3"
    audio.write_bytes(b"a" * 50_001)
    chapters = staging / "2026-07-31-12345678.json"
    chapters.write_text(
        json.dumps(
            {
                "version": "1.2.0",
                "chapters": [
                    {"startTime": 0, "title": "开场"},
                    {"startTime": 10.5, "title": "正文"},
                ],
            }
        ),
        encoding="utf-8",
    )
    feed = staging / "feed.xml"
    rss = ET.Element("rss")
    channel = ET.SubElement(rss, "channel")
    item = ET.SubElement(channel, "item")
    ET.SubElement(
        item,
        "enclosure",
        {"url": f"http://47.115.165.231:23654/audio/{audio.name}"},
    )
    ET.SubElement(
        item,
        f"{{{NS['podcast']}}}chapters",
        {"url": f"http://47.115.165.231:23654/chapters/{chapters.name}"},
    )
    ET.ElementTree(rss).write(feed, encoding="utf-8", xml_declaration=True)
    return audio, chapters, feed


def test_publish_failure_keeps_old_feed_and_removes_new_resources(tmp_path, monkeypatch) -> None:
    audio, chapters, feed = staged_episode(tmp_path)
    audio_dir = tmp_path / "public" / "audio"
    chapters_dir = tmp_path / "public" / "chapters"
    audio_dir.mkdir(parents=True)
    chapters_dir.mkdir(parents=True)
    live_feed = tmp_path / "public" / "feed.xml"
    live_feed.write_text("old-feed", encoding="utf-8")
    real_replace = os.replace

    def fail_feed(source, destination):
        if os.fspath(source) == os.fspath(feed):
            raise OSError("injected feed failure")
        real_replace(source, destination)

    monkeypatch.setattr("tech_news_purifier.publisher.os.replace", fail_feed)
    with pytest.raises(OSError):
        publish_episode(
            staged_audio=audio,
            staged_chapters=chapters,
            staged_feed=feed,
            audio_dir=audio_dir,
            chapters_dir=chapters_dir,
            feed_path=live_feed,
        )
    assert live_feed.read_text(encoding="utf-8") == "old-feed"
    assert not any(audio_dir.iterdir())
    assert not any(chapters_dir.iterdir())


def test_cleanup_only_removes_old_unreferenced_resources(tmp_path) -> None:
    audio, chapters, feed = staged_episode(tmp_path)
    public = tmp_path / "public"
    audio_dir = public / "audio"
    chapters_dir = public / "chapters"
    audio_dir.mkdir(parents=True)
    chapters_dir.mkdir(parents=True)
    referenced_audio = audio_dir / audio.name
    referenced_audio.write_bytes(audio.read_bytes())
    orphan = audio_dir / "old.mp3"
    orphan.write_bytes(b"old")
    old_time = time.time() - 8 * 86400
    os.utime(orphan, (old_time, old_time))
    live_feed = public / "feed.xml"
    live_feed.write_bytes(feed.read_bytes())
    removed = cleanup_orphans(live_feed, audio_dir, chapters_dir, now=time.time())
    assert removed == [orphan]
    assert referenced_audio.exists()
