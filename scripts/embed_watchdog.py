#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СТОРОЖ сервера эмбеддингов GOD2: сервис + туннель + публикация адреса.

Что делает (каждые 60 секунд):
  1) сервис эмбеддингов (scripts/embed_service.py) отвечает на /health? если нет —
     поднимает его заново;
  2) туннель cloudflared жив? если нет — поднимает и ждёт новый адрес;
  3) адрес изменился или статус старше 10 минут — публикует embed.json
     в HF-датасет arabyan/god-brain-status: {ok, url, model, dim, index, ts};
  4) сервис или туннель умерли — публикует {ok:false, error:...}: страница тогда
     честно скажет «сервер эмбеддеров не отвечает» и уйдёт в браузерный запасной
     путь (e5-small в браузере) — без секретов в публикуемых файлах.

Ключ NVIDIA лежит на сервере (~/.nvidia_key) и в страницу не попадает; ключ HF
нужен только для публикации статуса (~/.hf_token) и тоже не публикуется.

Запуск (на сервере):
    ~/s46n3/venv/bin/python embed_watchdog.py        # в цикле, с перезапуском
    python3 embed_watchdog.py --once                  # один проход (для проверки)
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
DIR = os.path.join(HOME, "god2-embed")
SERVICE = os.path.join(DIR, "embed_service.py")
LOG = os.path.join(DIR, "embed.log")
TUNNEL_LOG = os.path.join(DIR, "tunnel.log")
CLOUDFLARED = os.environ.get("CLOUDFLARED", os.path.join(HOME, "bin", "cloudflared"))
PORT = int(os.environ.get("EMBED_PORT", "8085"))
MODEL = os.environ.get("EMBED_MODEL", "nvidia/nemotron-3-embed-1b")
DIM = int(os.environ.get("EMBED_DIM", "2048"))
INDEX = os.environ.get("EMBED_INDEX", "data/embeddings_nemotron.bin")
STATUS_REPO = os.environ.get("GOD_STATUS_REPO", "arabyan/god-brain-status")
STATUS_FILE = os.environ.get("GOD_EMBED_STATUS_FILE", "embed.json")
HF_TOKEN_FILE = os.path.expanduser(os.environ.get("HF_TOKEN_FILE", "~/.hf_token"))
PUBLIC_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_last_published = {"url": "", "ts": 0, "ok": None}


def log(msg):
    sys.stderr.write("[watchdog] %s\n" % msg)
    sys.stderr.flush()


def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def tunnel_url():
    """Адрес туннеля из лога cloudflared (он печатает его при старте).

    Читаем лог целиком и берём ПОСЛЕДНИЙ адрес: в логе накапливаются запуски,
    а адрес нового туннеля печатается в самом начале его вывода — в хвосте
    лога его нет."""
    try:
        with io.open(TUNNEL_LOG, encoding="utf-8", errors="replace") as f:
            m = PUBLIC_URL_RE.findall(f.read())
        return m[-1] if m else ""
    except Exception:
        return ""


def tunnel_alive(url):
    """Туннель отвечает? Публикуем адрес только после проверки — иначе страница
    получит мёртвый адрес и не сможет даже честно сообщить о деградации."""
    if not url:
        return False
    try:
        with urllib.request.urlopen(url + "/health", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def start_service():
    log("поднимаю сервис эмбеддингов")
    with io.open(LOG, "ab") as lf:
        subprocess.Popen(["setsid", sys.executable, SERVICE, "--port", str(PORT)],
                         stdout=lf, stderr=lf, cwd=DIR, start_new_session=True)
    time.sleep(3)


def start_tunnel():
    log("поднимаю туннель cloudflared")
    with io.open(TUNNEL_LOG, "ab") as lf:
        lf.write(("\n=== запуск " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n").encode("utf-8"))
        lf.flush()
        subprocess.Popen(["setsid", CLOUDFLARED, "tunnel", "--url",
                          "http://127.0.0.1:%d" % PORT, "--no-autoupdate"],
                         stdout=lf, stderr=lf, cwd=DIR, start_new_session=True)
    for _ in range(40):
        time.sleep(2)
        u = tunnel_url()
        if u:
            return u
    return ""


def publish(ok, url="", error=""):
    """embed.json в HF-датасет — адрес, по которому страница достучится до сервиса."""
    payload = {"ok": bool(ok), "url": url, "model": MODEL, "dim": DIM,
               "index": INDEX, "ts": int(time.time()), "error": error}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    token = io.open(HF_TOKEN_FILE, encoding="utf-8").read().strip()
    from huggingface_hub import HfApi
    HfApi(token=token).upload_file(path_or_fileobj=raw, path_in_repo=STATUS_FILE,
                                   repo_id=STATUS_REPO, repo_type="dataset")
    log("опубликовано %s: ok=%s url=%s" % (STATUS_FILE, ok, url or error))
    return payload


def once():
    h = health()
    if not h:
        start_service()
        h = health()
    url = tunnel_url()
    if not url:
        url = start_tunnel()
    if not h:
        return publish(False, error="сервис эмбеддингов не отвечает")
    if not url:
        return publish(False, error="туннель не поднят")
    if not tunnel_alive(url):
        return publish(False, url=url, error="туннель не отвечает")
    stale = time.time() - _last_published["ts"] > 600
    if _last_published["url"] != url or _last_published["ok"] is not True or stale:
        return publish(True, url=url)
    return _last_published


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if args.once:
        once()
        return
    while True:
        try:
            p = once()
            _last_published.update({"url": p.get("url", ""), "ts": p.get("ts", 0),
                                    "ok": p.get("ok")})
        except Exception as e:
            log("ошибка прохода: %s: %s" % (type(e).__name__, e))
        time.sleep(60)


if __name__ == "__main__":
    main()
