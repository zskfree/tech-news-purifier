from tech_news_purifier.fetcher import (
    article_content_hash,
    canonicalize_url,
    clean_html,
    is_duplicate,
)
from tech_news_purifier.models import Article


def test_clean_html_and_tracking_url() -> None:
    assert clean_html("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
    assert (
        canonicalize_url("HTTPS://Example.COM/a?utm_source=rss&b=2#part")
        == "https://example.com/a?b=2"
    )
    assert canonicalize_url("javascript:alert(1)") == ""


def test_duplicate_by_url_hash_or_similar_title() -> None:
    article = Article("1", "source", "Python 3.15 发布重要更新", "https://e.test/a", "summary")
    recent = [
        {
            "canonical_url": "https://e.test/a",
            "content_hash": article_content_hash(article),
            "title": "Python 3.15 发布重要更新",
        }
    ]
    assert is_duplicate(article, recent)


def test_duplicate_check_ignores_the_same_persisted_article() -> None:
    article = Article("same", "source", "同一篇文章", "https://e.test/same", "summary")
    recent = [
        {
            "id": "same",
            "canonical_url": "https://e.test/same",
            "content_hash": article_content_hash(article),
            "title": "同一篇文章",
        }
    ]
    assert not is_duplicate(article, recent)
