from __future__ import annotations

import asyncio
import hashlib
import html
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from rapidfuzz.fuzz import token_set_ratio

from .models import Article

RSS_FEEDS = [
    ("Lobsters 极客社区", "https://lobste.rs/rss"),
    ("Solidot 奇客资讯", "https://www.solidot.org/index.rss"),
    ("InfoQ 架构与工程", "https://www.infoq.cn/feed"),
    ("OSChina 开源资讯", "https://www.oschina.net/news/rss"),
]
TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}


def clean_html(text: str | None) -> str:
    if not text:
        return ""
    value = html.unescape(text).replace("\u00a0", " ")
    value = re.sub(
        r"<(?:\s*br\s*/?|\s*/?\s*(?:p|div|li|blockquote)\s*)>",
        "\n",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n", value).strip()
    if value.lower() in {"comments", "comments...", "点击查看原文>", "点击查看原文"}:
        return ""
    return value


def canonicalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in {"http", "https"}:
            return ""
        query = urlencode(
            sorted((k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_KEYS)
        )
        path = re.sub(r"/{2,}", "/", parts.path or "/")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))
    except ValueError:
        return ""


def article_content_hash(article: Article) -> str:
    normalized = re.sub(r"\s+", " ", f"{article.title}\n{article.summary}").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_duplicate(
    article: Article,
    recent: list,
    *,
    title_threshold: int = 92,
) -> bool:
    canonical = canonicalize_url(article.link)
    digest = article_content_hash(article)
    for row in recent:
        try:
            row_id = row["id"]
        except (IndexError, KeyError):
            row_id = None
        if row_id == article.article_id:
            continue
        if canonical and row["canonical_url"] == canonical:
            return True
        if digest and row["content_hash"] == digest:
            return True
        if token_set_ratio(article.title, row["title"]) >= title_threshold:
            return True
    return False


async def _fetch_rss(
    client: httpx.AsyncClient, source: str, url: str, *, limit: int = 5
) -> list[Article]:
    response = await client.get(url)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    articles: list[Article] = []
    for entry in feed.entries[:limit]:
        title = clean_html(str(getattr(entry, "title", ""))).strip()
        link = str(getattr(entry, "link", "")).strip()
        if not title or not canonicalize_url(link):
            continue
        raw_summary = getattr(entry, "summary", getattr(entry, "description", ""))
        summary = clean_html(str(raw_summary))[:1000] or "（无详细摘要，请仅基于标题审慎研判）"
        article_id = str(getattr(entry, "id", link or title))
        articles.append(Article(article_id, source, title, link, summary))
    return articles


async def _fetch_github(client: httpx.AsyncClient, *, limit: int = 5) -> list[Article]:
    since = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    response = await client.get(
        "https://api.github.com/search/repositories",
        params={"q": f"created:>{since}", "sort": "stars", "order": "desc"},
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    articles: list[Article] = []
    for item in response.json().get("items", [])[:limit]:
        name = str(item.get("full_name", ""))
        link = str(item.get("html_url", ""))
        if not name or not canonicalize_url(link):
            continue
        description = clean_html(item.get("description")) or "暂无描述"
        stars = item.get("stargazers_count", 0)
        language = item.get("language") or "Unknown"
        title = f"{name} (Stars: {stars} | {language})"
        articles.append(
            Article(
                article_id=f"github_{item.get('id')}",
                source="GitHub 飙升项目",
                title=title,
                link=link,
                summary=description[:1000],
            )
        )
    return articles


async def fetch_all_articles() -> tuple[list[Article], list[str]]:
    timeout = httpx.Timeout(connect=10, read=20, write=10, pool=10)
    headers = {"User-Agent": "TechNewsPurifier/2.0 (+http://47.115.165.231:23654)"}
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        tasks = [_fetch_rss(client, source, url) for source, url in RSS_FEEDS]
        tasks.append(_fetch_github(client))
        results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[Article] = []
    names = [source for source, _ in RSS_FEEDS] + ["GitHub 飙升项目"]
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            errors.append(f"{name}: {type(result).__name__}: {result}")
        else:
            articles.extend(result)
    return articles, errors
