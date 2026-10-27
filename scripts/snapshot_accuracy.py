#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Снимок живой точности мозга → docs/data/accuracy.json.

Та же проверка, что в scripts/test_accuracy.py (10 вопросов → retrieval → мозг →
разбор 6 секций → сверка источника с корпусом), но результат кладётся в JSON,
чтобы сайт показывал честный снимок: сколько ответов пришло со всеми шестью
секциями, сколько — с источником из корпуса, сколько — полных, и какая оценка.

    python scripts/snapshot_accuracy.py            # живой прогон → docs/data/accuracy.json
    python scripts/snapshot_accuracy.py --print    # + подробности по каждому вопросу
    python scripts/snapshot_accuracy.py --test     # офлайн-самопроверка, без сети

Если мозг недоступен — файл всё равно создаётся (чтобы сайт не ломался):
    {"ok": false, "error": "...", "generated": "..."}
и скрипт возвращает ненулевой exit code.

Только stdlib (urllib). UTF-8. Ничего не коммитит.
"""
import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import record_dialogues as rd          # noqa: E402  (общие: статус мозга, запрос, парсер, retrieval)
import test_accuracy as ta             # noqa: E402  (те же 10 вопросов, что у живого гейта)

DEFAULT_OUT = "docs/data/accuracy.json"
DEFAULT_THRESHOLD = 0.6               # как в scripts/test_accuracy.py
DEFAULT_TIMEOUT = 180

# вопросы берём у test_accuracy.py — снимок сопоставим с живым гейтом
QUESTIONS = list(ta.QUESTIONS)


def _utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def find_source(sources_text, episodes):
    """Есть ли в [SOURCES] книга корпуса — та же эвристика, что в test_accuracy.py."""
    if not sources_text:
        return False
    low = sources_text.lower()
    aliases = rd._book_aliases()
    for book in sorted({e["book"] for e in episodes.values()}):
        names = [n for n, b in aliases.items() if b == book]
        if any(n in low for n in names):
            return True
    return False


def summarize(results):
    """Счётчики по ответам: полным считаем 5 содержательных слоёв + сверку с реестром
    + источник из реестра. [SOURCES] — служебная секция: источник берётся ИЗ РЕЕСТРА."""
    n = len(results)
    sections = sum(1 for r in results if r["sections"] >= ta.CONTENT_FULL)
    grounded = sum(1 for r in results if r.get("grounded"))
    sources = sum(1 for r in results if r["sources"])
    full = sum(1 for r in results if r["ok"])
    score = (full / n) if n else 0.0
    return {"n": n, "sections": sections, "grounded": grounded, "sources": sources,
            "full": full, "score": score}


def verdict_line(s, threshold):
    passed = s["score"] >= threshold
    return ("ИТОГ: %d/%d секций, %d/%d сверено с реестром, %d/%d источников, %d/%d полных — %s (оценка %.1f%% %s порог %.1f%%)"
            % (s["sections"], s["n"], s["grounded"], s["n"], s["sources"], s["n"], s["full"], s["n"],
               "PASS" if passed else "FAIL", s["score"] * 100, "≥" if passed else "<", threshold * 100))


def write_json(path, payload):
    out = Path(path)
    if not out.is_absolute():
        out = _ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=1))
    return out


def run_live(out_path, timeout, threshold, do_print, url_override=None, key_override=None):
    if url_override:
        status = {"_source": "локальный мозг (--url)", "url": url_override,
                  "key": key_override or "", "model": rd.API_MODEL}
    else:
        status = rd.fetch_status()
    url = (status.get("url") or "").rstrip("/")
    key = status.get("key") or ""
    model = status.get("model") or rd.API_MODEL
    print("Мозг: %s | url=%s | model=%s" % (status.get("_source"), url or "(нет)", model))
    ts = status.get("ts")
    if isinstance(ts, (int, float)):
        print("Пульс brain.json: %.0f мин назад" % ((time.time() - ts) / 60))
    if not url:
        err = "мозг недоступен: в brain.json нет url"
        print(err)
        out = write_json(out_path, {"ok": False, "error": err, "generated": rd.now_iso()})
        print("Записан: %s" % out)
        return 1

    episodes = rd.load_corpus()
    corpus_pairs = [(e["book"], e) for e in episodes.values()]   # реестр для сверки
    nikud_index = rd.load_nikud()
    endpoint = url.rstrip("/") + "/v1/chat/completions"
    print("Проверка точности мозга: %d вопросов через схему "
          "выбор эпизода → формулировка → сверка с корпусом\n" % len(QUESTIONS))

    results = []
    errors = []
    for qi, q in enumerate(QUESTIONS):
        trig = rd.classify(q)
        # пул 18 → фильтр «только с речью Бога» → 6 кандидатов (как на странице)
        hits = rd.rank_episodes_live(q, trig, episodes, 18, hybrid=True)
        ctx = rd.build_context(episodes, nikud_index, hits)
        print("[%d/%d] «%s» (trig=%s)" % (qi + 1, len(QUESTIONS), q, trig))
        try:
            st = rd.two_stage(q, ctx, endpoint, key, timeout=timeout, model=model,
                              memory=rd.memory_line(q))
            sections = rd.parse_sections(st["raw"])
            chosen = st["chosen"]
            n_sections = sum(1 for t in ta.CONTENT_TAGS if (sections.get(t) or "").strip())
            n_tags = sum(1 for t in rd.SECTIONS if (sections.get(t) or "").strip())
            print("   выбор эпизода: S%d [%s %s] — %s" % (
                st["index"], chosen["book"], chosen["span"]["start"],
                (chosen.get("summary_ru") or "")[:48]))
            # правило «S»: сверка реплики с реестром, источник — из реестра.
            # Окно сверки — ВЫБРАННЫЙ эпизод (ровно он ушёл модели).
            g = rd.apply_guard(sections, [chosen], corpus_pairs,
                               nikud_for=lambda b, refs: rd.nikud_for(b, refs, nikud_index))
            guard = g["guard"]
            grounded = guard["mode"] != "reject"
            src_ok = bool(g["sources"])
            ok = (n_sections >= ta.CONTENT_FULL and grounded and src_ok)
            results.append({"q": q, "ok": ok, "sections": n_sections, "tags": n_tags,
                            "grounded": grounded,
                            "sources": src_ok, "mode": guard["mode"], "ctx_cov": guard["ctx_cov"],
                            "selected": {"book": chosen["book"], "start": chosen["span"]["start"]}})
            print("   слоёв: %d/%d (тегов: %d/6) | сверка: %s (%.0f%%) | источник из реестра: %s | %s"
                  % (n_sections, ta.CONTENT_FULL, n_tags, guard["mode"], 100 * guard["ctx_cov"],
                     "ДА" if src_ok else "НЕТ", "OK" if ok else "!!"))
            if do_print:
                for t in rd.SECTIONS:
                    print("   %-17s %s" % (t, g["sections"].get(t, "")))
        except Exception as e:
            errors.append("%s: %s" % (type(e).__name__, e))
            results.append({"q": q, "ok": False, "sections": 0, "grounded": False,
                            "sources": False, "mode": "ошибка", "ctx_cov": 0.0})
            print("   ОШИБКА: %s" % e)
        print()
        time.sleep(1)

    s = summarize(results)
    passed = s["score"] >= threshold
    line = verdict_line(s, threshold)
    print(line)
    for r in results:
        print("  %s %-38s %d/%d слоёв | src: %s" % ("OK" if r["ok"] else "!!", r["q"][:36], r["sections"],
                                                     ta.CONTENT_FULL,
                                                     "ДА" if r["sources"] else "НЕТ"))

    if errors and s["full"] == 0 and len(errors) == len(results):
        # мозг не ответил ни на один вопрос — это «мозг недоступен», а не «мозг неверен»
        err = "мозг не ответил: " + "; ".join(errors[:3])
        out = write_json(out_path, {"ok": False, "error": err, "generated": rd.now_iso()})
        print("Записан: %s" % out)
        return 1

    payload = {
        "generated": rd.now_iso(),
        "ok": bool(passed),
        "sections": "%d/%d" % (s["sections"], s["n"]),
        "grounded": "%d/%d" % (s["grounded"], s["n"]),
        "sources": "%d/%d" % (s["sources"], s["n"]),
        "full": "%d/%d" % (s["full"], s["n"]),
        "score": round(s["score"] * 100, 1),
        "threshold": round(threshold * 100, 1),
        "model": model,
        "brain_source": status.get("_source"),
        "scheme": "шаг 1 выбор эпизода (temperature 0) → шаг 2 формулировка из одного эпизода → шаг 3 сверка с реестром",
        "questions": results,
    }
    if errors:
        payload["errors"] = errors
    out = write_json(out_path, payload)
    print("Записан: %s" % out)
    return 0 if passed else 1


# ─────────────────────────────────────────────────────────────────────────────
# Офлайн-самопроверка (сеть не нужна)
# ─────────────────────────────────────────────────────────────────────────────
def run_selftest():
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name)

    print("=== selftest: офлайн-проверка снимка точности (сеть не используется) ===")

    secs = rd.parse_sections(rd.FIXTURE)
    chk("парсер находит все 6 секций", len(secs) == 6)
    chk("парсеры record_dialogues и test_accuracy совпадают", secs == ta.parse_sections(rd.FIXTURE))

    episodes = rd.load_corpus()
    chk("источник из [SOURCES] найден в корпусе", find_source("Genesis 3:9", episodes) is True)
    chk("выдуманный источник честно не найден", find_source("[SOURCES] Никто", episodes) is False)
    chk("пустая [SOURCES] — источник не найден", find_source("", episodes) is False)

    good = {"q": "как тебя зовут?", "ok": True, "sections": 5, "grounded": True, "sources": True}
    bad = {"q": "я боюсь умереть", "ok": False, "sections": 0, "grounded": False, "sources": False}
    s = summarize([good, bad])
    chk("сводка считает слои", s["sections"] == 1 and s["sources"] == 1)
    chk("сводка считает сверенные с реестром", s["grounded"] == 1)
    chk("сводка считает полные ответы", s["full"] == 1 and abs(s["score"] - 0.5) < 1e-9)
    chk("все ошибки дают score 0", summarize([bad, bad])["score"] == 0.0)
    chk("вердикт PASS при score ≥ порога", "PASS" in verdict_line(summarize([good, good]), 0.6))
    chk("вердикт FAIL при score < порога", "FAIL" in verdict_line(summarize([good, bad]), 0.6))
    no_src = rd.parse_sections(rd.FIXTURE.replace("[SOURCES]", ""))
    chk("ответ без [SOURCES] — полный (пять содержательных слоёв)",
        sum(1 for t in ta.CONTENT_TAGS if (no_src.get(t) or "").strip()) == ta.CONTENT_FULL)

    chk("вопросов ровно 10, как в test_accuracy.py", len(QUESTIONS) == 10)
    chk("вопросы совпадают с test_accuracy.py", QUESTIONS == list(ta.QUESTIONS))

    payload = {"generated": rd.now_iso(), "ok": True, "sections": "10/10", "grounded": "9/10",
               "sources": "9/10",
               "full": "9/10", "score": 90.0, "threshold": 60.0, "model": "mock",
               "questions": [{"q": "как тебя зовут?", "ok": True, "sections": 6, "grounded": True, "sources": True}]}
    path = Path(os.environ.get("TEMP", "/tmp")) / "god2_accuracy_selftest.json"
    out = write_json(str(path), payload)
    back = json.load(io.open(out, encoding="utf-8"))
    chk("JSON снимка читается обратно", back["full"] == "9/10" and back["score"] == 90.0)
    try:
        os.remove(str(out))
    except OSError:
        pass

    passed = sum(1 for c in checks if c)
    print("\nSELFTEST: %s (%d/%d)" % ("PASS" if passed == len(checks) else "FAIL", passed, len(checks)))
    return 0 if passed == len(checks) else 1


def main(argv=None):
    _utf8_stdio()
    ap = argparse.ArgumentParser(description="Снимок живой точности мозга → docs/data/accuracy.json.")
    ap.add_argument("--out", default=DEFAULT_OUT, help="путь к JSON (по умолчанию %s)" % DEFAULT_OUT)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="таймаут одного запроса, с (по умолчанию %d)" % DEFAULT_TIMEOUT)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help="минимальная доля полных ответов для PASS (0..1, по умолчанию %s)" % DEFAULT_THRESHOLD)
    ap.add_argument("--print", dest="do_print", action="store_true", help="печатать ответы в консоль")
    ap.add_argument("--url", default=None,
                    help="эндпойнт мозга (по умолчанию — из HF brain.json; локальный: http://127.0.0.1:18099)")
    ap.add_argument("--key", default=None, help="ключ мозга (для --url)")
    ap.add_argument("--test", "--selftest", dest="selftest", action="store_true",
                    help="офлайн-самопроверка, без сети")
    args = ap.parse_args(argv)
    if not 0.0 <= args.threshold <= 1.0:
        ap.error("--threshold должен быть в диапазоне 0..1")
    if args.selftest:
        return run_selftest()
    return run_live(args.out, args.timeout, args.threshold, args.do_print,
                    url_override=args.url, key_override=args.key)


if __name__ == "__main__":
    sys.exit(main())
