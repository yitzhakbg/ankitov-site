#!/usr/bin/env python3
"""Static file server with no-cache + HTTP Range support (needed for <video> seeking/audio)."""
import http.server, socketserver, os, re, sys

class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()
    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try: f = open(path, 'rb')
        except OSError:
            self.send_error(404, "File not found"); return None
        try:
            fs = os.fstat(f.fileno())
            size = fs.st_size
            m = re.match(r'bytes=(\d+)-(\d*)', self.headers.get('Range','') or '')
            if m:
                start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size-1
                end = min(end, size-1)
                if start > end or start >= size:
                    self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); f.close(); return None
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.send_header('Content-Length', str(end-start+1))
                self.send_header('Content-Type', self.guess_type(path))
                self.end_headers()
                f.seek(start)
                return _RangeFile(f, end-start+1)
            self.send_response(200)
            self.send_header('Content-Length', str(size))
            self.send_header('Content-Type', self.guess_type(path))
            self.end_headers()
            return f
        except Exception:
            f.close(); raise

class _RangeFile:
    def __init__(self, f, remaining): self.f=f; self.remaining=remaining
    def read(self, n=-1):
        if self.remaining<=0: return b''
        data = self.f.read(self.remaining if n<0 else min(n,self.remaining))
        self.remaining -= len(data)
        return data

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    port = int(sys.argv[1]); bind = sys.argv[2]
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    with Server((bind, port), Handler) as httpd:
        print(f"serving no-cache+ranges on {bind}:{port}", flush=True)
        httpd.serve_forever()
