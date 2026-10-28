"""
eval_profile.py
Калибровка поведенческого профиля: честная вневыборочная оценка того, насколько
P(outcome|trigger) (и его условные версии) предсказывают исход.

Зачем это нужно профилю. Таблица P(outcome|trigger) выглядит убедительно, но
она посчитана по тому же корпусу, на котором потом «проверяется». Чтобы сказать,
что профиль действительно предсказывает, нужна оценка на данных, которых модель
не видела. Именно это здесь и делается.

Метод:
  * Grouped K-fold CV по КНИГАМ (K=5). Фолд — это набор книг целиком, поэтому
    ни одна книга не встречается одновременно в обучении и в проверке: иначе
    модель «выучила» бы не общий закон, а стиль конкретной книги. Фолды
    уравновешены по числу эпизодов (книги сортируются по размеру и раскладываются
    в самый лёгкий фолд).
  * Модели:
      M1 uniform      — равномерный априор по исходам (нижняя граница качества);
      M2 base_rate    — глобальная частота исходов;
      M3 trigger      — P(outcome|trigger) со сглаживанием Дирихле (alpha=5)
                        к базовой частоте;
      M4 trigger+адресат, M5 trigger+жанр, M6 trigger+эпоха — те же оценки,
                        сжатые к M3 при малом n (иерархическая модель);
      M7 trigger+тон  — M3, умноженная на наивно-байесовские веса признаков тона
                        (перевес гнева/милости, обращение, самоименование,
                        длина речи, молчание). Это и есть проверка пункта
                        «добавляет ли тон к точности».
  * Метрики: multi-class Brier (сумма по исходам в среднем на пример; и же
    нормированная на число исходов), log-loss, top-1 accuracy. Отдельно —
    по каждому классу обращения с n >= 20 в проверочной выборке.
  * Всё считается честно: если модель не обходит базовую частоту — так и
    пишется в verdict.

Выход:
    output/profile_calibration.json    — числа и вердикт
    docs/data/profile_calibration.json — копия для страницы (--publish)

Usage:
    python scripts/eval_profile.py
    python scripts/eval_profile.py --publish
    python scripts/eval_profile.py --test
"""
import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])
sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(_REPO)
sys.path.insert(0, str(BASE / "scripts"))
import corpus_meta   # noqa: E402
import tone_metrics  # noqa: E402

MASTER = BASE / "output/episodes_TANAKH_v2.json"
OUT_FILE = BASE / "output/profile_calibration.json"
DATA_FILE = BASE / "docs" / "data" / "profile_calibration.json"

FOLDS = 5
ALPHA = 5.0            # сглаживание Дирихле
MIN_CLASS_N = 20       # порог для per-trigger метрик
EPS = 1e-9
TONE_MARGIN = tone_metrics.SCORE_MARGIN


# ─────────────────────────────────────────────────────────────────────────────
# Данные
# ─────────────────────────────────────────────────────────────────────────────
def tone_features(speech):
    """Бинарные признаки тона для наивного байеса (M7).

    Признаки намеренно грубые: на 2050 эпизодах тонких признаков больше, чем
    данных, а крупные — устойчивы.

    ВАЖНО: признака «речи нет» (words == 0) здесь нет — он круговой. Исход
    «silence» в реестре означает, что Бог не ответил, то есть отсутствие речи
    заложено в САМ определении метки. Такой признак не предсказывает метку,
    а перекодирует её: с ним модель «выигрывала» у класса обращения на 1.2 %
    Brier чисто на трюке. После удаления (см. m8 в моделях) честный результат
    другой, и он записан в вердикт.
    """
    t = tone_metrics.tone_of(speech)
    words = t["words"]
    return {
        "anger": t["score"] >= TONE_MARGIN,
        "mercy": t["score"] <= -TONE_MARGIN,
        "address": t["address_rate"] > 0,
        "self_ref": t["self_rate"] > 0,
        "long": words >= 40,
        # не признак, а служебное число для диагностической модели с утечкой
        "words": words,
    }


def load_episodes():
    """Эпизоды мастер-корпуса с ключами контекста и признаками тона."""
    master = json.load(open(MASTER, encoding="utf-8"))
    eps = []
    for book, book_eps in master.items():
        for ep in book_eps:
            e = dict(ep)
            e["_book"] = book
            e["_era"] = corpus_meta.era_of(book)
            e["_genre"] = corpus_meta.genre_of(book)
            e["_addr"] = corpus_meta.addressee_group(e.get("addressee_type"))
            e["_tone"] = tone_features(e.get("god_speech_plain"))
            eps.append(e)
    return eps


def assign_folds(eps, k=FOLDS):
    """Книги целиком в k фолдов, уравновешенных по числу эпизодов.

    Книги сортируются по убыванию размера и кладутся в самый лёгкий фолд
    (при равенстве — в самый ранний по индексу). Так разброс эпизодов по
    фолдам минимален, а разбиение детерминировано.
    """
    counts = Counter(e["_book"] for e in eps)
    books = sorted(counts, key=lambda b: (-counts[b], b))
    folds = [[] for _ in range(k)]
    sizes = [0] * k
    for b in books:
        i = min(range(k), key=lambda j: (sizes[j], j))
        folds[i].append(b)
        sizes[i] += counts[b]
    return folds


# ─────────────────────────────────────────────────────────────────────────────
# Модели
# ─────────────────────────────────────────────────────────────────────────────
def _norm(d):
    """Нормализация распределения (страховка от суммы ≠ 1 после сглаживания)."""
    z = sum(d.values())
    if z <= 0:
        return d
    return {k: v / z for k, v in d.items()}


def smooth_counts(counts, base, alpha=ALPHA):
    """Дирихле к базовому распределению: (c + alpha*base) / (n + alpha)."""
    n = sum(counts.values())
    if n <= 0:
        return dict(base)
    keys = set(base) | set(counts)
    return {k: (counts.get(k, 0) + alpha * base.get(k, 0.0)) / (n + alpha) for k in keys}


def model_uniform(train, outcomes):
    p = {k: 1.0 / len(outcomes) for k in outcomes}
    return lambda ep: dict(p)


def model_base_rate(train, outcomes):
    c = Counter(e["outcome"] for e in train)
    base = _norm({k: c.get(k, 0) for k in outcomes})
    return lambda ep: dict(base)


def model_trigger(train, outcomes):
    c = Counter(e["outcome"] for e in train)
    base = _norm({k: c.get(k, 0) for k in outcomes})
    groups = defaultdict(Counter)
    for e in train:
        groups[e["trigger"]][e["outcome"]] += 1
    tables = {t: smooth_counts(g, base) for t, g in groups.items()}
    fb = smooth_counts(Counter(), base)   # триггер не встретился — база

    def predict(ep):
        return dict(tables.get(ep["trigger"], fb))
    return predict


def model_trigger_context(train, outcomes, key):
    """P(outcome | trigger, контекст) со сжатием к P(outcome | trigger).

    alpha — вес родителя: при n_ячейки = 5 это половина веса у класса,
    при n_ячейки = 50 — почти чистая ячейка.
    """
    base = _norm({k: Counter(e["outcome"] for e in train).get(k, 0) for k in outcomes})
    groups = defaultdict(Counter)
    for e in train:
        groups[e["trigger"]][e["outcome"]] += 1
    trig = {t: smooth_counts(g, base) for t, g in groups.items()}
    cells = defaultdict(Counter)
    for e in train:
        cells[(e["trigger"], e[key])][e["outcome"]] += 1
    tbl = {ck: smooth_counts(c, trig.get(ck[0], base)) for ck, c in cells.items()}
    fb = smooth_counts(Counter(), base)

    def predict(ep):
        ck = (ep["trigger"], ep[key])
        if ck in tbl:
            return dict(tbl[ck])
        if ep["trigger"] in trig:
            return dict(trig[ep["trigger"]])
        return dict(fb)
    return predict


def model_tone(train, outcomes, leak=False):
    """M3 + наивный байесовские веса признаков тона.

    Веса: log-отношение P(признак | исход) / P(признак | не исход) с
    сглаживанием Лапласа. Наивный байес мультиномиальный, поэтому веса
    перемножаются — и произведение нормируется.

    leak=True добавляет круговой признак «речи нет». Он НЕ используется в
    основной оценке: исход «silence» по определению означает отсутствие
    речи, поэтому признак не предсказывает метку, а перекодирует её.
    Модель с ним оставлена как диагностика величины утечки.
    """
    base = _norm({k: Counter(e["outcome"] for e in train).get(k, 0) for k in outcomes})
    groups = defaultdict(Counter)
    for e in train:
        groups[e["trigger"]][e["outcome"]] += 1
    trig = {t: smooth_counts(g, base) for t, g in groups.items()}
    fb = smooth_counts(Counter(), base)

    feats = sorted({f for e in train for f, v in e["_tone"].items()
                    if v and isinstance(v, bool)})
    # счётчики: (исход, признак) и (исход, всего)
    pos = defaultdict(Counter)
    tot = Counter()
    for e in train:
        tot[e["outcome"]] += 1
        for f, v in e["_tone"].items():
            if v:
                pos[e["outcome"]][f] += 1
    n_all = len(train)
    n_by_out = {k: tot.get(k, 0) for k in outcomes}

    def predict(ep):
        p = dict(trig.get(ep["trigger"], fb))
        active = list(feats)
        if leak and ep["_tone"].get("words") == 0:
            active = active + ["silent"]
        for f in active:
            if f != "silent" and not ep["_tone"].get(f):
                continue
            for k in outcomes:
                n_k = n_by_out.get(k, 0)
                n_rest = n_all - n_k
                c_k = pos.get(k, Counter()).get(f, 0)
                if f == "silent":
                    c_k = sum(1 for e in train if e["outcome"] == k and e["_tone"].get("words") == 0)
                    c_rest = sum(1 for e in train if e["outcome"] != k and e["_tone"].get("words") == 0)
                else:
                    c_rest = sum(pos.get(o, Counter()).get(f, 0) for o in outcomes if o != k)
                p_k = (c_k + 1) / (n_k + 2)
                p_rest = (c_rest + 1) / (n_rest + 2)
                p[k] = p.get(k, 1e-12) * (p_k / p_rest)
        return _norm(p)
    return predict


MODELS = {
    "m1_uniform": ("равномерный априор", lambda tr, out: model_uniform(tr, out)),
    "m2_base_rate": ("глобальная частота исходов", lambda tr, out: model_base_rate(tr, out)),
    "m3_trigger": ("P(исход|класс обращения)", lambda tr, out: model_trigger(tr, out)),
    "m4_trigger_addressee": ("класс × группа адресата",
                             lambda tr, out: model_trigger_context(tr, out, "_addr")),
    "m5_trigger_genre": ("класс × жанр",
                         lambda tr, out: model_trigger_context(tr, out, "_genre")),
    "m6_trigger_era": ("класс × эпоха",
                       lambda tr, out: model_trigger_context(tr, out, "_era")),
    "m7_trigger_tone": ("класс + признаки тона (без кругового признака)",
                        lambda tr, out: model_tone(tr, out)),
    "m8_trigger_tone_leak": ("ДИАГНОСТИКА: класс + тон с круговым признаком «нет речи»",
                             lambda tr, out: model_tone(tr, out, leak=True)),
}


# ─────────────────────────────────────────────────────────────────────────────
# Метрики
# ─────────────────────────────────────────────────────────────────────────────
def brier(p, y, outcomes):
    """Multi-class Brier: средняя сумма (p_k − y_k)^2 по исходам."""
    return sum((p.get(k, 0.0) - (1.0 if k == y else 0.0)) ** 2 for k in outcomes)


def logloss(p, y):
    return -math.log(max(p.get(y, 0.0), EPS))


class Acc:
    """Накопитель метрик по накопленным предсказаниям."""

    def __init__(self):
        self.b = 0.0
        self.ll = 0.0
        self.hit = 0
        self.n = 0

    def add(self, p, y):
        self.b += brier(p, y, p.keys())
        self.ll += logloss(p, y)
        self.hit += 1 if max(p, key=p.get) == y else 0
        self.n += 1

    def as_dict(self, n_outcomes):
        if not self.n:
            return {"n": 0}
        return {
            "n": self.n,
            "brier": round(self.b / self.n, 5),
            "brier_norm": round(self.b / self.n / max(n_outcomes, 1), 5),
            "logloss": round(self.ll / self.n, 5),
            "acc": round(self.hit / self.n, 4),
        }


def evaluate(eps, outcomes):
    """Grouped CV по книгам: возвращает словарь с метриками по всем моделям."""
    folds = assign_folds(eps)
    accs = {name: Acc() for name in MODELS}
    per_trigger = {name: defaultdict(Acc) for name in MODELS}
    fold_rows = []
    for fi, books in enumerate(folds):
        test = [e for e in eps if e["_book"] in books]
        train = [e for e in eps if e["_book"] not in books]
        if not test or not train:
            continue
        preds = {}
        for name, (_label, factory) in MODELS.items():
            fn = factory(train, outcomes)
            preds[name] = [(fn(e), e) for e in test]
        for name, items in preds.items():
            for p, e in items:
                accs[name].add(p, e["outcome"])
                per_trigger[name][e["trigger"]].add(p, e["outcome"])
        fold_rows.append({
            "fold": fi,
            "books": sorted(books),
            "train_episodes": len(train),
            "test_episodes": len(test),
            "acc": {name: round(accs[name].hit / max(accs[name].n, 1), 4) for name in MODELS},
            "brier": {name: round(accs[name].b / max(accs[name].n, 1), 5) for name in MODELS},
        })
    n_out = len(outcomes)
    models = {}
    for name, (_label, _f) in MODELS.items():
        d = accs[name].as_dict(n_out)
        d["label"] = MODELS[name][0]
        models[name] = d
    trig = {}
    for name in MODELS:
        rows = {}
        for cls, a in per_trigger[name].items():
            if a.n >= MIN_CLASS_N:
                rows[cls] = a.as_dict(n_out)
        trig[name] = rows
    return {"folds": fold_rows, "models": models, "per_trigger": trig,
            "fold_books": [sorted(b) for b in folds]}


def verdict(models):
    """Честный текстовый вывод: кто обходит базовую частоту и на сколько."""
    base = models["m2_base_rate"]
    unif = models["m1_uniform"]
    lines = []
    for name, m in models.items():
        if name in ("m1_uniform", "m2_base_rate"):
            continue
        d_b = (base["brier"] - m["brier"]) / base["brier"] * 100 if base["brier"] else 0.0
        d_u = (unif["brier"] - m["brier"]) / unif["brier"] * 100 if unif["brier"] else 0.0
        lines.append("%s: Brier %s (лучше базовой частоты на %.1f%%, равномерного на %.1f%%), "
                     "log-loss %s, top-1 %s"
                     % (name, m["brier"], d_b, d_u, m["logloss"], m["acc"]))
    real = {n: m for n, m in models.items() if not n.endswith("_leak")}
    best = min((m["brier"], n) for n, m in real.items())[1]
    better_than_base = [n for n, m in models.items()
                        if n not in ("m1_uniform", "m2_base_rate")
                        and m["brier"] < base["brier"]]
    tone_gain = None
    if "m7_trigger_tone" in models and "m3_trigger" in models:
        tone_gain = round((models["m3_trigger"]["brier"] - models["m7_trigger_tone"]["brier"]) / models["m3_trigger"]["brier"] * 100, 2)
    leak_gain = None
    if "m8_trigger_tone_leak" in models and "m7_trigger_tone" in models:
        leak_gain = round((models["m7_trigger_tone"]["brier"] - models["m8_trigger_tone_leak"]["brier"]) / models["m7_trigger_tone"]["brier"] * 100, 2)
    if tone_gain is None:
        tone_text = "тон не проверен"
    elif tone_gain <= 0.5:
        tone_text = ("тон не добавляет точности сверх класса обращения "
                     "(Brier хуже или равен: %+.2f%%)" % tone_gain)
    else:
        tone_text = ("тон добавляет точность сверх класса обращения (+%.2f%% Brier)" % tone_gain)
    return {
        "text": " | ".join(lines),
        "best_model": best,
        "better_than_base_rate": better_than_base,
        "tone_gain_pct_vs_trigger": tone_gain,
        "tone_verdict": tone_text,
        "leak_gain_pct": leak_gain,
        "leak_note": ("круговой признак «нет речи» дал ещё %+.2f%% Brier — это утечка: "
                      "исход «молчание» означает отсутствие речи по определению метки, "
                      "поэтому признак не предсказывает, а перекодирует её"
                      % leak_gain) if leak_gain is not None else "",
    }


def build(eps):
    outcomes = sorted({e["outcome"] for e in eps})
    res = evaluate(eps, outcomes)
    verdict_obj = verdict(res["models"])
    trigger_rows = {}
    base_rows = res["per_trigger"]["m2_base_rate"]
    best_rows = res["per_trigger"][res["verdict"] if False else verdict_obj["best_model"]]
    for cls, row in best_rows.items():
        trigger_rows[cls] = {"best_model": row, "base_rate": base_rows.get(cls, {"n": 0})}
    return {
        "metadata": {
            "version": "profile-calibration-v1",
            "episodes": len(eps),
            "books": len({e["_book"] for e in eps}),
            "folds": FOLDS,
            "alpha": ALPHA,
            "min_class_n": MIN_CLASS_N,
            "grouping": "по книгам (книга целиком в одном фолде — утечки нет)",
            "brier_convention": "сумма (p_k − y_k)^2 по исходам, в среднем на пример",
            "outcomes": outcomes,
        },
        "models": res["models"],
        "per_trigger": trigger_rows,
        "folds": res["folds"],
        "fold_books": res["fold_books"],
        "verdict": verdict_obj,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Самопроверка (синтетика, без корпуса и без сети)
# ─────────────────────────────────────────────────────────────────────────────
def _mk_ep(book, era, genre, addr, trig, out, i):
    return {
        "episode_id": "%s_%d" % (book, i), "_book": book, "_era": era, "_genre": genre,
        "_addr": addr, "_tone": {"anger": False, "mercy": False, "address": False,
                                 "self_ref": False, "long": False, "words": 20},
        "outcome": out, "trigger": trig, "severity": 3,
        "god_speech_plain": "", "addressee_type": "nation",
    }


def _synth(n_books=12, per_book=40):
    """Синтетический корпус, где исход однозначно определяется классом
    обращения (t1 → alpha, t2 → beta) в каждой книге.

    Проверяет главное: модель класса должна обходить равномерный априор, и
    добавление контекста (эпоха/жанр) не должно её портить — внутри каждой
    ячейки закон тот же.
    """
    eps = []
    for b in range(n_books):
        book = "Book%d" % b
        era = "Тора" if b % 2 == 0 else "Кетувим"
        genre = "law" if b < n_books // 2 else "poetry"
        for i in range(per_book):
            trig = "t1" if i % 2 == 0 else "t2"
            out = "alpha" if trig == "t1" else "beta"
            eps.append(_mk_ep(book, era, genre, "nation", trig, out, i))
    return eps


def _synth_genre(n_books=12, per_book=40):
    """Синтетический корпус, где исход определяется ЖАНРОМ, а не классом:
    закон → alpha, поэзия → beta, класс обращения ничего не значит.

    Проверяет, что условная таблица умеет ловить сигнал, которого нет
    в базовой таблице класса.
    """
    eps = []
    for b in range(n_books):
        book = "Book%d" % b
        era = "Тора" if b % 2 == 0 else "Кетувим"
        genre = "law" if b < n_books // 2 else "poetry"
        for i in range(per_book):
            trig = "t1" if i % 2 == 0 else "t2"
            out = "alpha" if genre == "law" else "beta"
            eps.append(_mk_ep(book, era, genre, "nation", trig, out, i))
    return eps


def _synth_small_cell():
    """Класс t1 с крошечной ячейкой в эпохе «Кетувим», где исход другой.

    Нужна для проверки сжатия: оценка ячейки обязана быть ближе к
    родителю (P(исход|t1)), чем к собственным счётчикам ячейки.
    """
    eps = []
    for b, era in ((0, "Тора"), (1, "Тора"), (2, "Тора"), (3, "Кетувим")):
        book = "Book%d" % b
        for i in range(40):
            trig = "t1" if i % 2 == 0 else "t2"
            if b < 3:
                out = "alpha" if trig == "t1" else "beta"
            else:
                out = "beta" if trig == "t1" else "alpha"   # редкая ячейка, инвертированная
            eps.append(_mk_ep(book, era, "law", "nation", trig, out, i))
    return eps


def selftest():
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name)

    # 1) разбиение по фолдам: книга целиком в одном фолде, фолды уравновешены
    eps = _synth()
    folds = assign_folds(eps)
    all_books = [b for f in folds for b in f]
    chk("каждая книга ровно в одном фолде", len(all_books) == len(set(all_books)) == 12)
    sizes = [sum(1 for e in eps if e["_book"] in f) for f in folds]
    biggest_book = max(Counter(e["_book"] for e in eps).values())
    chk("фолды уравновешены (разброс ≤ размера самой большой книги)",
        max(sizes) - min(sizes) <= biggest_book)
    chk("фолды не пусты", all(s > 0 for s in sizes))

    # 2) утечки нет: обучение каждого фолда не содержит книг проверки
    leak = False
    for books in folds:
        train = [e for e in eps if e["_book"] not in books]
        test = [e for e in eps if e["_book"] in books]
        tr_books = {e["_book"] for e in train}
        te_books = {e["_book"] for e in test}
        if tr_books & te_books:
            leak = True
    chk("в CV нет утечки между книгами", not leak)

    # 3) метрики считаются правильно на известном маленьком примере
    p = {"a": 0.7, "b": 0.3}
    chk("Brier для p=(0.7,0.3), y=a = 0.18", abs(brier(p, "a", ["a", "b"]) - 0.18) < 1e-12)
    chk("log-loss для p=(0.7,0.3), y=b = -ln 0.3", abs(logloss(p, "b") + math.log(0.3)) < 1e-12)

    # 4) на синтетике класс обращения обходит равномерный априор,
    #    добавление контекста его не портит
    res = evaluate(eps, ["alpha", "beta"])
    m = res["models"]
    chk("класс обращения лучше равномерного априора", m["m3_trigger"]["brier"] < m["m1_uniform"]["brier"])
    chk("класс обращения лучше базовой частоты", m["m3_trigger"]["brier"] < m["m2_base_rate"]["brier"])
    chk("класс×жанр не хуже класса", m["m5_trigger_genre"]["brier"] <= m["m3_trigger"]["brier"] + 1e-9)
    chk("класс×эпоха не хуже класса", m["m6_trigger_era"]["brier"] <= m["m3_trigger"]["brier"] + 1e-9)
    chk("у всех моделей одинаковое число примеров",
        len({m[k]["n"] for k in m}) == 1 and m["m1_uniform"]["n"] == len(eps))

    # 5) если сигнал в жанре, а не в классе — условная таблица его находит
    res_g = evaluate(_synth_genre(), ["alpha", "beta"])
    mg = res_g["models"]
    chk("класс×жанр ловит сигнал жанра", mg["m5_trigger_genre"]["brier"] < mg["m3_trigger"]["brier"])
    chk("класс×жанр почти идеален на чистом жанровом сигнале",
        mg["m5_trigger_genre"]["brier"] < 0.01)

    # 6) сжатие: малая ячейка притягивается к родителю, а не верит своим счётчикам
    eps_s = _synth_small_cell()
    train = eps_s
    fn = model_trigger_context(train, ["alpha", "beta"], "_era")
    cell = fn({"trigger": "t1", "_era": "Кетувим"})
    parent = model_trigger(train, ["alpha", "beta"])({"trigger": "t1"})
    chk("малая ячейка не доверяет своим счётчикам (0 < p(alpha) < 0.5)",
        0 < cell["alpha"] < 0.5)
    # точная проверка сжатия: ячейка сдвинута от сырых счётчиков к родителю
    # ровно на долю alpha/(n + alpha)
    n_cell = sum(1 for e in train if e["trigger"] == "t1" and e["_era"] == "Кетувим")
    expected = (0 + ALPHA * parent["alpha"]) / (n_cell + ALPHA)
    chk("ячейка сжата к родителю ровно по формуле",
        abs(cell["alpha"] - expected) < 1e-9)
    chk("ячейка лежит между сырым счётчиком и родителем",
        0.0 < cell["alpha"] < parent["alpha"])

    # 7) вердикт собирается и содержит честные числа
    v = verdict(m)
    chk("вердикт называет лучшую модель", v["best_model"] in m)
    chk("вердикт не выбирает диагностическую модель с утечкой",
        not v["best_model"].endswith("_leak"))
    chk("вердикт содержит текст", isinstance(v["text"], str) and len(v["text"]) > 20)

    # 8) файл читается обратно
    data = build(eps)
    tmp = OUT_FILE.with_name("_calibration_selftest.json")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(tmp.read_text(encoding="utf-8"))
    tmp.unlink()
    chk("JSON читается обратно", back["metadata"]["episodes"] == len(eps)
        and set(back["models"]) == set(MODELS))

    print("\nSELFTEST: %s (%d/%d)" % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)))
    return 0 if all(checks) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()
    if args.test:
        return selftest()

    eps = load_episodes()
    data = build(eps)
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("записано: %s" % OUT_FILE.relative_to(BASE))
    if args.publish:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("опубликовано: %s" % DATA_FILE.relative_to(BASE))

    print("\n=== калибровка профиля (grouped CV по книгам, %d фолдов) ===" % FOLDS)
    print("%-24s %-9s %-10s %-8s %s" % ("модель", "Brier", "Brier/к", "log-loss", "top-1"))
    for name, m in data["models"].items():
        print("%-24s %-9.5f %-10.5f %-8.4f %.1f%%" %
              (name, m["brier"], m["brier_norm"], m["logloss"], m["acc"] * 100))
    print("\n" + data["verdict"]["text"])
    print("тон против класса обращения: %s%%" % data["verdict"]["tone_gain_pct_vs_trigger"])
    print(data["verdict"]["tone_verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
