"""Калибровка сверки цитаты: слова + непрерывные фрагменты речи.

Для каждого записанного диалога ищет в корпусе:
  * покрытие словами (все слова [HEBREW], найденные в речи эпизода);
  * покрытие непрерывным фрагментом (contiguous) — сколько слов ответа идёт
    подряд, как в реальной речи эпизода;
  * лучший эпизод и его позицию в тексте.

Это и есть проверка «цитата настоящая»: модель почти всегда цитирует
непрерывный кусок стиха, поэтому contiguous-покрытие отличает настоящую
цитату от «лоскутного» текста из настоящих слов.

    python scripts/calibrate_quote.py
"""
import argparse
import io
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
DIALOGS = _ROOT / "docs" / "data" / "dialogs.json"
MASTER = _ROOT / "output" / "episodes_TANAKH_v2.json"

NIQ = re.compile(r"[֑-ֽֿ-ׇ]")
NON_WORD = re.compile(r"[^א-ת]+")


def toks(s):
    s = NIQ.sub("", str(s or "")).replace("־", " ").replace("-", " ")
    return [w for w in NON_WORD.split(s) if len(w) >= 2]


def blocks(model, ref):
    """Непрерывные совпадения (слова) model против ref."""
    sm = SequenceMatcher(None, model, ref, autojunk=False)
    return sm.get_matching_blocks()


def best_episode(model, episodes):
    """Лучший эпизод по непрерывному совпадению: (покрытие, длина блока, ключ, эпизод)."""
    best = (0.0, 0, None, None)
    for key, e in episodes.items():
        ref = toks(e.get("god_speech_plain") or "")
        if not ref or not model:
            continue
        bl = blocks(model, ref)
        covered = sum(b.size for b in bl)
        run = max((b.size for b in bl), default=0)
        cov = covered / len(model)
        if (cov, run) > (best[0], best[1]):
            best = (cov, run, key, e)
    return best


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    dlg = json.load(io.open(DIALOGS, encoding="utf-8"))
    master = json.load(io.open(MASTER, encoding="utf-8"))
    episodes = {}
    for book, arr in master.items():
        for e in arr:
            episodes[(book, e["span"]["start"])] = e

    rows = []
    print("%-3s %-18s %5s %6s %5s  %-22s %s" %
          ("id", "источник мозга", "words", "contig", "run", "лучший эпизод по цитате", "текст"))
    for d in dlg["dialogues"]:
        s = d["sections"]
        model = toks(s.get("[HEBREW]", ""))
        srcs = d.get("sources") or []
        cited = ("%s %s" % (srcs[0]["book"], srcs[0]["start"])) if srcs else "—"
        cov, run, key, e = best_episode(model, episodes)
        rows.append({
            "id": d["id"], "q": d["q"], "cited": cited,
            "words": len(model), "contig_cov": round(cov, 3), "run": run,
            "best_key": "%s %s" % key if key else None,
            "best_cov": round(cov, 3),
            "hebrew": s.get("[HEBREW]", ""),
        })
        print("%-3d %-18s %5d %6.2f %5d  %-22s %s" %
              (d["id"], cited, len(model), cov, run,
               ("%s %s" % key) if key else "—", s.get("[HEBREW]", "")[:42]))

    print("\nпорог contiguous-покрытия:")
    for th in (0.5, 0.6, 0.7, 0.8, 0.9):
        n = sum(1 for r in rows if r["contig_cov"] >= th)
        print("  ≥ %.1f: %d/%d" % (th, n, len(rows)))

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        with io.open(out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print("сохранено:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
