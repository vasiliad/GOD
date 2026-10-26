#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прогон правила «S» по уже записанным диалогам → docs/data/dialogs.json.

Записи витрины сделаны ДО появления сверки: модель могла выдумать реплику и
назвать неверный стих. Здесь каждая запись проверяется тем же правилом, что
живой чат на странице (scripts/answer_guard.py), а контекст восстанавливается
ТОЧНО: в новой схеме это выбранный эпизод (поле selected), в старых записях —
детерминированный отбор по вопросу и триггеру.

Что делается с каждой записью:
  * реплика сверяется с переданными фрагментами и со всем реестром;
  * если подтверждения нет — вместо реплики публикуется проверенный прецедент
    корпуса (как в режиме «мозг спит»), а решение пишется в поле guard;
  * источники публикуются ИЗ РЕЕСТРА, а не из цитаты модели.

    python scripts/apply_guard_dialogues.py            # переписать docs/data/dialogs.json
    python scripts/apply_guard_dialogues.py --dry      # только показать, без записи
    python scripts/apply_guard_dialogues.py --test     # офлайн-самопроверка

Только stdlib. UTF-8.
"""
import argparse
import io
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import record_dialogues as rd          # noqa: E402
from answer_guard import apply_guard    # noqa: E402

DEFAULT_PATH = "docs/data/dialogs.json"


def _ctx_for_dialogue(d, episodes, nikud_index):
    """Контекст, который ушёл модели при записи диалога.

    В новой схеме это ОДИН выбранный эпизод (поле selected) — он и есть окно
    сверки. В старых записях (без selected) берётся детерминированный отбор
    по вопросу и триггеру, как раньше.
    """
    sel = d.get("selected") or {}
    if sel.get("book") and sel.get("start"):
        key = "%s|%s" % (sel["book"], sel["start"])
        if key in episodes:
            return [rd.build_context(episodes, nikud_index, [key])[0]]
    q = d.get("q") or ""
    trig = d.get("trigger") or "inquiry"
    hits = rd.rank_episodes(q, trig, episodes, 6)
    return rd.build_context(episodes, nikud_index, hits)


def guard_dialogues(payload, episodes, nikud_index, corpus_pairs):
    """Возвращает (новый payload, сводка по режимам)."""
    modes = {"verified": 0, "corpus": 0, "reject": 0}
    out = []
    for d in payload.get("dialogues", []):
        ctx = _ctx_for_dialogue(d, episodes, nikud_index)
        sections = d.get("sections") or {}
        g = apply_guard(sections, ctx, corpus_pairs,
                        nikud_for=lambda b, refs: rd.nikud_for(b, refs, nikud_index))
        guard = g["guard"]
        modes[guard["mode"]] = modes.get(guard["mode"], 0) + 1
        nd = dict(d)
        nd["model_sections"] = {tag: sections.get(tag, "") for tag in rd.SECTIONS}
        nd["sections"] = {tag: g["sections"].get(tag, "") for tag in rd.SECTIONS}
        nd["model_sources"] = d.get("sources") or []
        nd["sources"] = g["sources"]
        nd["guard"] = guard
        nd["ok"] = bool(d.get("ok")) and guard["mode"] != "reject" and bool(g["sources"])
        out.append(nd)
    new = dict(payload)
    new["dialogues"] = out
    new["guarded"] = True
    new["guard_note"] = ("Ответы сверены с реестром эпизодов: подтверждённая реплика показана "
                         "с источником из реестра; неподтверждённая заменена прецедентом корпуса.")
    return new, modes


def run(path, dry):
    p = Path(path)
    if not p.is_absolute():
        p = _ROOT / p
    payload = json.load(io.open(p, encoding="utf-8"))
    episodes = rd.load_corpus()
    corpus_pairs = [(e["book"], e) for e in episodes.values()]
    nikud_index = rd.load_nikud()
    new, modes = guard_dialogues(payload, episodes, nikud_index, corpus_pairs)
    print("Диалогов: %d | сверка: verified=%d corpus=%d reject=%d"
          % (len(new["dialogues"]), modes.get("verified", 0), modes.get("corpus", 0), modes.get("reject", 0)))
    for d in new["dialogues"]:
        srcs = ", ".join("%s %s" % (s["book"], s["start"]) for s in d["sources"][:3]) or "—"
        print("  #%-2d %-9s cov=%.2f | %-38s | %s"
              % (d.get("id", 0), d["guard"]["mode"], d["guard"]["ctx_cov"], (d.get("q") or "")[:38], srcs))
    if dry:
        print("\n--dry: файл не изменён")
        return 0
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, ensure_ascii=False, indent=1))
    print("\nЗаписано: %s" % p)
    return 0


def run_selftest():
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name)

    episodes = rd.load_corpus()
    corpus_pairs = [(e["book"], e) for e in episodes.values()]
    nikud_index = rd.load_nikud()
    payload = {"dialogues": [
        {"id": 1, "q": "Молю тебя, услышь мой вопль из глубины.", "trigger": "prayer",
         "sections": {"[HEBREW]": "ענני יהוה ביום צרה קראני ואענה", "[Russian]": "Услышь меня",
                      "[English]": "Hear me", "[Hebrew Modern]": "הקשיב לי", "[SOURCES]": "Psalms 27:7"},
         "sources": [{"book": "Psalms", "start": "27:7", "end": "27:7"}], "ok": True}]}
    new, modes = guard_dialogues(payload, episodes, nikud_index, corpus_pairs)
    d = new["dialogues"][0]
    chk("витрина помечена как сверенная", new.get("guarded") is True)
    chk("стих из памяти отклонён", d["guard"]["mode"] == "reject" and modes["reject"] == 1)
    chk("вместо реплики показан прецедент корпуса",
        d["sections"]["[HEBREW]"] != "ענני יהוה ביום צרה קראני ואענה" and d["sections"]["[HEBREW]"] != "")
    chk("исходная реплика модели сохранена", d["model_sections"]["[HEBREW]"] == "ענני יהוה ביום צרה קראני ואענה")
    chk("источник взят из реестра", bool(d["sources"]) and "start" in d["sources"][0])
    chk("отказ снижает статус записи", d["ok"] is False)

    passed = sum(1 for c in checks if c)
    print("\nSELFTEST: %s (%d/%d)" % ("PASS" if passed == len(checks) else "FAIL", passed, len(checks)))
    return 0 if passed == len(checks) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Сверка записанных диалогов с реестром (правило «S»).")
    ap.add_argument("path", nargs="?", default=DEFAULT_PATH)
    ap.add_argument("--dry", action="store_true", help="показать, не записывая")
    ap.add_argument("--test", "--selftest", dest="selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return run_selftest()
    return run(args.path, args.dry)


if __name__ == "__main__":
    sys.exit(main())
