#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальный мозг: та же модель и тот же квант, что на Kaggle.

  модель: dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF
  файл:   DictaLM-3.0-Nemotron-12B-Instruct-Q5_K_M.gguf  (Q5_K_M — как на Kaggle)
  рантайм: .agent/llama/llama-server.exe (сборка с CUDA)

Зачем: квота Kaggle исчерпана, а проверять качество и перезаписывать витрину
нужно на ТОЙ ЖЕ модели. Этот скрипт поднимает её на локальной RTX 5090 и
пишет brain/brain_local.json — того же формата, что brain.json в HF-датасете,
поэтому страница (⚙ → endpoint) и скрипты записи работают с ним без правок.

Запуск:
    python brain/start_local_brain.py            # поднять и дождаться готовности
    python brain/start_local_brain.py --stop     # остановить
    python brain/start_local_brain.py --status   # что поднято сейчас
"""
import argparse
import io
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
LLAMA_DIR = _ROOT / ".agent" / "llama"
SERVER = LLAMA_DIR / "llama-server.exe"
MODEL = _ROOT / ".agent" / "hf_models" / "DictaLM-3.0-Nemotron-12B-Instruct-Q5_K_M.gguf"
LOG = _ROOT / ".agent" / "llama_server.log"
STATUS = _ROOT / "brain" / "brain_local.json"
PIDFILE = _ROOT / ".agent" / "llama_server.pid"

HOST = "127.0.0.1"
PORT = 18099
API_KEY = "godbrain-v1-vasiliad"
MODEL_NAME = "dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF"
CTX = 16384


def cuda_runtime_dir():
    """Каталог с cudart/cublas: ggml-cuda.dll без них не видит GPU.

    Берём из установленного torch (CUDA 12.8) — отдельного CUDA-тулчейна в
    проекте нет, а torch ставился под ту же карту.
    """
    try:
        import torch
        d = Path(torch.__file__).resolve().parent / "lib"
        if (d / "cudart64_12.dll").exists():
            return str(d)
    except Exception as e:
        print("torch не найден (%s) — CUDA-библиотеки не подключатся" % e)
    return None


def health(timeout=3):
    try:
        with urllib.request.urlopen("http://%s:%d/health" % (HOST, PORT), timeout=timeout) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


def stop():
    pid = None
    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text(encoding="utf-8").strip())
        except Exception:
            pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print("остановлен pid %d" % pid)
        except Exception as e:
            print("не удалось остановить pid %d: %s" % (pid, e))
    try:
        subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                       capture_output=True, timeout=30)
    except Exception:
        pass
    if PIDFILE.exists():
        PIDFILE.unlink()


def start(wait=180):
    if not SERVER.exists():
        print("нет сборки сервера: %s" % SERVER)
        return 2
    if not MODEL.exists():
        print("нет файла модели: %s" % MODEL)
        return 2
    if health():
        print("сервер уже поднят на порту %d" % PORT)
        write_status()
        return 0
    env = dict(os.environ)
    rt = cuda_runtime_dir()
    if rt:
        env["PATH"] = rt + os.pathsep + env.get("PATH", "")
    cmd = [str(SERVER), "-m", str(MODEL), "--host", HOST, "--port", str(PORT),
           "--ctx-size", str(CTX), "--n-gpu-layers", "999", "--api-key", API_KEY, "--parallel", "1"]
    print("запускаю:", " ".join(cmd))
    print("CUDA-библиотеки:", rt or "(не найдены — будет CPU)")
    with io.open(LOG, "a", encoding="utf-8", newline="\n") as log:
        log.write("\n=== запуск %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        log.flush()
        p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    PIDFILE.write_text(str(p.pid), encoding="utf-8")
    t0 = time.time()
    while time.time() - t0 < wait:
        if health():
            print("мозг готов за %.1f с: http://%s:%d" % (time.time() - t0, HOST, PORT))
            write_status()
            return 0
        if p.poll() is not None:
            print("сервер упал, код %s — смотри %s" % (p.returncode, LOG))
            return 2
        time.sleep(2)
    print("сервер не ответил за %d с" % wait)
    return 2


def write_status():
    payload = {
        "ok": True,
        "url": "http://%s:%d" % (HOST, PORT),
        "key": API_KEY,
        "model": MODEL_NAME,
        "model_files": [MODEL.name],
        "accel": "cuda-local",
        "ts": int(time.time()),
        "port": PORT,
        "note": "локальный мозг: тот же DictaLM-3.0-Nemotron-12B Q5_K_M, что на Kaggle",
    }
    with io.open(STATUS, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=1))
    print("статус: %s" % STATUS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Локальный мозг (тот же DictaLM 12B Q5_K_M, CUDA).")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--wait", type=int, default=180)
    args = ap.parse_args(argv)
    if args.stop:
        stop()
        return 0
    if args.status:
        print("жив: %s" % health())
        if STATUS.exists():
            print(io.open(STATUS, encoding="utf-8").read())
        return 0
    stop()
    rc = start(args.wait)
    return rc


if __name__ == "__main__":
    sys.exit(main())
