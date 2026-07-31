# 生产部署（IP + 23654）

生产入口：

- Podcast：`http://47.115.165.231:23654/feed.xml`
- OneAPI：`http://47.115.165.231:3000/v1`（本项目不修改）

本部署不使用域名、Cloudflare 或 HTTPS。Podcast 客户端需要重新订阅新地址。

## 目录与权限

- 代码：`/opt/tech-news-purifier`，root 持有并保持只读。
- 数据：`/var/lib/tech-news-purifier`，`technews:technews` 持有。
- 环境：`/etc/tech-news-purifier.env`，权限 `640 root:technews`。
- 日志：`/var/log/tech-news-purifier/pipeline.log`，由 logrotate 每周轮转。

项目目录不得保留生产 `.env`。`SERVER_BASE_URL` 必须为
`http://47.115.165.231:23654`，OneAPI 内部调用保持
`http://127.0.0.1:3000/v1/chat/completions`。

## 服务

- Nginx 只监听 `23654`，根路径返回 404，仅提供 Feed、封面、音频和章节。
- `tech-news-pipeline.timer` 每天 Asia/Shanghai 07:30 运行一次。
- `tech-news-failure@.service` 在失败时调用 `ALERT_WEBHOOK_URL`。
- 原 `tech-news-podcast.service` 和 root cron 在新入口通过验收后停用。

## 防火墙顺序

1. 确认阿里云安全组已允许 TCP `22`、`3000`、`23654`。
2. UFW 先允许 `22`、`3000`、`23654`，再启用并验证第二条 SSH 连接。
3. 验证 Podcast 新入口和 OneAPI 后拒绝 `80`，再删除安全组中的 80 规则。

## 验收

```bash
systemctl status tech-news-pipeline.timer
journalctl -u tech-news-pipeline.service -n 200 --no-pager
curl -I http://47.115.165.231:23654/feed.xml
curl -I -H 'Range: bytes=0-99' http://47.115.165.231:23654/audio/<episode>.mp3
```

必须验证根路径 404、目录列表关闭、Range 206/416、Feed 与 Chapters 可解析、
80 不可达、OneAPI 3000 未受影响。生成失败或音频不在 18–22 分钟时保留上一期。

## 回滚

恢复部署前备份的数据库、Feed、环境文件、旧 systemd 单元、cron、Nginx 和 UFW
状态，再启用旧 Podcast 服务。若已删除安全组 80 规则，回滚时重新放行。
