"""
god_chat.py
Прототип "говорящего Бога": RAG над реестром эпизодов v2 + сценический промпт.

Строгий режим (по умолчанию): речь Бога составляется ТОЛЬКО из god_speech_plain
реальных эпизодов реестра (композиция цитат). Свободный режим (--free) разрешает
модели импровизацию в стиле корпуса.

Вывод: иврит (консонантный) / огласованная цитата / русский подстрочник / источники.

Модель: DictaLM через LM Studio (OpenAI-compatible API, http://127.0.0.1:1234).
Без сервера используйте --test: ответ компонируется детерминированно из реестра.

Usage:
    python scripts/god_chat.py --message "почему ты покарал Иерихон?" --test
    python scripts/god_chat.py --message "..."            (нужен запущенный LM Studio)
    python scripts/god_chat.py --test                     (интерактивный диалог)
    python scripts/god_chat.py --test --selftest          (прогон контрольных вопросов)
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path("C:/GOD2")
EPISODES_GLOB = "output/episodes_*_v2.json"
TANAKH_DIR = BASE / "data/tanakh"
LM_API = "http://127.0.0.1:1234/v1/chat/completions"
LM_MODEL = "dicta-lm-3.0"
TOP_K = 4

# Русские слова, по которым ищем по summary_ru/god_action (стемминг грубый).
RU_STOP = set("и в на с по о не что как это то же ли бы а но или у к из за до для при ты он она они я мы вы мне тебя его её их кто почему зачем когда где".split())


def strip_nikud(text: str) -> str:
    return re.sub(r"[\u0591-\u05C7]", "", text)


def load_corpus():
    """Эпизоды реестра -> документы для поиска + словарь огласованных стихов.
    Предпочитает дедуплицированный мастер-корпус episodes_TANAKH_v2.json."""
    docs = []
    master = BASE / "output/episodes_TANAKH_v2.json"
    if master.exists():
        books = json.load(open(master, encoding="utf-8"))  # {book: [episodes]}
        for book, eps in books.items():
            for ep in eps:
                docs.append({
                    "book": book,
                    "span": ep["span"],
                    "quotes": ep["god_speech_plain"],
                    "refs": ep["god_speech_refs"],
                    "summary": ep["summary_ru"],
                    "action": ep["god_action"],
                    "trigger": ep["trigger"],
                    "severity": ep["severity"],
                    "emotions": ep.get("emotions", []),
                    "direction": ep["direction"],
                })
    else:
        for fp in sorted(BASE.glob(EPISODES_GLOB)):
            book = fp.stem.replace("episodes_", "").replace("_v2", "")
            for ep in json.load(open(fp, encoding="utf-8")):
                docs.append({
                    "book": book,
                    "span": ep["span"],
                    "quotes": ep["god_speech_plain"],
                    "refs": ep["god_speech_refs"],
                    "summary": ep["summary_ru"],
                    "action": ep["god_action"],
                    "trigger": ep["trigger"],
                    "severity": ep["severity"],
                    "emotions": ep.get("emotions", []),
                    "direction": ep["direction"],
                })
    verses = {}
    for fp in TANAKH_DIR.glob("*.json"):
        if fp.stem == "_index":
            continue
        book = fp.stem
        d = json.load(open(fp, encoding="utf-8"))
        for v in d["verses"]:
            verses[(book, v["chapter"], v["verse"])] = v["text_he"]
    return docs, verses


def rus_tokens(text: str):
    return {t for t in re.findall(r"[а-яё-]{4,}", text.lower()) if t not in RU_STOP}


def he_tokens(text: str):
    return {t for t in re.findall(r"[\u05D0-\u05EA]{3,}", text) if len(t) >= 4}


def _stems(tokens):
    """Грубой стемминг: токен + усечения на 1-2 символа (Иерихон ~ Иерихо)."""
    out = set()
    for t in tokens:
        out.add(t)
        out.add(t[:-1])
        if len(t) > 5:
            out.add(t[:-2])
    return out


# Русские синонимические пучки для реколла (умер~смерть~умирает и т.п.)
RU_SYN = [
    {"умер", "умереть", "смерть", "смерт", "умирает", "погиб", "погибель", "похорон"},
    {"гнев", "разгневал", "гнева", "разгневаться", "гневен"},
    {"милосерд", "милост", "простил", "прощение", "простить", "пощадил"},
    {"люб", "любов", "любовь", "любим"},
    {"страх", "боюсь", "боится", "страшно", "устраш"},
    {"наказа", "кара", "карает", "наказание"},
    {"спас", "спасение", "спасает", "избав"},
    {"молитв", "молитва", "молится", "молю", "моли"},
    {"завет", "завета", "завету"},
    {"грех", "греха", "грехов", "согрешил", "преступ"},
]


# EN intake -> русские концепты для retrieval (вопросы принимаются на любом языке;
# полноценный машинный перевод в ЛЮБЫЙ бэкенд отдаётся LLM-пути, здесь — частотный
# мост для частых вопрошаний)
EN_MAP = {
    "fear": "страх", "afraid": "страх", "scared": "страх",
    "anger": "гнев", "angry": "гнев", "wrath": "гнев",
    "destroy": "разруш", "destruction": "разруш",
    "punish": "наказ", "punishment": "наказ",
    "mercy": "милос", "forgive": "простил", "forgiveness": "прощение",
    "silence": "молчание", "quiet": "молчание",
    "pray": "молитва", "prayer": "молитва",
    "save": "спас", "rescue": "спас", "deliver": "избав",
    "sin": "грех", "sinned": "согрешил",
    "love": "люб", "covenant": "завет", "promise": "обет",
    "temple": "храм", "idol": "идол", "dream": "сон",
    "die": "умер", "death": "смерть", "died": "умер",
    "why": "почему", "how": "как", "who": "кто", "what": "что",
    "listen": "слыш", "hear": "слыш", "answer": "отвеча",
    "command": "повелен", "law": "закон", "torah": "тор",
}


def en_tokens(text: str):
    return [t for t in re.findall(r"[a-z]{2,}", text.lower()) if t not in EN_STOP]


EN_STOP = set("the and are for you your its with from that this have has had was were will would could should there here whom whose them they their our ours ours whom".split())


def en_to_ru_enriched(text: str):
    """EN-запрос -> русские концепты (псевдотокены) для doc-matching."""
    words = re.findall(r"[a-z']{2,}", text.lower())
    out = []
    for w in words:
        if w in EN_MAP:
            out.append(EN_MAP[w])
        else:
            stem = w.rstrip("".join("edings"))
            for p in ("es", "ing", "ed"):
                if w.endswith(p) and len(w) > len(p) + 2:
                    stem = w[:-len(p)]
                    if stem in EN_MAP:
                        out.append(EN_MAP[stem])
    return " ".join(out)


def _syn_roots(tokens):
    """Каждый токен -> множество корней его синонимического пучка (для реколла)."""
    out = set(tokens)
    for group in RU_SYN:
        if tokens & group:
            out |= group
    return out


def clean_he_display(text: str) -> str:
    """Чистка огласованного текста от HTML-артефактов источника ({ס}, &nbsp;, теги)."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"[{לּ}]", "", text)
    text = re.sub(r"[{][^}]*[}]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _he_roots(tokens):
    """Нормализация ивритских токенов запроса: снять префиксы ב/ל/כ/ה/ו/ש и суффиксы."""
    out = set()
    for t in tokens:
        out.add(t)
        for p in ("ב", "ל", "כ", "ה", "ו", "ש", "מ"):
            if t.startswith(p) and len(t) >= 5:
                out.add(t[1:])
        for s in ("ים", "ות", "ך", "ו", "י", "ה"):
            if t.endswith(s) and len(t) >= 5:
                out.add(t[:-len(s)])
    return out


def retrieve(query, docs, k=TOP_K):
    """BM25-подобный поиск: IDF по корпусу, нормализация длины документа,
    синонимические пучки для русского, префиксно-суффиксная нормализация иврита."""
    from collections import Counter
    ru_q = rus_tokens(query) | rus_tokens(en_to_ru_enriched(query))
    he_q = _he_roots(he_tokens(strip_nikud(query)))
    if not ru_q and not he_q:
        return []

    # предвычисляем токены документов один раз на вызов
    doc_ru = [ _syn_roots(rus_tokens(d["summary"] + " " + d["action"])) for d in docs ]
    doc_he = [ _he_roots(he_tokens(strip_nikud(d["quotes"]))) for d in docs ]
    n = len(docs)
    avg_len = sum(len(r) + len(h) for r, h in zip(doc_ru, doc_he)) / max(n, 1)
    df_ru = Counter()
    for s in doc_ru:
        for t in s:
            df_ru[t] += 1
    df_he = Counter()
    for s in doc_he:
        for t in s:
            df_he[t] += 1

    def bm25(qterms, doc_terms, df, k1=1.5, b=0.75, weight=1.0):
        dl = len(doc_terms)
        score = 0.0
        for t in qterms:
            if t not in doc_terms:
                continue
            idf = 1.0 + (n - df[t] + 0.5) / (df[t] + 0.5)
            tf = 1  # множества: tf=1
            score += weight * idf * tf * (k1 + 1) / (1 + k1 * (1 - b + b * dl / avg_len))
        return score

    scored = []
    for i, d in enumerate(docs):
        s = bm25(_syn_roots(ru_q), doc_ru[i], df_ru, weight=3.0)
        s += bm25(he_q, doc_he[i], df_he, weight=1.5)
        s += 0.2 * d["severity"] / n  # severity только тай-брейк
        scored.append((s, i))
    scored.sort(reverse=True)
    return [docs[i] for s, i in scored[:k] if s > 0]


def vowelled_quote(doc, verses):
    """Оласованный текст первых стихов речи Бога этого эпизода."""
    out = []
    for ref in doc["refs"][:3]:
        m = re.match(r"(\d+):(\d+)", ref)
        if not m:
            continue
        key = (doc["book"], int(m.group(1)), int(m.group(2)))
        if key in verses:
            out.append((ref, clean_he_display(verses[key])))
    return out


def compose_strict_reply(query, docs, hits, verses):
    """--test / без модели: детерминированная композиция из реальных цитат."""
    he_lines, sources, gloss_lines = [], [], []
    for d in hits[:3]:
        if d["quotes"]:
            he_lines.append(d["quotes"].split(" ... ")[0])
            for ref, vhe in vowelled_quote(d, verses):
                gloss_lines.append(vhe)
            sources.append(f"{d['book']} {d['span']['start']}-{d['span']['end']}")
    he = " ".join(he_lines) if he_lines else "שמע ישראל"
    gloss = " ".join(gloss_lines) if gloss_lines else "(огласовки недоступны)"
    summary = hits[0]["summary"] if hits else "(нет релевантных эпизодов)"
    return he, gloss, summary, sources


def lm_chat(messages):
    body = json.dumps({"model": LM_MODEL, "messages": messages, "temperature": 0.3}).encode()
    req = urllib.request.Request(LM_API, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


SYSTEM_PROMPT = """Ты — исследовательская имитация образа YHWH, извлечённого из Танаха (реестр эпизодов v2).
Ты пишешь (не говоришь) на библейском иврите. СТРОГИЙ РЕЖИМ: твоя ивритская реплика
составляется ТОЛЬКО из данных тебе фрагментов god_speech_plain — ты можешь их
комбинировать и сокращать, но не добавлять слов вне их лексики.

Формат ответа строго такой (вопрос мог прийти на любом языке — отвечай по существу вопроса):
[HEBREW]
<консонантный иврит — композиция данных цитат>
[NIKKUD]
<та же реплика с огласовкой, по образцу данных огласованных стихов>
[Russian]
<дословный русский подстрочник реплики, построчно>
[English]
<дословный английский перевод той же реплики>
[Hebrew Modern]
<та же реплика на современном иврите (иврит-иври), для читающего нового иврита>
[SOURCES]
<ссылки на эпизоды-источники: книга стихи>
Никакого текста вне этих секций."""


def build_messages(query, hits, verses):
    ctx = []
    for d in hits:
        ctx.append({
            "book": d["book"], "span": d["span"], "trigger": d["trigger"],
            "god_speech_plain": d["quotes"],
            "nikkud": [v for _, v in vowelled_quote(d, verses)],
            "summary_ru": d["summary"],
        })
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"РЕЛЕВАНТНЫЕ ЭПИЗОДЫ РЕЕСТРА:\n{json.dumps(ctx, ensure_ascii=False)}\n\nРеплика человека: {query}"},
    ]


def parse_sections(text):
    secs = {}
    for tag, key in [("[HEBREW]", "he"), ("[NIKKUD]", "nik"), ("[Russian]", "ru"),
                     ("[English]", "en"), ("[Hebrew Modern]", "he_mod"), ("[SOURCES]", "src")]:
        m = re.search(re.escape(tag) + r"\s*(.*?)(?=\[HEBREW\]|\[NIKKUD\]|\[Russian\]|\[SOURCES\]|$)", text, re.S)
        secs[key] = m.group(1).strip() if m else ""
    return secs


def answer(query, docs, verses, free=False, use_llm=True):
    hits = retrieve(query, docs)
    if not use_llm:
        he, nik, ru, src = compose_strict_reply(query, docs, hits, verses)
        return {"he": he, "nik": nik, "ru": ru, "en": "(требуется LLM-бэкенд: DictaLM/любой OpenAI-совместимый)",
                "he_mod": "(требуется LLM-бэкенд)", "src": src,
                "episodes": [h["book"] + " " + h["span"]["start"] for h in hits]}
    if free:
        prompt = SYSTEM_PROMPT.replace("СТРОГИЙ РЕЖИМ: твоя ивритская реплика\nсоставляется ТОЛЬКО из данных тебе фрагментов god_speech_plain — ты можешь их\nкомбинировать и сокращать, но не добавлять слов вне их лексики.",
                                       "СВОБОДНЫЙ РЕЖИМ: стиль и лексика — по образцу данных цитат; не цитируй их дословно обязательно.")
        messages = [{"role": "system", "content": prompt}] + build_messages(query, hits, verses)[1:]
    else:
        messages = build_messages(query, hits, verses)
    out = lm_chat(messages)
    secs = parse_sections(out)
    secs["episodes"] = [h["book"] + " " + h["span"]["start"] for h in hits]
    return secs


def selftest(docs, verses):
    checks = [
        ("почему ты покарал Иерихон?", "Joshua"),
        ("я согрешил, простишь ли меня", None),
        ("зачем ты вывел меня из Египта", None),
    ]
    ok = True
    for q, expect_book in checks:
        hits = retrieve(q, docs)
        assert hits, f"пустой retrieval: {q}"
        he, nik, ru, src = compose_strict_reply(q, docs, hits, verses)
        found = any(h["book"] == expect_book for h in hits) if expect_book else True
        print(f"Q: {q}\n  hits: {[h['book']+' '+h['span']['start'] for h in hits]}\n  HE: {he[:60]}...\n  src: {src}\n  expected_book={expect_book} -> {'OK' if found else 'FAIL'}")
        ok &= bool(found and he and src)
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return ok


def load_session(path=BASE / "output/god_chat_session.json"):
    """Б4: сессионное состояние диалога (память о проступках/благодати)."""
    if Path(path).exists():
        return json.load(open(path, encoding="utf-8"))
    return {"offenses": 0, "grace": 0, "history": []}


def save_session(sess, path=BASE / "output/god_chat_session.json"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sess, ensure_ascii=False, indent=1), encoding="utf-8")


def update_session(sess, query):
    """Классифицирует реплику и обновляет счётчики: непослушание/идолы копят
    проступки, покаяние/верность — гасят; возвращает карточку поведения."""
    import god_behavior
    profile = json.load(open(BASE / "output/god_behavior_profile.json", encoding="utf-8"))
    cls = god_behavior.classify(query)
    if cls["trigger"] == "disobedience" or cls["heavy"]:
        sess["offenses"] += 1
    if cls["confession"] or cls["trigger"] in ("faithfulness", "gratitude"):
        sess["offenses"] = max(0, sess["offenses"] - 1)
        sess["grace"] += 1
    sess["history"].append({"q": query, "trigger": cls["trigger"], "confession": cls["confession"]})
    save_session(sess)
    card = god_behavior.respond(query, profile, offenses=sess["offenses"])
    return cls, card


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", help="реплика человека (иначе интерактивный режим)")
    ap.add_argument("--test", action="store_true", help="без LLM: детерминированная композиция из реестра")
    ap.add_argument("--free", action="store_true", help="свободный режим (импровизация в стиле корпуса)")
    ap.add_argument("--behavior", action="store_true", help="перед речью показать карточку поведения (god_behavior)")
    ap.add_argument("--memory", action="store_true", help="Б4: диалоговая память (накопление проступков/благодати, файл output/god_chat_session.json)")
    ap.add_argument("--reset", action="store_true", help="сбросить диалоговую память")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    docs, verses = load_corpus()
    print(f"[god_chat] корпус: {len(docs)} эпизодов, огласовки: {len(verses)} стихов")

    if args.reset:
        p = BASE / "output/god_chat_session.json"
        if p.exists():
            p.unlink()
        print("[память диалога сброшена]")

    if args.selftest:
        sys.exit(0 if selftest(docs, verses) else 1)

    sess = load_session() if args.memory else None

    def with_memory(q):
        """Одна реплика с памятью: карточка поведения + ответ."""
        cls, card = update_session(sess, q)
        print(f"[память: проступки={sess['offenses']} благодать={sess['grace']}]")
        print(god_behavior_render(card) + "\n")
        return answer(q, docs, verses, free=args.free, use_llm=not args.test)

    import god_behavior
    god_behavior_render = god_behavior.render

    if args.message:
        if args.behavior or args.memory:
            if args.memory:
                a = with_memory(args.message)
            else:
                profile = json.load(open(BASE / "output/god_behavior_profile.json", encoding="utf-8"))
                print(god_behavior_render(god_behavior.respond(args.message, profile)) + "\n")
                a = answer(args.message, docs, verses, free=args.free, use_llm=not args.test)
        else:
            a = answer(args.message, docs, verses, free=args.free, use_llm=not args.test)
        print(f"\n=== עברית ===\n{a['he']}\n\n=== огласовка ===\n{a['nik']}\n\n=== русский подстрочник ===\n{a['ru']}\n\n=== источники ===\n" +
              "\n".join(a["src"]) if isinstance(a["src"], list) else a["src"])
        return

    print("Интерактивный режим (введите реплику, пустая строка — выход). Режим:", "free" if args.free else "strict")
    while True:
        try:
            q = input("\nВы> ").strip()
        except EOFError:
            break
        if not q:
            break
        if args.memory:
            a = with_memory(q)
        else:
            a = answer(q, docs, verses, free=args.free, use_llm=not args.test)
        print(f"\n[эпизоды: {', '.join(a['episodes'])}]")
        print(f"עברית: {a['he']}")
        print(f"огласовка: {a['nik']}")
        print(f"перевод: {a['ru']}")
        src = a["src"]
        print("источники: " + ("\n           ".join(src) if isinstance(src, list) else str(src)))


if __name__ == "__main__":
    main()
