# -*- coding: utf-8 -*-
import http.server
import socketserver
import os

PORT = 80
DIRECTORY = '/opt/tech-news-purifier/podcast'

class PodcastHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def send_my_headers(self, clean_path):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Accept-Ranges', 'bytes')
        if clean_path.endswith('.xml'):
            self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
        elif clean_path.endswith('.mp3'):
            self.send_header('Content-Type', 'audio/mpeg')

    def end_headers(self):
        clean_path = self.path.split('?')[0].lower()
        self.send_my_headers(clean_path)
        super().end_headers()

    def do_GET(self):
        """
        支持 HTTP Byte-Range 请求 (206 Partial Content)，
        完美兼容 Apple Podcasts / iOS AVPlayer 的音频流式播放与拖拽。
        """
        path = self.translate_path(self.path.split('?')[0])
        range_header = self.headers.get('Range')

        if not os.path.isfile(path) or not range_header or not range_header.startswith('bytes='):
            return super().do_GET()

        try:
            size = os.path.getsize(path)
            range_str = range_header.replace('bytes=', '').strip()
            parts = range_str.split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else size - 1

            if start >= size or end >= size or start > end:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return

            length = end - start + 1
            self.send_response(206)
            clean_path = self.path.split('?')[0].lower()
            self.send_my_headers(clean_path)
            self.send_header('Content-Length', str(length))
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            super().end_headers()

            with open(path, 'rb') as f:
                f.seek(start)
                remaining = length
                buffer_size = 64 * 1024
                while remaining > 0:
                    chunk = f.read(min(remaining, buffer_size))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f"[!] Range request error: {e}")

class ReusableThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == '__main__':
    os.makedirs(DIRECTORY, exist_ok=True)
    handler = PodcastHTTPRequestHandler
    try:
        print(f"📻 播客 HTTP 服务启动中，端口 {PORT}...")
        httpd = ReusableThreadingHTTPServer(('0.0.0.0', PORT), handler)
        print(f"✅ 播客 HTTP 服务在线（已开启 Byte-Range 206 串流）！监听端口: {PORT}")
        httpd.serve_forever()
    except Exception as e:
        print(f"⚠️ 端口 {PORT} 绑定失败 ({e})，尝试备用 8080 端口...")
        PORT = 8080
        httpd = ReusableThreadingHTTPServer(('0.0.0.0', PORT), handler)
        print(f"✅ 播客 HTTP 服务在线（已开启 Byte-Range 206 串流）！监听端口: {PORT}")
        httpd.serve_forever()
