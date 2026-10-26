"""Слепой бенчмарк retrieval: три алгоритма отбора — оценивает ЧЕЛОВЕК, не модель.

Рождён из вопроса проекта (2026-10-21): «как нам проверить, что ты не ошибся?» —
авторская самопроверка не является независимой, поэтому этот скрипт выдаёт
анонимизированный лист А/Б/В: для каждого вопроса топ-3 выдачи трёх алгоритмов
(лексика; z-гибрид как на проде; RRF-союз рангов), перемешанные случайно.
Расшифровка — в конце файла (оценивающий не читает её до оценки).

    python scripts/bench_retrieval.py            # полный прогон → docs/bench_retrieval_sheet.md
    python scripts/bench_retrieval.py --test     # 3 вопроса, проверка конвейера

Механическая метрика (совпадение триггера топ-1) печатается как ГРУБЫЙ прокси —
приговор по смыслу выносит только слепой лист.
"""
import base64, io, json, math, os, random, sys, unicodedata
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_REPO = str(_ROOT)
# NOTE: --test пишет во временный лист в output/ (самокоррупция аудита 2026-10-21)
OUT = os.path.join(_REPO, "docs", "bench_retrieval_sheet.md")
MASTER_CORPUS = _ROOT / "output" / "episodes_TANAKH_v2.json"
ANALYTICS = _ROOT / "docs" / "data" / "analytics.json"
EMBEDDINGS = _ROOT / "docs" / "data" / "embeddings.json"
MODEL = "intfloat/multilingual-e5-small"

QUESTIONS = [
    ("я согрешил, прости меня", "confession"),
    ("сердце моё нечисто перед тобой", "confession"),
    ("спаси меня от врагов моих", "distress"),
    ("мне страшно, я не справлюсь", "distress"),
    ("почему ты покинул меня", "complaint"),
    ("несправедливо, что праведник страдает", "complaint"),
    ("молю тебя, услышь меня", "prayer"),
    ("взываю к тебе из глубины", "prayer"),
    ("что мне делать, чтобы жить", "inquiry"),
    ("сотворение мира", "inquiry"),
    ("прости им, они не ведают", "intercession"),
    ("не губи народ за грех одного", "intercession"),
    ("даю обет посвятить тебе", "vow"),
    ("клянусь верностью тебе", "vow"),
    ("благодарю тебя за спасение", "gratitude"),
    ("воспою тебе песнь новую", "gratitude"),
    ("нарушу завет и пойду за чужими богами", "disobedience"),
    ("не буду слушать твои слова", "disobedience"),
    ("хожу путями твоими всеми сердцем", "faithfulness"),
    ("делаю всё как ты велел", "faithfulness"),
    ("заключи со мной завет мирный", "covenant"),
    ("помяни обещание отцам нашим", "covenant"),
]

RU_STOP = set("и в на с по о не что как это то же ли бы а но или у к из за до для при".split(" "))
RU_SYN = [
    ["умер", "смерть", "смерт", "умирает", "погиб", "погибель", "умрет", "мертв"],
    ["гнев", "разгневал", "гнева", "гневен", "ярост"],
    ["милосерд", "милост", "простил", "прощение", "простить", "пощадил", "милость"],
    ["люб", "любов", "любовь", "любим", "возлюб"],
    ["страх", "боюсь", "боится", "страшно", "устраш", "трепет", "бойся", "бойтесь", "испуг", "пугает"],
    ["наказа", "кара", "карает", "наказание", "покарал"],
    ["спас", "спасение", "спасает", "избав", "избавит"],
    ["молитв", "молитва", "молится", "молит"],
    ["завет", "завета", "завету", "договор"],
    ["грех", "греха", "грехов", "согрешил", "преступ"],
]


def query_tokens(q):
    m = q.lower()
    toks = set(t for t in ("".join(ch if ch.isalnum() or ch == "-" else " " for ch in m)).split())
    toks = set(t for t in toks if len(t) >= 4 and t not in RU_STOP
               and all(unicodedata.category(c)[0] == "L" for c in t))
    syn = set(toks)
    for t in toks:
        for g in RU_SYN:
            if any(x == t or (len(x) >= 4 and (x in t or t in x)) for x in g):
                syn.update(g)
    return syn


def lexical_scores(q, episodes, expected=None):
    toks = query_tokens(q)
    out = {}
    for key, e in episodes.items():
        txt = (e["summary_ru"] + " " + e["god_action"]).lower()
        s = 0.0
        for t in toks:
            if t in txt:
                s += 10 / math.log(4 + len(txt)) if len(t) >= 6 else 1 / math.log(3 + len(txt))
        if e.get("god_speech_plain"):
            s += 2.5
        if expected and e.get("trigger") == expected:
            s += 4
        out[key] = s
    return out


def load_master_episodes():
    """Корпус эпизодов: {book|span.start: эпизод} из мастер-файла.

    Мастер output/episodes_TANAKH_v2.json — словарь {книга: [эпизоды]}, 2050 эпизодов
    после дедупликации. Файлы по книгам (2056) больше не читаются: в них 6 дублей,
    которых нет в эмбеддингах. Ключ book|span.start — тот же, что на странице.
    """
    master = json.load(io.open(MASTER_CORPUS, encoding="utf-8"))
    a = json.load(io.open(ANALYTICS, encoding="utf-8"))
    books = [b for era in a["book_order"].values() for b in era if b in master]
    books += [b for b in master if b not in books]
    episodes = {}
    for book in books:
        for e in master[book]:
            episodes[f"{book}|{e['span']['start']}"] = dict(e, book=book)
    return episodes


def load_embedding_vectors():
    """(index, vecs): index[book|span.start] = номер строки, vecs[key] = вектор.

    Строки embeddings.json пересобраны на мастер-корпусе, поэтому вектор ищем
    по КЛЮЧУ (meta.b + "|" + meta.s1), а не по позиции: список ключей раньше
    строился из 2056 старых файлов по книгам и разъезжался со строками.
    """
    emb = json.load(io.open(EMBEDDINGS, encoding="utf-8"))
    index = {f"{m['b']}|{m['s1']}": i for i, m in enumerate(emb["meta"])}
    vecs = {}
    for key, i in index.items():
        row = emb["rows"][i]
        raw = base64.b64decode(row["q"])
        vecs[key] = [b * row["s"] / 127 for b in (v - 256 if v > 127 else v for v in raw)]
    return index, vecs


def load_retrieval_corpus():
    """(episodes, vecs): эпизоды и векторы, согласованные по ключу book|span.start."""
    episodes = load_master_episodes()
    index, vecs = load_embedding_vectors()
    missing = [k for k in episodes if k not in index]
    if missing:
        raise SystemExit("эмбеддинги не покрывают корпус: нет строк для "
                         f"{len(missing)} эпизодов, напр. {', '.join(missing[:5])}")
    return episodes, vecs


def main():
    selftest = "--test" in sys.argv
    questions = QUESTIONS[:3] if selftest else QUESTIONS
    out_path = os.path.join(_REPO, "output", "bench_test_sheet.md") if selftest else OUT
    qtrig = dict(questions)

    episodes, vecs = load_retrieval_corpus()

    from transformers import AutoModel, AutoTokenizer
    import torch
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL)
    model.eval()

    def embed(q):
        with torch.no_grad():
            enc = tok(["query: " + q], padding=True, truncation=True, max_length=64, return_tensors="pt")
            out = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            v = (out * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            v = v[0]
            return (v / v.norm()).tolist()

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    def top3(scores):
        return sorted(scores.items(), key=lambda kv: -kv[1])[:3]

    rng = random.Random(2050)
    sheet, tm = [], {"lex": 0, "zhyb": 0, "rrf": 0}
    for q, expected in questions:
        lex = lexical_scores(q, episodes, expected)
        lex_top = top3(lex)
        qv = embed(q)
        allcos = {k: cos(qv, vecs[k]) for k in episodes}
        mean = sum(allcos.values()) / len(allcos)
        std = math.sqrt(sum((c - mean) ** 2 for c in allcos.values()) / len(allcos)) or 1e-9
        zhyb = {k: lex[k] + 6.0 * (c - mean) / std for k, c in allcos.items()}
        zhyb_top = top3(zhyb)
        lex_rank = {k: r for r, (k, _) in enumerate(sorted(lex.items(), key=lambda kv: -kv[1]))}
        vec_rank = {k: r for r, (k, _) in enumerate(sorted(allcos.items(), key=lambda kv: -kv[1]))}
        fused = {k: 1.0 / (60 + lex_rank.get(k, 10**6)) + 1.0 / (60 + vec_rank.get(k, 10**6)) for k in lex}
        rrf_top = top3(fused)
        for name, top in (("lex", lex_top), ("zhyb", zhyb_top), ("rrf", rrf_top)):
            if qtrig.get(q) and episodes[top[0][0]].get("trigger") == expected:
                tm[name] += 1
        order3 = ["lex", "zhyb", "rrf"]
        rng.shuffle(order3)
        variants = {"lex": lex_top, "zhyb": zhyb_top, "rrf": rrf_top}
        sheet.append((q, [variants[n] for n in order3], order3))

    NL = chr(10)
    lines = ["# Слепой лист оценки retrieval (А/Б/В)", "",
             "Для каждого вопроса три варианта топ-3 выдачи (три разных алгоритма отбора).",
             "Отметь в последней колонке лучший вариант: А / Б / В / = (равны). Оцени СМЫСЛОВОЕ",
             "соответствие вопросу: это кандидат на «ответ Бога», а не поиск по словам.",
             "Расшифровка — в конце файла, не читай её до оценки.", "",
             "| # | Вопрос | Вариант А | Вариант Б | Вариант В | лучший |",
             "|---|---|---|---|---|---|"]
    for n, (q, tops, keys3) in enumerate(sheet, 1):
        fmt = lambda top: "<br>".join(
            f"{episodes[k]['book']} {episodes[k]['span']['start']} — {episodes[k]['summary_ru'][:70]}…" for k, _ in top)
        lines.append(f"| {n} | {q} | {fmt(tops[0])} | {fmt(tops[1])} | {fmt(tops[2])} | |")
    lines += ["", "---", "## РАСШИФРОВКА (не читать до оценки)", ""]
    names = {"lex": "ЛЕКСИКА (как до вектора)", "zhyb": "ГИБРИД z-косинус (как на проде сейчас)",
             "rrf": "RRF (союз рангов)"}
    for n, (q, tops, keys3) in enumerate(sheet, 1):
        lines.append(f"{n}. «{q}» — " + "; ".join(f"{ltr} = {names[k]}" for ltr, k in zip("АБВ", keys3)))
    io.open(out_path, "w", encoding="utf-8", newline="\n").write(NL.join(lines))
    print(f"лист записан: {out_path} (3 варианта x {len(questions)} вопросов)")
    print("механика (грубый прокси, НЕ приговор):",
          ", ".join(f"{n} {tm[n]}/{len(questions)}" for n in ("lex", "zhyb", "rrf")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
