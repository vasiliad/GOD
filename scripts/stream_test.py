#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ПОТОК ЖИВЫХ ВОПРОСОВ — стенд реального пути продукта.

Каждый вопрос идёт ровно тем же путём, что и вопрос посетителя на странице:

    1) отбор кандидатов — лексика; если лексика молчит, вектор (серверный Nemotron);
    2) мозг — два шага: выбор эпизода, затем формулировка из него;
    3) разбор шести секций ответа;
    4) сверка с реестром — scripts/answer_guard.py, правило «S».

Каждый ответ проверяется автоматически, строка уходит в лог сразу (живой поток),
в конце — сводка с числами и списком провалов.

Запуск:
    python scripts/stream_test.py --set all                       # весь поток
    python scripts/stream_test.py --set gold --shard 0 --shards 4 # пачка для fan-out
    python scripts/stream_test.py --judge shard0.jsonl shard1.jsonl
    python scripts/stream_test.py --selftest                      # офлайн-проверка стенда

Выход: JSONL-транскрипт (--out) — по одной записи на вопрос; его же читает
режим --judge, чтобы собрать сводку по пачкам.
"""
import argparse
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import answer_scheme as AS                                    # noqa: E402
from answer_guard import apply_guard                          # noqa: E402
from answer_scheme import (                                   # noqa: E402
    build_context, classify, load_corpus, load_nikud, rank_episodes, two_stage,
)

HF_STATUS = "https://huggingface.co/datasets/arabyan/god-brain-status/resolve/main/%s.json"
GOLD = os.path.join(_ROOT, "scripts", "topic_gold.json")
MENUS = os.path.join(_ROOT, "scripts", "page_menus.json")
PARA = os.path.join(_ROOT, "scripts", "vector_paraphrases.json")
PAGE = os.path.join(_ROOT, "docs", "index.html")

TAGS = ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]
# Содержательные слои — те пять, которые видит пользователь. [SOURCES] — служебная
# секция: источник показывается ИЗ РЕЕСТРА (book|span выбранного эпизода), а не из
# строки модели. Ответ без неё — полный (замер потока 2026-10-27: модель дописала все
# пять слоёв, но не написала [SOURCES], и хороший ответ заменялся прецедентом).
CONTENT_TAGS = ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]"]
CONTENT_FULL = len(CONTENT_TAGS)

TRANSIENT = (urllib.error.URLError, TimeoutError, ConnectionError, OSError)


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательное
# ─────────────────────────────────────────────────────────────────────────────
def hms():
    return time.strftime("%H:%M:%S")


def fetch_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "god2-stream-test"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def page_book_names(lang="ru"):
    """Названия книг со страницы (страница — единственный источник)."""
    try:
        html = io.open(PAGE, encoding="utf-8").read()
    except Exception:
        return {}
    m = re.search(r"const BOOK_NAMES = \{(.*?)\n\};", html, re.S)
    if not m:
        return {}
    seg = re.search(r"\b%s:\s*\{(.*?)\}" % lang, m.group(1), re.S)
    if not seg:
        return {}
    out = {}
    for k, v in re.findall(r'([A-Za-z_]+)\s*:\s*"([^"]*)"', seg.group(1)):
        out[k] = v
    return out


def parse_sections(text):
    """Шесть секций ответа мозга — тот же разбор, что на странице."""
    sections = {}
    for tag in TAGS:
        i = (text or "").find(tag)
        if i < 0:
            continue
        rest = text[i + len(tag):]
        end = len(rest)
        for t2 in TAGS:
            j = rest.find(t2)
            if j >= 0 and j < end:
                end = j
        sections[tag] = rest[:end].strip()
    return sections


def nikud_for(book, refs, index):
    """Огласовка из корпуса (порт nikudFor() страницы)."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Золотой эталон тематики — куда должен попасть ответ
# ─────────────────────────────────────────────────────────────────────────────
_GOLD_MAP = None
_PARA_BASE = None


def _place_key(s):
    """«Exodus 3:13» → «Exodus|3:13» (ключ корпуса)."""
    parts = str(s or "").split(" ")
    if len(parts) < 2:
        return ""
    return "%s|%s" % (parts[0], parts[1])


def gold_map():
    """Эталонный вопрос → (ядро, расширенные места) в ключах корпуса."""
    global _GOLD_MAP
    if _GOLD_MAP is None:
        gold = json.load(io.open(GOLD, encoding="utf-8"))
        _GOLD_MAP = {}
        for g in gold.get("questions", []):
            _GOLD_MAP[g["q"]] = (
                set(_place_key(p) for p in (g.get("core") or [])),
                set(_place_key(p) for p in (g.get("places") or [])),
            )
    return _GOLD_MAP


def para_base():
    """Перефраз → эталонный вопрос, которому он соответствует."""
    global _PARA_BASE
    if _PARA_BASE is None:
        _PARA_BASE = {}
        try:
            para = json.load(io.open(PARA, encoding="utf-8"))
        except Exception:               # noqa: BLE001 — файла может не быть
            para = {}
        for g in para.get("questions", []):
            base = g.get("q")
            for lst in (g.get("variants") or {}).values():
                for q in lst:
                    _PARA_BASE[q] = base
    return _PARA_BASE


def thematic(rec):
    """Попадание ответа в золотой эталон: ('core'|'places'|None, базовый вопрос).

    Проверяется ЭПИЗОД, из которого взят ответ (book + начало span).
    """
    q = rec.get("q", "")
    gm = gold_map()
    base = q if q in gm else para_base().get(q)
    if not base or base not in gm:
        return None, None
    core, places = gm[base]
    start = str(rec.get("span") or "").split("-")[0]
    key = "%s|%s" % (rec.get("book", ""), start)
    if key in core:
        return "core", base
    if key in places:
        return "places", base
    return "miss", base


# ─────────────────────────────────────────────────────────────────────────────
# Очередь вопросов
# ─────────────────────────────────────────────────────────────────────────────
def load_queue(which="all"):
    """Очередь потока: золотые вопросы, спасательные (вектор) и перефразы RU/EN/HE."""
    items = []

    if which in ("gold", "all"):
        gold = json.load(io.open(GOLD, encoding="utf-8"))
        for g in gold.get("questions", []):
            items.append({"q": g["q"], "lang": "ru", "tag": "gold",
                          "expect": g.get("core") or g.get("places") or []})

    if which in ("rescue", "all"):
        menus = json.load(io.open(MENUS, encoding="utf-8"))
        seen = set()
        for key in ("rescue_questions", "rescue_questions_server"):
            for q in (menus.get(key) or {}):
                if q in seen:
                    continue
                seen.add(q)
                items.append({"q": q, "lang": "ru", "tag": "rescue", "expect": []})

    if which in ("para", "all"):
        para = json.load(io.open(PARA, encoding="utf-8"))
        for g in para.get("questions", []):
            variants = g.get("variants") or {}
            for name, lst in variants.items():
                for q in lst:
                    lang = "he" if name.startswith("he") else ("en" if name.startswith("en") else "ru")
                    items.append({"q": q, "lang": lang, "tag": name, "expect": []})

    return items


def shard_items(items, shard, shards):
    """Разбор очереди на пачки: round-robin, чтобы пачки были равны по времени."""
    if shards <= 1:
        return list(items)
    return [it for i, it in enumerate(items) if i % shards == shard]


# ─────────────────────────────────────────────────────────────────────────────
# Движок эмбеддинга: считаем честно, чем нашёлся вектор
# ─────────────────────────────────────────────────────────────────────────────
class Trace(object):
    def __init__(self):
        self.nem = 0        # ответов серверного Nemotron
        self.e5 = 0         # ответов браузерного e5-small
        self.server_err = ""


def install_embedder(trace, allow_browser=True):
    """Перехватываем векторный путь, чтобы честно знать движок.

    Серверный Nemotron — основной путь (как в проде). Браузерный e5-small —
    запасной (он и на странице запасной). Без браузера тяжёлую модель не грузим:
    стенд не должен скачивать 118 МБ ради проверки.
    """
    orig_server = AS.embed_query_server

    def server(text):
        try:
            v = orig_server(text)
        except Exception as e:            # noqa: BLE001 — причина уходит в заметку
            trace.server_err = "%s: %s" % (type(e).__name__, e)
            return None
        if v:
            trace.nem += 1
        return v

    def embed_query(text):
        v = server(text)
        if v:
            return v
        be = getattr(AS, "browser_embedder", None)
        if allow_browser and be is not None and be.available():
            try:
                v = be.query_vector(text)
                if v:
                    trace.e5 += 1
                return v
            except Exception:             # noqa: BLE001
                return None
        return None

    AS.embed_query_server = server
    AS.embed_query = embed_query


def install_no_inner_retry():
    """Повторы — на уровне потока (их видно в логе), а не внутри ask_brain."""
    orig = AS.ask_brain

    def wrapper(*a, **kw):
        kw["retries"] = 0
        return orig(*a, **kw)

    AS.ask_brain = wrapper


# ─────────────────────────────────────────────────────────────────────────────
# Один вопрос
# ─────────────────────────────────────────────────────────────────────────────
def run_one(item, cfg, episodes, corpus_pairs, nikud_index, books_ru, trace, log):
    """Возвращает запись результата и печатает строку потока."""
    q = item["q"]
    t0 = time.time()
    trig = classify(q)

    lex = AS.lexical_scores(q, trig, episodes)
    lex_hit = any(hit for _, _, hit in lex)
    before = (trace.nem, trace.e5)

    notes = []
    hits = rank_episodes(q, trig, episodes, 18, hybrid=cfg.hybrid, note=notes.append)
    ctx = build_context(episodes, nikud_index, hits)

    if trace.nem > before[0]:
        engine = "nemotron"
    elif trace.e5 > before[1]:
        engine = "e5small"
    else:
        engine = "lex"

    # мозг: два шага. Повтор — только на сетевой сбой, не на «плохой» ответ.
    endpoint = cfg.brain_url.rstrip("/") + "/v1/chat/completions"
    attempts = 0
    st = None
    last_err = None
    while attempts <= cfg.retries:
        attempts += 1
        try:
            st = two_stage(q, ctx, endpoint, cfg.brain_key,
                           timeout=cfg.timeout, model=cfg.model)
            last_err = None
            break
        except Exception as e:            # noqa: BLE001 — в лог идёт причина
            last_err = "%s: %s" % (type(e).__name__, e)
            if attempts > cfg.retries:
                break
            log("⟳ %s → повтор (%d/%d)" % (q[:40], attempts, cfg.retries),
                mark="⟳", extra="  причина: " + last_err[:70])

    if st is None:
        rec = {"q": q, "lang": item["lang"], "tag": item["tag"], "status": "error",
               "engine": engine, "mode": "-", "sections": 0, "source": "",
               "latency_s": round(time.time() - t0, 1), "attempts": attempts,
               "note": last_err or "мозг не ответил", "ts": hms()}
        log("%s  %-38s → %s" % (hms(), q[:38], "ошибка: " + rec["note"][:70]),
            mark="!", extra="")
        return rec

    sections = parse_sections(st["raw"])
    g = apply_guard(sections, [st["chosen"]], corpus_pairs,
                    nikud_for=lambda b, refs: nikud_for(b, refs, nikud_index))
    guard = g["guard"]
    mode = guard["mode"]
    n_sections = len(sections)
    n_content = sum(1 for t in CONTENT_TAGS if (sections.get(t) or "").strip())
    srcs = g["sources"]

    chosen = st["chosen"]
    span = chosen.get("span") or {}
    book_ru = books_ru.get(chosen.get("book"), chosen.get("book"))
    src_label = ""
    if srcs:
        s0 = srcs[0]
        src_label = "%s %s" % (books_ru.get(s0.get("book"), s0.get("book")), s0.get("start"))
    else:
        src_label = "%s %s" % (book_ru, span.get("start", "?"))

    problems = []
    if mode == "reject":
        problems.append("речи Бога нет")
    if n_content < CONTENT_FULL:
        if st.get("degenerate"):
            problems.append("вырожденный повтор (слоёв %d/%d)" % (n_content, CONTENT_FULL))
        else:
            problems.append("слоёв %d/%d" % (n_content, CONTENT_FULL))
    if not srcs:
        problems.append("источник вне реестра")

    # вердикт: контракт целиком — 6 секций, реплика подтверждена реестром, источник из реестра
    if problems:
        verdict = "неполный ответ: " + "; ".join(problems)
    elif mode == "verified":
        verdict = "сверено с реестром"
    elif mode == "corpus":
        verdict = "сверено с реестром (цитата вне окна)"
    elif mode == "reject":
        verdict = "речи Бога нет → корпусный прецедент"
    else:
        verdict = mode or "неизвестно"

    ok = not problems
    status = "ok" if ok else "fail"
    rec = {"q": q, "lang": item["lang"], "tag": item["tag"], "status": status,
           "engine": engine, "mode": mode, "sections": n_sections, "content": n_content,
           "source": src_label, "latency_s": round(time.time() - t0, 1),
           "attempts": attempts, "form_attempts": st.get("form_attempts", 1),
           "form_finish": st.get("form_finish"),
           "note": "; ".join(problems),
           "missing": [t for t in TAGS if t not in sections],
           "span": "%s-%s" % (span.get("start", "?"), span.get("end", "?")),
           "book": chosen.get("book"), "ts": hms()}
    if not ok:
        # сырой ответ провала — чтобы разобрать, не гоняя заново
        rec["raw"] = (st["raw"] or "")[:3000]

    mark = "✓" if ok else "!"
    log("%s  %s %-38s → %-22s (%s)" % (hms(), mark, q[:38], src_label, verdict),
        mark=mark, extra="")
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Поток
# ─────────────────────────────────────────────────────────────────────────────
def resolve_brain(cfg):
    """Адрес мозга: --brain-url → GOD_BRAIN_URL → HF brain.json."""
    if cfg.brain_url:
        return {"url": cfg.brain_url.rstrip("/"), "key": cfg.brain_key or
                os.environ.get("GOD_BRAIN_KEY", "godbrain-v1-vasiliad"),
                "model": cfg.brain_model or "god-brain", "source": "--brain-url"}
    env = os.environ.get("GOD_BRAIN_URL", "").strip()
    if env:
        return {"url": env.rstrip("/"), "key": cfg.brain_key or
                os.environ.get("GOD_BRAIN_KEY", "godbrain-v1-vasiliad"),
                "model": cfg.brain_model or "god-brain", "source": "GOD_BRAIN_URL"}
    try:
        st = fetch_json(HF_STATUS % "brain")
    except Exception as e:                # noqa: BLE001
        raise SystemExit("Мозг недоступен: brain.json не читается (%s: %s)" % (type(e).__name__, e))
    return {"url": (st.get("url") or "").rstrip("/"),
            "key": st.get("key") or os.environ.get("GOD_BRAIN_KEY", "godbrain-v1-vasiliad"),
            "model": st.get("model") or "god-brain", "source": "HF brain.json",
            "ts": st.get("ts"), "ok": st.get("ok"), "error": st.get("error")}


def resolve_embed(cfg):
    """Адрес сервера эмбеддеров: --embed-url → GOD_EMBED_URL → HF embed.json."""
    if cfg.embed_url:
        return cfg.embed_url.rstrip("/"), "--embed-url"
    env = os.environ.get("GOD_EMBED_URL", "").strip()
    if env:
        return env.rstrip("/"), "GOD_EMBED_URL"
    try:
        st = fetch_json(HF_STATUS % "embed")
    except Exception:                     # noqa: BLE001
        return "", "нет (HF embed.json недоступен)"
    if not st.get("ok") or not st.get("url"):
        return "", "нет (embed.json: %s)" % (st.get("error") or "ok=false")
    return st["url"].rstrip("/"), "HF embed.json"


def run_stream(cfg):
    brain = resolve_brain(cfg)
    if not brain["url"]:
        print("Мозг недоступен: в brain.json нет адреса (ok=%s, ошибка: %s)"
              % (brain.get("ok"), brain.get("error")))
        return 1

    embed_url, embed_src = resolve_embed(cfg)
    # GOD_EMBED_URL читается зеркалом при импорте — задаём до первого запроса
    if embed_url:
        os.environ["GOD_EMBED_URL"] = embed_url
        AS.EMBED_URL = embed_url
    cfg.model = brain["model"]
    cfg.brain_url = brain["url"]
    cfg.brain_key = brain["key"]

    print("ПОТОК ВОПРОСОВ → страница → мозг → проверка")
    print("мозг: %s | %s | модель: %s" % (brain["source"], brain["url"], brain["model"]))
    print("эмбеддер: %s | %s" % (embed_src, embed_url or "—"))
    print("")

    items = load_queue(cfg.queue)
    items = shard_items(items, cfg.shard, cfg.shards)
    if cfg.only:
        items = [it for it in items if cfg.only.lower() in it["q"].lower()]
    if cfg.limit:
        items = items[:cfg.limit]
    print("в очереди: %d вопросов (набор: %s, пачка %d/%d)"
          % (len(items), cfg.queue, cfg.shard + 1, cfg.shards))
    print("")

    episodes = load_corpus()
    corpus_pairs = [(e["book"], e) for e in episodes.values()]
    nikud_index = load_nikud()
    books_ru = page_book_names("ru")

    trace = Trace()
    install_embedder(trace)
    install_no_inner_retry()
    cfg.hybrid = bool(embed_url) or (
        getattr(AS, "browser_embedder", None) is not None and AS.browser_embedder.available())

    out = None
    if cfg.out:
        out_dir = os.path.dirname(os.path.abspath(cfg.out))
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        out = io.open(cfg.out, "w", encoding="utf-8")
    t0 = time.time()
    results = []
    try:
        for i, item in enumerate(items):
            rec = run_one(item, cfg, episodes, corpus_pairs, nikud_index, books_ru, trace,
                          lambda msg, mark="", extra="": (print(msg + extra, flush=True)))
            results.append(rec)
            if out:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
            if i + 1 < len(items) and cfg.pause:
                time.sleep(cfg.pause)
        dur = time.time() - t0
        ok_n = sum(1 for r in results if r["status"] == "ok")
        retries = sum(max(0, r.get("attempts", 1) - 1) for r in results)
        if out:
            out.write(json.dumps({"meta": "shard", "shard": cfg.shard, "shards": cfg.shards,
                                  "wall_s": round(dur, 1), "n": len(results), "ok": ok_n,
                                  "retries": retries}, ensure_ascii=False) + "\n")
            out.flush()
    finally:
        if out:
            out.close()

    print("")
    print("пачка %d/%d: %d/%d сверено · повторов %d · %.0f с"
          % (cfg.shard + 1, cfg.shards, ok_n, len(results), retries, dur))
    return 0 if ok_n == len(results) else 1


# ─────────────────────────────────────────────────────────────────────────────
# Судья: сводка по пачкам
# ─────────────────────────────────────────────────────────────────────────────
def judge(files):
    recs = []
    metas = []
    for f in files:
        try:
            for line in io.open(f, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("meta") == "shard":
                    metas.append(obj)
                else:
                    recs.append(obj)
        except Exception as e:            # noqa: BLE001
            print("! файл %s не прочитан: %s: %s" % (f, type(e).__name__, e))
    if not recs:
        print("ИТОГ: нет результатов — нечего судить")
        return 1

    total = len(recs)
    ok = [r for r in recs if r.get("status") == "ok"]
    bad = [r for r in recs if r.get("status") != "ok"]
    retries = sum(max(0, int(r.get("attempts", 1)) - 1) for r in recs)
    form_retry = sum(max(0, int(r.get("form_attempts", 1)) - 1) for r in recs)
    dur = sum(float(r.get("latency_s", 0)) for r in recs)
    wall = max([float(m.get("wall_s", 0)) for m in metas], default=0.0)
    vec = [r for r in recs if r.get("engine") in ("nemotron", "e5small")]
    nem = [r for r in recs if r.get("engine") == "nemotron"]
    e5 = [r for r in recs if r.get("engine") == "e5small"]
    lex = [r for r in recs if r.get("engine") == "lex"]

    by_lang = {}
    for r in recs:
        d = by_lang.setdefault(r.get("lang", "?"), [0, 0])
        d[1] += 1
        if r.get("status") == "ok":
            d[0] += 1

    print("=== СВОДКА ПОТОКА ===")
    print("ИТОГ: %d/%d сверено · %d повторов · Σ %.0f с · движок: nemotron %d/%d (вектор), "
          "лексика %d/%d"
          % (len(ok), total, retries, dur, len(nem), len(vec), len(lex), total))
    if wall:
        print("стенд шёл %.0f с (пачки параллельно, %d пачек)"
              % (wall, len(metas) or 1))
    if form_retry:
        print("повторов формулировки (недописанные секции): %d" % form_retry)
    if e5:
        print("вектор браузерным e5-small: %d" % len(e5))
    print("по языкам: " + " · ".join("%s %d/%d" % (k, v[0], v[1])
                                     for k, v in sorted(by_lang.items())))
    # тематика: попадание эпизода в золотой эталон (ядро / расширенные места)
    core_n = place_n = miss_n = 0
    grp = {"gold": [0, 0], "para": [0, 0]}     # попало / всего по группе
    missed = {}
    for r in recs:
        kind, base = thematic(r)
        if kind is None:
            continue
        if kind == "core":
            core_n += 1
        elif kind == "places":
            place_n += 1
        else:
            miss_n += 1
        g = "gold" if r.get("tag") == "gold" else "para"
        grp[g][1] += 1
        if kind != "miss":
            grp[g][0] += 1
        else:
            missed.setdefault(base, 0)
            missed[base] += 1
    if grp["gold"][1] or grp["para"][1]:
        print("тематика: золотой эталон — ядро %d, расширенные места %d, мимо %d (из %d ответов)"
              % (core_n, place_n, miss_n, core_n + place_n + miss_n))
        print("  эталонные вопросы: %d/%d попали в эталон · перефразы: %d/%d"
              % (grp["gold"][0], grp["gold"][1], grp["para"][0], grp["para"][1]))
        if missed:
            print("  промах по теме: " + "; ".join("%s (%d)" % (q, n)
                                                   for q, n in sorted(missed.items())))
    lat = sorted(float(r.get("latency_s", 0)) for r in recs)
    if lat:
        print("время ответа: медиана %.1f с · максимум %.1f с"
              % (lat[len(lat) // 2], lat[-1]))
    if bad:
        print("")
        print("ПРОВАЛЫ (%d):" % len(bad))
        for r in bad:
            print("  ! %-40s → %-22s %s" % (r.get("q", "")[:40], r.get("source", "—"),
                                            r.get("note") or r.get("mode") or ""))
    else:
        print("провалов нет")
    return 0 if not bad else 1


# ─────────────────────────────────────────────────────────────────────────────
# Офлайн-самопроверка стенда (сеть подменена)
# ─────────────────────────────────────────────────────────────────────────────
class _FakeResp(object):
    def __init__(self, payload):
        self._data = payload.encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _mock_urlopen_factory(state):
    """Мок сети: отвечает как верный мозг (реплика — из присланного фрагмента)."""
    def fake(req, timeout=None):
        url = getattr(req, "full_url", req)
        body = getattr(req, "data", None)
        if "/v1/embeddings" in url:
            dim = state.get("dim", 8)
            return _FakeResp(json.dumps({"data": [{"embedding": [0.1] * dim}]}))
        if "/v1/chat/completions" in url:
            if state.get("fail_times"):
                state["fail_times"] -= 1
                raise urllib.error.URLError("mock: таймаут")
            payload = json.loads(body.decode("utf-8")) if body else {}
            user = ""
            for m in payload.get("messages", []):
                if m.get("role") == "user":
                    user = m.get("content", "")
            if payload.get("max_tokens", 0) <= 32:
                return _FakeResp(json.dumps({"choices": [{"message": {"content": "S1"}}]}))
            speech = ""
            m = re.search(r"речь Бога:\s*(.+)", user)
            if m:
                speech = m.group(1).strip()
            if state.get("forge"):
                speech = "ענני יהוה ביום צרה קראני ואענה"
            verse = "Genesis 3:9"
            m2 = re.search(r"СТИХ:\s*\[([^\]]+)\]", user)
            if m2:
                verse = m2.group(1).replace("|", " ")
            answer = ("[HEBREW] %s\n[NIKKUD] א\n[Russian] Где ты?\n[English] Where art thou?\n"
                      "[Hebrew Modern] איפה אתה" % (speech,))
            if not state.get("no_sources"):
                answer += "\n[SOURCES] %s" % verse
            return _FakeResp(json.dumps({"choices": [{"message": {"content": answer}}]}))
        raise urllib.error.URLError("mock: неожиданный запрос " + str(url))
    return fake


def selftest():
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name)

    print("=== selftest: офлайн-проверка стенда потока (сеть подменена) ===")

    items = load_queue("all")
    chk("очередь собрана (золотые + спасательные + перефразы)", len(items) > 80)
    gold_n = len(load_queue("gold"))
    rescue_n = len(load_queue("rescue"))
    para_n = len(load_queue("para"))
    chk("наборы не пересекаются по числу: золото %d, спасательные %d, перефразы %d"
        % (gold_n, rescue_n, para_n), gold_n == 14 and rescue_n >= 2 and para_n >= 70)

    seen = []
    for s in range(4):
        seen += shard_items(items, s, 4)
    chk("разбиение на 4 пачки покрывает очередь ровно один раз",
        len(seen) == len(items)
        and sorted(x["q"] for x in seen) == sorted(x["q"] for x in items))

    episodes = load_corpus()
    corpus_pairs = [(e["book"], e) for e in episodes.values()]
    nikud_index = load_nikud()
    books_ru = page_book_names("ru")
    chk("названия книг взяты со страницы", books_ru.get("Isaiah") == "Исаия")

    state = {"fail_times": 0, "forge": False, "dim": 8}
    saved = urllib.request.urlopen
    cfg = type("C", (), {})()
    cfg.brain_url = "http://mock-brain"
    cfg.brain_key = "k"
    cfg.brain_model = "mock"
    cfg.model = "mock"
    cfg.timeout = 10
    cfg.retries = 1
    cfg.hybrid = False

    try:
        urllib.request.urlopen = _mock_urlopen_factory(state)
        trace = Trace()
        install_embedder(trace, allow_browser=False)
        install_no_inner_retry()
        lines = []
        rec = run_one({"q": "как тебя зовут?", "lang": "ru", "tag": "t"}, cfg, episodes,
                      corpus_pairs, nikud_index, books_ru, trace,
                      lambda msg, mark="", extra="": lines.append(msg))
        chk("верный ответ: статус ok, сверка verified", rec["status"] == "ok"
            and rec["mode"] == "verified" and rec["sections"] == 6 and rec["source"])
        chk("строка потока помечена ✓ и содержит источник",
            any(l.startswith(time.strftime("%H:%M:%S")) and "✓" in l and "→" in l for l in lines))

        # ответ без служебной секции [SOURCES] — полный: источник берётся из реестра
        state["no_sources"] = True
        rec_ns = run_one({"q": "как тебя зовут?", "lang": "ru", "tag": "t"}, cfg, episodes,
                         corpus_pairs, nikud_index, books_ru, trace,
                         lambda msg, mark="", extra="": lines.append(msg))
        chk("ответ без [SOURCES] — полный (источник из реестра)", rec_ns["status"] == "ok"
            and rec_ns["content"] == 5 and rec_ns["source"]
            and "[SOURCES]" in (rec_ns.get("missing") or []))
        state["no_sources"] = False

        state["forge"] = True
        rec2 = run_one({"q": "как тебя зовут?", "lang": "ru", "tag": "t"}, cfg, episodes,
                       corpus_pairs, nikud_index, books_ru, trace,
                       lambda msg, mark="", extra="": lines.append(msg))
        chk("выдуманная реплика: провал с пометкой «речи Бога нет»",
            rec2["status"] == "fail" and "речи Бога нет" in rec2["note"]
            and rec2["mode"] == "reject")

        state["forge"] = False
        state["fail_times"] = 1
        lines2 = []
        rec3 = run_one({"q": "как тебя зовут?", "lang": "ru", "tag": "t"}, cfg, episodes,
                       corpus_pairs, nikud_index, books_ru, trace,
                       lambda msg, mark="", extra="": lines2.append(msg))
        chk("сетевой сбой: попытка 2, статус ok", rec3["status"] == "ok"
            and rec3["attempts"] == 2)
        chk("сетевой сбой: в лог ушла строка ⟳ с повтором",
            any("⟳" in l and "повтор" in l for l in lines2))

        state["fail_times"] = 5
        rec4 = run_one({"q": "как тебя зовут?", "lang": "ru", "tag": "t"}, cfg, episodes,
                       corpus_pairs, nikud_index, books_ru, trace,
                       lambda msg, mark="", extra="": lines2.append(msg))
        chk("мозг мёртв: статус error с причиной", rec4["status"] == "error"
            and rec4["attempts"] == 2 and rec4["note"])
        state["fail_times"] = 0
    finally:
        urllib.request.urlopen = saved

    # судья: сводка по поддельным пачкам
    tmp = os.path.join(tempfile.gettempdir(), "god2_stream_selftest.jsonl")
    rows = [{"q": "a", "lang": "ru", "tag": "gold", "status": "ok", "engine": "nemotron",
             "mode": "verified", "sections": 6, "source": "Исаия 58:1", "latency_s": 1.0,
             "attempts": 1, "note": ""},
            {"q": "b", "lang": "ru", "tag": "gold", "status": "fail", "engine": "lex",
             "mode": "reject", "sections": 6, "source": "Исаия 41:10", "latency_s": 2.0,
             "attempts": 2, "note": "речи Бога нет"}]
    with io.open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    code = judge([tmp])
    chk("судья: ненулевой код при провале и верный счёт 1/2", code == 1)
    try:
        os.remove(tmp)
    except OSError:
        pass

    passed = sum(1 for c in checks if c)
    print("")
    print("SELFTEST: %s (%d/%d)" % ("PASS" if passed == len(checks) else "FAIL",
                                    passed, len(checks)))
    return 0 if passed == len(checks) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Поток живых вопросов через реальный путь продукта")
    ap.add_argument("--set", dest="queue", default="all",
                    choices=["all", "gold", "rescue", "para"], help="набор вопросов")
    ap.add_argument("--shard", type=int, default=0, help="номер пачки (с нуля)")
    ap.add_argument("--shards", type=int, default=1, help="сколько пачек")
    ap.add_argument("--limit", type=int, default=0, help="ограничить число вопросов")
    ap.add_argument("--only", default=None, help="оставить только вопросы, содержащие подстроку")
    ap.add_argument("--brain-url", default=None, help="эндпойнт мозга")
    ap.add_argument("--brain-key", default=None, help="ключ мозга")
    ap.add_argument("--brain-model", default=None, help="имя модели для мозга")
    ap.add_argument("--embed-url", default=None, help="эндпойнт сервера эмбеддеров")
    ap.add_argument("--timeout", type=int, default=180, help="таймаут вызова мозга, с")
    ap.add_argument("--retries", type=int, default=1, help="повторов при сетевом сбое")
    ap.add_argument("--pause", type=float, default=0.0, help="пауза между вопросами, с")
    ap.add_argument("--out", default=None, help="JSONL-транскрипт пачки")
    ap.add_argument("--judge", nargs="+", default=None, help="свести пачки (файлы JSONL)")
    ap.add_argument("--selftest", action="store_true", help="офлайн-проверка стенда")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.judge:
        return judge(args.judge)
    if args.shards < 1 or not (0 <= args.shard < args.shards):
        ap.error("--shard/--shards задают несуществующую пачку")
    return run_stream(args)


if __name__ == "__main__":
    sys.exit(main())
