"""
tone_metrics.py
Тон речи Бога: измеримая ось вместо впечатления.

Что измеряется по god_speech_plain (консонантный иврит без огласовок):
  * длина речи (символы, слова);
  * плотность лексики гнева (anger) и лексики милости/утешения (mercy);
  * формулы утешения «не бойся» (comfort) — считаются в сторону милости, но
    отдельно, чтобы не путать «Бог утешил» с «Бог милосерден»;
  * структурные признаки: обращение к собеседнику (address_rate) и
    самоименование (self_rate);
  * score = anger_rate − mercy_rate (на 100 слов);
  * класс тона: severe / consoling / neutral — по знаку score с порогом
    SCORE_MARGIN (1.0 слова гнева-милости на 100 слов), silent — если речи нет.

Почему лексика, а не «настроение»: единственное, что можно воспроизвести —
это посчитанные признаки. Тон здесь — не характеристика Бога, а измеримая
особенность его речи в конкретном эпизоде, которую затем проверяет
независимая оценка моделью (scripts/tone_rater.py).

Лексика вычищена по фактическим словам корпуса (2026-10-27): каждое правило
прогонялось по всем 2050 эпизодам и ложные срабатывания убирались:
  אשר/כאשר (772+76) ≠ «огонь» → «огонь» только как אש/באש/האש/ואש/לאש/מאש;
  ירושלם (51) ≠ «мир» → «שלום» вместо корня שלם; שלמה (Соломон) исключён;
  אלעזר/אלישע (имена) исключены из корней עזר/ישע; «רע» (392 срабатываний:
  פרעה, רעה=«она», כרעים) снят как слишком двусмысленный; משחת (помазание)
  ≠ שחת (разрушение); אלעזר ≠ לעז (насмешка); תנאף ≠ אף; האחרון ≠ חרו;
  נכם (суффикс «ваши») ≠ гнев → только слово «נכם» целиком.

Usage:
    python scripts/tone_metrics.py                 # пересчитать output/tone.json
    python scripts/tone_metrics.py --publish       # + docs/data/tone.json (страница)
    python scripts/tone_metrics.py --test
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(_REPO)
MASTER = BASE / "output/episodes_TANAKH_v2.json"
OUT_FILE = BASE / "output/tone.json"
DATA_FILE = BASE / "docs" / "data" / "tone.json"

# ── Лексика ─────────────────────────────────────────────────────────────────
# Совпадение — по СЛОВАМ (токенам) текста, стем входит в слово.

ANGER_STEMS = [
    "חרה", "אף", "אפי", "אפים", "קצף", "עון", "עוון", "פשע",
    "השחית", "תשחת", "משחית", "קרע", "תקרע", "לענה", "לענות",
    "תוכיח", "וכיח", "מוכיח", "הוכיח", "יורה", "גדופ",
    "רעים", "ארור", "ארורה", "אבת", "בלע", "חרב", "חרבן",
    "הרס", "מלחמה", "מלחמות", "שרף", "שריפת", "עשן", "שלהבת",
    "גדול", "גדלה", "גדל", "עצם", "עצמות",
]
MERCY_STEMS = [
    "חננ", "חנם", "חנך", "תחנן", "רחם", "רחמ", "שמח", "נחמ",
    "ברך", "ברכ", "ברוך", "חסד", "שלום", "ישע", "ישוע", "תושע",
    "עזר", "נצח", "יצל", "הציל", "מציל", "נצל", "צלתי",
    "נשא", "סתר", "שמרת", "חיים", "חיי", "כפר", "סלח", "נחל", "חלק",
]
COMFORT_STEMS = ["תירא", "תפחד", "תחר"]

# Слова, которые не считаются за данный стем (ложные срабатывания)
EXCLUDE = {
    "אף": ("תנאף", "אפיל"),
    "אפי": ("אפיל",),
    "רעים": ("כרעים",),
    "בלע": ("בלעם",),
    "עזר": ("אלעזר",),
    "ישע": ("אלישע", "ואלישע"),
    "שלום": ("שלומי",),
    "נצל": ("אנצל",),
    "צלתי": ("אצלתי",),
    "נחל": ("נחלתו",),
}

# Слова, которые считаются за стем только целиком (суффиксные ложные срабатывания)
EXACT_ANGER = {"נכם"}

# Структурные признаки
ADDRESS_STEMS = ["כם", "לך"]
ADDRESS_EXCLUDE = {"שכם"}
SELF_STEMS = ["אנכי", "אני"]

# «Огонь» — особое правило: слово оканчивается на אש, приставка из списка.
# Так אשר (772) и ראש (26) не попадают в гнев.
FIRE_PREFIXES = ("", "ב", "ה", "ו", "ל", "מ")
FIRE_EXCLUDE = ("כאש", "מאש", "באשר")

# Порог класса тона: 1.0 гнева-слова на 100 слов над милостью
SCORE_MARGIN = 1.0
MIN_WORDS = 4
CLASS_SEVERE = "severe"
CLASS_CONSOLING = "consoling"
CLASS_NEUTRAL = "neutral"
CLASS_SILENT = "silent"


def is_fire(token):
    if token in FIRE_EXCLUDE:
        return False
    if not token.endswith("אש"):
        return False
    return token[:-2] in FIRE_PREFIXES


def tokenize(text):
    return (text or "").split()


def count_lex(tokens, stems):
    """Число слов, попавших под лексику (одно слово — не более одного раза)."""
    n = 0
    for t in tokens:
        if t in EXACT_ANGER:
            n += 1
            continue
        hit = False
        for s in stems:
            if s not in t:
                continue
            if EXCLUDE.get(s) and t in EXCLUDE[s]:
                continue
            hit = True
            break
        if hit:
            n += 1
        elif is_fire(t):
            n += 1
    return n


def count_struct(tokens, stems, exclude=()):
    n = 0
    for t in tokens:
        if t in exclude:
            continue
        for s in stems:
            if s in t:
                n += 1
                break
    return n


def tone_of(speech):
    """Метрики тона одной речи. Пустая речь → класс None (Бог молчит)."""
    text = (speech or "").strip()
    tokens = tokenize(text)
    words = len(tokens)
    anger = count_lex(tokens, ANGER_STEMS)
    mercy = count_lex(tokens, MERCY_STEMS)
    comfort = count_lex(tokens, COMFORT_STEMS)
    mercy_total = mercy + comfort
    address = count_struct(tokens, ADDRESS_STEMS, ADDRESS_EXCLUDE)
    self_ref = count_struct(tokens, SELF_STEMS)
    ar = round(100.0 * anger / words, 2) if words else 0.0
    mr = round(100.0 * mercy_total / words, 2) if words else 0.0
    return {
        "chars": len(text),
        "words": words,
        "anger": anger,
        "mercy": mercy,
        "comfort": comfort,
        "address": address,
        "self_ref": self_ref,
        "anger_rate": ar,
        "mercy_rate": mr,
        "address_rate": round(100.0 * address / words, 2) if words else 0.0,
        "self_rate": round(100.0 * self_ref / words, 2) if words else 0.0,
        "score": round(ar - mr, 2),
    }


def quantile(values, q):
    """Квантиль (интерполяция как в numpy 'linear'), без зависимостей."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return float(s[lo] * (1 - frac) + s[hi] * frac)


def thresholds_from(records):
    """Пороги классов: знак score + margin; квантили — для справки."""
    scores = [r["tone"]["score"] for r in records if r["tone"]["words"] >= MIN_WORDS]
    return {
        "margin": SCORE_MARGIN,
        "min_words": MIN_WORDS,
        "q33": round(quantile(scores, 0.33), 2),
        "q67": round(quantile(scores, 0.67), 2),
    }


def classify(tone, thresholds):
    if not tone or tone["words"] == 0:
        return CLASS_SILENT
    if tone["words"] < thresholds.get("min_words", MIN_WORDS):
        return CLASS_NEUTRAL
    margin = thresholds.get("margin", SCORE_MARGIN)
    if tone["score"] >= margin:
        return CLASS_SEVERE
    if tone["score"] <= -margin:
        return CLASS_CONSOLING
    return CLASS_NEUTRAL


def load_episodes():
    master = json.load(open(MASTER, encoding="utf-8"))
    eps = []
    for book, book_eps in master.items():
        for ep in book_eps:
            e = dict(ep)
            e["_book"] = book
            eps.append(e)
    return eps


def build(eps):
    records = []
    for e in eps:
        t = tone_of(e.get("god_speech_plain"))
        records.append({
            "episode_id": e.get("episode_id"),
            "book": e["_book"],
            "outcome": e.get("outcome"),
            "trigger": e.get("trigger"),
            "severity": e.get("severity"),
            "tone": t,
        })
    th = thresholds_from(records)
    for r in records:
        r["class"] = classify(r["tone"], th)
    by_ep = {r["episode_id"]: {
        "class": r["class"], "words": r["tone"]["words"], "chars": r["tone"]["chars"],
        "score": r["tone"]["score"], "anger": r["tone"]["anger"],
        "mercy": r["tone"]["mercy"], "comfort": r["tone"]["comfort"],
        "address": r["tone"]["address"], "self_ref": r["tone"]["self_ref"],
    } for r in records if r.get("episode_id")}
    return {
        "metadata": {
            "version": "tone-v1",
            "episodes": len(records),
            "with_speech": sum(1 for r in records if r["tone"]["words"] > 0),
            "thresholds": th,
            "legend": {
                CLASS_SEVERE: "резкая речь (перевес лексики гнева)",
                CLASS_CONSOLING: "утешительная речь (перевес лексики милости)",
                CLASS_NEUTRAL: "нейтральная речь",
                CLASS_SILENT: "Бог не говорит — только действует",
            },
            "note": ("score = (anger − mercy) на 100 слов; класс — по знаку score "
                     "с margin 1.0; лексика вычищена по словам корпуса"),
        },
        "by_episode": by_ep,
        "aggregates": aggregate(records),
    }


def aggregate(records):
    """Сводные числа тона по исходам и триггерам."""
    out = {}
    for field in ("outcome", "trigger"):
        groups = defaultdict(list)
        for r in records:
            groups[r.get(field)].append(r)
        table = {}
        for key, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            spoken = [r for r in rs if r["tone"]["words"] > 0]
            c = Counter(r["class"] for r in rs)
            mean = lambda key: round(sum(r["tone"][key] for r in spoken) / len(spoken), 2) if spoken else 0.0
            table[key] = {
                "n": len(rs),
                "spoken": len(spoken),
                "words_mean": round(sum(r["tone"]["words"] for r in spoken) / len(spoken), 1) if spoken else 0.0,
                "anger_rate_mean": mean("anger_rate"),
                "mercy_rate_mean": mean("mercy_rate"),
                "address_rate_mean": mean("address_rate"),
                "self_rate_mean": mean("self_rate"),
                "score_mean": mean("score"),
                "classes": {k: round(v / len(rs), 3) for k, v in c.most_common()},
            }
        out[field] = table
    return out


def selftest():
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name)

    # лексика: гнев
    t = tone_of("חרה אף בו נכם גדול")
    chk("злое слово распознано как anger", t["anger"] >= 4)
    # лексика: милость
    t = tone_of("חנני ורחמתי וברכתיך ברכה")
    chk("утешительное слово распознано как mercy", t["mercy"] >= 3)
    # формула утешения
    t = tone_of("אל תירא")
    chk("формула «не бойся» засчитана как comfort", t["comfort"] >= 1)
    # ложные срабатывания
    t = tone_of("כי אשר דבר ה' אל יעקב")
    chk("«אשר» не считается за «огонь»", t["anger"] == 0)
    t = tone_of("בראשית ברא אלהים את השמים ואת הארץ")
    chk("«בראשית» не считается за «огонь»", t["anger"] == 0)
    t = tone_of("ירושלם קרובה ושלמה")
    chk("«ירושלם/שלמה» не считаются за «мир»", t["mercy"] == 0)
    t = tone_of("אלעזר ואלישע ואלישע")
    chk("имена пророков не считаются за помощь/спасение", t["mercy"] == 0)
    t = tone_of("פרעה ורעה ההוא")
    chk("«פרעה/רעה» не считаются за зло", t["anger"] == 0)
    t = tone_of("משחת את אהרן")
    chk("«משחת» (помазание) ≠ «שחת» (разрушение)", t["anger"] == 0)
    t = tone_of("עינכם ואזנכם ואתכם")
    chk("«נכם» как суффикс «ваши» ≠ гнев", t["anger"] == 0)
    t = tone_of("נכם")
    chk("«נכם» отдельным словом = гнев", t["anger"] == 1)
    # структурные признаки
    t = tone_of("אני אלהיכם ואתכם")
    chk("обращение к «вам» посчитано", t["address"] >= 2)
    chk("самоименование посчитано", t["self_ref"] >= 1)
    # пустая речь
    t = tone_of("")
    chk("пустая речь → words=0, score=0", t["words"] == 0 and t["score"] == 0)
    # классификация
    th = {"margin": SCORE_MARGIN, "min_words": MIN_WORDS}
    chk("score выше порога → severe", classify({"words": 10, "score": 5}, th) == CLASS_SEVERE)
    chk("score ниже порога → consoling", classify({"words": 10, "score": -5}, th) == CLASS_CONSOLING)
    chk("score в нулевой зоне → neutral", classify({"words": 10, "score": 0}, th) == CLASS_NEUTRAL)
    chk("нет речи → silent", classify({"words": 0, "score": 0}, th) == CLASS_SILENT)
    chk("слишком короткая речь → neutral", classify({"words": 2, "score": 50}, th) == CLASS_NEUTRAL)
    # квантиль
    chk("квантиль на массиве", abs(quantile([0, 10], 0.5) - 5.0) < 1e-9)

    # корпус: профиль считается по-настоящему
    eps = load_episodes()
    data = build(eps)
    meta = data["metadata"]
    chk("эпизодов ≥ 2000", meta["episodes"] >= 2000)
    chk("речь есть у большинства эпизодов", meta["with_speech"] > meta["episodes"] * 0.5)
    chk("классы распределены (не один класс)", len(set(v["class"] for v in data["by_episode"].values())) >= 3)
    ag = data["aggregates"]["outcome"]
    chk("таблица по исходам непустая", len(ag) >= 6)
    pun = ag.get("punishment", {})
    bl = ag.get("blessing", {})
    chk("у кары плотность гнева выше, чем у благословения",
        pun.get("anger_rate_mean", 0) > bl.get("anger_rate_mean", 99))
    chk("у благословения плотность милости выше, чем у кары",
        bl.get("mercy_rate_mean", 0) > pun.get("mercy_rate_mean", 99))
    chk("тон (score) разделяет кару и благословение",
        pun.get("score_mean", -99) > bl.get("score_mean", 99))
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
    print("записано: %s (%d эпизодов)" % (OUT_FILE.relative_to(BASE), data["metadata"]["episodes"]))
    if args.publish:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("опубликовано: %s" % DATA_FILE.relative_to(BASE))
    ag = data["aggregates"]["outcome"]
    print("\n=== тон по исходам ===")
    for k, v in sorted(ag.items(), key=lambda kv: -kv[1]["n"]):
        print("%-16s n=%-5d слов=%-6s anger=%-6s mercy=%-6s score=%-7s %s"
              % (k, v["n"], v["words_mean"], v["anger_rate_mean"], v["mercy_rate_mean"],
                 v["score_mean"], v["classes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
