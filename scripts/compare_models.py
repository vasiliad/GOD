"""Сравнение качества: NVIDIA NIM модели против эталонных DictaLM-ответов.

Каждому вопросу → retrieval (тот же что на странице) → модели → 6-секционный ответ.
Проверка: формат, иврит, никауд, перевод, источник, галлюцинация.
"""
import base64, io, json, math, os, sys, time, urllib.request

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NIM_PROXY = "http://100.97.248.63:9090/v1/chat/completions"
EMB_MODEL = "intfloat/multilingual-e5-small"

SYS_PROMPT = "Ты — исследовательская имитация образа YHWH, извлечённого из Танаха (реестр эпизодов v2).\nТы пишешь (не говоришь) на библейском иврите. СТРОГИЙ РЕЖИМ: твоя ивритская реплика составляется ТОЛЬКО из данных тебе фрагментов god_speech_plain — комбинируй и сокращай, но не добавляй слов вне их лексики.\nФормат ответа: ровно шесть секций:\n[HEBREW] консонантный иврит БЕЗ ОГЛАСОВОК\n[NIKKUD] та же реплика с огласовкой\n[Russian] дословный русский подстрочник из summary_ru\n[English] дословный английский перевод\n[Hebrew Modern] та же реплика на современном иврите\n[SOURCES] книга глава:стих"

QUESTIONS = [
    {"q": "как тебя зовут?", "expect_theme": "самопредставление"},
    {"q": "я боюсь", "expect_theme": "утешение"},
    {"q": "я согрешил, прости меня", "expect_theme": "прощение"},
    {"q": "сотворение мира", "expect_theme": "творение"},
    {"q": "спаси меня от врагов", "expect_theme": "спасение"},
    {"q": "почему ты покинул меня", "expect_theme": "жалоба"},
    {"q": "заключи со мной завет", "expect_theme": "завет"},
    {"q": "благодарю тебя за спасение", "expect_theme": "благодарность"},
]

MODELS = [
    ("glm-5.3-flash", "z-ai/glm-5.3-flash"),
    ("nemotron-550b", "nvidia/nemotron-3-ultra-550b-a55b"),
]


def parse_sections(text):
    sections = {}
    for tag in ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]:
        i = text.find(tag)
        if i < 0:
            continue
        rest = text[i + len(tag):]
        end = len(rest)
        for t2 in ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]:
            j = rest.find(t2)
            if j >= 0 and j < end:
                end = j
        sections[tag] = rest[:end].strip()
    return sections


def main():
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    from bench_retrieval import lexical_scores, load_retrieval_corpus

    # Эпизоды и эмбеддинги берём СОГЛАСОВАННО по ключу book|span.start:
    # список ключей раньше строился из 2056 старых файлов по книгам и разъезжался
    # со строками embeddings.json (пересобраны на 2050 эпизодах мастер-корпуса).
    episodes, vecs = load_retrieval_corpus()
    print(f"Корпус: {len(episodes)} эпизодов, эмбеддингов: {len(vecs)}")

    from transformers import AutoModel, AutoTokenizer
    import torch
    tok = AutoTokenizer.from_pretrained(EMB_MODEL)
    model = AutoModel.from_pretrained(EMB_MODEL)
    model.eval()

    print("=== СРАВНЕНИЕ: NVIDIA NIM vs эталон DictaLM ===\n")
    scores = {m[0]: {"sections": 0, "hebrew": 0, "nikkud": 0, "russian": 0, "sources": 0, "no_hallucination": 0, "total": 0} for m in MODELS}

    for qi, qinfo in enumerate(QUESTIONS):
        q = qinfo["q"]
        print(f"[{qi+1}/{len(QUESTIONS)}] «{q}» ({qinfo['expect_theme']})")

        lex = lexical_scores(q, episodes)
        with torch.no_grad():
            enc = tok(["query: " + q], padding=True, truncation=True, max_length=64, return_tensors="pt")
            out = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            v = (out * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            v = v[0]
            qv = (v / v.norm()).tolist()
        cos = lambda a, b: sum(x * y for x, y in zip(a, b))
        allcos = {k: cos(qv, vecs[k]) for k in episodes}
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

        ctx_json = json.dumps(ctx, ensure_ascii=False)
        user_msg = f"РЕЛЕВАНТНЫЕ ЭПИЗОДЫ:\n{ctx_json}\n\nТриггер: distress.\n\nРеплика человека: {q}"

        for model_name, model_id in MODELS:
            try:
                body = json.dumps({"model": model_id,
                                   "messages": [{"role": "system", "content": SYS_PROMPT},
                                                {"role": "user", "content": user_msg}],
                                   "temperature": 0.3, "max_tokens": 2000}).encode()
                req = urllib.request.Request(NIM_PROXY, data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    j = json.loads(r.read())
                content = j["choices"][0]["message"].get("content") or ""
                sections = parse_sections(content)
                n = len(sections)
                heb = sections.get("[HEBREW]", "")
                nik = sections.get("[NIKKUD]", "")
                rus = sections.get("[Russian]", "")
                src = sections.get("[SOURCES]", "")

                has_hebrew = bool(heb) and any("\u05d0" <= c <= "\u05ea" for c in heb)
                has_nikkud = bool(nik) and any("\u0591" <= c <= "\u05c7" for c in nik)
                has_russian = bool(rus) and any("\u0400" <= c <= "\u04ff" for c in rus)
                has_sources = bool(src)

                hallucination = "?"
                if top6 and heb:
                    top_ep = episodes[top6[0][0]]
                    gs = (top_ep.get("god_speech_plain") or "").replace("\u05BE", "").replace(" ", "")
                    heb_clean = heb.replace("\u05BE", "").replace(" ", "")
                    if len(gs) > 5 and len(heb_clean) > 5:
                        heb_words = heb_clean.split()
                        overlap = sum(1 for w in heb_words if w in gs) / max(1, len(heb_words))
                        hallucination = f"{overlap:.0%}" + (" ✓" if overlap > 0.5 else " ⚠️")

                s = scores[model_name]
                s["total"] += 1
                if n >= 5: s["sections"] += 1
                if has_hebrew: s["hebrew"] += 1
                if has_nikkud: s["nikkud"] += 1
                if has_russian: s["russian"] += 1
                if has_sources: s["sources"] += 1
                if "✓" in hallucination: s["no_hallucination"] += 1

                print(f"  {model_name}: {n}/6 | ив:{'✓' if has_hebrew else '✗'} ник:{'✓' if has_nikkud else '✗'} рус:{'✓' if has_russian else '✗'} src:{'✓' if has_sources else '✗'} | галл:{hallucination}")
                print(f"    [HEB] {heb[:55]}{'…' if len(heb)>55 else ''}")
                print(f"    [SRC] {src[:45]}")
            except Exception as e:
                print(f"  {model_name}: ОШИБКА {repr(e)[:80]}")
            print()
        time.sleep(0.5)

    print("\n=== ИТОГ ===")
    print(f"{'Метрика':<22s} {'glm-5.3-flash':>16s} {'nemotron-550b':>16s} {'DictaLM(эталон)':>16s}")
    print("-" * 75)
    dicta_ref = {"sections": "6/8", "hebrew": "8/8", "nikkud": "8/8", "russian": "8/8", "sources": "8/8", "no_hallucination": "7/8"}
    for metric in ("sections", "hebrew", "nikkud", "russian", "sources", "no_hallucination"):
        line = f"{metric:<22s}"
        for name, _ in MODELS:
            sc = scores[name]
            pct = sc[metric] / max(1, sc["total"]) * 100
            line += f" {sc[metric]:>2d}/{sc['total']:>2d} ({pct:3.0f}%)"
        line += f"   {dicta_ref.get(metric, '—'):>12s}"
        print(line)
    print("\nЭталон DictaLM — из наших предыдущих тестов (строгий иврит, правильный никауд)")
    print("Verdict: NVIDIA модели должны показывать ≥ 80% от эталона DictaLM")


if __name__ == "__main__":
    main()
