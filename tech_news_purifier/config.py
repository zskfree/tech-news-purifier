from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path
    podcast_dir: Path
    one_api_url: str
    one_api_key: str
    server_base_url: str
    primary_model: str
    fallback_model: str
    target_min_seconds: int
    target_max_seconds: int
    tts_voice: str
    tts_fallback_voice: str
    max_ai_concurrency: int
    ai_request_interval_seconds: float
    min_quality_score: int
    max_episode_articles: int
    min_episode_articles: int
    force_regenerate: bool

    @classmethod
    def from_env(cls, *, require_api_key: bool = True) -> Settings:
        load_dotenv()
        key = os.environ.get("ONE_API_KEY", "").strip()
        if require_api_key and not key:
            raise RuntimeError("环境变量 ONE_API_KEY 未设置，请参考 .env.example。")
        return cls(
            db_path=Path(os.environ.get("DB_PATH", "/var/lib/tech-news-purifier/news.db")),
            podcast_dir=Path(os.environ.get("PODCAST_DIR", "/var/lib/tech-news-purifier/podcast")),
            one_api_url=os.environ.get("ONE_API_URL", "http://127.0.0.1:3000/v1/chat/completions"),
            one_api_key=key,
            server_base_url=os.environ.get(
                "SERVER_BASE_URL", "http://47.115.165.231:23654"
            ).rstrip("/"),
            primary_model=os.environ.get("PRIMARY_MODEL", "gemini-3.6-flash"),
            fallback_model=os.environ.get("FALLBACK_MODEL", "gemini-3.5-flash-lite"),
            target_min_seconds=int(os.environ.get("TARGET_MIN_SECONDS", "1080")),
            target_max_seconds=int(os.environ.get("TARGET_MAX_SECONDS", "1320")),
            tts_voice=os.environ.get("TTS_VOICE", "zh-CN-YunxiNeural"),
            tts_fallback_voice=os.environ.get("TTS_FALLBACK_VOICE", "zh-CN-XiaoxiaoNeural"),
            max_ai_concurrency=int(os.environ.get("MAX_AI_CONCURRENCY", "3")),
            ai_request_interval_seconds=float(
                os.environ.get("AI_REQUEST_INTERVAL_SECONDS", "10.2")
            ),
            min_quality_score=int(os.environ.get("MIN_QUALITY_SCORE", "7")),
            max_episode_articles=int(os.environ.get("MAX_EPISODE_ARTICLES", "10")),
            min_episode_articles=int(os.environ.get("MIN_EPISODE_ARTICLES", "3")),
            force_regenerate=os.environ.get("FORCE_REGENERATE", "false").lower()
            in {"1", "true", "yes"},
        )

    @property
    def audio_dir(self) -> Path:
        return self.podcast_dir / "audio"

    @property
    def chapters_dir(self) -> Path:
        return self.podcast_dir / "chapters"

    @property
    def feed_path(self) -> Path:
        return self.podcast_dir / "feed.xml"
