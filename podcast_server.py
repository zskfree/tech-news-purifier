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
        if self.path.endswith('.xml'):
            self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
        super().end_headers()

if __name__ == '__main__':
    os.makedirs(DIRECTORY, exist_ok=True)
    print(f'📻 播客 HTTP 服务启动中，端口 {PORT}...')
    handler = PodcastHTTPRequestHandler
    try:
        with socketserver.TCPServer(('0.0.0.0', PORT), handler) as httpd:
            print(f'✅ 播客 HTTP 服务在线！监听端口: {PORT}')
            httpd.serve_forever()
    except Exception as e:
        print(f'端口 {PORT} 启动失败，尝试使用 8080 端口: {e}')
        PORT = 8080
        with socketserver.TCPServer(('0.0.0.0', PORT), handler) as httpd:
            print(f'✅ 播客 HTTP 服务在线！监听端口: {PORT}')
            httpd.serve_forever()
