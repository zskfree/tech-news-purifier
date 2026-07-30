# -*- coding: utf-8 -*-
import sqlite3
import datetime
import os
import re
import time
import asyncio
import subprocess
from email.utils import formatdate
import httpx
import edge_tts
from dotenv import load_dotenv

load_dotenv()  # 加载 .env 文件

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
TTS_MIN_FILE_SIZE = 50_000

AI_KEYWORDS = [
    'ai', 'llm', 'agent', 'gpt', 'gemini', 'claude', '大模型', '机器学习',
    '深度学习', 'mlops', '神经网络', '智能', 'transformer', 'openai',
    'alphafold', 'deepmind', 'anthropic', 'kimi', '模型', '推理', '智源'
]

def ensure_dirs():
    os.makedirs(AUDIO_DIR, exist_ok=True)

def get_article_priority(source, title, content):
    text_lower = (f"{source} {title} {content}").lower()
    if any(kw in text_lower for kw in AI_KEYWORDS):
        return 1
    if 'github' in source.lower() or 'github' in text_lower:
        return 2
    return 3

def fetch_today_keep_articles(limit=15):
    """
    取过去 24 小时以内的 KEEP 资讯，不足则扩展至 72 小时。
    扩大取样数量至 12~15 篇，为 20 分钟长播客提供充足干货素材。
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT source, title, link, purified_content, created_at
        FROM articles
        WHERE status = 'KEEP' AND created_at >= datetime('now', '-24 hours')
        ORDER BY created_at DESC
        LIMIT ?
    ''', (limit * 2,))
    rows = cursor.fetchall()

    if len(rows) < 6:
        print(f'⚠️ 24 小时内资讯仅 {len(rows)} 条，扩展至过去 72 小时...')
        cursor.execute('''
            SELECT source, title, link, purified_content, created_at
            FROM articles
            WHERE status = 'KEEP' AND created_at >= datetime('now', '-72 hours')
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit * 2,))
        rows = cursor.fetchall()

    conn.close()

    sorted_articles = sorted(
        rows,
        key=lambda r: (get_article_priority(r[0], r[1], r[3]), r[4]),
    )
    return sorted_articles[:limit]

def call_ai(prompt, max_tokens=2000, temperature=0.3, min_length=150):
    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]
    for model in models_to_try:
        for attempt in range(2):
            try:
                payload = {
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': temperature,
                    'max_tokens': max_tokens
                }
                headers = {
                    'Authorization': f'Bearer {ONE_API_KEY}',
                    'Content-Type': 'application/json'
                }
                resp = httpx.post(ONE_API_URL, json=payload, headers=headers, timeout=60.0)
                if resp.status_code == 200:
                    text = resp.json()['choices'][0]['message']['content'].strip()
                    if len(text) >= min_length:
                        return re.sub(r'[\*\#\`\_]', '', text)
                    else:
                        print(f"[!] 模型 [{model}] 返回内容偏短 ({len(text)} 字 < {min_length} 字)，自动重试...")
            except Exception as e:
                print(f"[!] 模型 [{model}] 调用异常: {e}")
            time.sleep(2)
    return ""

def generate_20min_script_with_ai(articles):
    """
    分块深度写作链 (Map-Reduce Script Pipeline):
    将文章平衡分组为 3 个板块，逐板块发起 AI 生成，拼合为 5500~6500 字（约20分钟）的深度播客文稿。
    """
    if not articles:
        return None, []

    # 按优先级排序，然后按比例强行分成 3 组，确保无任何空板块
    sorted_arts = sorted(articles, key=lambda a: (get_article_priority(a[0], a[1], a[3]), a[4]))
    total_n = len(sorted_arts)
    c1_end = max(1, total_n // 3)
    c2_end = max(2, (total_n * 2) // 3)
    
    chunk1 = sorted_arts[:c1_end]
    chunk2 = sorted_arts[c1_end:c2_end]
    chunk3 = sorted_arts[c2_end:]

    segments = [
        ("AI 与前沿重磅深度解析", chunk1, "聚焦前沿大模型突破、安全对齐、行业大事件与宏观影响。深入探讨技术解决的痛点、架构逻辑与行业含义。"),
        ("GitHub 热门开源与工程实践", chunk2, "重点剖析优秀开源项目、开发者工具和实用框架。口语化解释项目背景、特色及应用场景。"),
        ("硬核科技与系统架构前沿", chunk3, "探讨编译器、网络协议、数据库、基础设施及前沿技术。深度剖析技术实现与架构启示。")
    ]

    full_script_parts = []
    chapter_timestamps = []  # (title, estimate_minute_str)
    current_word_count = 0

    # 1. 生成开场白
    intro_prompt = f'''你是一位资深技术播客主讲人。请为今天的《极客早报 20分钟深度版》撰写一段热情的开场白。
简要概括今天涵盖的三大核心板块（AI重磅前沿、GitHub开源精选、硬核系统架构）。
要求：口语化、自然流畅、有温度，字数在 400~500 字之间。无 Markdown 符号。'''
    
    print("🎙️ [1/5] 生成播客开场白与今日导览...")
    intro_text = call_ai(intro_prompt, max_tokens=1000, min_length=300) or "各位极客朋友们大家好，欢迎收听今天的极客早报深度版！我是你们的主播。今天的科技圈干货满满，废话不多说，我们直接进入今天的科技深度快讯。"
    full_script_parts.append(intro_text)
    
    # 记录开场时间戳
    chapter_timestamps.append(("🎙️ 节目开场与今日导览", "00:00"))
    current_word_count += len(intro_text)

    # 2. 逐板块生成深度演播文本
    for idx, (seg_title, seg_arts, seg_desc) in enumerate(segments, 2):
        if not seg_arts:
            continue

        # 计算当前预计时间戳 (按 280字/分钟 估算)
        est_minutes = int(current_word_count / 280)
        est_seconds = int((current_word_count % 280) / 280 * 60)
        time_str = f"{est_minutes:02d}:{est_seconds:02d}"
        chapter_timestamps.append((f"🔥 【板块】{seg_title}", time_str))

        arts_str = ""
        for i, (source, title, link, content, _) in enumerate(seg_arts, 1):
            arts_str += f"\n资讯 #{i}：[{source}] {title}\n详细提炼内容：\n{content}\n"

        seg_prompt = f'''你是一位资深技术播客主讲人。请根据以下【{seg_title}】板块的资讯列表，撰写一段非常深入、详实、口语化的播客演播文稿。

板块定位：{seg_desc}

资讯列表：
{arts_str}

【撰写要求】：
1. 字数必须达到 1500 ~ 1800 字！不要简单念标题，要深入拆解：为什么这个技术/项目重要？它解决了什么痛点？对开发者有哪些启发？
2. 口语化、自然流畅，用“我们看到”、“这里值得注意的是”、“对于开发者来说”等口语表达。
3. 严禁出现任何 Markdown 语法符号（如 #、**、-、🔗 等），严禁出现代码块。
4. 遇到的网址不要朗读，直接说“详细链接已放在节目简介中”。
5. 遇到版本号或专业词汇符合中文演播习惯（如 v5.109 读作“5点109版本”）。'''

        print(f"🎙️ [{idx}/5] 生成板块《{seg_title}》深度播客文稿（目标 1600 字）...")
        seg_script = call_ai(seg_prompt, max_tokens=3000, min_length=900)
        if seg_script:
            full_script_parts.append(seg_script)
            current_word_count += len(seg_script)
        else:
            print(f"[!] 板块《{seg_title}》AI 生成失败，跳过该板块")

    # 3. 生成结语与总结
    outro_prompt = '''你是一位资深技术播客主讲人。请为今天的 20 分钟极客早报撰写一段引发思考的结语与总结。
感谢听众收听，提示大家可以在 Apple Podcasts 节目简介中查看所有资讯的原文链接与时间戳章节。
字数要求 300~400 字，口语化自然，无 Markdown 符号。'''

    print("🎙️ [5/5] 生成播客总结与尾声...")
    outro_text = call_ai(outro_prompt, max_tokens=800) or "以上就是今天极客早报的全部深度内容。感谢大家的收听，节目简介中已附上所有项目的原文链接。我们明天早晨 7 点 30 分不见不散！"
    
    est_minutes = int(current_word_count / 280)
    est_seconds = int((current_word_count % 280) / 280 * 60)
    chapter_timestamps.append(("💬 结语与明日预告", f"{est_minutes:02d}:{est_seconds:02d}"))
    
    full_script_parts.append(outro_text)
    current_word_count += len(outro_text)

    full_script = "\n\n".join(full_script_parts)
    print(f"🎉 20 分钟长播客文稿生成完毕！总字数：{len(full_script)} 字")
    return full_script, chapter_timestamps

def split_script_into_chunks(text, max_len=280):
    """按句号/问号/感叹号切分长文本为 <=280 字的短句块，彻底杜绝 Edge-TTS 超时"""
    raw_sentences = re.split(r'(?<=[。！？\n])', text)
    chunks = []
    curr = ""
    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        if len(curr) + len(s) > max_len:
            if curr:
                chunks.append(curr)
            curr = s
        else:
            curr += (" " + s if curr else s)
    if curr:
        chunks.append(curr)
    return chunks

def clean_tts_text(text):
    """移除可能会导致 Edge-TTS 无法识别的 HTML/XML 字符及非打印字符"""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[\*\#\`\_\<\>\\\/]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

async def synthesize_audio_chunked(full_script, output_mp3_path):
    """
    分块合成 Edge-TTS 并使用 ffmpeg 转化为 24kbps 单声道高压缩人声 MP3。
    """
    paragraphs = split_script_into_chunks(full_script, max_len=280)
    chunk_paths = []

    # 1. 彻底清理目录中旧的临时 chunk 文件
    audio_dir = os.path.dirname(output_mp3_path)
    for old_file in os.listdir(audio_dir):
        if old_file.endswith('.mp3') and '.chunk_' in old_file:
            try:
                os.remove(os.path.join(audio_dir, old_file))
            except Exception:
                pass

    # 2. 临时分块文件合成
    for i, para in enumerate(paragraphs, 1):
        para_clean = clean_tts_text(para)
        if not para_clean:
            continue

        chunk_file = f"{output_mp3_path}.chunk_{i}.mp3"
        if os.path.exists(chunk_file):
            os.remove(chunk_file)

        voices = [TTS_VOICE, TTS_FALLBACK_VOICE, 'zh-CN-YunjianNeural']
        success = False
        
        for voice in voices:
            for attempt in range(3):
                try:
                    communicate = edge_tts.Communicate(para_clean, voice, rate='+0%')
                    await communicate.save(chunk_file)
                    if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 500:
                        success = True
                        break
                    elif os.path.exists(chunk_file):
                        os.remove(chunk_file)
                except Exception as e:
                    if os.path.exists(chunk_file):
                        os.remove(chunk_file)
                await asyncio.sleep(0.5)
            if success:
                break
        
        if success:
            chunk_paths.append(chunk_file)
        else:
            print(f"⚠️ 短块 #{i} 合成失败，跳过该小句...")
            if os.path.exists(chunk_file):
                os.remove(chunk_file)

    # 3. 仅保留实际存在且大于 500 字节的真实块
    valid_chunks = [cp for cp in chunk_paths if os.path.exists(cp) and os.path.getsize(cp) > 500]
    if not valid_chunks:
        raise RuntimeError("全部短块合成失败，无法压制音频。")

    # 4. 拼接原始 MP3 列表
    concat_list_path = f"{output_mp3_path}.txt"
    with open(concat_list_path, 'w', encoding='utf-8') as f:
        for cp in valid_chunks:
            f.write(f"file '{cp}'\n")

    # 5. 使用 ffmpeg concat 顺畅拼接并直接转码 (24 kbps Mono 22.05kHz MP3)
    cmd_compress = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', concat_list_path,
        '-ac', '1',          # 单声道 Mono
        '-ar', '22050',      # 22.05 kHz 采样率
        '-b:a', '24k',       # 24 kbps 目标码率
        output_mp3_path
    ]
    print(f"⚡ 使用 FFmpeg 压制 {len(valid_chunks)} 个切片为人声专属 24kbps 单声道 MP3: {output_mp3_path} ...")
    try:
        subprocess.run(cmd_compress, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[!] FFmpeg 压制异常: {e.stderr.decode('utf-8', errors='ignore')}")
        raise e

    # 清理所有段落临时文件
    for cp in valid_chunks:
        if os.path.exists(cp):
            os.remove(cp)
    if os.path.exists(concat_list_path):
        os.remove(concat_list_path)

    final_size = os.path.getsize(output_mp3_path)
    print(f"✅ 音频压制成功！最终体积: {final_size / (1024*1024):.2f} MB")
    return final_size

    # 清理临时文件
    for cp in chunk_paths:
        if os.path.exists(cp):
            os.remove(cp)
    if os.path.exists(concat_list_path):
        os.remove(concat_list_path)
    if os.path.exists(raw_mp3_concat):
        os.remove(raw_mp3_concat)

    final_size = os.path.getsize(output_mp3_path)
    print(f"✅ 音频压制成功！最终体积: {final_size / (1024*1024):.2f} MB")
    return final_size

def get_audio_duration_str(mp3_path):
    """使用 ffprobe 精确获取音频时长格式为 HH:MM:SS"""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries',
            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', mp3_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        total_seconds = float(res.stdout.strip())
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    except Exception as e:
        print(f"[!] 获取音频精确时长失败，使用默认值: {e}")
        return "20:00"

def build_feed_xml(date_str, mp3_filename, mp3_size, duration_str, articles_list, script_text, chapter_timestamps):
    """
    构建符合 Apple Podcasts 最佳规范的播客 XML：
    包含 <content:encoded> 富文本、带跳转点的时间戳章节导航、详细资讯卡片与准确时长。
    """
    audio_url = f"{SERVER_BASE_URL}/audio/{mp3_filename}"
    pub_date = formatdate(usegmt=True)

    # 1. 构建时间戳 HTML 导览 (Apple Podcasts 支持点击跳转)
    timestamps_html = "<h3>⏱️ 章节与时间戳导航</h3><ul>"
    for title, t_str in chapter_timestamps:
        timestamps_html += f"<li><b>{t_str}</b> - {title}</li>"
    timestamps_html += "</ul>"

    # 2. 构建分篇目详细资讯卡片 HTML
    articles_html = "<h3>📌 本期涵盖硬核资讯列表</h3>"
    for source, title, link, content, _ in articles_list:
        prio = get_article_priority(source, title, content)
        prio_tag = "🔥 [AI重磅]" if prio == 1 else ("🛠️ [开源飙升]" if prio == 2 else "🏗️ [系统架构]")
        
        articles_html += f'''<div style="margin-bottom: 15px; padding: 10px; border-left: 3px solid #007aff; background-color: #f8f9fa;">
  <p><b>{prio_tag} [{source}]</b> <a href="{link}"><b>{title}</b></a></p>
  <p style="font-size: 0.9em; color: #333;">{content}</p>
  <p style="font-size: 0.85em;"><a href="{link}">🔗 点击阅读原文/GitHub项目主页</a></p>
</div>'''

    # 3. 组合完整的 content:encoded HTML
    content_encoded_html = f'''<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <h2>🎙️ 极客早报 20分钟深度版 ({date_str})</h2>
  <p><i>每日 07:30 自动生成全网硬核技术资讯、优质开源项目与架构突破精炼音频播客。</i></p>
  <hr/>
  {timestamps_html}
  <hr/>
  <h3>📝 播客文稿导览</h3>
  <p>{script_text[:400]}...</p>
  <hr/>
  {articles_html}
</div>'''

    # 安全转义 CDATA 闭合符
    content_encoded_safe = content_encoded_html.replace(']]>', ']]&gt;')
    short_desc = f"极客早报深度版 ({date_str})：包含 AI 重磅前沿、GitHub 开源精选与系统架构等 {len(articles_list)} 篇技术干货。"

    new_item = f'''    <item>
      <title>极客早报 | {date_str} 20分钟硬核技术深度精选</title>
      <description><![CDATA[{short_desc}]]></description>
      <content:encoded><![CDATA[{content_encoded_safe}]]></content:encoded>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{audio_url}" length="{mp3_size}" type="audio/mpeg"/>
      <guid isPermaLink="false">geek-news-{date_str}</guid>
      <itunes:duration>{duration_str}</itunes:duration>
      <itunes:explicit>no</itunes:explicit>
      <itunes:image href="{COVER_URL}"/>
      <itunes:summary><![CDATA[{short_desc}]]></itunes:summary>
    </item>'''

    # 保留历史单集
    existing_items = ""
    if os.path.exists(FEED_XML_PATH):
        with open(FEED_XML_PATH, 'r', encoding='utf-8') as f:
            old_xml = f.read()
        items = re.findall(r'<item>.*?</item>', old_xml, flags=re.DOTALL)
        kept = [item for item in items if f'geek-news-{date_str}' not in item]
        existing_items = '\n'.join(kept[:30])  # 保留最近 30 期

    new_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" 
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>极客早报 | AI 自动精选技术播客</title>
    <link>{SERVER_BASE_URL}/feed.xml</link>
    <language>zh-cn</language>
    <copyright>Copyright 2026 Tech News Purifier</copyright>
    <itunes:author>Tech News Purifier Engine</itunes:author>
    <itunes:subtitle>每日 20 分钟硬核技术资讯、开源项目与架构突破听报</itunes:subtitle>
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
    print(f'🎙️ 开始生成【极客早报】20 分钟 AI 深度播客 [{today_str}]')
    print('=' * 60)

    articles = fetch_today_keep_articles(limit=15)
    if not articles:
        print('[!] 未找到可用资讯，跳过播客生成。')
        return

    print(f'🔍 获取到 {len(articles)} 篇资讯，开启“总-分-总”多板块深度台本写作链...')
    script_text, chapter_timestamps = generate_20min_script_with_ai(articles)
    if not script_text:
        print('[!] 播客台本生成失败。')
        return

    print('\n--- [播客台本部分预览] ---')
    print(script_text[:500] + '...\n')

    print('🎙️ 开始分段 Edge-TTS 语音合成与 FFmpeg 高压缩压制...')
    asyncio.run(synthesize_audio_chunked(script_text, output_mp3_path))
    mp3_size = os.path.getsize(output_mp3_path)

    duration_str = get_audio_duration_str(output_mp3_path)
    print(f"⏱️ 最终音频精确时长: {duration_str}")

    print('📻 正在更新 Podcast RSS Feed (包含 Apple 富文本与章节导航)...')
    build_feed_xml(today_str, mp3_filename, mp3_size, duration_str, articles, script_text, chapter_timestamps)

if __name__ == '__main__':
    main()
