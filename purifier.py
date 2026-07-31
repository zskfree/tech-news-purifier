#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import time

from tech_news_purifier.config import Settings
from tech_news_purifier.database import (
    database,
    get_recent_candidates,
    migrate,
    save_error,
    save_result,
    should_process,
)
from tech_news_purifier.fetcher import (
    article_content_hash,
    canonicalize_url,
    fetch_all_articles,
    is_duplicate,
)
from tech_news_purifier.llm import PURIFY_PROMPT_VERSION, LLMClient, LLMError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger("purifier")


async def run() -> int:
    started = time.monotonic()
    settings = Settings.from_env()
    with database(settings.db_path) as conn:
        migrate(conn)
        recent = get_recent_candidates(conn)

    articles, fetch_errors = await fetch_all_articles()
    for error in fetch_errors:
        LOGGER.warning("feed_error=%s", error)
    LOGGER.info("fetched=%d failed_sources=%d", len(articles), len(fetch_errors))

    unique = []
    current_candidates = list(recent)
    with database(settings.db_path) as conn:
        for article in articles:
            if not should_process(
                conn, article.article_id, prompt_version=PURIFY_PROMPT_VERSION
            ):
                continue
            if is_duplicate(article, current_candidates):
                LOGGER.info("duplicate article_id=%s title=%r", article.article_id, article.title)
                continue
            unique.append(article)
            current_candidates.append(
                {
                    "title": article.title,
                    "canonical_url": canonicalize_url(article.link),
                    "content_hash": article_content_hash(article),
                }
            )

    stats = {"KEEP": 0, "DISCARD": 0, "ERROR": 0}
    async with LLMClient(settings) as llm:
        tasks = [llm.purify(article) for article in unique]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    with database(settings.db_path) as conn:
        for article, outcome in zip(unique, results, strict=True):
            canonical = canonicalize_url(article.link)
            digest = article_content_hash(article)
            if isinstance(outcome, BaseException):
                attempts = outcome.attempts if isinstance(outcome, LLMError) else 1
                save_error(
                    conn,
                    article,
                    str(outcome),
                    canonical_url=canonical,
                    content_hash=digest,
                    attempts=attempts,
                )
                stats["ERROR"] += 1
                continue
            result, attempts = outcome
            save_result(
                conn,
                article,
                result,
                canonical_url=canonical,
                content_hash=digest,
                attempts=attempts,
            )
            stats[result.decision.upper()] += 1

    LOGGER.info(
        "completed new=%d keep=%d discard=%d error=%d duration_seconds=%.2f",
        len(unique),
        stats["KEEP"],
        stats["DISCARD"],
        stats["ERROR"],
        time.monotonic() - started,
    )
    return 0 if not (fetch_errors and not articles) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
