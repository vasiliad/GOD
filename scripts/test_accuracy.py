"""Проверка точности мозга: серия вопросов → сверка каждого ответа с корпусом.

Тест на галлюцинацию: DictaLM получает эпизоды через retrieval и должен
рекомбинировать ТОЛЬКО реальные цитаты. Для каждого ответа проверяем:
  1. Все ли 6 секций заполнены?
  2. Существует ли цитируемый эпизод в реестре?
  3. Совпадает ли [HEBREW] с god_speech_plain этого эпизода?
  4. Соответствует ли [SOURCES] реальному спану?
"""
import base64, io, json, math, os, sys, time, urllib.request

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRAIN = json.load(io.open(os.path.join(_REPO, "brain", "brain_snapshot.json"), encoding="utf-8"))
URL = BRAIN["url"] + "/v1/chat/completions"
KEY = BRAIN.get("key", "")

QUESTIONS = [
    "как тебя зовут?",
    "я боюсь умереть",
    "почему ты допустил зло в мире?",
    "сотворение мира",
    "я согрешил и хочу исправиться",
    "спаси меня от беды",
    "что такое завет с тобой?",
    "благодарю тебя за всё",
    "почему праведники страдают?",
    "хочу узнать твою волю",
]

# SYS_PROMPT — копия из docs/index.html
SYS_PROMPT = "Ты — исследовательская имитация образа YHWH, извлечённого из Танаха (реестр эпизодов v2).\n" \
"Ты пишешь (не говоришь) на библейском иврите. СТРОГИЙ РЕЖИМ: твоя ивритская реплика составляется\n" \
"ТОЛЬКО из данных тебе фрагментов god_speech_plain — комбинируй и сокращай, но не добавляй слов вне их лексики.\n" \
"Огласовку в [NIKKUD] бери ТОЛЬКО из полей nikud данных эпизодов, воспроизводя их пословно; слово без образца оставляй неогласованным.\n" \
"Отвечай по существу вопроса, каким бы языком он ни был задан. Каждая секция — короткая, 1–2 строки.\n\n" \
"Формат ответа: ровно шесть секций, ни одна не пропускается, ничего кроме них:\n" \
"[HEBREW] консонантный иврит БЕЗ ОГЛАСОВОК — только буквы (составлено из god_speech_plain)\n" \
"[NIKKUD] та же реплика с огласовкой, пословно скопированной из полей nikud данных эпизодов\n" \
"[Russian] ТОЛЬКО русские слова, взятые из русских аннотаций summary_ru данных эпизодов; не хватает слов — сократи реплику\n" \
"[English] дословный английский перевод, 1–2 строки\n" \
"[Hebrew Modern] та же реплика на современном иврите, 1 строка\n" \
"[SOURCES] обязательная последняя секция: книга глава:стих эпизодов-источников; не заканчивай ответ без неё"


def ask_brain(q, ctx_json, trig, probs):
    user = f"РЕЛЕВАНТНЫЕ ЭПИЗОДЫ РЕЕСТРА:\n{ctx_json}\n\nТриггер реплики: {trig}. Ожидаемые исходы: {json.dumps(probs)}\n\nРеплика человека: {q}\n\nНапоминание: ответ обязан кончаться секцией [SOURCES] со стихами-источниками."
    body = json.dumps({"messages": [
        {"role": "system", "content": SYS_PROMPT},
        {"role": "user", "content": user}
    ], "temperature": 0.3, "max_tokens": 1800}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=300) as r:
        j = json.loads(r.read())
    return j["choices"][0]["message"]["content"]


def parse_sections(text):
    sections = {}
    tags = ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]
    for tag in tags:
        i = text.find(tag)
        if i < 0:
            continue
        rest = text[i + len(tag):]
        end = len(rest)
        for t2 in tags:
            j = rest.find(t2)
            if j >= 0 and j < end:
                end = j
        sections[tag] = rest[:end].strip()
    return sections


def main():
    # загрузить корпус и retrieval
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    from bench_retrieval import lexical_scores, RU_SYN, RU_STOP
    import unicodedata

    a = json.load(io.open(os.path.join(_REPO, "docs", "data", "analytics.json"), encoding="utf-8"))
    episodes = {}
    for era in a["book_order"].values():
        for book in era:
            p = os.path.join(_REPO, "output", f"episodes_{book}_v2.json")
            if os.path.exists(p):
                for e in json.load(io.open(p, encoding="utf-8")):
                    episodes[f"{book}|{e['span']['start']}"] = dict(e, book=book)

    emb = json.load(io.open(os.path.join(_REPO, "docs", "data", "embeddings.json"), encoding="utf-8"))
    vecs = {}
    for i, row in enumerate(emb["rows"]):
        raw = base64.b64decode(row["q"])
        vecs[i] = [b * row["s"] / 127 for b in (v - 256 if v > 127 else v for v in raw)]

    from transformers import AutoModel, AutoTokenizer
    import torch
    EMB_MODEL = "intfloat/multilingual-e5-small"
    tok = AutoTokenizer.from_pretrained(EMB_MODEL)
    model = AutoModel.from_pretrained(EMB_MODEL)
    model.eval()

    def embed(q):
        with torch.no_grad():
            enc = tok(["query: " + q], padding=True, truncation=True, max_length=64, return_tensors="pt")
            out = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            v = (out * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            v = v[0]
            return (v / v.norm()).tolist()

    cos = lambda a, b: sum(x * y for x, y in zip(a, b))

    print("Проверка точности мозга: 10 вопросов через retrieval → DictaLM → сверка с корпусом\n")
    results = []

    for qi, q in enumerate(QUESTIONS):
        # retrieval (та же логика, что на странице)
        lex = lexical_scores(q, episodes)
        qv = embed(q)
        order_keys = list(episodes.keys())
        allcos = {k: cos(qv, vecs[i]) for i, k in enumerate(order_keys)}
        mean = sum(allcos.values()) / len(allcos)
        std = math.sqrt(sum((c - mean) ** 2 for c in allcos.values()) / len(allcos)) or 1e-9
        hyb = {k: lex[k] + 2.0 * (c - mean) / std for k, c in allcos.items()}
        top6 = sorted(hyb.items(), key=lambda kv: -kv[1])[:6]

        ctx = []
        for k, _ in top6:
            e = episodes[k]
            ctx.append({"book": e["book"], "span": e["span"], "trigger": e.get("trigger", ""),
                        "outcome": e.get("outcome", ""), "god_speech_plain": (e.get("god_speech_plain") or "")[:300],
                        "summary_ru": (e.get("summary_ru") or "")[:200], "god_action": (e.get("god_action") or "")[:160]})

        tt = {"n": 5, "answer_granted": 0.3, "silence": 0.25}
        ctx_json = json.dumps(ctx, ensure_ascii=False)
        print(f"[{qi+1}/10] «{q}»")
        try:
            raw = ask_brain(q, ctx_json, "inquiry", tt)
            sections = parse_sections(raw)
            n_sections = len(sections)
            hebrew = sections.get("[HEBREW]", "")
            nikud = sections.get("[NIKKUD]", "")
            sources = sections.get("[SOURCES]", "")
            russian = sections.get("[Russian]", "")

            # сверка: существует ли цитируемый эпизод?
            src_ok = "не проверено"
            src_book = ""
            for k, ep in episodes.items():
                bn = ep["book"]
                if bn.lower() in sources.lower() or (bn[0].upper() + bn[1:]) in sources:
                    src_ok = "ДА"
                    src_book = bn
                    break
            else:
                src_ok = "НЕ НАЙДЕН"

            # сверка: god_speech из top-1 эпизода содержит слова из [HEBREW]?
            match_ok = "—"
            if top6 and hebrew:
                top_ep = episodes[top6[0][0]]
                gs = (top_ep.get("god_speech_plain") or "").replace("\u05BE", "").replace(" ", "")
                heb = hebrew.replace("\u05BE", "").replace(" ", "")
                if len(gs) > 5 and len(heb) > 5:
                    overlap = sum(1 for w in heb.split() if w in gs) / max(1, len(heb.split()))
                    match_ok = f"{overlap:.0%}"

            results.append((q, n_sections, src_ok, match_ok, hebrew[:60], sources[:40]))
            print(f"  секций: {n_sections}/6 | источник найден: {src_ok} | совпадение речи: {match_ok}")
            print(f"  [HEBREW] {hebrew[:60]}…")
            print(f"  [SOURCES] {sources[:50]}")
            print(f"  [RU] {russian[:60]}…")
        except Exception as e:
            results.append((q, 0, f"ошибка: {e}", "—", "", ""))
            print(f"  ОШИБКА: {e}")
        print()
        time.sleep(1)

    print("=== СВОДКА ===")
    perfect = sum(1 for r in results if r[1] == 6 and r[2] == "ДА")
    has_all_sections = sum(1 for r in results if r[1] == 6)
    src_found = sum(1 for r in results if r[2] == "ДА")
    print(f"Все 6 секций: {has_all_sections}/10")
    print(f"Источник найден в корпусе: {src_found}/10")
    print(f"Идеальные ответы (6 секций + источник): {perfect}/10")
    for q, ns, src, match, heb, srcs in results:
        print(f"  {'OK' if ns==6 and src=='ДА' else '!!'} {q[:35]:37s} {ns}/6 секций | src: {src}")


if __name__ == "__main__":
    main()
