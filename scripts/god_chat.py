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
    """Эпизоды реестра -> документы для поиска + словарь огласованных стихов."""
    docs = []
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


def retrieve(query, docs, k=TOP_K):
    """IDF-взвешенный поиск: редкие токены запроса (имена, топонимы) доминируют."""
    ru_q = rus_tokens(query)
    he_q = he_tokens(strip_nikud(query))
    doc_tokens = [rus_tokens(d["summary"] + " " + d["action"]) for d in docs]
    doc_stems = [_stems(t) for t in doc_tokens]
    q_stems = _stems(ru_q)
    n = len(docs)

    def idf(stem):
        df = sum(1 for s in doc_stems if stem in s)
        return 1.0 / (df + 1)  # реже встречается — выше вес

    scored = []
    for i, d in enumerate(docs):
        matched = q_stems & doc_stems[i]
        score = 3 * sum(idf(s) for s in matched)
        score += sum(idf(t) for t in he_q & he_tokens(d["quotes"]))
        score += 0.2 * d["severity"] / n  # severity только тай-брейк
        scored.append((score, i))
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
            out.append((ref, verses[key]))
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

Формат ответа строго такой:
[HEBREW]
<консонантный иврит — композиция данных цитат>
[NIKKUD]
<та же реплика с огласовкой, по образцу данных огласованных стихов>
[Russian]
<дословный русский подстрочник реплики, построчно>
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
    for tag, key in [("[HEBREW]", "he"), ("[NIKKUD]", "nik"), ("[Russian]", "ru"), ("[SOURCES]", "src")]:
        m = re.search(re.escape(tag) + r"\s*(.*?)(?=\[HEBREW\]|\[NIKKUD\]|\[Russian\]|\[SOURCES\]|$)", text, re.S)
        secs[key] = m.group(1).strip() if m else ""
    return secs


def answer(query, docs, verses, free=False, use_llm=True):
    hits = retrieve(query, docs)
    if not use_llm:
        he, nik, ru, src = compose_strict_reply(query, docs, hits, verses)
        return {"he": he, "nik": nik, "ru": ru, "src": src, "episodes": [h["book"] + " " + h["span"]["start"] for h in hits]}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", help="реплика человека (иначе интерактивный режим)")
    ap.add_argument("--test", action="store_true", help="без LLM: детерминированная композиция из реестра")
    ap.add_argument("--free", action="store_true", help="свободный режим (импровизация в стиле корпуса)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    docs, verses = load_corpus()
    print(f"[god_chat] корпус: {len(docs)} эпизодов, огласовки: {len(verses)} стихов")

    if args.selftest:
        sys.exit(0 if selftest(docs, verses) else 1)

    if args.message:
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
        a = answer(q, docs, verses, free=args.free, use_llm=not args.test)
        print(f"\n[эпизоды: {', '.join(a['episodes'])}]")
        print(f"עברית: {a['he']}")
        print(f"огласовка: {a['nik']}")
        print(f"перевод: {a['ru']}")
        src = a["src"]
        print("источники: " + ("\n           ".join(src) if isinstance(src, list) else str(src)))


if __name__ == "__main__":
    main()
