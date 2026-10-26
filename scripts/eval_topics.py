#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ГЕЙТ ТЕМАТИКИ: попадает ли выбранный эпизод в золотой эталон вопроса.

Сверка ответа с реестром (answer_guard) отвечает на вопрос «слова взяты из
эпизода?». Этот гейт отвечает на другой: «эпизод вообще по теме вопроса?».
Эталон — scripts/topic_gold.json: по каждому вопросу множество ДОПУСТИМЫХ мест
Танаха (5–10 на вопрос), совпадение — вхождение стиха в span эпизода.

Конфигурации (--pool, --action):
    pool=6  action=0  — как было до волны «образ Бога»: 6 найденных, из них
                         модель видела 1–3 с речью Бога;
    pool=18 action=0  — широкий пул ДО фильтра (фильтр обеднял меню модели);
    pool=18 action=1  — плюс блок [ACTION]: форма реакции и P(исход|класс)
                         из профиля реестра («образ Бога») в шаге выбора.

Запуск (нужен живой мозг на 127.0.0.1:18099):
    python scripts/eval_topics.py --pool 18 --action 1 --stage select
    python scripts/eval_topics.py --pool 18 --action 1 --stage full

Ответы мозга кэшируются в .agent/topic_cache.json — повторный прогон не тратит GPU.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
from answer_scheme import (action_block, build_context, candidate_block, classify,  # noqa: E402
                           episode_block, load_corpus, load_nikud, load_profile,
                           pick_index, rank_episodes, spoken_candidates,
                           SYS_PROMPT, SYS_SELECT, trig_class)
from answer_guard import apply_guard   # noqa: E402

GOLD_FILE = _ROOT / "scripts" / "topic_gold.json"
CACHE_FILE = _ROOT / ".agent" / "topic_cache.json"
BRAIN_URL = "http://127.0.0.1:18099/v1/chat/completions"
BRAIN_KEY = "godbrain-v1-vasiliad"
BRAIN_MODEL = "god-brain"

_SECTIONS = ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]


def parse_sections(text):
    out = {}
    for tag in _SECTIONS:
        i = text.find(tag)
        if i < 0:
            continue
        rest = text[i + len(tag):]
        end = len(rest)
        for t2 in _SECTIONS:
            j = rest.find(t2)
            if 0 <= j < end:
                end = j
        out[tag] = rest[:end].strip()
    return out


def parse_ref(ref):
    m = re.match(r"^(\d+):(\d+)$", str(ref or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def span_contains(ep, ref):
    p = parse_ref(ref)
    if not p:
        return False
    s = parse_ref((ep.get("span") or {}).get("start"))
    e = parse_ref((ep.get("span") or {}).get("end")) or s
    return bool(s) and s <= p <= e


def load_gold():
    """[(вопрос, расширенный набор мест, строгое ядро)] — ядро может отсутствовать."""
    data = json.loads(GOLD_FILE.read_text(encoding="utf-8"))
    return [(item["q"], item["places"], item.get("core") or item["places"])
            for item in data["questions"]]


def gold_keys(episodes, refs, spoken_only=True):
    """Допустимые эпизоды реестра для мест эталона (стих внутри span эпизода).

    spoken_only=True — оставить только эпизоды, где Бог говорит: меню модели
    состоит именно из таких (остальное цитировать нечего), поэтому золотым
    местом считается то, куда ответ реально может прийти. Без этого фильтра
    гейт требовал попасть в места, где Бог молчит, и занижал оценку.
    """
    out = set()
    for r in refs:
        book, ref = r.rsplit(" ", 1)
        for k, e in episodes.items():
            if e["book"].lower() == book.lower() and span_contains(e, ref):
                if spoken_only and not (e.get("god_speech_plain") or "").strip():
                    continue
                out.add(k)
    return out


def key_of(ctx):
    """Ключ эпизода по book:start (ctx — срезанные копии из build_context)."""
    return "%s|%s" % (ctx["book"], ctx["span"]["start"])


def brain(system, user, max_tokens=16, temperature=0.0, cache=None, cache_key=None):
    import urllib.request
    if cache is not None and cache_key and cache_key in cache:
        return cache[cache_key]
    body = json.dumps({
        "model": BRAIN_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature, "max_tokens": max_tokens,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BRAIN_URL, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + BRAIN_KEY})
    with urllib.request.urlopen(req, timeout=300) as r:
        text = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
    if cache is not None and cache_key:
        cache[cache_key] = text
    return text


def prompt_key(tag, kind, q, payload):
    """Ключ кэша — с хэшем САМОГО промпта.

    Прежний ключ держал только вопрос: как только менялся отбор кандидатов
    (словари мостов, маппинг классов, блок [ACTION]), в кэше лежал ответ
    для другого меню — и замер считал не то, что делает страница. Теперь
    любой такой сдвиг автоматически инвалидирует кэш.
    """
    import hashlib
    h = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return "%s|%s|%s|%s" % (tag, kind, q, h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=18, help="размер пула до фильтра речи")
    ap.add_argument("--menu", type=int, default=6, help="сколько кандидатов видит модель")
    ap.add_argument("--action", type=int, default=1, help="1 — блок [ACTION] в шаге выбора")
    ap.add_argument("--stage", choices=["select", "full"], default="select")
    ap.add_argument("--gold", choices=["spoken", "all"], default="spoken",
                    help="spoken — эталон только там, где Бог говорит (достижимо)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    eps = load_corpus()
    nikud = load_nikud()
    prof = load_profile()
    gold = load_gold()
    cache = {} if args.no_cache else (json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                                      if CACHE_FILE.exists() else {})
    tag = "v4_pool%d_menu%d_action%d_%s_%s" % (args.pool, args.menu, args.action,
                                                args.stage, args.gold)

    hits = 0
    core_hits = 0
    menu_hits = 0
    rows = []
    for q, places, core in gold:
        trig = classify(q)
        cls = trig_class(trig)
        ranked = rank_episodes(q, trig, eps, args.pool)
        keys = ranked[:args.pool]
        ctx = build_context(eps, nikud, keys)
        cand = spoken_candidates(ctx, args.menu)
        act = action_block(cls, prof) if args.action else ""
        sel_user = candidate_block(q, cand) + ("\n\n" + act if act else "")
        raw_sel = brain(SYS_SELECT, sel_user, 16, 0.0, cache,
                        prompt_key(tag, "sel", q, sel_user))
        idx = pick_index(raw_sel, len(cand))
        chosen = cand[idx - 1]
        chosen_key = key_of(chosen)
        gk = gold_keys(eps, places, spoken_only=(args.gold == "spoken"))
        ck = gold_keys(eps, core, spoken_only=(args.gold == "spoken"))
        hit = chosen_key in gk
        core_hit = chosen_key in ck
        menu_hit = any(key_of(c) in gk for c in cand)

        grounded = None
        mode = "—"
        if args.stage == "full":
            user_form = "ВОПРОС ЧЕЛОВЕКА: %s\n\n%s\n\nОтветь шестью секциями." % (q, episode_block(chosen))
            raw = brain(SYS_PROMPT, user_form, 900, 0.15, cache,
                        prompt_key(tag, "form", q, user_form))
            sections = parse_sections(raw)
            registry = [(e["book"], e) for e in eps.values()]
            guard = apply_guard(sections, [chosen], registry, nikud_for=None)
            mode = guard["guard"]["mode"]
            grounded = mode != "reject"

        hits += 1 if hit else 0
        core_hits += 1 if core_hit else 0
        menu_hits += 1 if menu_hit else 0
        rows.append((q, chosen_key, hit, mode, grounded))
        print("%s %-32s → %-26s %s" % ("OK " if hit else "·  ", q[:32], chosen_key,
                                       ("сверка=%s" % mode) if args.stage == "full" else ""))

    n = len(gold)
    print("\n=== %s ===" % tag)
    print("тематика (расширенный эталон): %d/%d (%.0f%%)" % (hits, n, 100.0 * hits / n))
    print("тематика (строгое ядро):       %d/%d (%.0f%%)" % (core_hits, n, 100.0 * core_hits / n))
    print("меню содержит эталон:           %d/%d (%.0f%%)" % (menu_hits, n, 100.0 * menu_hits / n))
    if args.stage == "full":
        g = sum(1 for r in rows if r[4])
        print("сверено с реестром:            %d/%d (%.0f%%)" % (g, n, 100.0 * g / n))
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print("кэш ответов: %s" % CACHE_FILE)


if __name__ == "__main__":
    main()
