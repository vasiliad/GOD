"""
god_profile.py
Поведенческий профиль Бога для предсказания реакции: P(outcome | trigger) и
смежные распределения из реестра эпизодов v2 (все книги).

Отличие от старого output/god_profile.json (архетипы Юнга/Берна по 396
старым ситуациям): здесь — предсказательная статистика поведения.

Выход:
    output/god_behavior_profile.json  — машинный профиль (используется god_chat)
    консольный отчёт                  — человекочитаемый

Usage:
    python scripts/god_profile.py
    python scripts/god_profile.py --test
    python scripts/god_profile.py --predict "intercession"
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path("C:/GOD2")
EPISODES_GLOB = "output/episodes_*_v2.json"
OUT_FILE = BASE / "output/god_behavior_profile.json"


def load_episodes():
    eps = []
    for fp in sorted(BASE.glob(EPISODES_GLOB)):
        book = fp.stem.replace("episodes_", "").replace("_v2", "")
        for ep in json.load(open(fp, encoding="utf-8")):
            ep["_book"] = book
            eps.append(ep)
    return eps


def dist(counter, total):
    return {k: round(v / total, 3) for k, v in counter.most_common()}


def build_profile(eps):
    n = len(eps)
    profile = {
        "metadata": {
            "version": "behavioral-v1 (episodes v2)",
            "episodes": n,
            "books": sorted({e["_book"] for e in eps}),
            "note": "P(outcome|trigger) — предсказание реакции Бога; вероятности по наблюдениям реестра v2",
        },
        "overall": {
            "outcome": dist(Counter(e["outcome"] for e in eps), n),
            "direction": dist(Counter(e["direction"] for e in eps), n),
            "via": dist(Counter(e["via"] for e in eps), n),
            "addressee": dist(Counter(e["addressee_type"] for e in eps), n),
            "severity_mean": round(sum(e["severity"] for e in eps) / n, 2),
        },
        "by_trigger": {},
        "by_trigger_direction": {},
        "severity_by_outcome": {},
    }
    # P(outcome | trigger) + сигнатура триггера
    groups = defaultdict(list)
    for e in eps:
        groups[e["trigger"]].append(e)
    for trig, es in sorted(groups.items()):
        m = len(es)
        profile["by_trigger"][trig] = {
            "n": m,
            "outcome_p": dist(Counter(e["outcome"] for e in es), m),
            "severity_mean": round(sum(e["severity"] for e in es) / m, 2),
            "top_emotions": [emo.get("emotion", str(emo)) if isinstance(emo, dict) else str(emo)
                         for emo in sum((e["emotions"] for e in es), [])][:5],
            "typical_quote": next((e["god_speech_plain"][:80] for e in es if e["god_speech_plain"]), ""),
        }
    # trigger × direction
    td = defaultdict(Counter)
    for e in eps:
        td[e["trigger"]][e["direction"]] += 1
    profile["by_trigger_direction"] = {t: dict(c) for t, c in td.items()}
    # средняя severity по исходам
    so = defaultdict(list)
    for e in eps:
        so[e["outcome"]].append(e["severity"])
    profile["severity_by_outcome"] = {k: round(sum(v) / len(v), 2) for k, v in so.items()}
    return profile


def predict(profile, trigger):
    t = profile["by_trigger"].get(trigger)
    if not t:
        return None
    return {"trigger": trigger, "predicted_outcome": max(t["outcome_p"], key=t["outcome_p"].get),
            "probabilities": t["outcome_p"], "severity_expected": t["severity_mean"], "n_observed": t["n"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--predict", help="предсказать исход для trigger (например: intercession)")
    args = ap.parse_args()

    eps = load_episodes()
    profile = build_profile(eps)
    OUT_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.predict:
        p = predict(profile, args.predict)
        print(json.dumps(p, ensure_ascii=False, indent=1))
        return

    o = profile["overall"]
    print(f"Эпизодов: {profile['metadata']['episodes']}  Книги: {', '.join(profile['metadata']['books'])}")
    print(f"Исходы:   {o['outcome']}")
    print(f"Каналы:   {o['via']}")
    print(f"Средняя серьёзность: {o['severity_mean']}")
    print("\n=== P(outcome | trigger) — предсказание реакции ===")
    for trig, t in profile["by_trigger"].items():
        top = list(t["outcome_p"].items())[:3]
        print(f"{trig:<22} n={t['n']:>3} sev={t['severity_mean']:<4} " +
              " ".join(f"{k}:{v:.0%}" for k, v in top))
    print("\nСерьёзность по исходам:", profile["severity_by_outcome"])

    if args.test:
        d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        assert d["metadata"]["episodes"] >= 300, "полный реестр v2"
        assert set(d["by_trigger"]) >= {"complaint", "distress", "intercession", "covenant_follow_up", "disobedience"}, "ключевые триггеры"
        for trig, t in d["by_trigger"].items():
            assert abs(sum(t["outcome_p"].values()) - 1.0) < 0.05, f"вероятности {trig} не сходятся"
            assert 1 <= t["severity_mean"] <= 5
        pr = predict(d, "intercession")
        assert pr and 0 <= pr["probabilities"][pr["predicted_outcome"]] <= 1
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
