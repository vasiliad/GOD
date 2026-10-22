#!/usr/bin/env python3
"""CORS proxy для NVIDIA NIM — держит API ключ, добавляет CORS, пересылает."""
import http.server, urllib.request, json, sys

NVIDIA_KEY = open("/opt/nim_key.txt").read().strip()
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"

class Handler(http.server.BaseHTTPRequestHandler):
    def send_cors(self, code=200, ct="application/json"):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        if ct:
            self.send_header("Content-Type", ct)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_cors(200, None)

    def do_GET(self):
        if self.path == "/health":
            self.send_cors()
            self.wfile.write(b'{"status":"ok","proxy":"nim"}')
        else:
            self.send_cors(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        url = NVIDIA_BASE + self.path
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {NVIDIA_KEY}"
        })
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                result = r.read()
                self.send_cors()
                self.wfile.write(result)
        except urllib.error.HTTPError as e:
            self.send_cors(e.code)
            self.wfile.write(e.read())
        except Exception as e:
            self.send_cors(502)
            self.wfile.write(json.dumps({"error": str(e)}).encode())

if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("NIM proxy running on :8080")
    server.serve_forever()
