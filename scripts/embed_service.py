#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сервис эмбеддингов запроса для GOD2 — тонкий CORS-прокси к NVIDIA NIM.

Зачем. Векторный путь страницы работает ТОЛЬКО когда лексика молчит, и тогда
решает вектор. Сейчас страница считает вектор запроса в браузере моделью
e5-small (int8-WASM, ~120 МБ скачивания). Серверный путь даёт настоящую
сильную модель (Nemotron-3-Embed-1B, 2048 измерений) без загрузки модели
посетителем: страница спрашивает вектор у этого сервиса.

Безопасность:
  * ключ NVIDIA лежит ТОЛЬКО на сервере (~/.nvidia_key, 600) и в страницу не попадает;
  * сервис слушает 127.0.0.1 — наружу его открывает только туннель cloudflared;
  * наружу отдаётся ровно одна операция: вектор для строки запроса. Никаких
    произвольных моделей и никаких ключей клиента.

Формат ответа — как у OpenAI: {"data":[{"embedding":[...],"index":0}],"model":...}.
Инструкция запроса фиксирована и совпадает с той, что использовалась при сборке
индекса (scripts/build_embeddings.py --model nemotron): иначе вектор запроса и
вектор пассажа оказались бы в разных пространствах.

Запуск (на сервере):
    NIM_KEY_FILE=~/.nvidia_key python3 scripts/embed_service.py
    # или: python3 scripts/embed_service.py --port 8085 --model nvidia/nemotron-3-embed-1b

Проверка:
    curl -s localhost:8085/health
    curl -s -X POST localhost:8085/v1/embeddings -d '{"input":"я боюсь умереть"}' | head -c 120
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# Инструкция запроса. Должна совпадать с той, что применил build_embeddings.py
# при сборке индекса: Nemotron (как и весь nv-embed) различает запрос и пассаж
# именно этой инструкцией.
DEFAULT_INSTRUCT = ("Instruct: Given a user question, retrieve passages from the Hebrew Bible "
                    "that answer it\nQuery: ")
DEFAULT_MODEL = "nvidia/nemotron-3-embed-1b"
DEFAULT_BASE = "https://integrate.api.nvidia.com/v1"


class Service:
    def __init__(self, key, model, base, instruct, dim=2048, max_chars=2000, timeout=90):
        self.key = key
        self.model = model
        self.base = base.rstrip("/")
        self.instruct = instruct
        self.dim = dim
        self.max_chars = max_chars
        self.timeout = timeout

    def embed(self, text):
        """Вектор запроса: инструкция + текст, input_type=query."""
        text = (text or "").strip()
        if not text:
            raise ValueError("пустой запрос")
        if len(text) > self.max_chars:
            text = text[:self.max_chars]
        body = json.dumps({"model": self.model,
                           "input": [self.instruct + text],
                           "input_type": "query",
                           "encoding_format": "float",
                           "truncate": "END"}).encode("utf-8")
        req = urllib.request.Request(self.base + "/embeddings", data=body, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        data = d.get("data") or []
        if not data or not data[0].get("embedding"):
            raise RuntimeError("NIM вернул пустой результат")
        return data[0]["embedding"]


def make_handler(svc):
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "god2-embed/1.0"

        def _cors(self, code=200, ct="application/json"):
            self.send_response(code)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")
            if ct:
                self.send_header("Content-Type", ct)
            self.end_headers()

        def do_OPTIONS(self):
            self._cors(204, None)

        def do_GET(self):
            if self.path.split("?")[0] in ("/health", "/v1/health"):
                self._cors()
                self.wfile.write(json.dumps({
                    "status": "ok", "model": svc.model, "dim": svc.dim,
                    "service": "god2-embed"}).encode("utf-8"))
            else:
                self._cors(404)
                self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))

        def _read_body(self):
            """Тело запроса: и Content-Length, и chunked.

            Туннель cloudflared пересылает POST без Content-Length (Transfer-Encoding:
            chunked) — при чтении по Content-Length тело приходило пустым, и сервис
            отвечал 502 на нормальный запрос.
            """
            if (self.headers.get("Transfer-Encoding", "").lower() == "chunked"):
                chunks = []
                while True:
                    line = self.rfile.readline(65536).strip()
                    if not line:
                        break
                    try:
                        size = int(line.split(b";")[0], 16)
                    except ValueError:
                        break
                    if size == 0:
                        self.rfile.readline(65536)   # пустая строка после нуля
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline(65536)       # CRLF после чанка
                return b"".join(chunks)
            n = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(n) if n else b"{}"

        def do_POST(self):
            if self.path.split("?")[0] != "/v1/embeddings":
                self._cors(404)
                self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))
                return
            try:
                raw = self._read_body()
                req = json.loads(raw.decode("utf-8") or "{}")
                text = req.get("input")
                if isinstance(text, list):
                    text = text[0] if text else ""
                if not isinstance(text, str):
                    raise ValueError("input должен быть строкой")
                vec = svc.embed(text)
                self._cors()
                self.wfile.write(json.dumps({
                    "object": "list",
                    "data": [{"object": "embedding", "index": 0, "embedding": vec}],
                    "model": svc.model, "dim": len(vec)}).encode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode("utf-8", "replace")
                self._cors(502)
                self.wfile.write(json.dumps({"error": "NIM HTTP %d" % e.code,
                                             "detail": detail}).encode("utf-8"))
            except Exception as e:
                sys.stderr.write("[embed] ошибка: %s: %s\n" % (type(e).__name__, e))
                sys.stderr.flush()
                self._cors(502)
                self.wfile.write(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}).encode("utf-8"))

        def log_message(self, fmt, *a):
            sys.stderr.write("[embed] " + (fmt % a) + "\n")

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8085)
    ap.add_argument("--model", default=os.environ.get("NIM_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base", default=os.environ.get("NIM_BASE", DEFAULT_BASE))
    ap.add_argument("--key-file", default=os.environ.get("NIM_KEY_FILE", "~/.nvidia_key"))
    ap.add_argument("--instruct", default=os.environ.get("EMBED_INSTRUCT", DEFAULT_INSTRUCT))
    ap.add_argument("--dim", type=int, default=int(os.environ.get("EMBED_DIM", "2048")))
    args = ap.parse_args()

    key_path = os.path.expanduser(args.key_file)
    if not os.path.exists(key_path):
        raise SystemExit("нет файла ключа: " + key_path)
    key = open(key_path, encoding="utf-8").read().strip()
    if not key:
        raise SystemExit("файл ключа пуст: " + key_path)

    svc = Service(key, args.model, args.base, args.instruct, dim=args.dim)
    import http.server
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), make_handler(svc))
    sys.stderr.write("[embed] %s dim=%d на %s:%d (ключ из %s)\n"
                     % (args.model, args.dim, args.host, args.port, key_path))
    sys.stderr.flush()
    httpd.serve_forever()


if __name__ == "__main__":
    main()
