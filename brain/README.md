# GOD brain — LLM-мозг чата на бесплатном Kaggle

Назначение: живой режим чата на https://vasiliad.github.io/GOD/ работает через
LLM-сервер, который крутится в Kaggle-ноутбуке (аккаунт vasiliadi911, бесплатный
GPU T4x2/P100, ~30 ч/неделю, сессия ≤12 ч). HF-пути (Space/router) закрыты без
PRO/кредитов — проверено 2026-10-19: Space-creation отдаёт 402 даже на cpu-basic.

## Архитектура

    страница (retrieval в браузере, 2050 эпизодов)
        ↓ POST /v1/chat/completions (OpenAI-формат, ключ-константа из brain.json)
    cloudflared quick tunnel (https://xxx.trycloudflare.com, без аккаунта)
        ↓
    llama-server (llama.cpp, Qwen2.5-14B-Instruct q4_k_m, --api-key, CORS *)
        ↓ heartbeat каждые 15 мин (ts)
    HF-датасет arabyan/god-brain-status → brain.json {url,key,model,ts,ok}

Страница сама читает brain.json (CORS на HF resolve подтверждён), берёт url и
ключ; если ts старше часа или ok:false — мозг офлайн, живой режим честно
фолбэкится на корпусный ответ.

## Файлы

- `kernel.py` — ядро (скачивает свежую дневную сборку llama.cpp + GGUF, поднимает
  сервер, туннель, самопроверку, публикует пульс). В git токен НЕ хранится —
  плейсхолдер `__HF_TOKEN__`, подставляется при пуше в Kaggle.
- `kernel-metadata.json` — метаданные kaggle kernels push.
- `test_page.js` — Node-тесты JS страницы (10 проверок: офлайн/онлайн/ошибка).
- `_localtest/` — временный каталог локальной отладки (не коммитить).

## Запуск / перезапуск мозга

1. Раз в ~12 ч сессия Kaggle умирает (лимит) — мозг засыпает, brain.json
   протухает, страница это видит (🔴) и отвечает корпусом.
2. Перезапуск: https://www.kaggle.com/code/vasiliadi911/god-brain → Run All
   (или `kaggle kernels push` из этого каталога с подстановкой токена).
3. Первый ответ после старта ~3-6 мин (загрузка модели в VRAM).

## Локальная самопроверка ядра (Windows, крошечная модель)

    cd brain && mkdir -p _localtest
    HF_TOKEN=$(cat ../.agent/hf_token) GOD_LOCAL_TEST=1 \
      GOD_STATUS_FILE=brain_localtest.json GOD_WORK="$(pwd)/_localtest" python kernel.py

Пишет статус в тестовый файл того же датасета, туннель настоящий.

## Экспериментальный TPU

TPU VM v3-8 (128 ГБ HBM) на аккаунте есть (`malysh-tpu-probe`), но у torch_xla
на v3-8 нет KV-cache → генерация минутная; GPU+llama.cpp надёжнее. Для попытки:
заменить скачивание на jax/maxtext-стек — отдельная задача.
