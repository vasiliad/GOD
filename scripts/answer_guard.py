"""Сверка ответа мозга с корпусом — общий эталон правил для страницы и скриптов.

Правило «S» — «сквозная сверка»: ни один слой ответа не показывается, пока он
не подтверждён реестром; источник ответа — всегда из реестра, а не из цитаты
модели (она часто называет стих, в котором этого текста нет).

Ивритская реплика [HEBREW]:

  G (grounding, контекст): слова реплики должны быть составлены из фрагментов
    god_speech_plain, которые реально переданы модели (те же 300 символов,
    что уходят в контекст). Доля найденных слов — ctx_cov, порог 0.80.

  A (привязка к реестру, строгая): эпизод реестра, в чьей речи реплика идёт
    НЕПРЕРЫВНЫМ участком, покрывающим ≥ 50 % её слов, — это настоящая цитата.

  B (привязка к реестру, мягкая): эпизод, в чьей речи есть ≥ 80 % слов реплики
    (переработка/комбинация — так и просит системный промпт).

  Режимы:
    verified — ctx_cov ≥ 0.80: реплика собрана из переданных фрагментов.
               Источник: A → B → эпизоды контекста.
    corpus   — ctx_cov < 0.80, но нашлась строгая привязка A: реплика —
               настоящая цитата реестра, просто не из того окна, которое
               подобрал retrieval. Показываем её, источник — по реестру.
    reject   — подтверждения нет (пересказ, стих из памяти, чужая речь,
               другая нумерация стихов). Показываем проверенный прецедент
               корпуса — как в режиме «мозг спит».

Нормализация слов (одинаковая в JS и Python):
  * снимаем огласовку и кантилляцию (U+0591..U+05BD, U+05BF..U+05C7);
  * маккеф и дефис → пробел;
  * слова короче 2 букв не считаем;
  * для сравнения снимаем ведущий «ו» (в реестре «וענני», у модели часто
    «ענני» — одна лексема).

Русский слой [Russian]: слова сверяются со словарём summary_ru тех же
эпизодов-контекста; при низком покрытии показывается корпусная аннотация
эпизода-источника (то же, что делает старая проверка «иврит в русском»).

Правила на JS-странице (docs/index.html) — те же самые; совпадение
проверяется общим фикстурным тестом (scripts/guard_cases.json).

    python scripts/answer_guard.py --test           # самопроверка без сети
    python scripts/answer_guard.py --calibrate      # разбор записанных диалогов
"""
import io
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
PAGE = _ROOT / "docs" / "index.html"
MASTER = _ROOT / "output" / "episodes_TANAKH_v2.json"
DIALOGS = _ROOT / "docs" / "data" / "dialogs.json"
CASES = _ROOT / "scripts" / "guard_cases.json"

# Огласовка + кантилляция: U+0591..U+05BD и U+05BF..U+05C7 (маккеф U+05BE — нет).
NIQ = re.compile(r"[֑-ֽֿ-ׇ]")
# Всё, кроме ивритских букв, — разделитель слов.
NON_HEB = re.compile(r"[^א-ת]+")

GATE_CTX = 0.80        # доля слов реплики из переданных фрагментов
GATE_QUOTE = 0.50      # доля слов реплики в непрерывном участке речи эпизода
GATE_LOOSE = 0.80      # доля слов реплики в словаре речи эпизода
GATE_RUN = 3           # минимальная длина подряд идущего участка для строгой цитаты
GATE_RU = 0.60         # доля слов русского слоя в summary_ру контекста
GATE_NIKUD = 0.60      # доля слов реплики в огласованном слое [NIKKUD]
MIN_WORD = 2           # короче — служебные частицы, не считаем
CTX_CHARS = 300        # столько символов речи эпизода уходит в контекст


# ─────────────────────────────────────────────────────────────────────────────
# Иврит: слова и нормализация
# ─────────────────────────────────────────────────────────────────────────────
def heb_words(s):
    """Слова ивритского текста: без огласовки, маккеф/дефис → пробел, длина ≥ 2."""
    s = NIQ.sub("", str(s or ""))
    s = s.replace("־", " ").replace("-", " ")
    return [w for w in NON_HEB.split(s) if len(w) >= MIN_WORD]


def norm(w):
    """Форма слова для сравнения: без ведущего «ו» («וענני» == «ענני»)."""
    if len(w) > MIN_WORD and w.startswith("ו"):
        return w[1:]
    return w


def norm_set(words):
    return {norm(w) for w in words}


def coverage(words, vocab):
    """Доля слов реплики, найденных в словаре (0..1)."""
    if not words:
        return 0.0
    return sum(1 for w in words if norm(w) in vocab) / len(words)


def runs_cover(reply, speech):
    """Непрерывные совпадения реплики с речью эпизода.

    Возвращает (длина самого длинного участка, число покрытых слов реплики).
    Жадный проход: на каждой позиции реплики ищем самое длинное совпадение,
    покрытые позиции помечаем и идём дальше.
    """
    reply = [norm(w) for w in reply]
    speech = [norm(w) for w in speech]
    pos = {}
    for j, w in enumerate(speech):
        pos.setdefault(w, []).append(j)
    covered = set()
    longest = 0
    i = 0
    while i < len(reply):
        best = 0
        for j in pos.get(reply[i], []):
            k = 0
            while (i + k < len(reply) and j + k < len(speech)
                   and reply[i + k] == speech[j + k]):
                k += 1
            if k > best:
                best = k
        if best > 0:
            covered.update(range(i, i + best))
            longest = max(longest, best)
            i += best
        else:
            i += 1
    return longest, len(covered)


# ─────────────────────────────────────────────────────────────────────────────
# Русский: слова и нормализация
# ─────────────────────────────────────────────────────────────────────────────
RU_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")


def ru_words(s):
    return [w.lower() for w in RU_WORD.findall(str(s or ""))]


def ru_coverage(reply, texts):
    """Доля слов русского слоя, найденных в аннотациях summary_ру контекста."""
    vocab = set()
    for t in texts:
        vocab.update(ru_words(t))
    if not vocab or not reply:
        return 0.0
    return sum(1 for w in reply if w in vocab) / len(reply)


# ─────────────────────────────────────────────────────────────────────────────
# Привязка к реестру
# ─────────────────────────────────────────────────────────────────────────────
def ctx_coverage(reply, fragments):
    """Доля слов реплики, найденных в переданных модели фрагментах речи."""
    vocab = set()
    for f in fragments:
        vocab.update(norm(w) for w in heb_words(str(f or "")[:CTX_CHARS]))
    return coverage(reply, vocab)


def attribute_quote(reply, episodes):
    """Строгая привязка: эпизод, где реплика идёт непрерывным участком.

    Условия: покрыто ≥ GATE_QUOTE слов реплики И подряд идёт ≥ GATE_RUN слов
    (для реплики из 1–2 слов достаточно полного совпадения). Без требования
    подряд идущего участка смесь двух стихов («ענני … ביום צרה …» из Пс 27:7 и
    Пс 50:15) привязывалась к одному стиху, которого не покрывает целиком.

    episodes: список (book, episode). Возвращает [(book, episode), ...].
    """
    if not reply:
        return []
    min_run = GATE_RUN if len(reply) >= GATE_RUN else len(reply)
    found = []
    for book, e in episodes:
        speech = heb_words(e.get("god_speech_plain") or "")
        if not speech:
            continue
        longest, covered = runs_cover(reply, speech)
        if covered / len(reply) >= GATE_QUOTE and longest >= min_run:
            found.append((covered / len(reply), longest, book, e))
    if not found:
        return []
    found.sort(key=lambda x: (-x[0], -x[1]))
    return [(b, e) for _, _, b, e in found]


def attribute_loose(reply, episodes):
    """Мягкая привязка: эпизод, где есть ≥ 80 % слов реплики."""
    if not reply:
        return []
    found = []
    for book, e in episodes:
        speech = heb_words(e.get("god_speech_plain") or "")
        if not speech:
            continue
        frac = coverage(reply, norm_set(speech))
        if frac >= GATE_LOOSE:
            found.append((frac, book, e))
    if not found:
        return []
    found.sort(key=lambda x: -x[0])
    return [(b, e) for _, b, e in found]


def verify(reply_hebrew, fragments, corpus, hits=None):
    """Полная сверка ивритского слоя.

    fragments: речь эпизодов, переданных модели (строки god_speech_plain).
    corpus:    [(book, episode)] — реестр в порядке корпуса.
    hits:      [(book, episode)] — эпизоды контекста (для мягкой привязки).

    Возвращает:
      mode    — "verified" | "corpus" | "reject"
      ctx_cov — доля слов из переданных фрагментов
      sources — [(book, episode)] — откуда реплика на самом деле
    """
    reply = heb_words(reply_hebrew)
    cc = ctx_coverage(reply, fragments)
    if cc >= GATE_CTX:
        src = attribute_quote(reply, corpus)
        if not src:
            src = attribute_loose(reply, corpus)
        if not src:
            src = attribute_loose(reply, hits or [])
        return {"mode": "verified", "ctx_cov": cc, "sources": src}
    src = attribute_quote(reply, corpus)
    if src:
        return {"mode": "corpus", "ctx_cov": cc, "sources": src}
    return {"mode": "reject", "ctx_cov": cc, "sources": []}


# ─────────────────────────────────────────────────────────────────────────────
# Полный проход по шести слоям ответа: что показываем пользователю
# ─────────────────────────────────────────────────────────────────────────────
SECTIONS = ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]
HEB_LETTER = re.compile(r"[א-ת]")


def strip_nikud(s):
    """Слой без огласовки и кантилляции (маккеф остаётся) — как на странице."""
    return NIQ.sub("", str(s or ""))


def has_hebrew(s):
    return bool(HEB_LETTER.search(str(s or "")))


def _registry_episode(book, episode, corpus):
    """Полный эпизод реестра по (book, span.start).

    Контекст на странице и в записях — урезанные копии (300/200 символов) без
    god_speech_refs; для прецедента нужен оригинал.
    """
    if episode.get("god_speech_refs") is not None:
        return episode
    start = (episode.get("span") or {}).get("start")
    for b, e in (corpus or []):
        if b == book and (e.get("span") or {}).get("start") == start:
            return e
    return episode


def apply_guard(sections, ctx, corpus, nikud_for=None):
    """Правило «S» целиком: что показываем, откуда источник, что не подтверждено.

    ctx:      контекстные эпизоды (dict с book/span/god_speech_plain/summary_ru) —
              ровно те, что ушли модели.
    corpus:   [(book, episode)] — реестр.
    nikud_for: callable(book, refs) -> str; нужен для огласовки и прецедента.

    Возвращает {"sections": {...}, "sources": [...], "guard": {...}}:
      sections — что показываем (в отказе — проверенный прецедент корпуса);
      sources  — источники ИЗ РЕЕСТРА (не цитата модели);
      guard    — {"mode": verified|corpus|reject, "ctx_cov": float}.
    """
    s = {tag: str((sections or {}).get(tag) or "").strip() for tag in SECTIONS}
    ctx_pairs = [(c["book"], c) for c in (ctx or [])]
    # Окно сверки — всё, что реально ушло модели: и консонантная речь, и
    # огласовка. Раньше сверяли только god_speech_plain, и модель получала
    # «отказ» за цитату, взятую из поля nikud того же эпизода.
    frags = []
    for c in (ctx or []):
        frags.append(str(c.get("god_speech_plain") or "")[:CTX_CHARS])
        frags.append(str(c.get("nikud") or "")[:CTX_CHARS])
    v = verify(s["[HEBREW]"], frags, corpus, ctx_pairs)
    mode, cc, srcs = v["mode"], v["ctx_cov"], v["sources"]
    shown = dict(s)

    if mode == "reject":
        # неподтверждённая реплика не показывается — вместо неё прецедент корпуса
        top = ctx_pairs[0] if ctx_pairs else None
        if top:
            book, e = top
            full = _registry_episode(book, e, corpus)
            shown["[HEBREW]"] = str(full.get("god_speech_plain") or "")[:600]
            shown["[NIKKUD]"] = (nikud_for(book, full.get("god_speech_refs")) if nikud_for else "")
            shown["[Russian]"] = str(full.get("summary_ru") or "")
        shown["[English]"] = ""
        shown["[Hebrew Modern]"] = ""
        shown["[SOURCES]"] = ""
        out = [{"book": top[0], "start": top[1]["span"]["start"], "end": top[1]["span"]["end"]}] if top else []
        return {"sections": shown, "sources": out,
                "guard": {"mode": "reject", "ctx_cov": round(cc, 3), "sources": out}}

    # огласовка: слой [NIKKUD] должен ПРОГОВАРИВАТЬ ту же реплику (подряд, в том
    # же порядке). Проверка «есть ли слова» не годилась: модель могла дать
    # огласовку другого куска стиха — рядом с репликой это читалось как сбой.
    if s["[NIKKUD]"]:
        rw = heb_words(s["[HEBREW]"])
        sw = heb_words(s["[NIKKUD]"])
        longest, covered = runs_cover(rw, sw)
        frac = (covered / len(rw)) if rw else 0.0
        min_run = GATE_RUN if len(rw) >= GATE_RUN else len(rw)
        if frac < GATE_NIKUD or longest < min_run:
            corpus_nik = ""
            if srcs and nikud_for:
                corpus_nik = nikud_for(srcs[0][0], srcs[0][1].get("god_speech_refs")) or ""
            shown["[NIKKUD]"] = corpus_nik
    # русский слой: слова сверяются с аннотациями эпизодов-контекста
    if s["[Russian]"]:
        texts = [str(c.get("summary_ru") or "") for c in (ctx or [])]
        if has_hebrew(s["[Russian]"]) or ru_coverage(s["[Russian]"], texts) < GATE_RU:
            ann = srcs[0][1] if srcs else (ctx_pairs[0][1] if ctx_pairs else None)
            shown["[Russian]"] = str(ann.get("summary_ru") or "") if ann else ""
    out = [{"book": b, "start": e["span"]["start"], "end": e["span"]["end"]} for b, e in srcs]
    if not out and ctx_pairs:
        out = [{"book": b, "start": e["span"]["start"], "end": e["span"]["end"]}
               for b, e in ctx_pairs[:3]]
    return {"sections": shown, "sources": out,
            "guard": {"mode": mode, "ctx_cov": round(cc, 3), "sources": out}}


# ─────────────────────────────────────────────────────────────────────────────
# Текст системного промпта — из страницы (символ в символ)
# ─────────────────────────────────────────────────────────────────────────────
def _page_const(name):
    """Достаёт константу-доку из docs/index.html: страница — единственный источник."""
    html = io.open(PAGE, encoding="utf-8").read()
    m = re.search(r'const %s = ((?:"(?:[^"\\]|\\.)*"\s*\+?\s*)+);' % name, html)
    if not m:
        raise RuntimeError("%s не найден в docs/index.html" % name)
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    out = []
    for p in parts:
        try:
            out.append(p.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8"))
        except (UnicodeDecodeError, UnicodeEncodeError):
            out.append(p)
    return "".join(out)


def page_sys_prompt():
    """Достаёт SYS_PROMPT из docs/index.html: страница — единственный источник."""
    return _page_const("SYS_PROMPT")


def page_sys_select():
    """Достаёт SYS_SELECT из docs/index.html: промпт шага выбора эпизода."""
    return _page_const("SYS_SELECT")


# ─────────────────────────────────────────────────────────────────────────────
# Корпус
# ─────────────────────────────────────────────────────────────────────────────
def load_corpus():
    """Реестр эпизодов в порядке корпуса: список (book, episode)."""
    master = json.load(io.open(MASTER, encoding="utf-8"))
    out = []
    for book, arr in master.items():
        for e in arr:
            out.append((book, e))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Самопроверка: общие фикстуры — те же, что проверяет brain/test_page.js
# ─────────────────────────────────────────────────────────────────────────────
def run_test():
    checks = []

    def chk(name, cond):
        checks.append(bool(cond))
        print(("PASS" if cond else "FAIL") + "  " + name)

    cases = json.load(io.open(CASES, encoding="utf-8"))["cases"]
    for c in cases:
        reply = heb_words(c["hebrew"])
        cc = ctx_coverage(reply, c["fragments"])
        want = c["ctx_cov"]
        chk("фикстура «%s»: ctx_cov=%.3f (ожидалось %.3f)" % (c["name"], cc, want),
            abs(cc - want) < 0.005)
        corpus = [(e["book"], e) for e in c["corpus"]]
        hits = [(e["book"], e) for e in c.get("hits", [])]
        v = verify(c["hebrew"], c["fragments"], corpus, hits)
        chk("фикстура «%s»: mode=%s (ожидалось %s)" % (c["name"], v["mode"], c["mode"]),
            v["mode"] == c["mode"])
        got = ("%s|%s" % (v["sources"][0][0], v["sources"][0][1]["span"]["start"])) if v["sources"] else None
        chk("фикстура «%s»: источник %s (ожидалось %s)" % (c["name"], got, c.get("source")),
            got == c.get("source"))

    # границы правил
    chk("слова короче 2 символов не считаются", heb_words("א ו ל") == [])
    chk("огласовка не мешает сверке", heb_words("שְׁמַעְתֶּֽם") == heb_words("שמעתם"))
    chk("маккеф разделяет слова", heb_words("אל־משה") == ["אל", "משה"])
    chk("ведущий «ו» не мешает сверке", norm("וענני") == "ענני" and norm("וענני") == norm("ענני"))
    chk("пустая реплика не проходит", verify("", ["שמע"], [])["mode"] == "reject")
    chk("точная цитата проходит", verify("שמע יהוה", ["שמע יהוה קולי"], [])["mode"] == "verified")
    chk("пересказ не проходит", verify("אני אלהים רב רע", ["ויאמר יהוה אל משה"], [])["mode"] == "reject")

    try:
        sp = page_sys_prompt()
        chk("SYS_PROMPT достаётся со страницы", "ТОЛЬКО из указанного эпизода" in sp)
        chk("в SYS_PROMPT шесть секций", all(t in sp for t in SECTIONS))
    except Exception as e:
        chk("SYS_PROMPT достаётся со страницы (%s)" % e, False)
    try:
        ss = page_sys_select()
        chk("SYS_SELECT достаётся со страницы", "выбрать ОДИН эпизод" in ss)
        chk("SYS_SELECT и SYS_PROMPT разные", ss != sp)
    except Exception as e:
        chk("SYS_SELECT достаётся со страницы (%s)" % e, False)

    # apply_guard: огласовка должна проговаривать ту же реплику
    ctx_ep = [{"book": "Psalms", "span": {"start": "27:7", "end": "27:7"},
               "god_speech_plain": "שמע יהוה קולי וענני", "nikud": "שְׁמַע יְהֹוָה קוֹלִי",
               "summary_ru": "Бог взывает: услышь меня"}]
    corpus_ep = [("Psalms", {"book": "Psalms", "span": {"start": "27:7", "end": "27:7"},
                             "god_speech_plain": "שמע יהוה קולי וענני",
                             "god_speech_refs": ["27:7"], "summary_ru": "Бог взывает: услышь меня"})]
    nik_stub = lambda b, refs: "אַיֵּה"
    g_ok = apply_guard({"[HEBREW]": "שמע יהוה קולי", "[NIKKUD]": "שְׁמַע יְהֹוָה קוֹלִי"}, ctx_ep, corpus_ep, nik_stub)
    chk("apply_guard: огласовка той же реплики остаётся", g_ok["sections"]["[NIKKUD]"] == "שְׁמַע יְהֹוָה קוֹלִי")
    g_bad = apply_guard({"[HEBREW]": "שמע יהוה קולי", "[NIKKUD]": "כֹּה אָמַר יְהֹוָה"}, ctx_ep, corpus_ep, nik_stub)
    chk("apply_guard: огласовка другого кусока заменяется корпусной", g_bad["sections"]["[NIKKUD]"] == "אַיֵּה")

    passed = sum(1 for c in checks if c)
    print("\nSELFTEST: %s (%d/%d)" % ("PASS" if passed == len(checks) else "FAIL", passed, len(checks)))
    return 0 if passed == len(checks) else 1


def calibrate():
    """Разбор записанных диалогов: сколько реплик проходят сверку."""
    corpus = load_corpus()
    dlg = json.load(io.open(DIALOGS, encoding="utf-8"))
    modes = {"verified": 0, "corpus": 0, "reject": 0}
    print("%-3s %-22s %7s %-9s %s" % ("id", "источник модели", "ctx_cov", "режим", "источник по реестру"))
    for d in dlg["dialogues"]:
        s = d["sections"]
        srcs = d.get("sources") or []
        frags = []
        for q in srcs:
            for book, e in corpus:
                if book == q["book"] and e["span"]["start"] == q["start"]:
                    frags.append(e.get("god_speech_plain") or "")
        v = verify(s.get("[HEBREW]", ""), frags, corpus)
        modes[v["mode"]] = modes.get(v["mode"], 0) + 1
        got = ("%s %s" % (v["sources"][0][0], v["sources"][0][1]["span"]["start"])) if v["sources"] else "—"
        print("%-3s %-22s %7.2f %-9s %s" %
              (d["id"], ("%s %s" % (srcs[0]["book"], srcs[0]["start"])) if srcs else "—",
               v["ctx_cov"], v["mode"], got))
    print("\nитого: verified=%d corpus=%d reject=%d (всего %d)" %
          (modes["verified"], modes["corpus"], modes["reject"], len(dlg["dialogues"])))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--test" in argv or "--selftest" in argv:
        return run_test()
    if "--calibrate" in argv:
        return calibrate()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
