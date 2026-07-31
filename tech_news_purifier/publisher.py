from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit


def _same_file(left: Path, right: Path) -> bool:
    return left.read_bytes() == right.read_bytes()


def _validate_staged(
    audio: Path,
    chapters: Path,
    feed: Path,
    *,
    audio_filename: str,
    chapter_filename: str,
) -> None:
    if not audio.is_file() or audio.stat().st_size < 50_000:
        raise ValueError("待发布音频不存在或异常偏小")
    chapter_data = json.loads(chapters.read_text(encoding="utf-8"))
    chapter_rows = chapter_data.get("chapters")
    if not isinstance(chapter_rows, list) or not chapter_rows:
        raise ValueError("章节文件为空")
    starts = [row.get("startTime") for row in chapter_rows if isinstance(row, dict)]
    if len(starts) != len(chapter_rows) or starts[0] != 0:
        raise ValueError("章节时间非法")
    if any(not isinstance(value, (int, float)) for value in starts):
        raise ValueError("章节时间必须是数字")
    if any(current <= previous for previous, current in zip(starts, starts[1:], strict=False)):
        raise ValueError("章节时间必须严格递增")
    root = ET.parse(feed).getroot()
    enclosure = root.find("./channel/item/enclosure")
    enclosure_name = (
        Path(urlsplit(enclosure.attrib.get("url", "")).path).name if enclosure is not None else ""
    )
    if enclosure is None or enclosure_name != audio_filename:
        raise ValueError("Feed 未引用待发布音频")
    chapter_nodes = [node for node in root.iter() if node.tag.endswith("}chapters")]
    chapter_name = (
        Path(urlsplit(chapter_nodes[0].attrib.get("url", "")).path).name
        if chapter_nodes
        else ""
    )
    if not chapter_nodes or chapter_name != chapter_filename:
        raise ValueError("Feed 未引用待发布章节")


def publish_episode(
    *,
    staged_audio: Path,
    staged_chapters: Path,
    staged_feed: Path,
    audio_dir: Path,
    chapters_dir: Path,
    feed_path: Path,
) -> tuple[Path, Path]:
    """Commit immutable resources first and Feed last; clean this batch on failure."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir.mkdir(parents=True, exist_ok=True)
    final_audio = audio_dir / staged_audio.name
    final_chapters = chapters_dir / staged_chapters.name
    _validate_staged(
        staged_audio,
        staged_chapters,
        staged_feed,
        audio_filename=final_audio.name,
        chapter_filename=final_chapters.name,
    )
    created: list[Path] = []
    try:
        for staged, final in (
            (staged_audio, final_audio),
            (staged_chapters, final_chapters),
        ):
            if final.exists():
                if not _same_file(staged, final):
                    raise FileExistsError(f"不可变资源冲突：{final}")
                staged.unlink()
            else:
                os.replace(staged, final)
                created.append(final)
        os.replace(staged_feed, feed_path)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return final_audio, final_chapters


def cleanup_orphans(
    feed_path: Path,
    audio_dir: Path,
    chapters_dir: Path,
    *,
    minimum_age_days: int = 7,
    now: float | None = None,
) -> list[Path]:
    """Remove old hashed resources not referenced by the current Feed."""
    if not feed_path.exists():
        return []
    referenced: set[str] = set()
    root = ET.parse(feed_path).getroot()
    for node in root.iter():
        for attribute in ("url", "href"):
            value = node.attrib.get(attribute)
            if value:
                referenced.add(Path(urlsplit(value).path).name)
    cutoff = (now if now is not None else time.time()) - minimum_age_days * 86400
    removed: list[Path] = []
    for directory, suffix in ((audio_dir, ".mp3"), (chapters_dir, ".json")):
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if (
                path.is_file()
                and path.suffix == suffix
                and path.name not in referenced
                and path.stat().st_mtime < cutoff
            ):
                path.unlink()
                removed.append(path)
    return removed
