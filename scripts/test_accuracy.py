"""Проверка точности мозга: серия вопросов → сверка каждого ответа с корпусом.

Тест на галлюцинацию: DictaLM получает эпизоды через retrieval и должен
рекомбинировать ТОЛЬКО реальные цитаты. Для каждого ответа проверяем:
  1. Все ли 6 секций заполнены?
  2. Существует ли цитируемый эпизод в реестре?
  3. Совпадает ли [HEBREW] с god_speech_plain этого эпизода?
  4. Соответствует ли [SOURCES] реальному спану?

Прогон идёт по ТОЙ ЖЕ схеме, что живой чат страницы (scripts/answer_scheme.py —
зеркало docs/index.html):
    ШАГ 1 — выбор одного эпизода (короткий вызов, ответ = номер);
    ШАГ 2 — формулировка из этого эпизода;
    ШАГ 3 — сверка с реестром, окно сверки = выбранный эпизод.
Кандидаты отбираются той же формулой, что на странице (лексика + вектор e5-small).

Запуск:
    python scripts/test_accuracy.py                  # живой прогон (сеть + мозг)
    python scripts/test_accuracy.py --test           # офлайн-самопроверка, без сети
    python scripts/test_accuracy.py --threshold 0.8  # свой порог для PASS

Живой прогон берёт url/key мозга из brain.json в HF-датасете arabyan/god-brain-status —
того же источника, что читает страница (docs/index.html). Локальный brain/brain_snapshot.json
используется ТОЛЬКО если сеть недоступна: его туннель обычно мёртв, и тест честно падает.

Оценка гейта — доля ответов, выполнивших контракт целиком (6 секций + источник в корпусе).
Ниже порога — ненулевой exit code: «мозг спит» это провал гейта, а не успех.
"""
import argparse, io, json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_REPO = str(_ROOT)
BRAIN_STATUS_URL = "https://huggingface.co/datasets/arabyan/god-brain-status/resolve/main/brain.json"
BRAIN_SNAPSHOT = _ROOT / "brain" / "brain_snapshot.json"
NIKUD_INDEX = _ROOT / "docs" / "data" / "nikud.json"
DEFAULT_THRESHOLD = 0.6

# Правило «S» (сверка ответа с реестром) и текст промпта — из общего эталона
# scripts/answer_guard.py: страница остаётся единственным источником промпта.
# Схема ответа и отбор кандидатов — scripts/answer_scheme.py (зеркало страницы).
sys.path.insert(0, str(_ROOT / "scripts"))
from answer_guard import apply_guard, page_sys_prompt   # noqa: E402
from answer_scheme import (                               # noqa: E402
    build_context, classify, load_corpus, load_nikud, rank_episodes, two_stage,
)

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

# SYS_PROMPT — прямо из docs/index.html (страница — единственный источник).
# Раньше здесь была копия, которая разошлась со страницей (лишняя строка про
# огласовку, «1–2 строк» вместо «1–2 строки»): гейт мерил не тот текст, по
# которому отвечает живой чат. Теперь копий нет — промпт берётся из страницы.
SYS_PROMPT = page_sys_prompt()


def fetch_status(timeout=20):
    """Живой статус мозга: локальный сервер (GOD_BRAIN_URL) → HF brain.json → снимок.

    url и key берутся из ОДНОГО источника, иначе можно получить ключ от одного туннеля
    и адрес от другого — мозг ответит 401 и тест врёт.
    """
    local_url = os.environ.get("GOD_BRAIN_URL", "").strip()
    if local_url:
        return {"_source": "локальный мозг (GOD_BRAIN_URL)", "ok": True, "url": local_url,
                "key": os.environ.get("GOD_BRAIN_KEY", "godbrain-v1-vasiliad"),
                "model": os.environ.get("GOD_BRAIN_MODEL", ""), "ts": int(time.time())}
    try:
        req = urllib.request.Request(BRAIN_STATUS_URL, headers={"User-Agent": "god2-test-accuracy"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("brain.json — не объект")
        data["_source"] = "HF brain.json"
        return data
    except Exception as e:
        print(f"⚠️ brain.json с HF недоступен ({type(e).__name__}: {e}) — беру запасной локальный снимок")
        try:
            snap = json.load(io.open(BRAIN_SNAPSHOT, encoding="utf-8"))
        except Exception as e2:
            print(f"⚠️ запасной снимок {BRAIN_SNAPSHOT} тоже недоступен ({type(e2).__name__}: {e2})")
            return {"_source": "ни HF brain.json, ни локальный снимок", "url": "", "key": ""}
        snap["_source"] = "локальный brain/brain_snapshot.json (запасной путь, туннель может быть мёртв)"
        return snap


def ask_brain(q, ctx_json, trig, probs, url, key):
    """Один вызов мозга с SYS_PROMPT страницы — как шаг формулировки.

    Живой прогон идёт через two_stage() (выбор эпизода → формулировка); эта
    функция остаётся для офлайн-самопроверки, где сеть подменена моком.
    """
    from answer_scheme import ask_brain as _ask, FORM_TEMP, FORM_MAX_TOKENS
    user = f"РЕЛЕВАНТНЫЕ ЭПИЗОДЫ РЕЕСТРА:\n{ctx_json}\n\nТриггер реплики: {trig}. Ожидаемые исходы: {json.dumps(probs)}\n\nРеплика человека: {q}\n\nНапоминание: ответ обязан кончаться секцией [SOURCES] со стихами-источниками."
    return _ask(SYS_PROMPT, user, url.rstrip("/") + "/v1/chat/completions", key,
                timeout=300, temperature=FORM_TEMP, max_tokens=FORM_MAX_TOKENS)


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


def nikud_for(book, refs, index):
    """Порт nikudFor() из docs/index.html — огласовка из корпуса (регистр, 3 стиха)."""
    bk = book[:1].upper() + book[1:]
    out = []
    for r in (refs or [])[:3]:
        m = re.match(r"^(\d+):(\d+)$", r or "")
        if not m:
            continue
        t = index.get(bk + "|" + m[1] + "|" + m[2])
        if t:
            out.append(t)
    return "  ".join(out)


def find_source(sources, episodes):
    """Есть ли в [SOURCES] книга корпуса (та же эвристика, что в живом прогоне)."""
    for k, ep in episodes.items():
        bn = ep["book"]
        if bn.lower() in sources.lower() or (bn[0].upper() + bn[1:]) in sources:
            return "ДА", bn
    return "НЕ НАЙДЕН", ""


def speech_overlap(hebrew, top_ep):
    """Доля слов [HEBREW], найденных в god_speech_plain топ-1 эпизода."""
    if not hebrew or top_ep is None:
        return "—"
    gs = (top_ep.get("god_speech_plain") or "").replace("\u05BE", "").replace(" ", "")
    heb = hebrew.replace("\u05BE", "").replace(" ", "")
    if len(gs) > 5 and len(heb) > 5:
        overlap = sum(1 for w in heb.split() if w in gs) / max(1, len(heb.split()))
        return f"{overlap:.0%}"
    return "—"


def summarize(results):
    """Счётчики по ответам.

    Полным считаем ответ, который выполнил контракт целиком: все 6 секций,
    реплика подтверждена реестром (правило «S») и источник взят ИЗ реестра.
    """
    n = len(results)
    sections = sum(1 for r in results if r["sections"] == 6)
    grounded = sum(1 for r in results if r["grounded"])
    sources = sum(1 for r in results if r["sources"])
    perfect = sum(1 for r in results if r["sections"] == 6 and r["grounded"] and r["sources"])
    return {"n": n, "sections": sections, "grounded": grounded, "sources": sources,
            "perfect": perfect, "score": (perfect / n) if n else 0.0}


def format_verdict(summary, threshold):
    passed = summary["score"] >= threshold
    line = (f"ИТОГ: {summary['sections']}/{summary['n']} секций, "
            f"{summary['grounded']}/{summary['n']} сверено с реестром, "
            f"{summary['sources']}/{summary['n']} источников из реестра, "
            f"{summary['perfect']}/{summary['n']} полных — {'PASS' if passed else 'FAIL'} "
            f"(оценка {summary['score']*100:.1f}% {'≥' if passed else '<'} порог {threshold*100:.1f}%)")
    return line, passed


def finalize(results, threshold):
    """Печатает сводку и вердикт; возвращает exit code (0 — PASS, 1 — FAIL)."""
    s = summarize(results)
    print("=== СВОДКА ===")
    print(f"Все 6 секций: {s['sections']}/{s['n']}")
    print(f"Сверено с реестром: {s['grounded']}/{s['n']}")
    print(f"Источник из реестра: {s['sources']}/{s['n']}")
    print(f"Идеальные ответы (6 секций + сверка + источник): {s['perfect']}/{s['n']}")
    for r in results:
        print(f"  {'OK' if r['sections'] == 6 and r['grounded'] and r['sources'] else '!!'} "
              f"{r['q'][:35]:37s} {r['sections']}/6 секций | сверка: {r.get('mode', '—')} "
              f"({r.get('ctx_cov', 0)*100:.0f}%)")
    line, passed = format_verdict(s, threshold)
    print(line)
    return 0 if passed else 1


def run_live(threshold, url_override=None, key_override=None):
    if url_override:
        status = {"_source": "локальный мозг (--url)", "url": url_override,
                  "key": key_override or "", "model": "god-brain"}
    else:
        status = fetch_status()
    url = (status.get("url") or "").rstrip("/")
    key = status.get("key") or ""
    print(f"Мозг: {status.get('_source')} | url={url or '(нет)'} | model={status.get('model', '')}")
    ts = status.get("ts")
    if isinstance(ts, (int, float)):
        age_min = (time.time() - ts) / 60
        print(f"Пульс brain.json: {age_min:.0f} мин назад" + (" — УСТАРЕЛ" if age_min > 60 else ""))
    if not url:
        print("Мозг недоступен: в brain.json нет url — спросить некого.")
        print(format_verdict({"n": len(QUESTIONS), "sections": 0, "sources": 0,
                               "perfect": 0, "score": 0.0}, threshold)[0])
        return 1

    episodes = load_corpus()
    corpus_pairs = [(e["book"], e) for e in episodes.values()]   # реестр для сверки
    nikud_index = load_nikud()
    endpoint = url.rstrip("/") + "/v1/chat/completions"
    model = status.get("model") or "god-brain"

    print("Проверка точности мозга: 10 вопросов через схему "
          "выбор эпизода → формулировка → сверка с корпусом\n")
    results = []

    for qi, q in enumerate(QUESTIONS):
        trig = classify(q)
        # отбор кандидатов — та же формула, что на странице (лексика + вектор)
        # пул 18 → фильтр «только с речью Бога» → 6 кандидатов (как на странице)
        hits = rank_episodes(q, trig, episodes, 18, hybrid=True)
        ctx = build_context(episodes, nikud_index, hits)
        print(f"[{qi+1}/10] «{q}»  (триггер: {trig})")
        try:
            st = two_stage(q, ctx, endpoint, key, timeout=300, model=model)
            sections = parse_sections(st["raw"])
            chosen = st["chosen"]
            n_sections = len(sections)
            hebrew = sections.get("[HEBREW]", "")
            sources = sections.get("[SOURCES]", "")
            russian = sections.get("[Russian]", "")
            print(f"  выбор эпизода: S{st['index']} [{chosen['book']} {chosen['span']['start']}] — "
                  f"{(chosen.get('summary_ru') or '')[:48]}")

            # правило «S»: сверяем реплику с реестром и берём источник ИЗ реестра.
            # Окно сверки — ВЫБРАННЫЙ эпизод (ровно он ушёл модели).
            g = apply_guard(sections, [chosen], corpus_pairs,
                            nikud_for=lambda b, refs: nikud_for(b, refs, nikud_index))
            guard = g["guard"]
            grounded = guard["mode"] != "reject"
            src_ok = bool(g["sources"])
            ok = (n_sections == 6 and grounded and src_ok)
            results.append({"q": q, "sections": n_sections, "grounded": grounded,
                            "sources": src_ok, "mode": guard["mode"],
                            "ctx_cov": guard["ctx_cov"], "ok": ok})
            print(f"  секций: {n_sections}/6 | сверка: {guard['mode']} "
                  f"({guard['ctx_cov']*100:.0f}% слов из контекста) | источник из реестра: {'ДА' if src_ok else 'НЕТ'}")
            print(f"  [HEBREW] {hebrew[:60]}…")
            print(f"  [SOURCES] модели: {sources[:50]} → по реестру: "
                  f"{', '.join('%s %s' % (s['book'], s['start']) for s in g['sources'][:3]) or '—'}")
            print(f"  [RU] {russian[:60]}…")
        except Exception as e:
            results.append({"q": q, "sections": 0, "grounded": False, "sources": False,
                            "mode": "ошибка", "ctx_cov": 0.0, "ok": False})
            print(f"  ОШИБКА: {e}")
        print()
        time.sleep(1)

    return finalize(results, threshold)


# ============================================================
# ОФЛАЙН-САМОПРОВЕРКА: сетевой слой подменён, чтобы гейт проверял себя без сети
# ============================================================
FAKE_URL = "https://mock-brain.trycloudflare.com"
FAKE_KEY = "mock-key"
FAKE_STATUS = {"ok": True, "url": FAKE_URL, "key": FAKE_KEY, "model": "mock-model", "ts": 0}
FAKE_ANSWER = ("[HEBREW] איכה\n[NIKKUD] אַיֵּה\n[Russian] Где ты?\n"
               "[English] Where art thou?\n[Hebrew Modern] איפה אתה\n[SOURCES] Genesis 3:9")


class _FakeResp:
    """Минимальный ответ urlopen: сетевой слой подменён, тело — обычный JSON."""
    def __init__(self, payload):
        self._data = payload.encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    url = getattr(req, "full_url", req)
    if BRAIN_STATUS_URL in url:
        return _FakeResp(json.dumps(FAKE_STATUS))
    if "/v1/chat/completions" in url:
        return _FakeResp(json.dumps({"choices": [{"message": {"content": FAKE_ANSWER}}]}))
    raise urllib.error.URLError("selftest: неожиданный запрос " + str(url))


def _dead_urlopen(req, timeout=None):
    raise urllib.error.URLError("selftest: сеть недоступна")


def run_selftest():
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name)

    print("=== selftest: офлайн-проверка гейта точности (сеть подменена) ===")

    saved = urllib.request.urlopen
    try:
        urllib.request.urlopen = _fake_urlopen
        st = fetch_status()
        chk("статус мозга берётся из brain.json (mock HF)", st.get("url") == FAKE_URL and st.get("key") == FAKE_KEY)
        raw = ask_brain("как тебя зовут?", "[]", "inquiry", {"n": 5}, st["url"], st["key"])
        chk("ask_brain возвращает ответ мока без сети", raw == FAKE_ANSWER)
    finally:
        urllib.request.urlopen = saved

    try:
        urllib.request.urlopen = _dead_urlopen
        st2 = fetch_status()
    finally:
        urllib.request.urlopen = saved
    chk("при недоступной сети включается запасной локальный снимок", "brain_snapshot" in st2.get("_source", ""))

    secs = parse_sections(FAKE_ANSWER)
    chk("парсер находит все 6 секций", len(secs) == 6)
    chk("[HEBREW] разобран верно", secs.get("[HEBREW]") == "איכה")

    episodes = {"Genesis|3:9": {"book": "Genesis", "god_speech_plain": "ויאמר יהוה אליו"}}
    chk("источник из [SOURCES] найден в корпусе", find_source(secs.get("[SOURCES]", ""), episodes)[0] == "ДА")
    chk("выдуманный источник честно помечается", find_source("[SOURCES] Никто", episodes)[0] == "НЕ НАЙДЕН")
    chk("совпадение речи считается по god_speech_plain", speech_overlap("ויאמר יהוה", episodes["Genesis|3:9"]) == "100%")

    good = {"q": "как тебя зовут?", "sections": 6, "grounded": True, "sources": True,
            "mode": "verified", "ctx_cov": 0.93, "ok": True}
    bad = {"q": "я боюсь умереть", "sections": 0, "grounded": False, "sources": False,
           "mode": "ошибка", "ctx_cov": 0.0, "ok": False}
    ungrounded = {"q": "почему ты допустил зло?", "sections": 6, "grounded": False, "sources": False,
                  "mode": "reject", "ctx_cov": 0.17, "ok": False}
    s = summarize([good, bad])
    chk("сводка считает секции и источники", s["sections"] == 1 and s["sources"] == 1)
    chk("сводка считает сверенные с реестром ответы", s["grounded"] == 1)
    chk("сводка считает полные ответы", s["perfect"] == 1 and abs(s["score"] - 0.5) < 1e-9)
    chk("все ошибки (мозг недоступен) дают score 0", summarize([bad, bad])["score"] == 0.0)
    chk("неподтверждённая реплика не попадает в полные", summarize([good, ungrounded])["perfect"] == 1
        and summarize([good, ungrounded])["score"] == 0.5)

    # правило «S» внутри гейта: та же сверка, что на странице
    ctx = [{"book": "Genesis", "span": {"start": "3:9", "end": "3:15"},
            "god_speech_plain": "איכה", "summary_ru": "Бог призывает к ответу"}]
    corpus = [("Genesis", {"book": "Genesis", "span": {"start": "3:9", "end": "3:15"},
                            "god_speech_plain": "איכה", "summary_ru": "Бог призывает к ответу"})]
    g_ok = apply_guard({"[HEBREW]": "איכה"}, ctx, corpus)
    chk("сверка: реплика из фрагмента подтверждена", g_ok["guard"]["mode"] == "verified")
    chk("сверка: источник взят из реестра", bool(g_ok["sources"])
        and g_ok["sources"][0]["start"] == "3:9")
    g_bad = apply_guard({"[HEBREW]": "ענני יהוה ביום צרה קראני ואענה"}, ctx, corpus)
    chk("сверка: стих из памяти отклонён", g_bad["guard"]["mode"] == "reject")
    chk("сверка: при отказе показан прецедент корпуса",
        g_bad["sections"]["[HEBREW]"] == "איכה" and g_bad["sections"]["[English]"] == "")

    print("\n--- проверка порога: score 50% при пороге 60% ---")
    code_fail = finalize([good, bad], 0.6)
    chk("гейт возвращает ненулевой код при score ниже порога", code_fail == 1)

    print("\n--- проверка порога: score 100% при пороге 60% ---")
    code_pass = finalize([good, good], 0.6)
    chk("гейт возвращает 0 при score не ниже порога", code_pass == 0)

    passed = sum(1 for c in checks if c)
    print(f"\nSELFTEST: {'PASS' if passed == len(checks) else 'FAIL'} ({passed}/{len(checks)})")
    return 0 if passed == len(checks) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Проверка точности мозга: 10 вопросов → сверка с корпусом; честный exit code.")
    ap.add_argument("--test", "--selftest", dest="selftest", action="store_true",
                    help="офлайн-самопроверка гейта: сеть подменена, ничего не скачивается")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"минимальная доля полных ответов для PASS (0..1, по умолчанию {DEFAULT_THRESHOLD})")
    ap.add_argument("--url", default=None,
                    help="эндпойнт мозга (по умолчанию — из HF brain.json; локальный: http://127.0.0.1:18099)")
    ap.add_argument("--key", default=None, help="ключ мозга (для --url)")
    args = ap.parse_args(argv)
    if not 0.0 <= args.threshold <= 1.0:
        ap.error("--threshold должен быть в диапазоне 0..1")
    if args.selftest:
        return run_selftest()
    return run_live(args.threshold, url_override=args.url, key_override=args.key)


if __name__ == "__main__":
    sys.exit(main())
