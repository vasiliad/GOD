"""Перезапуск мозга GOD: убить живую сессию Kaggle, запушить свежую, дождаться ok:true.

Запуск локально:  python brain/restart_brain.py   (или brain/restart_brain.bat)
Запуск кнопкой:   GitHub -> vasiliad/GOD -> Actions -> "Restart GOD brain" -> Run workflow
                  (нужны секреты репозитория KAGGLE_KEY и HF_TOKEN, см. brain/README.md)

Аутентификация Kaggle: локально — ~/.kaggle/kaggle.json; в Actions — env KAGGLE_USERNAME/KAGGLE_KEY.
Токен HF: локально — .agent/hf_token; в Actions — env HF_TOKEN.
"""
import json, os, shutil, subprocess, sys, time, urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(REPO)
KREF = "vasiliadi911/god-brain-server"
STATUS_URL = "https://huggingface.co/datasets/arabyan/god-brain-status/resolve/main/brain.json"


def log(*a):
    print(*a, flush=True)


def ensure_kaggle_auth():
    """Новые kaggle CLI (2.2+) для KGAT-токенов читают env KAGGLE_API_TOKEN или файл
    ~/.kaggle/access_token — kaggle.json они игнорируют. Пишем оба, чтобы работало везде."""
    k = os.environ.get("KAGGLE_KEY")
    if not k:
        return
    kd = os.path.expanduser("~/.kaggle")
    os.makedirs(kd, exist_ok=True)
    with open(os.path.join(kd, "access_token"), "w") as f:
        f.write(k)
    os.environ["KAGGLE_API_TOKEN"] = k
    log("~/.kaggle/access_token + KAGGLE_API_TOKEN установлены из KAGGLE_KEY")


def main():
    ensure_kaggle_auth()
    hf = os.environ.get("HF_TOKEN") or open(os.path.join(ROOT, ".agent", "hf_token")).read().strip()
    src = open(os.path.join(REPO, "kernel.py"), encoding="utf-8").read()
    pushdir = os.path.join(REPO, "_kagglepush")
    os.makedirs(pushdir, exist_ok=True)
    open(os.path.join(pushdir, "kernel.py"), "w", encoding="utf-8").write(src.replace("__HF_TOKEN__", hf))
    shutil.copy(os.path.join(REPO, "kernel-metadata.json"), pushdir)
    log("push-каталог собран (токен только там, он же в .gitignore)")

    try:
        import kaggle
        api = kaggle.KaggleApi()
        api.authenticate()
        api.kernels_delete(KREF, no_confirm=True)
        log("живая сессия убрана (delete) — свежая стартует сразу, без очереди")
    except Exception as e:
        log("delete пропущен (ядра не было?):", e)

    t0 = time.time()
    proc = subprocess.run([sys.executable, "-m", "kaggle", "kernels", "push", "-p", pushdir],
                          capture_output=True, text=True)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        log("kaggle push:", out[-800:])
    low = out.lower()
    if proc.returncode != 0 or "kernel push error" in low:
        # Частая причина — исчерпана недельная квота Kaggle GPU (30 ч/нед):
        # сессия не запустится, ждать пульса бессмысленно. Говорим причину сразу.
        reason = ("КВОТА KAGGLE GPU исчерпана (30 ч/нед) — сессия не запустится"
                  if "quota" in low else "push не прошёл")
        log("МОЗГ НЕ ПОДНЯТСЯ:", reason)
        log("публичный мозг спит до сброса квоты; auto-heal повторит через 6 ч")
        return 3
    log("запушено; жду мозг (пульс brain.json, до 20 мин)...")
    deadline = t0 + 1200
    while time.time() < deadline:
        time.sleep(60)
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=15) as r:
                d = json.loads(r.read())
            fresh = d.get("ts", 0) > t0           # принимаем только пульс НОВОЙ сессии
            if d.get("ok") and fresh and d.get("url"):
                log("МОЗГ ОНЛАЙН:", d["url"])
                log("модель:", d.get("model"), "| ускоритель:", d.get("accel"))
                return 0
            log("...пульс:", d.get("ok"), "| возраст, мин:", int((time.time() - d.get("ts", 0)) / 60))
        except Exception as e:
            log("...ещё нет:", e)
    log("мозг не поднялся за 20 мин — открой kaggle.com/code/" + KREF + " и смотри лог сессии")
    return 1


if __name__ == "__main__":
    sys.exit(main())
