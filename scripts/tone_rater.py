"""
tone_rater.py
Независимая оценка тона речи Бога моделью — проверка лексической метрики
(scripts/tone_metrics.py) на живом мозге.

Зачем это нужно. Лексика гнева и милости — это словарь, составленный по
фактическим словам корпуса. Словарь может быть вычищен от ложных срабатываний
и всё равно быть неполным: в 62 % эпизодов со словами речи score равен нулю,
то есть словарь просто не находит в речи ни гнева, ни милости. Тогда «ось
тона» измеряет не тон, а покрытие словаря. Чтобы это проверить, нужен судья,
который не смотрит в словарь: модель оценивает тон по самому тексту речи.

Метод:
  * выборка — детерминированная, стратифицированная по исходу (пропорционально
    доле исхода, но не меньше MIN_PER_OUTCOME эпизодов), только эпизоды с
    непустой речью Бога;
  * модели отдаётся ТОЛЬКО текст речи — без исхода, триггера, книги и любых
    метрик. Иначе это не оценка тона, а подгонка под известный ответ;
  * модель отвечает четырьмя полями: TONE (anger / comfort / neutral / mixed),
    INTENSITY (1–5), GRAMMATICAL (short / medium / long), CONF (0–100);
  * ответ сопоставляется с лексической метрикой: доля совпадений «резкая речь ↔
    anger+интенсивность», корреляция score с интенсивностью, доля эпизодов,
    где словарь не сработал вовсе.

Результат:
    output/tone_rater.json — сырые оценки и сводка сверки
    docs/data/tone_rater.json — публичная сводка (--publish): метаданные и
        сверка без сырых ответов — страница цитирует её числа в блоке тона

Докачка: уже оценённые episode_id не запрашиваются повторно (файл переписывается
после каждого ответа), поэтому длинный прогон можно безопасно прерывать и
продолжать.

Usage:
    python scripts/tone_rater.py --limit 60
    python scripts/tone_rater.py --limit 60 --compare
    python scripts/tone_rater.py --publish
    python scripts/tone_rater.py --test
"""
import argparse
import json
import math
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])
sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(_REPO)
sys.path.insert(0, str(BASE / "scripts"))
import tone_metrics  # noqa: E402

MASTER = BASE / "output/episodes_TANAKH_v2.json"
OUT_FILE = BASE / "output/tone_rater.json"
PUB_FILE = BASE / "docs" / "data" / "tone_rater.json"

DEFAULT_URL = "http://127.0.0.1:18099/v1/chat/completions"
DEFAULT_KEY = "godbrain-v1-vasiliad"
DEFAULT_MODEL = "dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF"

TARGET = 180            # сколько эпизодов планировалось
MIN_PER_OUTCOME = 8     # минимум на исход (стратификация)
SEED = 20261027
TONES = ("anger", "comfort", "neutral", "mixed")
GRAMS = ("short", "medium", "long")

PROMPT_VERSION = "tone-rater-v1"

SYSTEM = (
    "Ты оцениваешь тон речи. Тебе дан ТОЛЬКО текст речи — без контекста, "
    "без указания, кто и к кому говорит, и без любых метрик.\n"
    "Ответь строго четырьмя строками, без пояснений:\n"
    "TONE: одно слово из anger / comfort / neutral / mixed\n"
    "INTENSITY: целое от 1 до 5\n"
    "GRAMMATICAL: одно слово из short / medium / long (длина реплики)\n"
    "CONF: целое от 0 до 100 (насколько уверен в оценке тона)\n"
    "TONE — это эмоциональная окраска речи: anger (гнев, угроза, осуждение), "
    "comfort (утешение, обещание, милость), neutral (ровная речь без явной "
    "окраски, в том числе вопрос и призыв), mixed (в речи есть и гнев и "
    "утешение)."
)


# ─────────────────────────────────────────────────────────────────────────────
# Данные и выборка
# ─────────────────────────────────────────────────────────────────────────────
def load_episodes():
    master = json.load(open(MASTER, encoding="utf-8"))
    eps = []
    for book, book_eps in master.items():
        for ep in book_eps:
            e = dict(ep)
            e["_book"] = book
            eps.append(e)
    return eps


def stratified_sample(eps, target=TARGET, min_per=MIN_PER_OUTCOME, seed=SEED):
    """Детерминированная выборка: сначала по MIN_PER_OUTCOME на каждый исход,
    затем добор пропорционально доле исхода до общего target.

    Порядок чередующийся (исходы по кругу), чтобы любой префикс выборки
    оставался стратифицированным: важно для докачки с --limit.
    """
    by_out = defaultdict(list)
    for e in eps:
        if (e.get("god_speech_plain") or "").strip():
            by_out[e.get("outcome")].append(e)
    for k in by_out:
        by_out[k].sort(key=lambda e: (e.get("episode_id") or ""))
    # детерминированный «перемешивание» без random: сортировка по id-суффиксу
    # через хеш с фиксированным seed
    def key(e):
        h = 0
        ref = "%s|%s|%s" % (seed, e.get("episode_id"), e.get("span", {}).get("start", ""))
        for ch in ref:
            h = (h * 131 + ord(ch)) % 1000003
        return (h, e.get("episode_id") or "")
    for k in by_out:
        by_out[k].sort(key=key)

    outcomes = sorted(by_out)
    total = sum(len(v) for v in by_out.values())
    quota = {}
    for k in outcomes:
        share = max(min_per, round(target * len(by_out[k]) / total))
        quota[k] = min(share, len(by_out[k]))
    # добор до target по самому дефицитному (по доле) исходу
    while sum(quota.values()) < target:
        progressed = False
        for k in outcomes:
            if sum(quota.values()) >= target:
                break
            if quota[k] < len(by_out[k]):
                quota[k] += 1
                progressed = True
        if not progressed:
            break

    picked = []
    slots = []
    for k in outcomes:
        slots.extend([k] * quota[k])
    # чередование: сначала по одному из каждого исхода, потом добор
    queues = {k: list(by_out[k][:quota[k]]) for k in outcomes}
    used = {k: 0 for k in outcomes}
    while len(picked) < len(slots):
        for k in outcomes:
            if used[k] < len(queues[k]):
                picked.append(queues[k][used[k]])
                used[k] += 1
                if len(picked) >= len(slots):
                    break
    return picked


# ─────────────────────────────────────────────────────────────────────────────
# Запрос к мозгу
# ─────────────────────────────────────────────────────────────────────────────
def ask_brain(text, url=DEFAULT_URL, key=DEFAULT_KEY, model=DEFAULT_MODEL, timeout=180):
    """Один запрос к OpenAI-совместимому мозгу. Возвращает текст ответа.

    Кодировка — строго UTF-8 байтами: кириллица в аргументах curl ломает JSON
    (Git Bash), а здесь тело запроса кодируется явно.
    """
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "max_tokens": 120,
        "stream": False,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    obj = json.loads(raw)
    choices = obj.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content") or ""


def parse_rating(raw):
    """Разбор четырёх полей ответа. Терпимо к лишним строкам и регистру."""
    out = {"tone": "", "intensity": 0, "grammatical": "", "conf": 0, "parsed": False}
    if not raw:
        return out
    low = raw.lower()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip().lower()
        v = v.strip().strip(".!,").lower()
        if k == "tone":
            for t in TONES:
                if t in v:
                    out["tone"] = t
                    break
        elif k == "intensity":
            d = "".join(ch for ch in v if ch.isdigit())
            if d:
                out["intensity"] = max(1, min(5, int(d)))
        elif k == "grammatical":
            for g in GRAMS:
                if g in v:
                    out["grammatical"] = g
                    break
        elif k == "conf":
            d = "".join(ch for ch in v if ch.isdigit())
            if d:
                out["conf"] = max(0, min(100, int(d)))
    out["parsed"] = bool(out["tone"] and out["intensity"] and out["grammatical"])
    if not out["tone"] and low:
        for t in TONES:
            if t in low:
                out["tone"] = t
                break
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Сверка с лексикой
# ─────────────────────────────────────────────────────────────────────────────
def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def compare(items):
    """Сверка модельной оценки с лексической метрикой."""
    rated = [it for it in items if it.get("tone")]
    n = len(rated)
    if not n:
        return {"n": 0, "note": "нет разобранных ответов модели"}
    lex_severe = [it for it in rated if it["lexical"]["class"] == tone_metrics.CLASS_SEVERE]
    lex_cons = [it for it in rated if it["lexical"]["class"] == tone_metrics.CLASS_CONSOLING]
    lex_neutral = [it for it in rated if it["lexical"]["class"] == tone_metrics.CLASS_NEUTRAL]
    model_anger = [it for it in rated if it["tone"] == "anger"]
    model_comfort = [it for it in rated if it["tone"] == "comfort"]
    hit_severe = sum(1 for it in lex_severe if it["tone"] == "anger")
    hit_cons = sum(1 for it in lex_cons if it["tone"] in ("comfort", "mixed"))
    dead = [it for it in rated if it["lexical"]["score"] == 0.0]
    dead_by_tone = Counter(it["tone"] for it in dead)
    score_by_tone = defaultdict(list)
    for it in rated:
        score_by_tone[it["tone"]].append(it["lexical"]["score"])
    xs = [it["lexical"]["score"] for it in rated]
    ys = [float(it["intensity"]) for it in rated]
    by_outcome = defaultdict(list)
    for it in rated:
        by_outcome[it["outcome"]].append(it["lexical"]["score"])
    return {
        "n": n,
        "n_failed": sum(1 for it in items if not it.get("tone")),
        "match_severe_to_anger": {
            "lexical_severe": len(lex_severe), "model_anger": len(model_anger),
            "both": hit_severe,
            "rate": round(hit_severe / len(lex_severe), 3) if lex_severe else None,
        },
        "match_consoling_to_comfort": {
            "lexical_consoling": len(lex_cons), "model_comfort": len(model_comfort),
            "both": hit_cons,
            "rate": round(hit_cons / len(lex_cons), 3) if lex_cons else None,
        },
        "model_tone_counts": dict(Counter(it["tone"] for it in rated)),
        "lexical_class_counts": dict(Counter(it["lexical"]["class"] for it in rated)),
        "mean_lexical_score_by_model_tone": {
            k: round(sum(v) / len(v), 3) for k, v in sorted(score_by_tone.items())},
        "lexical_dead_zone": {
            "n_score_zero": len(dead),
            "share": round(len(dead) / n, 3),
            "by_model_tone": dict(dead_by_tone),
        },
        "pearson_score_vs_intensity": round(pearson(xs, ys), 3),
        "mean_lexical_score_by_outcome": {
            k: round(sum(v) / len(v), 3) for k, v in sorted(by_outcome.items())},
        "mean_model_intensity_by_outcome": {
            k: round(sum(float(it["intensity"]) for it in rated if it["outcome"] == k)
                     / max(1, sum(1 for it in rated if it["outcome"] == k)), 3)
            for k in sorted(by_outcome)},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Прогон
# ─────────────────────────────────────────────────────────────────────────────
def run(limit=None, out_path=OUT_FILE, url=DEFAULT_URL, key=DEFAULT_KEY,
        model=DEFAULT_MODEL, timeout=180, seed=SEED):
    eps = load_episodes()
    sample = stratified_sample(eps, seed=seed)
    existing = {}
    if out_path.exists():
        try:
            old = json.loads(out_path.read_text(encoding="utf-8"))
            for it in old.get("items", []):
                if it.get("episode_id"):
                    existing[it["episode_id"]] = it
        except Exception:
            existing = {}

    th = tone_metrics.thresholds_from(
        [{"tone": tone_metrics.tone_of(e.get("god_speech_plain"))} for e in eps])
    items = list(existing.values())
    done = {it["episode_id"] for it in items}
    todo = [e for e in sample if e.get("episode_id") not in done]
    if limit is not None:
        todo = todo[:limit]
    print("выборка: %d эпизодов, уже оценено: %d, к оценке: %d"
          % (len(sample), len(done), len(todo)))

    n_ok = 0
    for i, e in enumerate(todo, 1):
        speech = (e.get("god_speech_plain") or "").strip()
        tone = tone_metrics.tone_of(speech)
        rec = {
            "episode_id": e.get("episode_id"),
            "book": e.get("_book"),
            "outcome": e.get("outcome"),
            "trigger": e.get("trigger"),
            "severity": e.get("severity"),
            "speech": speech[:400],
            "tone": "", "intensity": 0, "grammatical": "", "conf": 0, "raw": "",
            "lexical": {
                "class": tone_metrics.classify(tone, th),
                "score": tone["score"], "words": tone["words"],
                "anger_rate": tone["anger_rate"], "mercy_rate": tone["mercy_rate"],
            },
        }
        raw = ""
        for attempt in range(3):
            try:
                raw = ask_brain(speech, url=url, key=key, model=model, timeout=timeout)
                break
            except Exception as ex:                      # noqa: BLE001 — сеть/сервер
                print("  попытка %d не удалась: %s" % (attempt + 1, ex))
                time.sleep(5 * (attempt + 1))
        parsed = parse_rating(raw)
        rec.update(parsed)
        rec["raw"] = raw[:300]
        if parsed["parsed"]:
            n_ok += 1
        items.append(rec)
        # пишем после каждого ответа: прерывание без потерь
        payload = {
            "metadata": {
                "prompt_version": PROMPT_VERSION, "model": model, "seed": seed,
                "sample_size": len(sample), "n_rated": sum(1 for x in items if x.get("tone")),
                "n_failed": sum(1 for x in items if not x.get("tone")),
                "n_requested_this_run": len(todo), "n_ok_this_run": n_ok,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            "items": items,
            "compare": compare(items),
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print("%d/%d  %-18s %-10s модель=%-8s инт=%d  лекс=%s (score %+.2f)"
              % (i, len(todo), e.get("episode_id"), e.get("outcome"),
                 parsed["tone"] or "—", parsed["intensity"],
                 rec["lexical"]["class"], rec["lexical"]["score"]))
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Самопроверка (без сети)
# ─────────────────────────────────────────────────────────────────────────────
def selftest():
    checks = []

    def chk(name, cond, detail=""):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name + (("  — " + detail) if detail else ""))

    # разбор типичного ответа
    raw = "TONE: anger\nINTENSITY: 4\nGRAMMATICAL: medium\nCONF: 80\n"
    p = parse_rating(raw)
    chk("разбор четырёх полей", p["tone"] == "anger" and p["intensity"] == 4
        and p["grammatical"] == "medium" and p["conf"] == 80 and p["parsed"])
    # мусорные строки не должны ломать разбор
    raw2 = "Вот моя оценка:\nTONE: comfort\nINTENSITY: 2\nGRAMMATICAL: short\nCONF: 55\nСпасибо!"
    p2 = parse_rating(raw2)
    chk("разбор терпим к лишним строкам", p2["tone"] == "comfort" and p2["intensity"] == 2)
    # нечитаемый ответ не считается разобранным
    p3 = parse_rating("не знаю")
    chk("нечитаемый ответ не разобран", not p3["parsed"] and not p3["tone"])
    # выборка детерминирована и стратифицирована
    eps = load_episodes()
    s1 = stratified_sample(eps)
    s2 = stratified_sample(eps)
    chk("выборка детерминирована", [e["episode_id"] for e in s1] == [e["episode_id"] for e in s2])
    chk("выборка содержит только эпизоды с речью",
        all((e.get("god_speech_plain") or "").strip() for e in s1))
    cnt = Counter(e["outcome"] for e in s1)
    avail = Counter(e["outcome"] for e in eps if (e.get("god_speech_plain") or "").strip())
    chk("в выборке есть все исходы", len(cnt) >= 6, str(dict(cnt)))
    chk("минимум на исход соблюдён (или исход исчерпан)",
        all(cnt[k] >= min(MIN_PER_OUTCOME, avail[k]) for k in avail),
        "silence: %d из %d доступных" % (cnt.get("silence", 0), avail.get("silence", 0)))
    chk("выборка не больше корпуса", len(s1) <= len(eps))
    # корреляция
    chk("Пирсон на идеальной паре = 1", abs(pearson([1, 2, 3], [2, 4, 6]) - 1.0) < 1e-9)
    chk("Пирсон на нулевой дисперсии = 0", pearson([1, 1, 1], [1, 2, 3]) == 0.0)
    # сверка: считается на искусственных данных
    items = [
        {"tone": "anger", "intensity": 5, "outcome": "punishment",
         "lexical": {"class": "severe", "score": 2.0}},
        {"tone": "comfort", "intensity": 2, "outcome": "blessing",
         "lexical": {"class": "consoling", "score": -2.0}},
        {"tone": "neutral", "intensity": 3, "outcome": "revelation",
         "lexical": {"class": "neutral", "score": 0.0}},
    ]
    c = compare(items)
    chk("сверка считает совпадения", c["match_severe_to_anger"]["both"] == 1
        and c["match_consoling_to_comfort"]["both"] == 1)
    chk("сверка находит мёртвую зону словаря", c["lexical_dead_zone"]["n_score_zero"] == 1)
    print("\nSELFTEST: %s (%d/%d)" % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)))
    return 0 if all(checks) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="сколько эпизодов оценить в этом запуске")
    ap.add_argument("--out", default=str(OUT_FILE))
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--key", default=DEFAULT_KEY)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--compare", action="store_true", help="только сводка по уже оценённым")
    ap.add_argument("--publish", action="store_true",
                    help="перезаписать docs/data/tone_rater.json (страница читает сводку)")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    if args.test:
        return selftest()

    out_path = Path(args.out)
    if args.compare or args.publish:
        data = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"items": []}
        cmp_ = compare(data.get("items", []))
        if args.publish:
            meta = data.get("metadata", {})
            pub = {"metadata": {k: meta.get(k) for k in
                                ("prompt_version", "model", "seed", "n_rated", "n_failed", "ts")},
                   "compare": cmp_}
            PUB_FILE.write_text(json.dumps(pub, ensure_ascii=False, indent=1), encoding="utf-8")
            print("опубликовано: %s" % PUB_FILE.relative_to(BASE))
        print(json.dumps(cmp_, ensure_ascii=False, indent=1))
        return 0

    payload = run(limit=args.limit, out_path=out_path, url=args.url, key=args.key,
                  model=args.model, timeout=args.timeout, seed=args.seed)
    print("\n=== сводка сверки ===")
    print(json.dumps(payload["compare"], ensure_ascii=False, indent=1))
    print("файл: %s" % out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
