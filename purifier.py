# -*- coding: utf-8 -*-
import os
import sqlite3
import datetime
import sys
import json
import html
import re
import time
import feedparser
import httpx
from dotenv import load_dotenv

load_dotenv()  # 加载 .env 文件（生产环境直接设置系统环境变量）

DB_PATH = os.environ.get('DB_PATH', '/opt/tech-news-purifier/news.db')
ONE_API_URL = os.environ.get('ONE_API_URL', 'http://127.0.0.1:3000/v1/chat/completions')
ONE_API_KEY = os.environ.get('ONE_API_KEY', '')
if not ONE_API_KEY:
    raise RuntimeError('环境变量 ONE_API_KEY 未设置！请参考 .env.example 配置。')

PRIMARY_MODEL = 'gemini-3.6-flash'
FALLBACK_MODEL = 'gemini-3.5-flash-lite'

def _github_since_date():
    """动态计算最近 30 天的日期，避免日期写死"""
    since = datetime.date.today() - datetime.timedelta(days=30)
    return since.strftime('%Y-%m-%d')

FEEDS = [
    ('Lobsters 极客社区', 'https://lobste.rs/rss', 'rss'),
    ('Solidot 奇客资讯', 'https://www.solidot.org/index.rss', 'rss'),
    ('InfoQ 架构与工程', 'https://www.infoq.cn/feed', 'rss'),
    ('OSChina 开源资讯', 'https://www.oschina.net/news/rss', 'rss'),
]

def get_feeds():
    """运行时动态生成 FEEDS，确保 GitHub 日期始终为最近 30 天"""
    feeds = list(FEEDS)
    since = _github_since_date()
    feeds.append(
        ('GitHub 飙升项目', f'https://api.github.com/search/repositories?q=created:>{since}&sort=stars', 'github_api')
    )
    return feeds

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            link TEXT,
            summary TEXT,
            purified_content TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_processed(article_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM articles WHERE id = ?', (article_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def save_article(article_id, source, title, link, summary, purified_content, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO articles (id, source, title, link, summary, purified_content, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (article_id, source, title, link, summary, purified_content, status))
    conn.commit()
    conn.close()

def clean_html(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r'<(?:\s*br\s*/?|\s*/?\s*(?:p|div|li|blockquote)\s*)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    cleaned = text.strip()
    if cleaned.lower() in ('comments', 'comments...', '点击查看原文>', '点击查看原文'):
        return ""
    return cleaned

def fetch_rss(source_name, url):
    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            aid = getattr(entry, 'id', getattr(entry, 'link', entry.title))
            summary_raw = getattr(entry, 'summary', getattr(entry, 'description', ''))
            summary_clean = clean_html(summary_raw)[:500]
            if not summary_clean:
                summary_clean = '（无正文详细摘要，请基于标题与链接研判）'
            articles.append({
                'id': aid,
                'source': source_name,
                'title': entry.title.strip(),
                'link': entry.link.strip(),
                'summary': summary_clean
            })
    except Exception as e:
        print(f'[!] 抓取 {source_name} 失败: {e}')
    return articles

def fetch_github_api(source_name, url):
    articles = []
    try:
        headers = {'User-Agent': 'TechNewsPurifier/1.0'}
        resp = httpx.get(url, headers=headers, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get('items', [])[:5]:
                name = item.get('full_name', '')
                desc = clean_html(item.get('description', '')) or '暂无描述'
                lang = item.get('language', 'Unknown')
                stars = item.get('stargazers_count', 0)
                articles.append({
                    'id': f"github_{item.get('id')}",
                    'source': source_name,
                    'title': f"{name} (Stars: {stars} | {lang})",
                    'link': item.get('html_url', ''),
                    'summary': desc
                })
        else:
            print(f'[!] GitHub API 响应异常: {resp.status_code}')
    except Exception as e:
        print(f'[!] 抓取 GitHub 失败: {e}')
    return articles

def purify_with_ai(article):
    prompt = f'''你是一个专业的技术情报筛选与提纯官。请评估并提纯以下技术资讯/项目：

来源：{article['source']}
标题：{article['title']}
链接：{article['link']}
摘要：{article['summary']}

处理规则：
1. 如果内容是"通用营销广告、泛水文、无硬核价值的套话"，直接仅回复一个词：DISCARD
2. 如果是"硬核技术讨论、优质开源项目、架构突破或硬核科技资讯"，请按以下格式输出精炼 Markdown：

### 📌 [{article['source']}] {article['title']}
- 💡 **核心亮点**：[一句话说明解决了什么问题/有什么突破]
- 🎯 **推荐关注**：[1~2句核心价值提炼]
- 🔗 **链接**：{article['link']}
'''

    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]
    
    for model in models_to_try:
        for attempt in range(2):
            try:
                payload = {
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.2,
                    'max_tokens': 500
                }
                headers = {
                    'Authorization': f'Bearer {ONE_API_KEY}',
                    'Content-Type': 'application/json'
                }
                resp = httpx.post(ONE_API_URL, json=payload, headers=headers, timeout=25.0)
                if resp.status_code == 200:
                    res_data = resp.json()
                    content = res_data['choices'][0]['message']['content'].strip()
                    if content:
                        print(f"   [AI] 使用模型 [{model}] 成功返回")
                        return content
                else:
                    print(f"   [!] 模型 [{model}] 尝试 {attempt+1} 失败 (HTTP {resp.status_code})")
            except Exception as e:
                print(f"   [!] 模型 [{model}] 尝试 {attempt+1} 异常: {e}")
            time.sleep(1)

    print('[!] 所有 AI 模型与重试均失败')
    return None

def main():
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print('=' * 60)
    print(f'🚀 开始运行全网技术资讯 AI 自动提纯引擎 [{now_str}]')
    print('=' * 60)
    init_db()

    raw_articles = []
    for name, url, feed_type in get_feeds():
        print(f'📡 正在抓取：{name} ...')
        if feed_type == 'rss':
            raw_articles.extend(fetch_rss(name, url))
        elif feed_type == 'github_api':
            raw_articles.extend(fetch_github_api(name, url))

    print(f'\n🔍 共获取到 {len(raw_articles)} 条最新资讯/项目，正在对比去重与 AI 提纯 ...\n')

    purified_results = []
    new_count = 0

    for art in raw_articles:
        if is_processed(art['id']):
            continue

        new_count += 1
        print(f'🤖 正在 AI 分析 [{art["source"]}] {art["title"]} ...')
        result = purify_with_ai(art)

        if result:
            if 'DISCARD' in result.upper() and len(result) < 20:
                print('   └─ 🗑️ 已过滤：水文或价值不高')
                save_article(art['id'], art['source'], art['title'], art['link'], art['summary'], '', 'DISCARD')
            else:
                print('   └─ ✅ 提纯成功！')
                save_article(art['id'], art['source'], art['title'], art['link'], art['summary'], result, 'KEEP')
                purified_results.append(result)
        else:
            print('   └─ ⚠️ 跳过：AI 分析未能正常返回')

    print('\n' + '=' * 60)
    print(f'🎉 本次提纯完成！处理新文章 {new_count} 篇，精炼保留 {len(purified_results)} 篇：')
    print('=' * 60 + '\n')

    for i, res in enumerate(purified_results, 1):
        print(f'--- [精炼资讯 #{i}] ---')
        print(res)
        print()

if __name__ == '__main__':
    main()
