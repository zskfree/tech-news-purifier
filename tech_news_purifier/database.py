from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Article, KeptArticle, PurificationResult

SCHEMA_VERSION = 3


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def database(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            purified_content TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ERROR',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    existing = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
    additions = {
        "canonical_url": "TEXT NOT NULL DEFAULT ''",
        "content_hash": "TEXT NOT NULL DEFAULT ''",
        "category": "TEXT NOT NULL DEFAULT 'systems'",
        "quality_score": "INTEGER NOT NULL DEFAULT 0",
        "reason": "TEXT NOT NULL DEFAULT ''",
        "model_used": "TEXT NOT NULL DEFAULT ''",
        "prompt_version": "TEXT NOT NULL DEFAULT 'v3-objective-concise'",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "last_error": "TEXT NOT NULL DEFAULT ''",
        "next_retry_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
    }
    for name, declaration in additions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {name} {declaration}")
    conn.execute(
        "UPDATE articles SET prompt_version='legacy' "
        "WHERE quality_score=0 AND model_used='' "
        "AND status IN ('KEEP', 'DISCARD')"
    )
    conn.execute(
        "UPDATE articles SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_status_created_at "
        "ON articles(status, created_at DESC)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_canonical_url ON articles(canonical_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_content_hash ON articles(content_hash)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def get_recent_candidates(conn: sqlite3.Connection, days: int = 7) -> list[sqlite3.Row]:
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return list(
        conn.execute(
            "SELECT id, title, canonical_url, content_hash FROM articles WHERE created_at >= ?",
            (cutoff,),
        )
    )


def should_process(conn: sqlite3.Connection, article_id: str, *, prompt_version: str) -> bool:
    row = conn.execute(
        "SELECT status, next_retry_at, prompt_version FROM articles WHERE id = ?", (article_id,)
    ).fetchone()
    if row is None:
        return True
    if row["prompt_version"] != prompt_version:
        return True
    if row["status"] != "ERROR":
        return False
    retry_at = row["next_retry_at"]
    return retry_at is None or retry_at <= datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def save_result(
    conn: sqlite3.Connection,
    article: Article,
    result: PurificationResult,
    *,
    canonical_url: str,
    content_hash: str,
    attempts: int,
) -> None:
    status = result.decision.upper()
    conn.execute(
        """
        INSERT INTO articles (
            id, source, title, link, summary, purified_content, status, canonical_url,
            content_hash, category, quality_score, reason, model_used, prompt_version,
            attempt_count, last_error, next_retry_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v3-objective-concise',
            ?, '', NULL, CURRENT_TIMESTAMP
        )
        ON CONFLICT(id) DO UPDATE SET
            source=excluded.source, title=excluded.title, link=excluded.link,
            summary=excluded.summary, purified_content=excluded.purified_content,
            status=excluded.status, canonical_url=excluded.canonical_url,
            content_hash=excluded.content_hash, category=excluded.category,
            quality_score=excluded.quality_score, reason=excluded.reason,
            model_used=excluded.model_used, prompt_version=excluded.prompt_version,
            attempt_count=excluded.attempt_count, last_error='', next_retry_at=NULL,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            article.article_id,
            article.source,
            article.title,
            article.link,
            article.summary,
            result.summary,
            status,
            canonical_url,
            content_hash,
            result.category,
            result.quality_score,
            result.reason,
            result.model_used,
            attempts,
        ),
    )


def save_error(
    conn: sqlite3.Connection,
    article: Article,
    error: str,
    *,
    canonical_url: str,
    content_hash: str,
    attempts: int,
) -> None:
    delay_minutes = min(24 * 60, 15 * (2 ** max(0, attempts - 1)))
    retry_at = (datetime.now(UTC) + timedelta(minutes=delay_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO articles (
            id, source, title, link, summary, status, canonical_url, content_hash,
            attempt_count, last_error, next_retry_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'ERROR', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            status='ERROR', attempt_count=excluded.attempt_count,
            last_error=excluded.last_error, next_retry_at=excluded.next_retry_at,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            article.article_id,
            article.source,
            article.title,
            article.link,
            article.summary,
            canonical_url,
            content_hash,
            attempts,
            error[:1000],
            retry_at,
        ),
    )


def fetch_kept_articles(conn: sqlite3.Connection, limit: int = 15) -> list[KeptArticle]:
    rows = list(
        conn.execute(
            """
            SELECT source, title, link, purified_content, reason, category,
                   quality_score, created_at
            FROM articles
            WHERE status = 'KEEP' AND created_at >= datetime('now', '-72 hours')
            ORDER BY quality_score DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    )
    return [
        KeptArticle(
            source=row["source"],
            title=row["title"],
            link=row["link"],
            summary=row["purified_content"],
            reason=row["reason"],
            category=row["category"],
            quality_score=row["quality_score"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def main() -> int:
    from .config import Settings

    settings = Settings.from_env(require_api_key=False)
    with database(settings.db_path) as conn:
        migrate(conn)
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        column_count = len(conn.execute("PRAGMA table_info(articles)").fetchall())
    print(f"schema_version={version} article_columns={column_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
