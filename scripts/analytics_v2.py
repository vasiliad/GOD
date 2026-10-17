"""
analytics_v2.py
Аналитика второго порядка по мастер-корпусу (output/episodes_TANAKH_v2.json):
по-книжная и по-эпохальная статистика, P(outcome|trigger), разделение
«объявленных» и «исполненных» кар, распределение каналов.

Выход: output/analytics.json (данные для веб-браузера корпуса) + отчёт.

Usage:
    python scripts/analytics_v2.py
    python scripts/analytics_v2.py --test
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path("C:/GOD2")
MASTER = BASE / "output/episodes_TANAKH_v2.json"
OUT = BASE / "output/analytics.json"

BOOK_ORDER = [
    ("Тора", ["genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]),
    ("Невиим (ранние)", ["Joshua", "Judges", "I_Samuel", "II_Samuel", "I_Kings", "II_Kings"]),
    ("Невиим (поздние)", ["Isaiah", "Jeremiah", "Ezekiel", "Hosea", "Joel", "Amos",
                          "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk",
                          "Zephaniah", "Haggai", "Zechariah", "Malachi"]),
    ("Кетувим", ["Psalms", "Proverbs", "Job", "Song_of_Songs", "Ruth", "Lamentations",
                 "Ecclesiastes", "Esther", "Daniel", "Ezra", "Nehemiah",
                 "I_Chronicles", "II_Chronicles"]),
]


def dist(counter):
    total = sum(counter.values())
    return {k: round(v / total, 3) for k, v in counter.most_common()} if total else {}


def book_stats(eps):
    oc = Counter(e["outcome"] for e in eps)
    dr = Counter(e["direction"] for e in eps)
    via = Counter(e["via"] for e in eps)
    tr = Counter(e["trigger"] for e in eps)
    return {
        "episodes": len(eps),
        "outcome_p": dist(oc),
        "direction_p": dist(dr),
        "via_p": dist(via),
        "top_triggers": dict(tr.most_common(5)),
        "severity_mean": round(sum(e["severity"] for e in eps) / len(eps), 2),
        "silence_rate": round(oc["silence"] / len(eps), 3),
        "punishment_rate": round(oc["punishment"] / len(eps), 3),
        "speech_rate": round(sum(1 for e in eps if e.get("god_speech_refs")) / len(eps), 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    master = json.load(open(MASTER, encoding="utf-8"))

    per_book = {}
    for era, books in BOOK_ORDER:
        for b in books:
            key = b if b in master else ("genesis" if b == "genesis" else b)
            if key not in master:
                per_book[b] = {"episodes": 0, "missing": True}
                continue
            per_book[b] = book_stats(master[key])
            per_book[b]["era"] = era

    per_era = {}
    for era, books in BOOK_ORDER:
        eps = [e for b in books for e in master.get(b if b in master else ("genesis" if b == "genesis" else b), [])]
        if eps:
            per_era[era] = book_stats(eps)

    # P(outcome | trigger) по всему корпусу
    by_trigger = defaultdict(Counter)
    for eps in master.values():
        for e in eps:
            by_trigger[e["trigger"]][e["outcome"]] += 1
    trigger_table = {t: dist(c) | {"n": sum(c.values())} for t, c in sorted(by_trigger.items(), key=lambda x: -sum(x[1].values()))}

    # объявленные vs исполненные кары
    pun = [e for eps in master.values() for e in eps if e["outcome"] == "punishment"]
    announced = [e for e in pun if e["direction"] == "god_initiated"]
    executed = [e for e in pun if e["direction"] == "divine_action"]
    punishment_split = {
        "total": len(pun),
        "announced_oracle": len(announced),
        "executed_action": len(executed),
        "announced_p": round(len(announced) / len(pun), 3),
        "executed_p": round(len(executed) / len(pun), 3),
    }

    total_eps = sum(len(v) for v in master.values())
    analytics = {
        "generated": "2026-10-17",
        "corpus": {"books": len(master), "episodes": total_eps},
        "book_order": {era: books for era, books in BOOK_ORDER},
        "per_book": per_book,
        "per_era": per_era,
        "trigger_table": trigger_table,
        "punishment_split": punishment_split,
    }
    OUT.write_text(json.dumps(analytics, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Книг: {len(master)}, эпизодов: {total_eps}")
    print("\n=== По эпохам ===")
    for era, s in per_era.items():
        top_oc = list(s["outcome_p"].items())[:3]
        print(f"{era:<20} n={s['episodes']:>4} sev={s['severity_mean']:<5} silence={s['silence_rate']:.0%} "
              f"punish={s['punishment_rate']:.0%} | " + " ".join(f"{k}:{v:.0%}" for k, v in top_oc))
    print("\n=== Кара: объявлена vs исполнена ===")
    print(f"  всего {punishment_split['total']}: оракулы {punishment_split['announced_oracle']} "
          f"({punishment_split['announced_p']:.0%}), действия {punishment_split['executed_action']} "
          f"({punishment_split['executed_p']:.0%})")

    if args.test:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        assert d["corpus"]["books"] == 39 and d["corpus"]["episodes"] >= 2000
        assert abs(sum(d["per_era"].values(), start=Counter())["episodes"] if False else sum(s["episodes"] for s in d["per_era"].values()) - d["corpus"]["episodes"]) <= 40  # перекрытия батчей
        for era, s in d["per_era"].items():
            assert 1 <= s["severity_mean"] <= 5
        assert d["punishment_split"]["announced_p"] + d["punishment_split"]["executed_p"] <= 1.001
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
