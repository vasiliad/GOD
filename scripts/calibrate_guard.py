"""Калибровка порога сверки ивритского слоя с корпусом.

Считает для каждого записанного диалога долю слов [HEBREW], найденных:
  * в god_speech_plain эпизода-источника (то, что назвал сам мозг);
  * в объединении god_speech_plain всех эпизодов, переданных мозгу (контекст);
  * во всём корпусе (2050 эпизодов) — проверка «цитата по памяти».

Правило: слова нормализуются (снятие огласовки и кантилляции, маккеф → пробел,
длина ≥ 2 символа). Итог печатается таблицей и сохраняется в JSON — по нему
выбирается порог guard_cov, который потом используют и страница, и скрипты.

    python scripts/calibrate_guard.py
    python scripts/calibrate_guard.py --json /tmp/guard.json
"""
import argparse
import io
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
DIALOGS = _ROOT / "docs" / "data" / "dialogs.json"
MASTER = _ROOT / "output" / "episodes_TANAKH_v2.json"

# Огласовка + кантилляция (U+0591..U+05BD, U+05BF..U+05C7). Маккеф U+05BE не входит.
NIQ = re.compile(r"[֑-ֽֿ-ׇ]")
NON_WORD = re.compile(r"[^א-ת]+")


def toks(s):
    """Слова ивритского текста: без огласовки, маккеф и дефис → пробел, длина ≥ 2."""
    s = NIQ.sub("", str(s or "")).replace("־", " ").replace("-", " ")
    return [w for w in NON_WORD.split(s) if len(w) >= 2]


def coverage(model_words, ref_words):
    """Доля слов ответа, найденных в опорном тексте (0..1)."""
    if not model_words:
        return 0.0
    ref = set(ref_words)
    return sum(1 for w in model_words if w in ref) / len(model_words)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Калибровка порога сверки ивритского слоя")
    ap.add_argument("--json", default=None, help="куда сохранить подробный разбор")
    args = ap.parse_args(argv)

    dlg = json.load(io.open(DIALOGS, encoding="utf-8"))
    master = json.load(io.open(MASTER, encoding="utf-8"))
    episodes = {}
    for book, arr in master.items():
        for e in arr:
            episodes[(book, e["span"]["start"])] = e

    corpus_words = set()
    for e in episodes.values():
        corpus_words.update(toks(e.get("god_speech_plain") or ""))

    rows = []
    print("%-3s %-22s %6s %6s %6s %6s  %s" %
          ("id", "источник мозга", "words", "src", "ctx", "corp", "вердикт"))
    for d in dlg["dialogues"]:
        s = d["sections"]
        model = toks(s.get("[HEBREW]", ""))
        srcs = d.get("sources") or []
        ep = None
        if srcs:
            ep = episodes.get((srcs[0]["book"], srcs[0]["start"]))
        cov_src = coverage(model, toks(ep.get("god_speech_plain") or "")) if ep else 0.0
        cov_corp = coverage(model, corpus_words)
        rows.append({
            "id": d["id"], "q": d["q"], "ok": d["ok"],
            "src_book": srcs[0]["book"] if srcs else None,
            "src_start": srcs[0]["start"] if srcs else None,
            "words": len(model),
            "cov_src": round(cov_src, 3),
            "cov_corp": round(cov_corp, 3),
            "hebrew": s.get("[HEBREW]", ""),
        })
        print("%-3d %-22s %6d %6.2f %6s %6.2f  %s" %
              (d["id"], ("%s %s" % (srcs[0]["book"], srcs[0]["start"])) if srcs else "—",
               len(model), cov_src, "—", cov_corp,
               "ok" if d["ok"] else "FAIL"))

    good = [r for r in rows if r["cov_corp"] >= 0.8]
    bad = [r for r in rows if r["cov_corp"] < 0.8]
    print("\nразделение по порогу 0.80 (покрытие по всему корпусу):")
    print("  проходят: %d/%d, минимум среди проходящих: %s" %
          (len(good), len(rows), ("%.2f" % min(r["cov_corp"] for r in good)) if good else "—"))
    print("  не проходят: %d/%d, максимум среди непроходящих: %s" %
          (len(bad), len(rows), ("%.2f" % max(r["cov_corp"] for r in bad)) if bad else "—"))
    if good and bad:
        print("  зазор: %.2f → %.2f (порог выбирается внутри)" %
              (max(r["cov_corp"] for r in bad), min(r["cov_corp"] for r in good)))

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        with io.open(out, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "corpus_words": len(corpus_words)}, f, ensure_ascii=False, indent=1)
        print("сохранено:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
