"""
GOD brain kernel — LLM-сервер «мозг» чата vasiliad.github.io/GOD.

Платформа: Kaggle (GPU T4x2/P100, linux) — основной режим; локальный запуск
(Windows/CPU) — режим самопроверки (GOD_LOCAL_TEST=1, крошечная модель).

Поток ядро:
  1) скачать свежую сборку llama.cpp (ubuntu-cuda) и GGUF модели
  2) поднять llama-server (OpenAI-совместимый, /v1/chat/completions, /health)
  3) пробросить наружу туннелем cloudflared (quick tunnel, без аккаунта)
  4) самопроверка: реальный запрос через туннель + CORS-проверка
  5) опубликовать brain.json (url/key/model/ts) в HF-датасет god-brain-status
  6) пульс каждые 15 мин: модель жива → обновлённый ts; смерть → ok:false

Страница чата читает brain.json, берёт url и шлёт туда промпты.
Токен HF подставляется при пуше в Kaggle (в git только плейсхолдер).
"""
import base64, json, os, re, shutil, subprocess, sys, tarfile, time, zipfile
import urllib.parse, urllib.request

# ---------------- конфиг ----------------
PORT = 8123
API_KEY = "godbrain-v1-vasiliad"
STATUS_REPO = "arabyan/god-brain-status"
STATUS_FILE = os.environ.get("GOD_STATUS_FILE", "brain.json")
HF_TOKEN = os.environ.get("HF_TOKEN", "__HF_TOKEN__")   # плейсхолдер; подменяется при пуше

LOCAL_TEST = os.environ.get("GOD_LOCAL_TEST") == "1"
IS_WIN = sys.platform.startswith("win")
WORK = os.environ.get("GOD_WORK", os.getcwd())
BIN_DIR = os.path.join(WORK, "bin")
MDL_DIR = os.path.join(WORK, "model")

if LOCAL_TEST:
    MODEL_REPO = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
    MODEL_FILES = ["qwen2.5-0.5b-instruct-q4_k_m.gguf"]
else:
    MODEL_REPO = "Qwen/Qwen2.5-14B-Instruct-GGUF"
    MODEL_FILES = [f"qwen2.5-14b-instruct-q4_k_m-{i:05d}-of-00003.gguf" for i in (1, 2, 3)]

LOG = print


def log(*a):
    LOG(*a, flush=True)


def http_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def download(url, dest, timeout=1800):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    log("download:", url, "->", dest)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


# ---------------- 1) llama.cpp ----------------
def latest_llamacpp_release():
    """Свежая дневная сборка bNNNNN (у них >30 ассетов; у тегов vN.N.N ассетов нет)."""
    rels = http_json("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=12")
    for r in rels:
        if len(r.get("assets", [])) > 20:
            return r
    raise RuntimeError("нет сборок llama.cpp с ассетами")


def pick_asset(rel, match):
    """match(name)->bool; возвращает URL первого подходящего ассета."""
    for a in rel["assets"]:
        if match(a["name"]):
            return a["browser_download_url"]
    return None


def setup_llamacpp():
    rel = latest_llamacpp_release()
    tag = rel["tag_name"]
    log("llama.cpp build:", tag)
    os.makedirs(BIN_DIR, exist_ok=True)
    if IS_WIN:
        url = pick_asset(rel, lambda n: "bin-win-cpu-x64" in n)
    else:
        url = pick_asset(rel, lambda n: "bin-ubuntu-cuda-12.8-x64" in n) \
              or pick_asset(rel, lambda n: "bin-ubuntu-cuda-12.4-x64" in n)
    if not url and not IS_WIN:
        url = pick_asset(rel, lambda n: n.endswith("bin-ubuntu-x64.tar.gz"))
    dest = os.path.join(BIN_DIR, "llama_dist")
    if url.endswith(".zip"):
        download(url, dest + ".zip")
        with zipfile.ZipFile(dest + ".zip") as z:
            z.extractall(dest)
    else:
        download(url, dest + ".tar.gz")
        with tarfile.open(dest + ".tar.gz") as t:
            t.extractall(dest)
    exe = "llama-server.exe" if IS_WIN else "llama-server"
    for root, _, files in os.walk(dest):
        if exe in files:
            p = os.path.join(root, exe)
            if not IS_WIN:
                os.chmod(p, 0o755)
            return p
    raise RuntimeError("llama-server не найден в сборке")


# ---------------- 2) модель ----------------
def setup_model():
    os.makedirs(MDL_DIR, exist_ok=True)
    paths = []
    for fn in MODEL_FILES:
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{urllib.parse.quote(fn)}"
        p = os.path.join(MDL_DIR, fn)
        if not os.path.exists(p):
            download(url, p)
        paths.append(p)
    return paths[0]


# ---------------- 3) сервер ----------------
def start_server(exe, model_path):
    def spawn():
        env = dict(os.environ)
        if not IS_WIN and not LOCAL_TEST:
            env["CUDA_VISIBLE_DEVICES"] = "0"
        cmd = [exe, "-m", model_path, "--host", "127.0.0.1", "--port", str(PORT),
               "-c", "8192" if LOCAL_TEST else "16384",
               "--parallel", "1" if LOCAL_TEST else "2",
               "--api-key", API_KEY, "--alias", "god-brain", "--no-webui"]
        if not IS_WIN and not LOCAL_TEST:
            cmd += ["-ngl", "99", "-fa"]
        log("cmd:", " ".join(cmd))
        return subprocess.Popen(cmd, stdout=open(os.path.join(WORK, "server.log"), "w"),
                                stderr=subprocess.STDOUT, env=env)

    srv = spawn()
    for attempt in (1, 2):
        for _ in range(120):
            time.sleep(5)
            if srv.poll() is None:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5) as r:
                        if json.loads(r.read()).get("status") == "ok":
                            log("llama-server: готов, модель загружена")
                            return srv
                except Exception:
                    pass
            else:
                log(f"llama-server умер (код {srv.returncode}), попытка {attempt}; tail лога:")
                os.system(f"tail -c 2000 '{os.path.join(WORK, 'server.log')}' 2>/dev/null || "
                          f"powershell -c \"Get-Content '{os.path.join(WORK, 'server.log')}' -Tail 20\"")
                break
        if attempt == 1 and not IS_WIN and not LOCAL_TEST:
            # у сервера CUDA-сборка: если упал на рантайме — кладём рядом бандл cudart и пробуем снова
            log("подкладываю cudart-бандл и повторяю")
            try:
                rel = latest_llamacpp_release()
                url = pick_asset(rel, lambda n: "cudart-llama-" in n and
                                "bin-ubuntu-cuda-12.8-x64" in n)
                if url:
                    p = os.path.join(BIN_DIR, "cudart.tar.gz")
                    download(url, p)
                    with tarfile.open(p) as t:
                        t.extractall(os.path.dirname(exe))
                    srv = spawn()
                    continue
            except Exception as e:
                log("cudart-фолбэк не удался:", repr(e))
    raise RuntimeError("llama-server не поднялся; см. server.log")


# ---------------- 4) туннель ----------------
def start_tunnel():
    exe = os.path.join(BIN_DIR, "cloudflared.exe" if IS_WIN else "cloudflared")
    if not os.path.exists(exe):
        name = "cloudflared-windows-amd64.exe" if IS_WIN else "cloudflared-linux-amd64"
        download(f"https://github.com/cloudflare/cloudflared/releases/latest/download/{name}", exe)
        if not IS_WIN:
            os.chmod(exe, 0o755)
    log("start cloudflared quick tunnel")
    cf_log = open(os.path.join(WORK, "cf.log"), "w")
    subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}",
                      "--no-autoupdate", "--protocol", "http2"],
                     stdout=cf_log, stderr=subprocess.STDOUT)
    url_re = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(3)
        try:
            txt = open(os.path.join(WORK, "cf.log"), encoding="utf-8", errors="replace").read()
            m = url_re.search(txt)
            if m:
                log("tunnel URL:", m.group(0))
                return m.group(0)
        except Exception:
            pass
    raise RuntimeError("туннель не поднялся за 3 мин; см. cf.log")


# ---------------- 5) самопроверка ----------------
def self_test(url):
    body = json.dumps({"messages": [{"role": "user", "content": "Ответь одним словом: Шалом"}],
                       "max_tokens": 20, "temperature": 0.1}).encode()
    req = urllib.request.Request(url + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + API_KEY,
                                          "Origin": "https://vasiliad.github.io"})
    with urllib.request.urlopen(req, timeout=300) as r:
        j = json.loads(r.read())
        cors = r.headers.get("Access-Control-Allow-Origin")
    content = j["choices"][0]["message"]["content"]
    log("self-test ответ:", content[:80].replace("\n", " "))
    log("CORS Access-Control-Allow-Origin:", cors)
    if not content:
        raise RuntimeError("пустой ответ модели")
    if cors != "*":
        log("ВНИМАНИЕ: CORS не '*', возможно нужен прокси")
    return content


# ---------------- 6) публикация статуса ----------------
def publish(status):
    from huggingface_hub import HfApi
    payload = dict(status)
    payload["ts"] = int(time.time())
    payload["port"] = PORT
    payload["repo"] = STATUS_REPO
    raw = json.dumps(payload, ensure_ascii=False).encode()
    HfApi(token=HF_TOKEN).upload_file(path_or_fileobj=raw, path_in_repo=STATUS_FILE,
                                      repo_id=STATUS_REPO, repo_type="dataset")
    log("статус опубликован:", STATUS_FILE, "->", STATUS_REPO)


def server_alive():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


# ---------------- главный поток ----------------
def main():
    log("=== GOD brain kernel ===")
    log("python:", sys.version.split()[0], "| platform:", sys.platform,
        "| LOCAL_TEST:", LOCAL_TEST, "| work:", WORK)
    if not IS_WIN:
        os.system("nvidia-smi --query-gpu=name,memory.total --format=csv 2>/dev/null || echo 'nvidia-smi недоступен'")
    try:
        exe = setup_llamacpp()
        model_path = setup_model()
        srv = start_server(exe, model_path)
        url = start_tunnel()
        self_test(url)
        status = {"ok": True, "url": url, "key": API_KEY, "model": MODEL_REPO,
                  "accel": "cpu-local" if LOCAL_TEST else ("gpu" if not IS_WIN else "cpu-win"),
                  "model_files": MODEL_FILES, "error": None}
        publish(status)
        log("ГОТОВО: мозг онлайн ->", url)
        # пульс: обновляем ts каждые 15 мин; при смерти сервера — ok:false
        while True:
            time.sleep(900)
            alive = server_alive()
            log("heartbeat: server_alive =", alive)
            publish(dict(status, ok=alive, error=None if alive else "llama-server не отвечает"))
            if not alive:
                log("попытка перезапуска llama-server")
                try:
                    srv.kill()
                except Exception:
                    pass
                srv = start_server(exe, model_path)
                publish(dict(status, ok=True))
    except Exception as e:
        log("ОШИБКА:", repr(e))
        try:
            publish({"ok": False, "url": None, "key": API_KEY, "model": MODEL_REPO,
                     "accel": None, "error": repr(e)})
        except Exception as e2:
            log("не удалось опубликовать статус:", repr(e2))
        # в автономном режиме держим процесс живым, чтобы лог читался в UI Kaggle
        time.sleep(3600)


if __name__ == "__main__":
    main()
