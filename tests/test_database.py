import sqlite3

from tech_news_purifier.database import SCHEMA_VERSION, connect, migrate, should_process


def test_migration_upgrades_legacy_database(tmp_path) -> None:
    path = tmp_path / "news.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE articles (id TEXT PRIMARY KEY, source TEXT, title TEXT, link TEXT, "
        "summary TEXT, purified_content TEXT, status TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    legacy.commit()
    legacy.close()

    conn = connect(path)
    migrate(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
    version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(articles)")}
    null_updated_at = conn.execute(
        "SELECT count(*) FROM articles WHERE updated_at IS NULL"
    ).fetchone()[0]
    conn.close()

    assert {"canonical_url", "category", "attempt_count", "next_retry_at"} <= columns
    assert version == str(SCHEMA_VERSION)
    assert "idx_articles_status_created_at" in indexes
    assert null_updated_at == 0


def test_old_prompt_rows_are_reprocessed(tmp_path) -> None:
    path = tmp_path / "news.db"
    conn = connect(path)
    migrate(conn)
    conn.execute(
        "INSERT INTO articles(id, status, prompt_version) VALUES('old', 'KEEP', 'v2')"
    )
    conn.execute(
        "INSERT INTO articles(id, status, prompt_version) "
        "VALUES('current', 'KEEP', 'v3-objective-concise')"
    )
    assert should_process(conn, "old", prompt_version="v3-objective-concise")
    assert not should_process(conn, "current", prompt_version="v3-objective-concise")
    conn.close()


def test_migration_marks_unscored_legacy_rows_for_reprocessing(tmp_path) -> None:
    path = tmp_path / "news.db"
    conn = connect(path)
    migrate(conn)
    conn.execute(
        "INSERT INTO articles(id, status, prompt_version, quality_score, model_used) "
        "VALUES('legacy-current-default', 'KEEP', 'v3-objective-concise', 0, '')"
    )
    migrate(conn)
    version = conn.execute(
        "SELECT prompt_version FROM articles WHERE id='legacy-current-default'"
    ).fetchone()[0]
    conn.close()
    assert version == "legacy"
