# -*- coding: utf-8 -*-
import os
import sqlite3
import datetime
import re
import time
import asyncio
from email.utils import formatdate
import httpx
import edge_tts
from dotenv import load_dotenv

load_dotenv()  # 加载 .env 文件（生产环境直接设置系统环境变量）

DB_PATH = os.environ.get('DB_PATH', '/opt/tech-news-purifier/news.db')
PODCAST_DIR = os.environ.get('PODCAST_DIR', '/opt/tech-news-purifier/podcast')
AUDIO_DIR = os.path.join(PODCAST_DIR, 'audio')
FEED_XML_PATH = os.path.join(PODCAST_DIR, 'feed.xml')

ONE_API_URL = os.environ.get('ONE_API_URL', 'http://127.0.0.1:3000/v1/chat/completions')
ONE_API_KEY = os.environ.get('ONE_API_KEY', '')
if not ONE_API_KEY:
    raise RuntimeError('环境变量 ONE_API_KEY 未设置！请参考 .env.example 配置。')

PRIMARY_MODEL = os.environ.get('PRIMARY_MODEL', 'gemini-3.6-flash')
FALLBACK_MODEL = os.environ.get('FALLBACK_MODEL', 'gemini-3.5-flash-lite')

SERVER_BASE_URL = os.environ.get('SERVER_BASE_URL', 'http://47.115.165.231')
COVER_URL = f"{SERVER_BASE_URL}/cover.png"
TTS_VOICE = 'zh-CN-YunxiNeural'
TTS_FALLBACK_VOICE = 'zh-CN-XiaoxiaoNeural'
TTS_MIN_FILE_SIZE = 50_000  # 50KB，小于此则认为合成失败

AI_KEYWORDS = [
    'ai', 'llm', 'agent', 'gpt', 'gemini', 'claude', '大模型', '机器学习',
    '深度学习', 'mlops', '神经网络', '智能', 'transformer', 'openai',
    'alphafold', 'deepmind', 'anthropic', 'kimi', '模型', '推理'
]

def ensure_dirs():
    os.makedirs(AUDIO_DIR, exist_ok=True)

def get_article_priority(source, title, content):
    text_lower = (f"{source} {title} {content}").lower()
    if any(kw in text_lower for kw in AI_KEYWORDS):
        return 1
    if 'github' in source.lower():
        return 2
    return 3

def fetch_today_keep_articles(limit=10):
    """
    Bug Fix: 使用相对 UTC 时间 (-24 hours) 获取最新资讯，
    完全规避 UTC 格式与 CST 北京时间早晨 07:30 跨日界线匹配失败的 Bug。
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 优先取过去 24 小时以内的资讯
    cursor.execute('''
        SELECT source, title, link, purified_content, created_at
        FROM articles
        WHERE status = 'KEEP' AND created_at >= datetime('now', '-24 hours')
        ORDER BY created_at DESC
        LIMIT ?
    ''', (limit * 3,))
    rows = cursor.fetchall()

    # 若 24 小时内资讯不足 3 条，扩展至过去 72 小时
    if len(rows) < 3:
        print(f'⚠️ 24 小时内资讯仅 {len(rows)} 条，扩展至过去 72 小时...')
        cursor.execute('''
            SELECT source, title, link, purified_content, created_at
            FROM articles
            WHERE status = 'KEEP' AND created_at >= datetime('now', '-72 hours')
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit * 3,))
        rows = cursor.fetchall()

    conn.close()

    sorted_articles = sorted(
        rows,
        key=lambda r: (get_article_priority(r[0], r[1], r[3]), r[4]),
    )
    return sorted_articles[:limit]

def generate_script_with_ai(articles):
    if not articles:
        return None

    articles_formatted = []
    for i, (source, title, link, content, created_at) in enumerate(articles, 1):
        prio = get_article_priority(source, title, content)
        prio_tag = "【AI 核心】" if prio == 1 else ("【GitHub 开源项目】" if prio == 2 else "【硬核科技】")
        articles_formatted.append(f"[{prio_tag}] 来源：{source}\n标题：{title}\n内容提炼：\n{content}\n")

    articles_str = "\n".join(articles_formatted)

    prompt = f'''你是一位充满活力的科技播客主讲人。请根据以下按优先级排序筛选出的【{len(articles)}篇】技术资讯/项目，撰写一份可以直接用于语音朗读的【极客早报播客文稿】。

资讯列表：
{articles_str}

【播客结构与演播顺序严格要求】：
1. 【第一板块：AI 重磅前沿】（最高优先级，优先演播）：开场白后，优先聚焦演播 AI、大模型、AI Agent 及 MLOps 相关的重磅资讯与行业深度研判。
2. 【第二板块：GitHub 优质开源推荐】（次高优先级）：重点介绍优秀的 GitHub 飙升项目，清晰口语化说明项目解决了什么痛点、核心特色及适用场景。
3. 【第三板块：硬核科技与架构前沿】：最后演播其他系统级、编译器、基础设施网络或前端动态。

文稿撰写要求：
1. 口语化、自然流畅、有温度，适合单人主持演播（开场白 -> AI重磅 -> GitHub开源 -> 其他硬核 -> 简短结语）。
2. 严禁出现任何 Markdown 语法符号（如 #、**、-、🔗 等）、严禁出现代码块。
3. 严禁朗读复杂的 URL 网址，遇到链接只需提示"详细链接已放在节目简介中"。
4. 遇到技术词汇和版本号要符合中文口语习惯（例如 v5.109.2 读作"5点109点2版本"）。
5. 字数控制在 900 ~ 1300 字之间，节奏明快，总演播时长约 3~4 分钟。
'''

    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]
    for model in models_to_try:
        for attempt in range(2):
            try:
                print(f"🤖 尝试模型 [{model}] 生成台本 (第 {attempt + 1} 次)...")
                payload = {
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.3,
                    'max_tokens': 1500
                }
                headers = {
                    'Authorization': f'Bearer {ONE_API_KEY}',
                    'Content-Type': 'application/json'
                }
                resp = httpx.post(ONE_API_URL, json=payload, headers=headers, timeout=45.0)
                if resp.status_code == 200:
                    script = resp.json()['choices'][0]['message']['content'].strip()
                    if len(script) > 200:  # 防止模型返回极短异常内容
                        print(f"✅ 模型 [{model}] 成功生成台本（{len(script)} 字）！")
                        # 二次清洗 Markdown 符号
                        return re.sub(r'[\*\#\`\_]', '', script)
                    else:
                        print(f"[!] 模型 [{model}] 返回内容过短 ({len(script)} 字)，重试...")
                else:
                    print(f"[!] 模型 [{model}] HTTP {resp.status_code}: {resp.text[:80]}")
            except Exception as e:
                print(f"[!] 模型 [{model}] 异常: {e}")
            time.sleep(2)

    print("[!] 所有模型与重试均失败！")
    return None

async def synthesize_audio(text, output_mp3_path):
    """带自动重试和备用音色兜底的 Edge-TTS 合成"""
    voices = [TTS_VOICE, TTS_FALLBACK_VOICE]
    for voice in voices:
        for attempt in range(3):
            try:
                print(f'🎙️ Edge-TTS [{voice}] 合成 (尝试 {attempt + 1})...')
                communicate = edge_tts.Communicate(text, voice, rate='+5%')
                await communicate.save(output_mp3_path)
                size = os.path.getsize(output_mp3_path) if os.path.exists(output_mp3_path) else 0
                if size >= TTS_MIN_FILE_SIZE:
                    print(f'✅ 音频生成成功: {output_mp3_path} ({size / 1024:.1f} KB)')
                    return True
                else:
                    print(f'[!] 音频文件过小 ({size} 字节)，判定为失败，重试...')
            except Exception as e:
                print(f'[!] Edge-TTS [{voice}] 尝试 {attempt + 1} 失败: {e}')
            await asyncio.sleep(3)

    raise RuntimeError("Edge-TTS 全部重试失败，无法生成音频")

def build_feed_xml(date_str, mp3_filename, mp3_size, articles_list, script_text):
    """
    Bug Fix: 重写 feed.xml 构建逻辑，采用完整重建策略，
    避免旧的字符串替换逻辑导致的 XML 结构损坏问题。
    读取已有 <item> 列表，插入新 <item>，整体重新输出。
    """
    audio_url = f"{SERVER_BASE_URL}/audio/{mp3_filename}"
    pub_date = formatdate(usegmt=True)

    html_desc = f"<h3>🎙️ 极客早报 ({date_str})</h3><p>{script_text[:250]}...</p><h4>📌 本期涵盖资讯：</h4><ul>"
    for source, title, link, content, _ in articles_list:
        html_desc += f"<li><b>[{source}]</b> <a href='{link}'>{title}</a></li>"
    html_desc += "</ul><p><i>本播客由 AI 自动提纯技术资讯并生成声音。</i></p>"
    html_desc = html_desc.replace(']]>', ']]&gt;')

    new_item = f'''    <item>
      <title>极客早报 | {date_str} 硬核技术精选</title>
      <description><![CDATA[{html_desc}]]></description>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{audio_url}" length="{mp3_size}" type="audio/mpeg"/>
      <guid isPermaLink="false">geek-news-{date_str}</guid>
      <itunes:duration>04:00</itunes:duration>
      <itunes:explicit>no</itunes:explicit>
      <itunes:image href="{COVER_URL}"/>
    </item>'''

    # 提取已有 feed 中的所有 <item>，并过滤掉今日已存在的
    existing_items = ""
    if os.path.exists(FEED_XML_PATH):
        with open(FEED_XML_PATH, 'r', encoding='utf-8') as f:
            old_xml = f.read()
        # 提取所有 <item>...</item> 块，移除今日旧版本
        items = re.findall(r'<item>.*?</item>', old_xml, flags=re.DOTALL)
        kept = [item for item in items if f'geek-news-{date_str}' not in item]
        existing_items = '\n'.join(kept)
        if kept:
            print(f'   └─ 保留了 {len(kept)} 条历史单集')

    # 重建完整 feed.xml（最新单集在最前面）
    new_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>极客早报 | AI 自动精选技术播客</title>
    <link>{SERVER_BASE_URL}/feed.xml</link>
    <language>zh-cn</language>
    <copyright>Copyright 2026 Tech News Purifier</copyright>
    <itunes:author>Tech News Purifier Engine</itunes:author>
    <itunes:subtitle>每日硬核技术资讯与架构突破精炼音频听报</itunes:subtitle>
    <itunes:summary>每日 07:30 自动生成全网硬核技术资讯、优质开源项目与架构突破精炼音频播客。</itunes:summary>
    <itunes:owner>
      <itunes:name>极客早报</itunes:name>
      <itunes:email>podcast@47.115.165.231</itunes:email>
    </itunes:owner>
    <itunes:image href="{COVER_URL}"/>
    <image>
      <url>{COVER_URL}</url>
      <title>极客早报 | AI 自动精选技术播客</title>
      <link>{SERVER_BASE_URL}/feed.xml</link>
    </image>
    <itunes:category text="Technology">
      <itunes:category text="Tech News"/>
    </itunes:category>
    <itunes:explicit>no</itunes:explicit>
{new_item}
{existing_items}
  </channel>
</rss>'''

    with open(FEED_XML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_xml)
    print(f'🎉 RSS Feed 更新成功！订阅地址: {SERVER_BASE_URL}/feed.xml')

def main():
    ensure_dirs()
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    mp3_filename = f"{today_str}.mp3"
    output_mp3_path = os.path.join(AUDIO_DIR, mp3_filename)

    print('=' * 60)
    print(f'🎙️ 开始生成【极客早报】AI 音频播客 [{today_str}]')
    print('=' * 60)

    articles = fetch_today_keep_articles(limit=8)
    if not articles:
        print('[!] 未找到可用资讯，跳过播客生成。')
        return

    print(f'🔍 获取到 {len(articles)} 篇资讯，优先尝试模型 [{PRIMARY_MODEL}]...')
    script_text = generate_script_with_ai(articles)
    if not script_text:
        print('[!] 播客台本生成失败。')
        return

    print('\n--- [播客台本预览] ---')
    print(script_text[:400] + '...\n')

    asyncio.run(synthesize_audio(script_text, output_mp3_path))
    mp3_size = os.path.getsize(output_mp3_path)

    print('📻 正在更新 Podcast RSS Feed...')
    build_feed_xml(today_str, mp3_filename, mp3_size, articles, script_text)

if __name__ == '__main__':
    main()
