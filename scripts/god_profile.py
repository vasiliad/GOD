"""
god_profile.py
Поведенческий профиль Бога для предсказания реакции: P(outcome | trigger) и
смежные распределения из реестра эпизодов v2 (все книги).

Отличие от старого output/god_profile.json (архетипы Юнга/Берна по 396
старым ситуациям): здесь — предсказательная статистика поведения.

Версия 2 (2026-10-27) добавляет к базовой таблице три вещи, без которых
«профиль» остаётся арифметикой по корпусу, а не инструментом:

  1. УСЛОВНЫЕ ТАБЛИЦЫ P(outcome | trigger, эпоха/жанр/адресат).
     Один и тот же класс обращения в Торе, у пророков и в псалмодии даёт
     разную реакцию: закон — угрозу и суд, пророческая речь — откровение и
     призыв, поэзия — благословение и утешение. Смешанная таблица P(outcome|
     trigger) это различие прячет. Ключи контекста — scripts/corpus_meta.py
     (единая разметка книг, общая с калибровкой и страницей).
  2. СГЛАЖЕННЫЕ ВЕРОЯТНОСТИ (Дирихле, alpha = 5) к базовой частоте исходов.
     Сырые доли на малых выборках дают 0 % и 100 %: класс с тремя эпизодами
     выглядит как правило, хотя это шум. Сглаженная оценка честно показывает,
     где данных мало, и не выдаёт шум за профиль.
  3. ОСЬ ТОНА (из scripts/tone_metrics.py): длина речи, плотность лексики
     гнева и милости, доля обращения и самоименования. Тон — измеримая
     особенность речи в эпизоде, а не характеристика Бога; она проверяется
     независимой оценкой моделью (scripts/tone_rater.py).

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
    python scripts/god_profile.py --predict "disobedience" --era "Кетувим"
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(_REPO)
sys.path.insert(0, str(BASE / "scripts"))
import corpus_meta   # noqa: E402
import tone_metrics  # noqa: E402

MASTER = BASE / "output/episodes_TANAKH_v2.json"
OUT_FILE = BASE / "output/god_behavior_profile.json"
DATA_FILE = BASE / "docs" / "data" / "god_behavior_profile.json"

# Сглаживание Дирихле к базовой частоте исходов. alpha = 5 — компромисс:
# при n = 5 сглаживание отводит примерно половину веса глобальной базе,
# при n = 50 — почти ничего (своя статистика класса остаётся решающей).
ALPHA = 5.0

# Минимальная выборка, начиная с которой оценка класса считается «надежной».
# Меньше — показываем явно как предварительную.
RELIABLE_N = 20

# Легенда фактора действия — словарь страницы и отчётов.
RESPONSE_MODE_LEGEND = {
    "speaks_and_acts": "Бог говорит И действует (основной паттерн для непослушания, завета)",
    "acts_silently": "Бог действует МОЛЧА — без слов, только действие (доминирует для мольбы, молитвы, верности)",
    "silence": "Бог молчит полностью — ни слова, ни действия",
    "speaks_only": "Бог только говорит без видимого действия (редчайший паттерн — 0-1%)",
}

# Легенды измерений контекста — словарь страницы.
CONTEXT_LEGEND = {
    "era": "эпоха корпуса (Тора / Невиим ранние / Невиим поздние / Кетувим)",
    "genre": "жанр книги (закон / повествование / пророчество / поэзия / мудрость)",
    "addressee": "кому обращено (нация / индивид / иноплеменник / коллектив)",
}

# Ключи контекста: (имя в профиле, поле эпизода)
CONTEXT_DIMS = (("era", "_era"), ("genre", "_genre"), ("addressee", "_addr"))


def load_episodes():
    """Эпизоды мастер-корпуса output/episodes_TANAKH_v2.json (dict {книга: [эп]}).

    Раньше читались файлы по книгам output/episodes_*_v2.json (2056 эпизодов
    до дедупликации); мастер содержит те же 2056 после слития 6 перекрытий —
    статистика считается по нему, чтобы профиль совпадал с корпусом на странице.

    Каждому эпизоду проставляются ключи контекста: _era, _genre, _addr.
    """
    master = json.load(open(MASTER, encoding="utf-8"))
    eps = []
    for book, book_eps in master.items():
        for ep in book_eps:
            ep = dict(ep)
            ep["_book"] = book
            ep["_era"] = corpus_meta.era_of(book)
            ep["_genre"] = corpus_meta.genre_of(book)
            ep["_addr"] = corpus_meta.addressee_group(ep.get("addressee_type"))
            eps.append(ep)
    return eps


def dist(counter, total):
    return {k: round(v / total, 3) for k, v in counter.most_common()}


def probs(counter):
    """Точные доли (без округления) — база для сглаживания."""
    total = sum(counter.values())
    if not total:
        return {}
    return {k: v / total for k, v in counter.items()}


def smooth(counts, base_p, alpha=ALPHA):
    """Сглаживание Дирихле к базовому распределению.

        p(k) = (count(k) + alpha * base(k)) / (n + alpha)

    При base — распределении с суммой 1 итоговая сумма p = 1.
    Малые выборки притягиваются к базе, большие остаются своими.
    """
    n = sum(counts.values())
    if n <= 0:
        return {}
    keys = set(base_p) | set(counts)
    raw = {k: (counts.get(k, 0) + alpha * base_p.get(k, 0.0)) / (n + alpha) for k in keys}
    return {k: round(raw[k], 4) for k in sorted(raw, key=lambda k: (-raw[k], k))}


def base_rate(eps):
    """Глобальная частота исходов — цель сглаживания."""
    return probs(Counter(e["outcome"] for e in eps))


def response_modes(eps):
    """Фактор действия: четыре паттерна реакции Бога по словам × действие.

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


def _marginal(eps, base_p):
    """Сводка по одной группе: n, исходы (сырые и сглаженные), серьёзность, доля речи."""
    n = len(eps)
    if not n:
        return None
    counts = Counter(e["outcome"] for e in eps)
    spoken = sum(1 for e in eps if (e.get("god_speech_plain") or "").strip())
    return {
        "n": n,
        "outcome_p": dist(counts, n),
        "outcome_p_smooth": smooth(counts, base_p),
        "severity_mean": round(sum(e["severity"] for e in eps) / n, 2),
        "speech_share": round(spoken / n, 3),
        "reliable": n >= RELIABLE_N,
    }


def _conditional(eps, parent_p):
    """P(outcome | класс, контекст) со сжатием к родительскому распределению.

    Ячейка с малым n не должна переопределять класс: её оценка притягивается
    к распределению родителя (P(outcome|trigger)) сглаживанием alpha.
    """
    n = len(eps)
    if not n:
        return None
    counts = Counter(e["outcome"] for e in eps)
    return {
        "n": n,
        "outcome_p": dist(counts, n),
        "outcome_p_smooth": smooth(counts, parent_p),
        "severity_mean": round(sum(e["severity"] for e in eps) / n, 2),
        "reliable": n >= RELIABLE_N,
    }


def build_profile(eps):
    n = len(eps)
    base_p = base_rate(eps)
    profile = {
        "metadata": {
            "version": "behavioral-v2 (episodes v2, условные таблицы + сглаживание)",
            "episodes": n,
            "books": sorted({e["_book"] for e in eps}),
            "alpha": ALPHA,
            "reliable_n": RELIABLE_N,
            "note": ("P(outcome|trigger) — предсказание реакции Бога; вероятности по "
                     "наблюдениям реестра v2. outcome_p — сырые доли, outcome_p_smooth — "
                     "сглаживание Дирихле (alpha=%s) к базовой частоте исходов. "
                     "Условные таблицы by_trigger_era/genre/addressee — "
                     "P(outcome|класс,контекст) со сжатием к классу при малом n." % ALPHA),
            "context_legend": CONTEXT_LEGEND,
        },
        "overall": {
            "outcome": dist(Counter(e["outcome"] for e in eps), n),
            "outcome_smooth": {k: round(v, 4) for k, v in sorted(base_p.items())},
            "direction": dist(Counter(e["direction"] for e in eps), n),
            "via": dist(Counter(e["via"] for e in eps), n),
            "addressee": dist(Counter(e["addressee_type"] for e in eps), n),
            "severity_mean": round(sum(e["severity"] for e in eps) / n, 2),
        },
        "by_trigger": {},
        "by_trigger_direction": {},
        "by_trigger_era": {},
        "by_trigger_genre": {},
        "by_trigger_addressee": {},
        "marginals": {},
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
        counts = Counter(e["outcome"] for e in es)
        profile["by_trigger"][trig] = {
            "n": m,
            "outcome_p": dist(counts, m),
            "outcome_p_smooth": smooth(counts, base_p),
            "severity_mean": round(sum(e["severity"] for e in es) / m, 2),
            "top_emotions": [emo.get("emotion", str(emo)) if isinstance(emo, dict) else str(emo)
                         for emo in sum((e["emotions"] for e in es), [])][:5],
            "typical_quote": next((e["god_speech_plain"][:80] for e in es if e["god_speech_plain"]), ""),
            "reliable": m >= RELIABLE_N,
        }
    # условные таблицы: класс × эпоха / жанр / группа адресата
    for dim, key in CONTEXT_DIMS:
        table = {}
        for trig, es in sorted(groups.items()):
            parent_p = probs(Counter(e["outcome"] for e in es))
            cells = defaultdict(list)
            for e in es:
                cells[e[key]].append(e)
            table[trig] = {}
            for cell, ces in sorted(cells.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                c = _conditional(ces, parent_p)
                if c:
                    table[trig][cell] = c
        profile["by_trigger_" + dim] = table
    # маргинали по контексту (без класса)
    for dim, key in CONTEXT_DIMS:
        cells = defaultdict(list)
        for e in eps:
            cells[e[key]].append(e)
        marg = {}
        for cell, ces in sorted(cells.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            m = _marginal(ces, base_p)
            if m:
                marg[cell] = m
        profile["marginals"][dim] = marg
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
    # ось тона: сводки по исходам и классам (сами метрики — в scripts/tone_metrics.py)
    tone = tone_metrics.build(eps)
    profile["tone"] = {
        "metadata": tone["metadata"],
        "aggregates": tone["aggregates"],
        "note": ("тон — измеримая особенность речи в эпизоде (плотность лексики гнева и "
                 "милости, длина, обращение), а не характеристика Бога; "
                 "подробные метрики — docs/data/tone.json"),
    }
    return profile


def predict(profile, trigger, era=None, genre=None, addressee=None):
    """Предсказание исхода для класса обращения с необязательным контекстом.

    Если контекст задан и есть ячейка в условной таблице — берётся она
    (сглаженная к классу). Если ячейки нет — остаётся базовая таблица класса.
    """
    t = profile["by_trigger"].get(trigger)
    if not t:
        return None
    out = {
        "trigger": trigger,
        "predicted_outcome": max(t["outcome_p"], key=t["outcome_p"].get),
        "probabilities": t["outcome_p"],
        "probabilities_smooth": t["outcome_p_smooth"],
        "severity_expected": t["severity_mean"],
        "n_observed": t["n"],
        "context": {},
    }
    for dim, value in (("era", era), ("genre", genre), ("addressee", addressee)):
        if not value:
            continue
        cell = (profile.get("by_trigger_" + dim) or {}).get(trigger, {}).get(value)
        if not cell:
            continue
        out["context"][dim] = {"value": value, "n": cell["n"], "reliable": cell["reliable"]}
        out["probabilities"] = cell["outcome_p_smooth"]
        out["probabilities_smooth"] = cell["outcome_p_smooth"]
        out["predicted_outcome"] = max(out["probabilities_smooth"], key=out["probabilities_smooth"].get)
        out["severity_expected"] = cell["severity_mean"]
        out["n_observed"] = cell["n"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="перезаписать docs/data/god_behavior_profile.json (страница читает его)")
    ap.add_argument("--predict", help="предсказать исход для trigger (например: intercession)")
    ap.add_argument("--era", help="условие по эпохе (например: Кетувим)")
    ap.add_argument("--genre", help="условие по жанру (например: prophecy)")
    ap.add_argument("--addressee", help="условие по группе адресата (например: individual)")
    args = ap.parse_args()

    eps = load_episodes()
    profile = build_profile(eps)
    OUT_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.publish:
        DATA_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
        print("опубликовано: %s" % DATA_FILE.relative_to(BASE))

    if args.predict:
        p = predict(profile, args.predict, era=args.era, genre=args.genre, addressee=args.addressee)
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
    print("\n=== маргинали по контексту (доля исходов) ===")
    for dim, _key in CONTEXT_DIMS:
        print(f"-- {dim}: {CONTEXT_LEGEND[dim]}")
        for cell, m in profile["marginals"][dim].items():
            top = list(m["outcome_p"].items())[:3]
            print(f"   {cell:<22} n={m['n']:>4} sev={m['severity_mean']:<5} " +
                  " ".join(f"{k}:{v:.0%}" for k, v in top))
    print("\nСерьёзность по исходам:", profile["severity_by_outcome"])

    if args.test:
        d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        assert d["metadata"]["episodes"] >= 300, "полный реестр v2"
        assert set(d["by_trigger"]) >= {"complaint", "distress", "intercession", "covenant_follow_up", "disobedience"}, "ключевые триггеры"
        for trig, t in d["by_trigger"].items():
            assert abs(sum(t["outcome_p"].values()) - 1.0) < 0.05, f"вероятности {trig} не сходятся"
            assert abs(sum(t["outcome_p_smooth"].values()) - 1.0) < 0.01, f"сглаженные вероятности {trig} не сходятся"
            assert 1 <= t["severity_mean"] <= 5
        # сглаживание обязано смягчать вырожденные доли
        for trig, t in d["by_trigger"].items():
            raw_max = max(t["outcome_p"].values())
            sm_max = max(t["outcome_p_smooth"].values())
            assert sm_max <= raw_max + 1e-9, f"сглаживание усилило пик в {trig}"
        pr = predict(d, "intercession")
        assert pr and 0 <= pr["probabilities"][pr["predicted_outcome"]] <= 1
        # фактор действия: сумма долей класса ≈ 1, режим — самый частый паттерн
        for trig, rm in d["response_modes"].items():
            assert abs(sum(rm["distribution"].values()) - 1.0) < 0.03, f"режимы {trig} не сходятся"
            assert rm["total"] == d["by_trigger"][trig]["n"], f"режимы {trig}: расхождение n"
            assert rm["mode"] == max(rm["distribution"], key=rm["distribution"].get), f"режим {trig} не самый частый"
        assert set(d["response_mode_legend"]) == {"speaks_and_acts", "acts_silently", "silence", "speaks_only"}
        # условные таблицы: полнота и корректность ячеек
        for dim, _key in CONTEXT_DIMS:
            table = d["by_trigger_" + dim]
            assert table, f"пустая условная таблица {dim}"
            for trig, cells in table.items():
                n_class = d["by_trigger"][trig]["n"]
                n_cells = sum(c["n"] for c in cells.values())
                assert n_cells == n_class, f"{dim}/{trig}: ячейки {n_cells} != класс {n_class}"
                for cell, c in cells.items():
                    assert c["n"] > 0
                    assert abs(sum(c["outcome_p_smooth"].values()) - 1.0) < 0.01, f"{dim}/{trig}/{cell} не сходится"
                    assert c["reliable"] == (c["n"] >= d["metadata"]["reliable_n"])
        # маргинали: сумма n по контексту = число эпизодов
        for dim, _key in CONTEXT_DIMS:
            marg = d["marginals"][dim]
            assert sum(m["n"] for m in marg.values()) == d["metadata"]["episodes"], f"маргинали {dim} не покрывают корпус"
            for cell, m in marg.items():
                assert abs(sum(m["outcome_p_smooth"].values()) - 1.0) < 0.01, f"маргиналь {dim}/{cell} не сходится"
        # предсказание с контекстом должно применить условие
        pr2 = predict(d, "intercession", addressee="individual")
        assert pr2 and pr2["context"], "контекст не применился"
        assert abs(sum(pr2["probabilities_smooth"].values()) - 1.0) < 0.01
        # тон в профиле: сводки на месте и различают кару и благословение
        tone = d["tone"]["aggregates"]["outcome"]
        assert tone["punishment"]["score_mean"] > tone["blessing"]["score_mean"], "тон не разделяет кару и благословение"
        # опубликованная копия страницы не должна разойтись с мастером
        if DATA_FILE.exists():
            pub = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            assert pub["response_modes"] == d["response_modes"], "docs/data профиль разошёлся с output"
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
