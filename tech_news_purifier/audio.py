from __future__ import annotations

import asyncio
import contextlib
import re
import subprocess
import tempfile
from pathlib import Path

import edge_tts

from .config import Settings


def validate_duration(seconds: float, minimum: int, maximum: int) -> float:
    if not minimum <= seconds <= maximum:
        raise ValueError(f"音频时长 {seconds:.3f} 秒不在 {minimum}-{maximum} 秒范围")
    return seconds


def clean_tts_text(text: str) -> str:
    value = re.sub(r"<[^>]+>", "", text)
    value = re.sub(r"[*#`_<>\\/]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def split_text(text: str, max_length: int = 280) -> list[str]:
    sentences = re.split(r"(?<=[。！？\n])", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_length:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:max_length])
            sentence = sentence[max_length:]
        candidate = f"{current} {sentence}".strip()
        if len(candidate) > max_length and current:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _concat_mp3(inputs: list[Path], output: Path) -> None:
    if not inputs:
        raise RuntimeError("没有可拼接的音频片段")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", dir=output.parent, delete=False
    ) as handle:
        list_path = Path(handle.name)
        for path in inputs:
            escaped = str(path.resolve()).replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "22050",
                "-b:a",
                "24k",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        list_path.unlink(missing_ok=True)


async def synthesize_text(text: str, output: Path, settings: Settings) -> float:
    chunks = split_text(clean_tts_text(text))
    if not chunks:
        raise RuntimeError("TTS 文本为空")
    output.parent.mkdir(parents=True, exist_ok=True)
    voices = [settings.tts_voice, settings.tts_fallback_voice, "zh-CN-YunjianNeural"]
    with tempfile.TemporaryDirectory(prefix="tts-", dir=output.parent) as temp_name:
        temp_dir = Path(temp_name)
        chunk_paths: list[Path] = []
        for index, chunk in enumerate(chunks):
            chunk_path = temp_dir / f"{index:04d}.mp3"
            completed = False
            last_error: Exception | None = None
            for voice in voices:
                for attempt in range(3):
                    try:
                        await edge_tts.Communicate(chunk, voice, rate="+0%").save(str(chunk_path))
                        if chunk_path.exists() and chunk_path.stat().st_size > 500:
                            completed = True
                            break
                    except Exception as exc:  # edge-tts exposes transport-specific errors
                        last_error = exc
                    chunk_path.unlink(missing_ok=True)
                    await asyncio.sleep(0.5 * (attempt + 1))
                if completed:
                    break
            if not completed:
                raise RuntimeError(f"TTS 片段 {index + 1} 生成失败: {last_error}")
            chunk_paths.append(chunk_path)
        temp_output = temp_dir / "combined.mp3"
        _concat_mp3(chunk_paths, temp_output)
        output.write_bytes(temp_output.read_bytes())
    if output.stat().st_size < 50_000:
        output.unlink(missing_ok=True)
        raise RuntimeError("最终音频文件异常偏小")
    return probe_duration(output)


def concatenate_segments(inputs: list[Path], output: Path) -> float:
    temp_output = output.with_suffix(".tmp.mp3")
    try:
        _concat_mp3(inputs, temp_output)
        if temp_output.stat().st_size < 50_000:
            raise RuntimeError("拼接后的音频文件异常偏小")
        temp_output.replace(output)
        return probe_duration(output)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_output.unlink()
