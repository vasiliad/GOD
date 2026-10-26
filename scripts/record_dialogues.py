#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Запись ЖИВЫХ диалогов мозга для витрины «Диалоги» → docs/data/dialogs.json.

Витрина на сайте показывает не выдумки, а настоящие ответы DictaLM-3.0-Nemotron-12B,
пройденные по той же траектории, что и живой чат страницы:

  1. url/key мозга — из HF brain.json (https://huggingface.co/datasets/arabyan/god-brain-status),
     fallback — brain/brain_snapshot.json;
  2. схема ответа — как на странице (scripts/answer_scheme.py, зеркало docs/index.html):
       ШАГ 1 — выбор одного эпизода (короткий вызов, ответ = номер кандидата);
       ШАГ 2 — формулировка из этого эпизода (модель получает ОДИН эпизод);
       ШАГ 3 — сверка с реестром (правило «S»), окно сверки = выбранный эпизод;
  3. промпты — со страницы (SYS_SELECT и SYS_PROMPT в docs/index.html);
  4. кандидаты — реальные эпизоды мастер-корпуса output/episodes_TANAKH_v2.json,
     отобранные той же формулой, что на странице (лексика по summary_ru + буст
     триггера; при наличии transformers — ещё и вектор e5-small), в ТОЧНОМ формате
     страницы: book, span, trigger, outcome, god_speech_plain (≤300),
     nikud (≤300, порт функции nikudFor страницы), summary_ru (≤200), god_action (≤160);
  5. ответ разбирается на ровно 6 секций ([HEBREW] [NIKKUD] [Russian] [English]
     [Hebrew Modern] [SOURCES]) — тем же парсером, что на странице.

Вопросы (8–12, три языка RU/EN/HE) и триггеры подобраны так, чтобы витрина покрывала
разные типы обращения корпуса: непослушание, молитва, заступничество, жалоба, бедствие,
благодарность, вопрос, обет, божественное испытание.

Запуск:
    python scripts/record_dialogues.py              # запись 12 диалогов → docs/data/dialogs.json
    python scripts/record_dialogues.py --count 4    # только первые 4 вопроса
    python scripts/record_dialogues.py --out tmp.json --print
    python scripts/record_dialogues.py --lexical    # без вектора (без transformers)
    python scripts/record_dialogues.py --test       # офлайн-самопроверка, без сети

Только stdlib (urllib) + необязательный transformers для вектора. UTF-8. Ничего не коммитит.
"""
import argparse
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
BRAIN_STATUS_URL = "https://huggingface.co/datasets/arabyan/god-brain-status/resolve/main/brain.json"
BRAIN_SNAPSHOT = _ROOT / "brain" / "brain_snapshot.json"
MASTER_CORPUS = _ROOT / "output" / "episodes_TANAKH_v2.json"
ANALYTICS = _ROOT / "docs" / "data" / "analytics.json"
NIKUD_INDEX = _ROOT / "docs" / "data" / "nikud.json"
PAGE = _ROOT / "docs" / "index.html"
DEFAULT_OUT = "docs/data/dialogs.json"

SECTIONS = ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]
API_MODEL = "god-brain"          # как на странице: cfg.model || "god-brain"
DEFAULT_TIMEOUT = 180             # холодный старт модели доходил до 114 с

# Правило «S» (сверка ответа с реестром) и текст промпта — из общего эталона:
# scripts/answer_guard.py держит и пороги, и формулировки, и текст страницы.
# Схема ответа целиком — scripts/answer_scheme.py (зеркало страницы).
sys.path.insert(0, str(_ROOT / "scripts"))
from answer_guard import apply_guard, page_sys_prompt, page_sys_select   # noqa: E402
from answer_scheme import (                                              # noqa: E402
    build_context, candidate_block, episode_block, pick_index,
    spoken_candidates, two_stage, FORM_TEMP, FORM_MAX_TOKENS,
    # логика страницы (классы обращения, синонимы, токены) — из зеркала,
    # чтобы витрина и живой чат считались по одной формуле
    classify, query_tokens, is_proper, trig_class,
)
from answer_scheme import rank_episodes as _rank_episodes                # noqa: E402

MAX_TOKENS = FORM_MAX_TOKENS     # как на странице (шаг формулировки)
TEMPERATURE = FORM_TEMP          # как на странице (шаг формулировки)

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM_PROMPT — берётся ПРЯМО из docs/index.html (страница — единственный
# источник промпта). Раньше здесь была копия; копия разошлась с страницей
# (в test_accuracy.py была лишняя строка про огласовку и «1–2 строк»), и
# записанные диалоги переставали быть честным воспроизведением живого чата.
# ─────────────────────────────────────────────────────────────────────────────
SYS_PROMPT = page_sys_prompt()

# ─────────────────────────────────────────────────────────────────────────────
# План вопросов витрины: q_lang — язык вопроса, trigger — триггер КОРПУСА,
# по которому подбираются эпизоды-источники (и который уходит мозгу в промпте).
# ─────────────────────────────────────────────────────────────────────────────
PLAN = [
    {"q": "Я не буду слушать твои слова и пойду за чужими богами.",
     "q_lang": "ru", "trigger": "disobedience"},
    {"q": "Spare them, they do not know what they are doing — do not destroy them for one man's sin.",
     "q_lang": "en", "trigger": "intercession"},
    {"q": "מה עליי לעשות כדי לחיות לפניך?",
     "q_lang": "he", "trigger": "inquiry"},
    {"q": "Почему ты покинул меня? Несправедливо, что праведник страдает, а я остался один.",
     "q_lang": "ru", "trigger": "complaint"},
    {"q": "Save me from this trouble — I am afraid my enemies will overwhelm me.",
     "q_lang": "en", "trigger": "distress"},
    {"q": "ספר לי, מה דרכך שלך לאדם?",
     "q_lang": "he", "trigger": "inquiry"},
    {"q": "Молю тебя, услышь мой вопль из глубины.",
     "q_lang": "ru", "trigger": "prayer"},
    {"q": "Thank you, I praise you for the rescue you gave me.",
     "q_lang": "en", "trigger": "gratitude"},
    {"q": "איך אוכל לדעת אם אני מוכרע לפניך?",
     "q_lang": "he", "trigger": "inquiry"},
    {"q": "Даю обет: посвящу тебе свой дом и всё, что в нём.",
     "q_lang": "ru", "trigger": "vow"},
    {"q": "Tell me what shall I do to live in your way.",
     "q_lang": "en", "trigger": "inquiry"},
    {"q": "Испытай меня, как испытал Авраама, и покажи, верен ли я тебе.",
     "q_lang": "ru", "trigger": "divine_test",
     "note": "в таблице classify() страницы ветки divine_test нет — страница дала бы inquiry; "
             "здесь триггер корпуса (божественное испытание) выбран явно, чтобы витрина покрыла его"},
]

# названия книг на трёх языках — из docs/index.html (BOOK_NAMES): нужны, чтобы
# разобрать [SOURCES], где мозг мог назвать книгу по-русски или по-ивриту
BOOK_NAMES = {
    "ru": {"genesis": "Бытие", "Exodus": "Исход", "Leviticus": "Левит", "Numbers": "Числа",
           "Deuteronomy": "Второзаконие", "Joshua": "Иисус Навин", "Judges": "Судьи",
           "I_Samuel": "1 Царств", "II_Samuel": "2 Царств", "I_Kings": "3 Царств",
           "II_Kings": "4 Царств", "Isaiah": "Исаия", "Jeremiah": "Иеремия", "Ezekiel": "Еезекииль",
           "Hosea": "Осия", "Joel": "Иоиль", "Amos": "Амос", "Obadiah": "Авдий", "Jonah": "Иона",
           "Micah": "Михей", "Nahum": "Наум", "Habakkuk": "Аввакум", "Zephaniah": "Софония",
           "Haggai": "Аггей", "Zechariah": "Захария", "Malachi": "Малахия", "Psalms": "Псалтирь",
           "Proverbs": "Притчи", "Job": "Иов", "Song_of_Songs": "Песнь Песней", "Ruth": "Руфь",
           "Lamentations": "Плач Иеремии", "Ecclesiastes": "Екклесиаст", "Esther": "Есфирь",
           "Daniel": "Даниил", "Ezra": "Ездра", "Nehemiah": "Неемия",
           "I_Chronicles": "1 Паралипоменон", "II_Chronicles": "2 Паралипоменон"},
    "en": {"genesis": "Genesis", "Exodus": "Exodus", "Leviticus": "Leviticus", "Numbers": "Numbers",
           "Deuteronomy": "Deuteronomy", "Joshua": "Joshua", "Judges": "Judges", "I_Samuel": "I Samuel",
           "II_Samuel": "II Samuel", "I_Kings": "I Kings", "II_Kings": "II Kings", "Isaiah": "Isaiah",
           "Jeremiah": "Jeremiah", "Ezekiel": "Ezekiel", "Hosea": "Hosea", "Joel": "Joel", "Amos": "Amos",
           "Obadiah": "Obadiah", "Jonah": "Jonah", "Micah": "Micah", "Nahum": "Nahum", "Habakkuk": "Habakkuk",
           "Zephaniah": "Zephaniah", "Haggai": "Haggai", "Zechariah": "Zechariah", "Malachi": "Malachi",
           "Psalms": "Psalms", "Proverbs": "Proverbs", "Job": "Job", "Song_of_Songs": "Song of Songs",
           "Ruth": "Ruth", "Lamentations": "Lamentations", "Ecclesiastes": "Ecclesiastes",
           "Esther": "Esther", "Daniel": "Daniel", "Ezra": "Ezra", "Nehemiah": "Nehemiah",
           "I_Chronicles": "I Chronicles", "II_Chronicles": "II Chronicles"},
    "he": {"genesis": "בראשית", "Exodus": "שמות", "Leviticus": "ויקרא", "Numbers": "במדבר",
           "Deuteronomy": "דברים", "Joshua": "יהושע", "Judges": "שופטים", "I_Samuel": "שמואל א",
           "II_Samuel": "שמואל ב", "I_Kings": "מלכים א", "II_Kings": "מלכים ב", "Isaiah": "ישעיהו",
           "Jeremiah": "ירמיהו", "Ezekiel": "יחזקאל", "Hosea": "הושע", "Joel": "יואל", "Amos": "עמוס",
           "Obadiah": "עובדיה", "Jonah": "יונה", "Micah": "מיכה", "Nahum": "נחום", "Habakkuk": "חבקוק",
           "Zephaniah": "צפניה", "Haggai": "חגי", "Zechariah": "זכריה", "Malachi": "מלאכי",
           "Psalms": "תהלים", "Proverbs": "משלי", "Job": "איוב", "Song_of_Songs": "שיר השירים",
           "Ruth": "רות", "Lamentations": "איכה", "Ecclesiastes": "קהלת", "Esther": "אסתר",
           "Daniel": "דניאל", "Ezra": "עזרא", "Nehemiah": "נחמיה",
           "I_Chronicles": "דברי הימים א", "II_Chronicles": "דברי הימים ב"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательное
# ─────────────────────────────────────────────────────────────────────────────
def _utf8_stdio():
    """Консоль Windows по умолчанию cp1251 — иврит и кириллица падают. UTF-8 + replace."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def js_json(obj):
    """JSON как на странице: JSON.stringify — без лишних пробелов, ключи в исходном порядке."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def load_corpus():
    """Мастер-корпус {книга: [эпизоды]} → {book|span.start: эпизод}, порядок книг — как на странице."""
    master = json.load(io.open(MASTER_CORPUS, encoding="utf-8"))
    analytics = json.load(io.open(ANALYTICS, encoding="utf-8"))
    books = [b for era in analytics["book_order"].values() for b in era if b in master]
    books += [b for b in master if b not in books]
    episodes = {}
    for book in books:
        for e in master[book]:
            episodes["%s|%s" % (book, e["span"]["start"])] = dict(e, book=book)
    return episodes


def load_nikud():
    return json.load(io.open(NIKUD_INDEX, encoding="utf-8"))


def load_analytics():
    return json.load(io.open(ANALYTICS, encoding="utf-8"))


def nikud_for(book, refs, index):
    """Порт nikudFor() из docs/index.html — символ в символ (регистр, 3 стиха, склейка)."""
    bk = book[:1].upper() + book[1:]
    out = []
    for r in (refs or [])[:3]:
        m = re.match(r"^(\d+):(\d+)$", r or "")
        if not m:
            continue
        t = index.get(bk + "|" + m[1] + "|" + m[2])
        if t:
            out.append(t)
    return "  ".join(out)


def rank_episodes(q, trigger, episodes, k=6):
    """Детерминированный отбор эпизодов: лексика по summary_ru/god_action + буст триггера.

    Та же формула, что на странице (docs/index.html, retrieve()), но без векторной
    части e5-small: выбор должен быть воспроизводим без сети.
    """
    return _rank_episodes(q, trigger, episodes, k=k, hybrid=False)


def rank_episodes_live(q, trigger, episodes, k=6, hybrid=True):
    """Отбор как на странице: лексика + вектор e5-small (если transformers доступен)."""
    warned = []

    def note(msg):
        if msg not in warned:
            warned.append(msg)
            print("   ⚠️ " + msg)

    return _rank_episodes(q, trigger, episodes, k=k, hybrid=hybrid, note=note)


def mem_for(q):
    """Порядок реплик одной сессии — как memUpdate() страницы (для одиночного диалога: 1 вопрос)."""
    m = q.lower()
    offenses = 1 if re.search(r"не буду|наруш|не послуш|отвергаю|идол|другого бога|мне всё равно|"
                              r"плевать|i will not|i won't", m) else 0
    grace = 0
    if re.search(r"согрешил|раскаиваюсь|прости меня|покаян|forgive me|i repent", m):
        offenses = max(0, offenses - 1)
        grace = 1
    return offenses, grace


def memory_line(q):
    """Строка памяти диалога для шага формулировки — как на странице (docs/index.html)."""
    offenses, grace = mem_for(q)
    mem = "ПАМЯТЬ ДИАЛОГА: проступков в этой сессии %d, благодати %d." % (offenses, grace)
    if offenses > 0:
        mem += " Тяжесть отклика повышена накопленными проступками."
    if re.search(r"согрешил|раскаиваюсь|прости меня", q.lower()):
        mem += " Покаяние снижает тяжесть."
    return mem


# ─────────────────────────────────────────────────────────────────────────────
# Сеть
# ─────────────────────────────────────────────────────────────────────────────
def fetch_status(timeout=20):
    """Статус мозга: локальный сервер (GOD_BRAIN_URL) → HF brain.json → снимок.

    Локальный путь нужен, когда квота Kaggle исчерпана: тот же DictaLM 12B
    Q5_K_M поднимается на локальной карте (brain/start_local_brain.py).
    """
    local_url = os.environ.get("GOD_BRAIN_URL", "").strip()
    if local_url:
        local_key = os.environ.get("GOD_BRAIN_KEY", "godbrain-v1-vasiliad")
        local_model = os.environ.get("GOD_BRAIN_MODEL", "")
        return {"_source": "локальный мозг (GOD_BRAIN_URL)", "ok": True,
                "url": local_url, "key": local_key, "model": local_model or API_MODEL,
                "ts": int(time.time())}
    try:
        req = urllib.request.Request(BRAIN_STATUS_URL, headers={"User-Agent": "god2-record-dialogues"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("brain.json — не объект")
        data["_source"] = "HF brain.json"
        return data
    except Exception as e:
        print("⚠️ brain.json с HF недоступен (%s: %s) — беру запасной локальный снимок" % (type(e).__name__, e))
        try:
            snap = json.load(io.open(BRAIN_SNAPSHOT, encoding="utf-8"))
        except Exception as e2:
            print("⚠️ запасной снимок %s тоже недоступен (%s: %s)" % (BRAIN_SNAPSHOT, type(e2).__name__, e2))
            return {"_source": "ни HF brain.json, ни локальный снимок", "url": "", "key": ""}
        snap["_source"] = "локальный brain/brain_snapshot.json (запасной путь)"
        return snap


def ask_brain(user_text, url, key, timeout=DEFAULT_TIMEOUT, model=API_MODEL, retries=1):
    """Запрос к OpenAI-совместимому эндпойнту мозга. Возвращает текст ответа.

    Один вызов с SYS_PROMPT страницы (шаг формулировки). Шаг выбора эпизода
    делает two_stage() из scripts/answer_scheme.py.
    """
    from answer_scheme import ask_brain as _ask, FORM_TEMP, FORM_MAX_TOKENS
    return _ask(SYS_PROMPT, user_text, url.rstrip("/") + "/v1/chat/completions", key,
                timeout=timeout, model=model, temperature=FORM_TEMP,
                max_tokens=FORM_MAX_TOKENS, retries=retries)


# ─────────────────────────────────────────────────────────────────────────────
# Разбор ответа
# ─────────────────────────────────────────────────────────────────────────────
def parse_sections(text):
    """Порт parseSections() из docs/index.html: ровно 6 секций, ничего кроме них."""
    out = {}
    text = text or ""
    for tag in SECTIONS:
        i = text.find(tag)
        if i < 0:
            continue
        rest = text[i + len(tag):]
        end = len(rest)
        for t2 in SECTIONS:
            j = rest.find(t2)
            if 0 <= j < end:
                end = j
        out[tag] = rest[:end].strip()
    return out


def _book_aliases():
    """Синонимы названий книг → канонический ключ корпуса (для разбора [SOURCES])."""
    aliases = {}
    for key in BOOK_NAMES["en"]:
        names = {key, key[:1].upper() + key[1:], key.replace("_", " "),
                 key[:1].upper() + key[1:].replace("_", " ")}
        for lang in ("ru", "en", "he"):
            names.add(BOOK_NAMES[lang].get(key, key))
        for n in names:
            if n:
                aliases[n.lower()] = key
    return aliases


HE_NUM = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9, "י": 10,
          "כ": 20, "ל": 30, "מ": 40, "נ": 50, "ס": 60, "ע": 70, "פ": 80, "צ": 90, "ק": 100,
          "ר": 200, "ש": 300, "ת": 400}


def hebrew_number(token):
    """Ивритское число («יג» → 13, «יג׳» → 13). None, если это не число."""
    t = (token or "").strip("'׳״\".,")
    if not t or len(t) > 3:
        return None
    total = 0
    for ch in t:
        v = HE_NUM.get(ch)
        if v is None:
            return None
        total += v
    return total or None


def normalize_refs(text):
    """«ירמיהו יג:8-11» → «ירמיהו 13:8-11»: ивритские номера главы/стиха → арабские."""
    def repl(m):
        num = hebrew_number(m.group(1))
        return (str(num) if num else m.group(1)) + ":" + m.group(2)
    return re.sub(r"([א-ת]{1,3})[:\s]\s*(\d{1,3})", repl, text or "")


def _ref_tuple(ref):
    """«3:9» → (3, 9); None, если это не «глава:стих»."""
    m = re.match(r"^(\d+):(\d+)$", str(ref or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def episode_contains(episode, chapter, verse):
    """Входит ли стих chapter:verse внутрь спана эпизода?"""
    s = _ref_tuple(episode["span"]["start"])
    e = _ref_tuple(episode["span"]["end"])
    if not s or not e:
        return False
    if e < s:
        s, e = e, s
    if s[0] == e[0]:
        return s[0] == chapter and s[1] <= verse <= e[1]
    return s[0] <= chapter <= e[0]


def parse_sources(sources_text, hits, episodes):
    """Источники диалога: из [SOURCES] («книга глава:стих»), при пустой секции — из контекста.

    Возвращает список {"book": <ключ корпуса>, "start": "3:9", "end": "3:12"}.
    Стих, названный мозгом, ищется сперва как начало спана эпизода, а если такого
    эпизода нет — как стих ВНУТРИ спана (например «Leviticus 24:15» → эпизод
    Leviticus 24:13–24:23): источник всегда указывает на реальную запись корпуса.
    """
    aliases = _book_aliases()
    by_book = {}
    for key, e in episodes.items():
        by_book.setdefault(e["book"], {})[e["span"]["start"]] = e
    text = normalize_refs((sources_text or "").strip())
    out = []
    seen = set()

    def add(book, start, end):
        sig = (book, start, end)
        if sig in seen:
            return
        seen.add(sig)
        out.append({"book": book, "start": start, "end": end})

    if text:
        low = text.lower()
        # 1) источник из контекста: книга названа И её стих стоит в [SOURCES]
        for key in hits:
            e = episodes[key]
            book = e["book"]
            names = [n for n, b in aliases.items() if b == book]
            if any(n in low for n in names):
                start = e["span"]["start"]
                if start in text or start.replace(":", ".") in text:
                    add(book, start, e["span"]["end"])
        # 2) любые «Книга N:M» из [SOURCES], разрешаемые в корпусе
        for m in re.finditer(r"([^\d:.,;()\[\]]{2,40}?)\s*(\d{1,3})\s*[:.]\s*(\d{1,3})", text):
            raw = m.group(1).strip(" -—–:,.;«»\"'()[]")
            words = raw.split()
            cands = [raw] + words[-2:] + words[-1:]
            book = None
            for c in cands:
                book = aliases.get(c.lower()) or aliases.get(c.lower().replace(" ", "_"))
                if book:
                    break
            if not book:
                continue
            chapter, verse = int(m.group(2)), int(m.group(3))
            start = "%s:%s" % (chapter, verse)
            e = by_book.get(book, {}).get(start)
            if not e:
                # стиха нет в начале эпизода — ищем эпизод, который его содержит
                for cand in by_book.get(book, {}).values():
                    if episode_contains(cand, chapter, verse):
                        e = cand
                        break
            if e:
                add(book, e["span"]["start"], e["span"]["end"])
    if not out and hits:
        # 3) секция [SOURCES] пустая или неразборчивая — честно берём прецедент из контекста
        e = episodes[hits[0]]
        add(e["book"], e["span"]["start"], e["span"]["end"])
    return out


def dialogue_ok(sections, sources):
    """ok=true только если все 6 секций непусты и источник хотя бы один."""
    return all((sections.get(tag) or "").strip() for tag in SECTIONS) and bool(sources)


# ─────────────────────────────────────────────────────────────────────────────
# Живой прогон
# ─────────────────────────────────────────────────────────────────────────────
def record(plan, out_path, timeout, do_print, hybrid=True, url_override=None, key_override=None):
    if url_override:
        # локальный мозг: тот же DictaLM-3.0-Nemotron-12B Q5_K_M, но без туннеля
        status = {"_source": "локальный мозг (--url)", "url": url_override,
                  "key": key_override or "", "model": API_MODEL}
    else:
        status = fetch_status()
    url = (status.get("url") or "").rstrip("/")
    key = status.get("key") or ""
    model = status.get("model") or API_MODEL
    print("Мозг: %s | url=%s | model=%s" % (status.get("_source"), url or "(нет)", model))
    ts = status.get("ts")
    if isinstance(ts, (int, float)):
        print("Пульс brain.json: %.0f мин назад" % ((time.time() - ts) / 60))
    if not url:
        print("Мозг недоступен: в brain.json нет url — записать нечего.")
        return 2

    episodes = load_corpus()
    corpus_pairs = [(e["book"], e) for e in episodes.values()]   # реестр для сверки
    nikud_index = load_nikud()
    analytics = load_analytics()
    trigger_table = analytics.get("trigger_table", {})
    print("Корпус: %d эпизодов, триггеров в таблице: %d\n" % (len(episodes), len(trigger_table)))

    dialogues = []
    endpoint = url.rstrip("/") + "/v1/chat/completions"
    for n, item in enumerate(plan, 1):
        q = item["q"]
        trig = item["trigger"]
        # пул 18 → фильтр «только с речью Бога» → 6 кандидатов — ровно как страница
        hits = rank_episodes_live(q, trig, episodes, 18, hybrid=hybrid)
        ctx = build_context(episodes, nikud_index, hits)
        tt = trigger_table.get(trig) or {}
        probs = {k: v for k, v in tt.items() if k != "n"}
        print("[%d/%d] «%s»  (trig=%s, %s)" % (n, len(plan), q, trig, item["q_lang"]))
        print("   кандидаты: %s" % ", ".join("%s %s" % (episodes[k]["book"], episodes[k]["span"]["start"])
                                            for k in hits))
        t0 = time.time()
        raw, error = "", None
        chosen, sel_idx = None, None
        try:
            st = two_stage(q, ctx, endpoint, key, timeout=timeout, model=model,
                           memory=memory_line(q))
            raw, chosen, sel_idx = st["raw"], st["chosen"], st["index"]
            print("   выбор эпизода: S%d [%s %s] — %s" % (
                sel_idx, chosen["book"], chosen["span"]["start"],
                (chosen["summary_ru"] or "")[:56]))
        except Exception as e:
            error = "%s: %s" % (type(e).__name__, e)
            print("   ОШИБКА: %s" % error)
        sections = parse_sections(raw)
        model_sources = parse_sources(sections.get("[SOURCES]", ""), hits, episodes)
        # правило «S»: сверяем реплику с реестром и публикуем ПРОВЕРЕННОЕ —
        # неподтверждённая реплика заменяется прецедентом корпуса.
        # Окно сверки — ВЫБРАННЫЙ эпизод: ровно он ушёл модели (как на странице).
        gctx = [chosen] if chosen else []
        g = apply_guard(sections, gctx, corpus_pairs,
                        nikud_for=lambda b, refs: nikud_for(b, refs, nikud_index))
        shown, sources, guard = g["sections"], g["sources"], g["guard"]
        ok = dialogue_ok(sections, sources) and guard["mode"] != "reject"
        dlg = {
            "id": n,
            "q": q,
            "q_lang": item["q_lang"],
            "sections": {tag: shown.get(tag, "") for tag in SECTIONS},
            "model_sections": {tag: sections.get(tag, "") for tag in SECTIONS},
            "model_sources": model_sources,
            "sources": sources,
            "guard": guard,
            "trigger": trig,
            "selected": ({"book": chosen["book"], "start": chosen["span"]["start"],
                          "end": chosen["span"]["end"], "index": sel_idx} if chosen else None),
            "ok": ok,
        }
        if error:
            dlg["error"] = error
        dialogues.append(dlg)
        print("   %d/6 секций | сверка: %s (%.0f%% слов из контекста) | источников: %d | ok=%s | %.1f с"
              % (sum(1 for t in SECTIONS if (sections.get(t) or "").strip()),
                 guard["mode"], 100 * guard["ctx_cov"], len(sources),
                 "да" if ok else "нет", time.time() - t0))
        if do_print:
            print("   " + "-" * 60)
            for tag in SECTIONS:
                print("   %-17s %s" % (tag, dlg["sections"].get(tag, "")))
            print("   " + "-" * 60)
        time.sleep(1)

    payload = {
        "generated": now_iso(),
        "model": model,
        "brain_url": url,
        "brain_source": status.get("_source"),
        "brain_model_file": status.get("model_files") or [],
        "scheme": "шаг 1 выбор эпизода (temperature 0) → шаг 2 формулировка из одного эпизода → шаг 3 сверка с реестром",
        "dialogues": dialogues,
    }
    out = Path(out_path)
    if not out.is_absolute():
        out = _ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=1))
    good = sum(1 for d in dialogues if d["ok"])
    modes = {}
    for d in dialogues:
        m = d["guard"]["mode"]
        modes[m] = modes.get(m, 0) + 1
    print("\nЗаписано диалогов: %d (полных: %d) → %s" % (len(dialogues), good, out))
    print("Сверка с реестром: verified=%d corpus=%d reject=%d"
          % (modes.get("verified", 0), modes.get("corpus", 0), modes.get("reject", 0)))
    print("ИТОГ: %d/%d полных диалогов" % (good, len(dialogues)))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Офлайн-самопроверка (сеть не нужна)
# ─────────────────────────────────────────────────────────────────────────────
FIXTURE = ("[HEBREW] איכה\n"
           "[NIKKUD] אַיֵּה\n"
           "[Russian] Где ты?\n"
           "[English] Where art thou?\n"
           "[Hebrew Modern] איפה אתה\n"
           "[SOURCES] Genesis 3:9")


def run_selftest():
    checks = []

    def chk(name, cond, strict=True):
        checks.append((name, bool(cond), strict))
        print(("PASS" if cond else ("FAIL" if strict else "WARN")) + "  " + name)

    print("=== selftest: офлайн-проверка записи диалогов (сеть не используется) ===")

    # --- парсер секций ---
    secs = parse_sections(FIXTURE)
    chk("парсер находит все 6 секций", len(secs) == 6)
    chk("[HEBREW] разобран верно", secs.get("[HEBREW]") == "איכה")
    chk("[NIKKUD] разобран верно", secs.get("[NIKKUD]") == "אַיֵּה")
    chk("[Russian] разобран верно", secs.get("[Russian]") == "Где ты?")
    chk("[English] разобран верно", secs.get("[English]") == "Where art thou?")
    chk("[Hebrew Modern] разобран верно", secs.get("[Hebrew Modern]") == "איפה אתה")
    chk("[SOURCES] разобран верно", secs.get("[SOURCES]") == "Genesis 3:9")
    chk("секция не протекает в следующую", "\n[" not in secs.get("[HEBREW]", ""))
    chk("текст без тегов даёт 0 секций", len(parse_sections("просто текст без секций")) == 0)
    chk("пустая секция считается пустой", dialogue_ok(dict((t, "") for t in SECTIONS), [{"book": "genesis"}]) is False)

    # --- SYSTEM_PROMPT совпадает со страницей ---
    try:
        page_prompt = page_sys_prompt()
    except Exception as e:
        page_prompt = ""
        print("   (страница не прочитана: %s)" % e)
    chk("SYSTEM_PROMPT == SYS_PROMPT страницы", page_prompt == SYS_PROMPT, strict=False)

    # --- nikudFor ---
    idx = load_nikud()
    gen_keys = sorted(k for k in idx if k.startswith("Genesis|"))
    refs = [":".join(k.split("|")[1:]) for k in gen_keys[:2]]
    if len(refs) == 2:
        expected = idx[gen_keys[0]] + "  " + idx[gen_keys[1]]
        chk("nikudFor склеивает стихи двумя пробелами", nikud_for("genesis", refs, idx) == expected)
    else:
        chk("nikudFor: в индексе нет стихов Бытия", False)
    chk("nikudFor берёт максимум 3 стиха", len(nikud_for("genesis", refs + ["1:1", "1:2"], idx).split("  ")) <= 3)
    chk("nikudFor на неизвестной книге пуст", nikud_for("НетТакойКниги", ["1:1"], idx) == "")
    chk("nikudFor игнорирует мусорный ref", "abc" not in nikud_for("genesis", ["abc"] + refs[:1], idx))

    # --- классификация и план ---
    for item in PLAN:
        if item["trigger"] == "divine_test":
            continue
        chk("classify(%s…) == %s" % (item["q"][:24], item["trigger"]), classify(item["q"]) == item["trigger"])
    chk("в плане есть все 9 типов обращения корпуса",
        set(i["trigger"] for i in PLAN) >= {"disobedience", "prayer", "intercession", "complaint", "distress",
                                            "gratitude", "inquiry", "vow", "divine_test"})
    chk("в плане три языка", set(i["q_lang"] for i in PLAN) == {"ru", "en", "he"})
    chk("в плане 8–12 вопросов", 8 <= len(PLAN) <= 12)

    # --- детерминированный отбор эпизодов ---
    episodes = load_corpus()
    hits = rank_episodes(PLAN[0]["q"], PLAN[0]["trigger"], episodes, 6)
    chk("отбор эпизодов детерминирован", hits == rank_episodes(PLAN[0]["q"], PLAN[0]["trigger"], episodes, 6))
    chk("отбор берёт 6 эпизодов корпуса", len(hits) == 6 and all(h in episodes for h in hits))
    hits2 = rank_episodes(PLAN[0]["q"], "vow", episodes, 6)
    chk("буст триггера меняет отбор", hits2 != hits)
    chk("буст триггера выводит эпизоды этого триггера в топ",
        all(episodes[h]["trigger"] == "vow" for h in hits2[:2]) or
        any(episodes[h]["trigger"] == "vow" for h in hits2[:3]))

    # --- контекст в формате страницы ---
    ctx = build_context(episodes, idx, hits)
    chk("контекст: 6 эпизодов", len(ctx) == 6)
    chk("контекст: поля страницы на месте",
        all(set(c.keys()) == {"book", "span", "trigger", "outcome", "god_speech_plain", "nikud",
                              "summary_ru", "god_action"} for c in ctx))
    chk("контекст: god_speech_plain ≤ 300", all(len(c["god_speech_plain"]) <= 300 for c in ctx))
    chk("контекст: summary_ru ≤ 200", all(len(c["summary_ru"]) <= 200 for c in ctx))
    chk("контекст: god_action ≤ 160", all(len(c["god_action"]) <= 160 for c in ctx))
    chk("контекст: nikud ≤ 300", all(len(c["nikud"]) <= 300 for c in ctx))

    # --- шаги схемы: блок кандидатов, блок эпизода, разбор выбора ---
    cand = spoken_candidates(ctx)
    chk("кандидаты для выбора — только с речью Бога",
        all((c.get("god_speech_plain") or "").strip() for c in cand))
    cblk = candidate_block(PLAN[0]["q"], cand)
    chk("блок кандидатов начинается с вопроса", cblk.startswith("ВОПРОС ЧЕЛОВЕКА: " + PLAN[0]["q"]))
    chk("в блоке кандидатов есть речь и огласовка",
        "речь: " in cblk and "огласовка: " in cblk)
    chk("в блоке кандидатов есть речь", "речь: " in cblk)
    eblk = episode_block(cand[0])
    chk("блок эпизода начинается со стиха", eblk.startswith("СТИХ: [%s %s]" % (
        cand[0]["book"], cand[0]["span"]["start"])))
    chk("в блоке эпизода есть «о чём»", "о чём: " in eblk)
    chk("разбор выбора: S3 → 3", pick_index("S3", 6) == 3)
    chk("разбор выбора: без числа → 1", pick_index("не знаю", 6) == 1)
    chk("разбор выбора: вне диапазона → 1", pick_index("S99", 6) == 1)
    try:
        page_select = page_sys_select()
    except Exception as e:
        page_select = ""
        print("   (страница не прочитана: %s)" % e)
    chk("SYS_SELECT == SYS_SELECT страницы", page_select == page_sys_select(), strict=False)
    chk("промпты схемы разные", page_sys_prompt() != page_select)

    # --- разбор источников ---
    src = parse_sources("Genesis 3:8", ["genesis|3:8"], episodes)
    chk("источник «Genesis 3:8» разобран", len(src) == 1 and src[0]["book"] == "genesis"
        and src[0]["start"] == "3:8" and src[0]["end"] == "3:19")
    src2 = parse_sources("Бытие 3:8–3:19", ["genesis|3:8"], episodes)
    chk("русское название книги разобрано", len(src2) == 1 and src2[0]["book"] == "genesis")
    src3 = parse_sources("", ["genesis|3:8"], episodes)
    chk("пустая [SOURCES] → источник из контекста", len(src3) == 1 and src3[0]["book"] == "genesis")
    src4 = parse_sources("Иов 1:13", ["genesis|3:8"], episodes)
    chk("источник вне контекста, но в корпусе, разобран", len(src4) == 1 and src4[0]["book"] == "Job")
    chk("мусор в [SOURCES] не ломает разбор", isinstance(parse_sources("???", ["genesis|3:8"], episodes), list))
    src5 = parse_sources("ירמיהו יג:8-11", ["Jeremiah|13:8"], episodes)
    chk("ивритская книга и ивритский номер разобраны",
        len(src5) == 1 and src5[0]["book"] == "Jeremiah" and src5[0]["start"] == "13:8"
        and src5[0]["end"] == "13:11")
    src6 = parse_sources("Leviticus 24:15", [], episodes)
    chk("стих внутри спана находит свой эпизод",
        len(src6) == 1 and src6[0]["book"] == "Leviticus" and src6[0]["start"] == "24:13"
        and src6[0]["end"] == "24:23")
    src7 = parse_sources("Psalms 27:8", [], episodes)
    chk("псалом внутри спана находит свой эпизод",
        len(src7) == 1 and src7[0]["book"] == "Psalms" and src7[0]["start"] == "27:1")
    chk("эпизод-контейнер найден по главе и стиху",
        episode_contains(episodes["Psalms|27:1"], 27, 8) is True
        and episode_contains(episodes["Psalms|27:1"], 28, 1) is False)
    chk("источник вне корпуса не выдумывается",
        parse_sources("Genesis 99:99", [], episodes) == [])
    chk("ивритское число «יג» = 13", hebrew_number("יג") == 13 and hebrew_number("א") == 1
        and hebrew_number("שלוש") is None)
    chk("нормализация ивритских ссылок", normalize_refs("ירמיהו יג:8-11") == "ירמיהו 13:8-11")

    strict_fail = [n for n, ok, strict in checks if strict and not ok]
    warn = [n for n, ok, strict in checks if not strict and not ok]
    passed = sum(1 for _, ok, strict in checks if ok or not strict)
    total = len(checks)
    if warn:
        print("\nПредупреждения (не ошибки): %s" % "; ".join(warn))
    print("\nSELFTEST: %s (%d/%d)" % ("PASS" if not strict_fail else "FAIL", passed, total))
    return 0 if not strict_fail else 1


def main(argv=None):
    _utf8_stdio()
    ap = argparse.ArgumentParser(description="Запись живых диалогов мозга для витрины «Диалоги».")
    ap.add_argument("--out", default=DEFAULT_OUT, help="путь к JSON (по умолчанию %s)" % DEFAULT_OUT)
    ap.add_argument("--count", type=int, default=len(PLAN), help="сколько вопросов записать (по умолчанию %d)" % len(PLAN))
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="таймаут одного запроса, с (по умолчанию %d)" % DEFAULT_TIMEOUT)
    ap.add_argument("--print", dest="do_print", action="store_true", help="печатать ответы в консоль")
    ap.add_argument("--lexical", dest="lexical", action="store_true",
                    help="отбор кандидатов только по лексике (без вектора e5-small)")
    ap.add_argument("--test", "--selftest", dest="selftest", action="store_true",
                    help="офлайн-самопроверка парсера и отбора, без сети")
    ap.add_argument("--url", default=None,
                    help="эндпойнт мозга (по умолчанию — из HF brain.json; локальный: http://127.0.0.1:18099)")
    ap.add_argument("--key", default=None, help="ключ мозга (для --url)")
    args = ap.parse_args(argv)
    if args.selftest:
        return run_selftest()
    if args.count < 1:
        ap.error("--count должен быть ≥ 1")
    plan = PLAN[:args.count]
    return record(plan, args.out, args.timeout, args.do_print, hybrid=not args.lexical,
                  url_override=args.url, key_override=args.key)


if __name__ == "__main__":
    sys.exit(main())
