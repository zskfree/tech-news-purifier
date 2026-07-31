<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Tech News Purifier - AI 科技新闻净化与 20 分钟长播客引擎">
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.12-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.12"></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/badge/package%20manager-uv-DE5FE9.svg?style=flat-square" alt="uv"></a>
  <a href="https://github.com/rany2/edge-tts"><img src="https://img.shields.io/badge/TTS-Edge--TTS-0078D4.svg?style=flat-square" alt="Edge-TTS"></a>
  <a href="https://ffmpeg.org/"><img src="https://img.shields.io/badge/Audio%20Codec-FFmpeg%2024kbps-009639.svg?style=flat-square&logo=ffmpeg&logoColor=white" alt="FFmpeg 24kbps"></a>
  <a href="https://apple.com/apple-podcasts/"><img src="https://img.shields.io/badge/Podcast-Apple%20Podcasts-872EC4.svg?style=flat-square&logo=apple-podcasts&logoColor=white" alt="Apple Podcasts"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License MIT"></a>
</p>

---

## 💡 项目简介 (Overview)

**Tech News Purifier（极客早报净化与播客引擎）** 是自动化 AI 技术资讯处理与播客生成系统。

系统自动抓取多源 RSS 技术新闻，使用 OneAPI 大模型执行结构化筛选、去重和质量评分；再通过“编辑提纲、顺序写作、全文审校”生成客观、精练且前后连贯的演播稿。Edge-TTS 与 FFmpeg 将内容压制为 24kbps 单声道 MP3，只有时长处于 18–22 分钟且全部发布校验通过的成品才会进入 RSS Feed。

---

## 🔥 核心特性 (Key Features)

- 📡 **多源 RSS 抓取与降噪 (Purifier Engine)**
  - 定时采集全网优质科技 RSS 订阅源。
  - 使用大语言模型识别并剔除公关稿、标题党与低质资讯。
  - 使用结构化 JSON 归类与打分，执行 URL、内容哈希和七日标题相似度去重。

- 🎙️ **20 分钟 “总-分-总” 深度播客台本 (Multi-stage Script Writer)**
  - 采用编辑提纲、共享事实卡、顺序分板块写作和最多两轮全文审校。
  - 聚焦评分不低于 7 的重点新闻，保持事实、来源观点和推断之间的界限。
  - 自动检查预告兑现、术语一致、上下文衔接、重复段落和宣传性语言。
  - 按板块独立合成并用 FFprobe 实测时长；仅发布 **18~22 分钟** 的成品。

- ⚡ **24kbps 单声道高压缩音频压制 (Ultra-compressed Audio)**
  - 智能分句切割与文本清洗，规避 Edge-TTS 长文本超时与非法字符断连。
  - 采用人声专属压制参数：`24kbps CBR` + `Mono 单声道` + `22.05kHz 采样率`。
  - **极致体积压缩**：20 分钟长播客音频体积降至 **~2.0 MB**，节省 90% 以上的网络带宽与存储空间。

- 📻 **Apple Podcast 深度增强 (Rich-Text & Chapters)**
  - 完美解决 Apple 播放器由于分段 Header 导致的 **时长识别错误与无法播放问题**。
  - **HTML 结构化富文本**：支持在播客客户端展示带有 CSS 样式的排版表格与板块导览。
  - **Podcasting 2.0 章节导航**：基于真实分段音频时长生成 JSON Chapters，并通过 `<podcast:chapters>` 发布。

---

## 🏗️ 系统架构与发布流程 (Architecture)

<p align="center">
  <img src="./assets/readme/architecture.svg" width="100%" alt="Tech News Purifier 系统架构图">
</p>

---

## 🚀 快速开始 (Quick Start)

### 1. 环境准备

本项目推荐使用 **uv** 进行 Python 依赖管理：

```bash
# 克隆仓库
git clone git@github.com:zskfree/tech-news-purifier.git
cd tech-news-purifier

# 必须安装系统的 FFmpeg 命令行工具
# Ubuntu/Debian: sudo apt update && sudo apt install -y ffmpeg
```

### 2. 配置环境变量

复制 `.env.example` 并填入您的 API 密钥与服务器配置：

```bash
cp .env.example .env
```

配置 `.env` 内容：

```env
ONE_API_KEY=your_one_api_key_here
ONE_API_URL=http://127.0.0.1:3000/v1/chat/completions
SERVER_BASE_URL=http://47.115.165.231:23654
DB_PATH=/var/lib/tech-news-purifier/news.db
PODCAST_DIR=/var/lib/tech-news-purifier/podcast
```

---

## 🛠️ 运行与部署 (Usage)

### 1. 执行资讯抓取与净化

```bash
uv run python purifier.py
```

### 2. 生成 20 分钟长播客与 RSS Feed

```bash
uv run python podcast_generator.py
```

### 3. 生产部署

生产环境由 Nginx 在 `23654` 提供 Range 和静态文件服务，systemd timer 每天 07:30
运行处理管线。该入口使用 HTTP，不配置域名或 HTTPS。完整配置见
[生产部署说明](docs/DEPLOYMENT.md)。

---

## 📱 播客客户端订阅指南 (Podcast Subscription)

复制订阅地址 `http://47.115.165.231:23654/feed.xml`：

1. **Apple Podcasts (苹果播客)**：
   - 打开 App -> 点击顶部 `“通过 URL 添加节目...”` -> 粘贴 `feed.xml` 地址 -> 订阅。
2. **Pocket Casts / Overcast / 小宇宙**：
   - 在搜索栏直接粘贴 `feed.xml` URL 即可一键订阅并展示富文本及章节。

---

## 📁 目录结构 (Project Structure)

```text
tech-news-purifier/
├── assets/
│   └── readme/               # README 矢量 SVG 视觉资源
│       ├── hero.svg
│       └── architecture.svg
├── purifier.py               # 多源 RSS 抓取与 LLM 降噪引擎
├── podcast_generator.py      # 20分钟播客台本生成、Edge-TTS 与 FFmpeg 高压编码
├── tech_news_purifier/       # 抓取、LLM、数据库、音频与 Feed 核心模块
├── deploy/                   # Nginx、systemd 与防火墙配置
├── tests/                    # 不调用真实 AI/TTS 的离线测试
├── pyproject.toml             # uv 项目依赖与配置
├── .env.example              # 环境变量配置模板
└── README.md                 # 项目主页文档
```

---

## 📄 开源许可证 (License)

本项目采用 [MIT License](./LICENSE) 开源许可证。
