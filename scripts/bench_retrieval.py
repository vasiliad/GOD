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

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(_REPO, "docs", "bench_retrieval_sheet.md")
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


def main():
    selftest = "--test" in sys.argv
    questions = QUESTIONS[:3] if selftest else QUESTIONS
    qtrig = dict(questions)

    a = json.load(io.open(os.path.join(_REPO, "docs", "data", "analytics.json"), encoding="utf-8"))
    episodes, order = {}, []
    for era in a["book_order"].values():
        for book in era:
            p = os.path.join(_REPO, "output", f"episodes_{book}_v2.json")
            if os.path.exists(p):
                for e in json.load(io.open(p, encoding="utf-8")):
                    key = f"{book}|{e['span']['start']}"
                    episodes[key] = dict(e, book=book)
                    order.append(key)

    emb = json.load(io.open(os.path.join(_REPO, "docs", "data", "embeddings.json"), encoding="utf-8"))
    vecs = {}
    for i, row in enumerate(emb["rows"]):
        raw = base64.b64decode(row["q"])
        vecs[i] = [b * row["s"] / 127 for b in (v - 256 if v > 127 else v for v in raw)]

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
        allcos = {k: cos(qv, vecs[i]) for i, k in enumerate(order)}
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
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(NL.join(lines))
    print(f"лист записан: {OUT} (3 варианта x {len(questions)} вопросов)")
    print("механика (грубый прокси, НЕ приговор):",
          ", ".join(f"{n} {tm[n]}/{len(questions)}" for n in ("lex", "zhyb", "rrf")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
