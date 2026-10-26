"""
god_profile.py
Поведенческий профиль Бога для предсказания реакции: P(outcome | trigger) и
смежные распределения из реестра эпизодов v2 (все книги).

Отличие от старого output/god_profile.json (архетипы Юнга/Берна по 396
старым ситуациям): здесь — предсказательная статистика поведения.

Выход:
    output/god_behavior_profile.json  — машинный профиль (используется god_chat)
    docs/data/god_behavior_profile.json — тот же профиль для страницы (--publish)
    консольный отчёт                  — человекочитаемый

Фактор действия (response_modes) — четыре паттерна реакции Бога, выведенные из
реестра: слова × действие. Раньше эти числа были вписаны в публикуемый JSON руками
и не пересчитывались ни одним скриптом; теперь они считаются здесь и публикуются
вместе с остальным профилем, поэтому страница и реестр не могут разойтись.

Usage:
    python scripts/god_profile.py
    python scripts/god_profile.py --publish
    python scripts/god_profile.py --test
    python scripts/god_profile.py --predict "intercession"
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(_REPO)
MASTER = BASE / "output/episodes_TANAKH_v2.json"
OUT_FILE = BASE / "output/god_behavior_profile.json"
DATA_FILE = BASE / "docs" / "data" / "god_behavior_profile.json"

# Легенда фактора действия — словарь страницы и отчётов.
RESPONSE_MODE_LEGEND = {
    "speaks_and_acts": "Бог говорит И действует (основной паттерн для непослушания, завета)",
    "acts_silently": "Бог действует МОЛЧА — без слов, только действие (доминирует для мольбы, молитвы, верности)",
    "silence": "Бог молчит полностью — ни слова, ни действия",
    "speaks_only": "Бог только говорит без видимого действия (редчайший паттерн — 0-1%)",
}


def load_episodes():
    """Эпизоды мастер-корпуса output/episodes_TANAKH_v2.json (dict {книга: [эп]}).

    Раньше читались файлы по книгам output/episodes_*_v2.json (2056 эпизодов
    до дедупликации); мастер содержит те же 2056 после слития 6 перекрытий —
    статистика считается по нему, чтобы профиль совпадал с корпусом на странице.
    """
    master = json.load(open(MASTER, encoding="utf-8"))
    eps = []
    for book, book_eps in master.items():
        for ep in book_eps:
            ep = dict(ep)
            ep["_book"] = book
            eps.append(ep)
    return eps


def dist(counter, total):
    return {k: round(v / total, 3) for k, v in counter.most_common()}


def response_modes(eps):
    """Фактор действия: четыре паттерна реакции Бога по словам × действию.

    speaks_and_acts — есть и слова, и действие; acts_silently — действие без слов;
    silence — ни слов, ни действия; speaks_only — слова без видимого действия.
    Режим класса = самый частый паттерн, confidence = его доля.
    """
    groups = defaultdict(list)
    for e in eps:
        groups[e["trigger"]].append(e)
    modes = {}
    for trig, es in sorted(groups.items()):
        n = len(es)
        c = Counter()
        for e in es:
            speaks = bool((e.get("god_speech_plain") or "").strip())
            acts = bool((e.get("god_action") or "").strip())
            if speaks and acts:
                c["speaks_and_acts"] += 1
            elif acts:
                c["acts_silently"] += 1
            elif speaks:
                c["speaks_only"] += 1
            else:
                c["silence"] += 1
        dist = {k: round(v / n, 2) for k, v in c.most_common()}
        mode = max(dist, key=dist.get) if dist else "silence"
        modes[trig] = {"mode": mode, "confidence": dist.get(mode, 0.0),
                       "distribution": dist, "total": n}
    return modes


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
        "response_modes": {},
        "response_mode_legend": RESPONSE_MODE_LEGEND,
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
    # фактор действия: форма реакции по классам обращения
    profile["response_modes"] = response_modes(eps)
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
    ap.add_argument("--publish", action="store_true",
                    help="перезаписать docs/data/god_behavior_profile.json (страница читает его)")
    ap.add_argument("--predict", help="предсказать исход для trigger (например: intercession)")
    args = ap.parse_args()

    eps = load_episodes()
    profile = build_profile(eps)
    OUT_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.publish:
        DATA_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
        print("опубликовано: %s" % DATA_FILE.relative_to(BASE))

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
        rm = profile["response_modes"][trig]
        print(f"{trig:<22} n={t['n']:>3} sev={t['severity_mean']:<4} " +
              " ".join(f"{k}:{v:.0%}" for k, v in top) +
              f"   [{rm['mode']} {rm['confidence']:.0%}]")
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
        # фактор действия: сумма долей класса ≈ 1, режим — самый частый паттерн
        for trig, rm in d["response_modes"].items():
            assert abs(sum(rm["distribution"].values()) - 1.0) < 0.03, f"режимы {trig} не сходятся"
            assert rm["total"] == d["by_trigger"][trig]["n"], f"режимы {trig}: расхождение n"
            assert rm["mode"] == max(rm["distribution"], key=rm["distribution"].get), f"режим {trig} не самый частый"
        assert set(d["response_mode_legend"]) == {"speaks_and_acts", "acts_silently", "silence", "speaks_only"}
        # опубликованная копия страницы не должна разойтись с мастером
        if DATA_FILE.exists():
            pub = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            assert pub["response_modes"] == d["response_modes"], "docs/data профиль разошёлся с output"
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
