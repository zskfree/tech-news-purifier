# -*- coding: utf-8 -*-
import http.server
import socketserver
import os

PORT = 80
DIRECTORY = '/opt/tech-news-purifier/podcast'

class PodcastHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        clean_path = self.path.split('?')[0].lower()
        if clean_path.endswith('.xml'):
            self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
        elif clean_path.endswith('.mp3'):
            self.send_header('Content-Type', 'audio/mpeg')
        super().end_headers()

class ReusableThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True

if __name__ == '__main__':
    os.makedirs(DIRECTORY, exist_ok=True)
    handler = PodcastHTTPRequestHandler
    try:
        print(f"📻 播客 HTTP 服务启动中，端口 {PORT}...")
        httpd = ReusableThreadingHTTPServer(('0.0.0.0', PORT), handler)
        print(f"✅ 播客 HTTP 服务在线！监听端口: {PORT}")
        httpd.serve_forever()
    except Exception as e:
        print(f"⚠️ 端口 {PORT} 绑定失败 ({e})，尝试备用 8080 端口...")
        PORT = 8080
        httpd = ReusableThreadingHTTPServer(('0.0.0.0', PORT), handler)
        print(f"✅ 播客 HTTP 服务在线！监听端口: {PORT}")
        httpd.serve_forever()
