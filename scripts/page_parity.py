#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПАРИТЕТ страницы и зеркала: страница (docs/index.html) — источник истины.

Страница и скрипты-гейты делят одну и ту же логику отбора: классы обращения
(TRIGGERS), синонимы (RU_SYN), мосты языков (EN_BRIDGE, HE_BRIDGE), маппинг
классов на классы реестра (TRIG_CLASS), вес вектора (VEC_W) и пороги сверки
(GATE_*). До этого кода копии жили отдельно и однажды разошлись с живой
страницей — гейты считали одно, пользователь видел другое.

Этот скрипт читает константы прямо из docs/index.html и сверяет их с зеркалом
(scripts/answer_scheme.py, scripts/answer_guard.py). Любое расхождение — ненулевой
exit code, то есть CI падает.

    python scripts/page_parity.py            # гейт (exit code)
    python scripts/page_parity.py --test     # то же + печать всех сверок
"""
import io
import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

PAGE = _ROOT / "docs" / "index.html"
import answer_guard   # noqa: E402
import answer_scheme  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Чтение JS-констант со страницы
# ─────────────────────────────────────────────────────────────────────────────
def page_text():
    return io.open(PAGE, encoding="utf-8").read()


def js_literal(name):
    """Текст литерала JS по имени: `const NAME = <литерал>;` → строка литерала.

    Скан идёт по вложенным скобкам/кавычкам, поэтому многострочные массивы
    (TRIGGERS, RU_SYN) читаются целиком, а не по первой строке.
    """
    src = page_text()
    m = re.search(r"\b(?:const|let|var)\s+%s\s*=\s*" % re.escape(name), src)
    if not m:
        raise KeyError("на странице нет константы %s" % name)
    i = m.end()
    depth = 0
    quote = None
    while i < len(src):
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return src[m.end():i + 1]
        elif c == ";" and depth == 0:
            return src[m.end():i]
        i += 1
    raise ValueError("литерал %s не закрыт" % name)


def js_value(name):
    """JS-литерал → значение Python (массивы/объекты со строковыми ключами)."""
    txt = js_literal(name)
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)      # блочные комментарии
    txt = re.sub(r"//[^\n]*", "", txt)                    # строковые комментарии
    # некавыченные ключи объектов (в т.ч. ивритские): { מה:"что" } → JSON
    txt = re.sub(r"([{,]\s*)([^\s\"'\[\]{}:,]+)\s*:", r'\1"\2":', txt)
    txt = re.sub(r",(\s*[}\]])", r"\1", txt)                  # висячая запятая
    return json.loads(txt)


def page_number(name):
    """Числовая константа страницы (`const VEC_W = 1.0;` или `const A = 2, B = 300;`)."""
    src = page_text()
    m = re.search(r"\b%s\s*=\s*(-?[0-9.]+)\s*(?:;|,)" % re.escape(name), src)
    if not m:
        raise KeyError("на странице нет числовой константы %s" % name)
    return float(m.group(1))


def page_number_decl(line, names):
    """Числа из строки объявления: `const A = 0.8, B = 0.5, ...;` → {имя: число}."""
    src = page_text()
    m = re.search(r"\bconst\s+%s\s*=\s*([^;]+);" % re.escape(line), src)
    if not m:
        raise KeyError("на странице нет строки констант %s" % line)
    out = {}
    parts = m.group(1).split(",")
    for i, part in enumerate(parts):
        if i == 0:
            k, v = line, part          # первый элемент — сам объявленный идентификатор
        elif "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
        else:
            continue
        if k in names:
            out[k] = float(v.strip())
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Сверка
# ─────────────────────────────────────────────────────────────────────────────
def run(verbose=True):
    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))
        if verbose:
            print(("PASS" if cond else "FAIL") + "  " + name + (("  — " + detail) if (detail and not cond) else ""))

    # 1) классы обращения
    p_trig = js_value("TRIGGERS")
    m_trig = [[t, list(k)] for t, k in answer_scheme.TRIGGERS]
    same = len(p_trig) == len(m_trig) and all(
        p[0] == m[0] and list(p[1]) == list(m[1]) for p, m in zip(p_trig, m_trig))
    chk("TRIGGERS страницы == зеркала", same,
        "страница: %d классов, зеркало: %d" % (len(p_trig), len(m_trig)))
    if not same and verbose:
        for p, m in zip(p_trig, m_trig):
            if p[0] != m[0] or list(p[1]) != list(m[1]):
                print("   расхождение класса %s: только в странице %s / только в зеркале %s"
                      % (p[0], set(p[1]) - set(m[1]), set(m[1]) - set(p[1])))

    # 2) синонимы
    p_syn = js_value("RU_SYN")
    m_syn = [list(g) for g in answer_scheme.RU_SYN]
    chk("RU_SYN страницы == зеркала", p_syn == m_syn,
        "страница: %d групп, зеркало: %d" % (len(p_syn), len(m_syn)))

    # 3) языковые мосты
    p_en = js_value("EN_BRIDGE")
    m_en = answer_scheme.EN_BRIDGE
    chk("EN_BRIDGE страницы == зеркала", p_en == m_en,
        "только в странице: %s / только в зеркале: %s" % (
            sorted(set(p_en) - set(m_en)), sorted(set(m_en) - set(p_en))))
    p_he = js_value("HE_BRIDGE")
    m_he = answer_scheme.HE_BRIDGE
    chk("HE_BRIDGE страницы == зеркала", p_he == m_he,
        "только в странице: %s / только в зеркале: %s" % (
            sorted(set(p_he) - set(m_he)), sorted(set(m_he) - set(p_he))))

    # 4) маппинг класс → класс реестра
    p_cls = js_value("TRIG_CLASS")
    m_cls = answer_scheme.TRIG_CLASS
    chk("TRIG_CLASS страницы == зеркала", p_cls == m_cls,
        "страница %s / зеркало %s" % (p_cls, m_cls))

    # 5) вес вектора
    p_vec = page_number("VEC_W")
    chk("VEC_W страницы == зеркала (%.2f)" % p_vec,
        abs(p_vec - answer_scheme.VEC_W) < 1e-9,
        "страница %.2f, зеркало %.2f" % (p_vec, answer_scheme.VEC_W))

    # 6) пороги сверки ответа (страница ↔ answer_guard)
    names = ["GATE_CTX", "GATE_QUOTE", "GATE_LOOSE", "GATE_RUN", "GATE_RU", "GATE_NIKUD"]
    p_gate = page_number_decl("GATE_CTX", names)
    for n in names:
        chk("порог %s страницы == answer_guard" % n,
            abs(p_gate.get(n, -1) - getattr(answer_guard, n)) < 1e-9,
            "страница %s, answer_guard %s" % (p_gate.get(n), getattr(answer_guard, n)))
    p_min = page_number("GUARD_MIN_WORD")
    p_chars = page_number("GUARD_CTX_CHARS")
    chk("GUARD_MIN_WORD страницы == answer_guard",
        p_min == answer_guard.MIN_WORD, "%s vs %s" % (p_min, answer_guard.MIN_WORD))
    chk("GUARD_CTX_CHARS страницы == answer_guard",
        p_chars == answer_guard.CTX_CHARS, "%s vs %s" % (p_chars, answer_guard.CTX_CHARS))

    # 7) класс, которого нет в реестре, обязан быть привязан к существующему
    prof = answer_scheme.load_profile()
    reg = set((prof.get("by_trigger") or {}).keys())
    for src_cls, dst_cls in p_cls.items():
        chk("класс реестра «%s» существует (из «%s»)" % (dst_cls, src_cls), dst_cls in reg,
            "в реестре есть: %s" % sorted(reg))

    # 8) класс возврата classify(): страница и зеркало одинаково отвечают
    probes = ["Почему ты меня оставил?", "что мне делать", "מה עליי", "thanks, i praise you",
              "даю обет", "спаси меня", "прости меня", "почему же так несправедливо",
              "я не буду слушать", "что это за книга"]
    diffs = [(q, js_classify(q), answer_scheme.classify(q)) for q in probes]
    bad = [d for d in diffs if d[1] != d[2]]
    chk("classify() страницы == зеркала на %d пробах" % len(probes), not bad, str(bad))

    # 9) форма ответа: словарь, исходы и приговор — страница и зеркало совпадают
    p_forms = js_value("REQ_FORMS")
    m_forms = [[f, list(k)] for f, k in answer_scheme.REQ_FORMS]
    chk("REQ_FORMS страницы == зеркала", p_forms == m_forms,
        "страница: %s / зеркало: %s" % (p_forms, m_forms))
    p_out = js_value("FORM_OUTCOMES")
    m_out = {k: {"good": list(v["good"]), "bad": list(v["bad"])}
             for k, v in answer_scheme.FORM_OUTCOMES.items()}
    chk("FORM_OUTCOMES страницы == зеркала", p_out == m_out,
        "страница: %s / зеркало: %s" % (p_out, m_out))
    p_death = js_value("DEATH_VERDICT")
    chk("DEATH_VERDICT страницы == зеркала", list(p_death) == list(answer_scheme.DEATH_VERDICT),
        "страница: %s / зеркало: %s" % (p_death, answer_scheme.DEATH_VERDICT))

    # 10) requestForm(): страница и зеркало одинаково определяют форму
    fprobes = ["утешь меня в скорби", "прости мне мой грех", "сохрани меня от врагов",
               "научи меня твоему пути", "благодарю тебя за всё", "почему ты допустил зло?",
               "я боюсь умереть", "что такое завет с тобой?", "дай мне силы", "покажи путь"]
    fdiffs = [(q, js_request_form(q), answer_scheme.request_form(q)) for q in fprobes]
    fbad = [d for d in fdiffs if d[1] != d[2]]
    chk("requestForm() страницы == зеркала на %d пробах" % len(fprobes), not fbad, str(fbad))

    # 11) веса формы ответа (страница: константы в lexical-блоке)
    src = page_text()
    wgood = re.search(r"s \+= 2;\s*// форма ответа", src)
    chk("вес совпавшей формы ответа на странице == 2.0",
        bool(wgood) and abs(answer_scheme.FORM_GOOD - 2.0) < 1e-9,
        "зеркало: %s" % answer_scheme.FORM_GOOD)
    wbad = re.search(r"s -= 1\.5;", src)
    chk("вес неуместного исхода на странице == -1.5",
        bool(wbad) and abs(answer_scheme.FORM_BAD + 1.5) < 1e-9,
        "зеркало: %s" % answer_scheme.FORM_BAD)
    wdeath = re.search(r"s -= 8;", src)
    chk("штраф за смертный приговор на странице == -8.0",
        bool(wdeath) and abs(answer_scheme.DEATH_PENALTY + 8.0) < 1e-9,
        "зеркало: %s" % answer_scheme.DEATH_PENALTY)

    # 12) приговор не утешает: в корпусе таких эпизодов ровно три
    eps = answer_scheme.load_corpus()
    deaths = [k for k, e in eps.items()
              if any(w in (e.get("god_speech_plain") or "") for w in answer_scheme.DEATH_VERDICT)]
    chk("смертных приговоров в речи Бога ровно три", len(deaths) == 3,
        "найдено %d: %s" % (len(deaths), deaths))

    # 13) вектор — только спасатель: страница и зеркало включают его одинаково
    p_rescue = re.search(r"if\(!lexHit\)\{", src) is not None
    m_rescue = "if hybrid and not lex_hit:" in open(
        str(Path(__file__).resolve().parent / "answer_scheme.py"), encoding="utf-8").read()
    chk("вектор включается только когда лексика не нашла ничего (страница)",
        p_rescue, "на странице нет условия if(!lexHit)")
    chk("вектор включается только когда лексика не нашла ничего (зеркало)",
        m_rescue, "в зеркале нет условия not lex_hit")
    chk("сигнал лексики на странице ставится по слову и по имени",
        bool(re.search(r"lexHit\s*=\s*true;", src)), "")
    m_src = open(str(Path(__file__).resolve().parent / "answer_scheme.py"), encoding="utf-8").read()
    chk("сигнал лексики в зеркале ставится по слову и по имени",
        m_src.count("hit = True") >= 2, "")

    # 14) сортировка при равных очках одинаковая: округление 1e-6, книга без локали, стих числами
    chk("страница округляет очки до 1e-6", "Math.round(v*1e6)/1e6" in src, "")
    chk("зеркало округляет очки до 1e-6", "_round6" in m_src, "")
    chk("страница сравнивает книги без локали", "cmpBook" in src, "")
    chk("зеркало сравнивает книги без локали",
        'split("|")[0].lower()' in m_src, "")

    # 15) эталон меню: зеркало даёт РОВНО те меню, что сняты с живой страницы
    fixture = json.loads((Path(__file__).resolve().parent / "page_menus.json")
                         .read_text(encoding="utf-8"))["questions"]
    eps2 = answer_scheme.load_corpus()
    nik2 = answer_scheme.load_nikud()
    bad_menus = []
    for qq, page_keys in fixture.items():
        trig = answer_scheme.classify(qq)
        ranked = answer_scheme.rank_episodes(qq, trig, eps2, 18)
        ctx = answer_scheme.build_context(eps2, nik2, ranked[:18])
        cand = answer_scheme.spoken_candidates(ctx, 6)
        mkeys = ["%s|%s" % (c["book"], c["span"]["start"]) for c in cand]
        if mkeys != page_keys:
            bad_menus.append((qq, mkeys, page_keys))
    chk("меню зеркала == меню живой страницы на %d вопросах" % len(fixture),
        not bad_menus, "расхождения: %s" % bad_menus[:2])

    # 15б) «спасательный» путь: вопросы без лексического совпадения, отбор по вектору.
    # Сверяем, только если локальная int8-модель есть (она вне git): без неё зеркало
    # считает вектор в torch fp32, и меню законно другое — гейт это не про ложь.
    _pm = json.loads((Path(__file__).resolve().parent / "page_menus.json")
                      .read_text(encoding="utf-8"))
    rescue = _pm.get("rescue_questions") or {}
    rescue_srv = _pm.get("rescue_questions_server") or {}
    if os.environ.get("GOD_EMBED_URL", "").strip():
        # СЕРВЕРНЫЙ РЕЖИМ: эмбеддит Nemotron-3-Embed-1B на сервере проекта.
        # Эталон — меню, снятые с живой страницы именно в этом режиме.
        if rescue_srv:
            bad_srv = []
            for qq, page_keys in rescue_srv.items():
                trig = answer_scheme.classify(qq)
                ranked = answer_scheme.rank_episodes(qq, trig, eps2, 18)
                ctx = answer_scheme.build_context(eps2, nik2, ranked[:18])
                cand = answer_scheme.spoken_candidates(ctx, 6)
                mkeys = ["%s|%s" % (c["book"], c["span"]["start"]) for c in cand]
                if mkeys != page_keys:
                    bad_srv.append((qq, mkeys, page_keys))
            chk("меню зеркала (сервер, Nemotron) == меню живой страницы на «спасательных» вопросах (%d)" % len(rescue_srv),
                not bad_srv, "расхождения: %s" % bad_srv[:2])
        else:
            print("SKIP  серверный «спасательный» путь — нет фикстуры rescue_questions_server")
    elif rescue:
        try:
            import browser_embedder
            have_onnx = browser_embedder.available()
        except Exception:
            have_onnx = False
        if have_onnx:
            bad_rescue = []
            for qq, page_keys in rescue.items():
                trig = answer_scheme.classify(qq)
                ranked = answer_scheme.rank_episodes(qq, trig, eps2, 18)
                ctx = answer_scheme.build_context(eps2, nik2, ranked[:18])
                cand = answer_scheme.spoken_candidates(ctx, 6)
                mkeys = ["%s|%s" % (c["book"], c["span"]["start"]) for c in cand]
                if mkeys != page_keys:
                    bad_rescue.append((qq, mkeys, page_keys))
            chk("меню зеркала == меню живой страницы на «спасательных» вопросах (%d)" % len(rescue),
                not bad_rescue, "расхождения: %s" % bad_rescue[:2])
        else:
            print("SKIP  «спасательный» путь — нет локальной int8-модели (.agent/models/…): "
                  "сверка только на живой странице")

    # 16) стоп-слова и вопросительные маркеры: страница и зеркало совпадают
    p_stop = page_set_literal("RU_STOP")
    m_stop = set(answer_scheme.RU_STOP)
    chk("RU_STOP страницы == зеркала", p_stop == m_stop,
        "только в странице: %s / только в зеркале: %s" % (
            sorted(p_stop - m_stop), sorted(m_stop - p_stop)))
    p_markers = page_set_literal("RU_MARKERS")
    m_markers = set(answer_scheme.RU_MARKERS)
    chk("RU_MARKERS страницы == зеркала", p_markers == m_markers and bool(p_markers),
        "страница: %s / зеркало: %s" % (sorted(p_markers), sorted(m_markers)))

    # 17) queryTokens(): страница и зеркало дают ОДИН И ТОТ ЖЕ набор токенов
    tprobes = list(fixture.keys()) + ["why do the righteous suffer?",
                                      "מה עליי", "сколько это стоит?", "почему?",
                                      "зачем ты молчишь?", "какой путь?"]
    tdiffs = [(q, sorted(js_query_tokens(q)), sorted(answer_scheme.query_tokens(q)))
              for q in tprobes]
    tbad = [d for d in tdiffs if d[1] != d[2]]
    chk("queryTokens() страницы == зеркала на %d пробах" % len(tprobes), not tbad,
        str(tbad[:2]))
    marker_leak = sorted(set(js_query_tokens("почему ты допустил зло в мире?"))
                         & set(["почему", "зачем", "какой", "какая", "какие", "сколько"]))
    chk("вопросительные маркеры не попадают в тематические токены", not marker_leak,
        "остались в токенах: %s" % marker_leak)

    # 18) строгость таблицы формы ответа (блокировка размывания, а не только паритета)
    strict = {"утешение": ({"blessing", "rescue", "covenant"}, set()),
              "объяснение": ({"revelation"}, {"silence"})}
    for frm, (wgood, wbad) in strict.items():
        got_good = set(answer_scheme.FORM_OUTCOMES[frm]["good"])
        got_bad = set(answer_scheme.FORM_OUTCOMES[frm]["bad"])
        chk("форма «%s» строгая (good=%s, bad=%s)" % (frm, sorted(wgood), sorted(wbad)),
            got_good == wgood and got_bad == wbad,
            "зеркало: good=%s bad=%s" % (sorted(got_good), sorted(got_bad)))

    # 19) в блок выбора идёт полный summary_ru (обрезка на 200 символах рвала фразы)
    chk("страница кладёт в блок полный summary_ru",
        bool(re.search(r"summary_ru\s*:\s*\(h\[2\]\.summary_ru\|\|\"\"\)", src)), "")
    chk("страница не обрезает summary_ru на 200 символах",
        not re.search(r"summary_ru[^\n]{0,80}slice\(0,200\)", src), "")
    bi = m_src.find("def build_context")
    m_build = m_src[bi: m_src.find("\ndef ", bi + 10)]
    chk("зеркало кладёт в блок полный summary_ru",
        '"summary_ru": (e.get("summary_ru") or "")' in m_build and "[:200]" not in m_build,
        "")

    # 20) порядок при равных очках: книга по алфавиту, стих числами
    chk("страница сравнивает стих числами", "cmpVerse" in src, "")
    chk("зеркало сравнивает стих числами", "_verse_key" in m_src, "")
    chk("зеркало сортирует по очкам, книге, стиху",
        "(-_round6(kv[0])" in m_src and "_verse_key(kv[1].split" in m_src, "")

    ok = sum(1 for _, c, _ in checks if c)
    print("\nИТОГ: %d/%d сверок — %s" % (ok, len(checks), "PASS" if ok == len(checks) else "FAIL"))
    return 0 if ok == len(checks) else 1


def js_classify(q):
    """classify() страницы, исполненная по тем же правилам (порядок TRIGGERS)."""
    m = q.lower()
    for t, kws in js_value("TRIGGERS"):
        for k in kws:
            if k in m:
                return t
    return ""


def js_request_form(q):
    """requestForm() страницы по тем же правилам (порядок REQ_FORMS)."""
    m = q.lower()
    for f, kws in js_value("REQ_FORMS"):
        for k in kws:
            if k in m:
                return f
    return ""


def page_set_literal(name):
    """`const NAME = new Set("a b c".split(" "));` → множество строк."""
    src = page_text()
    m = re.search(r"const\s+%s\s*=\s*new\s+Set\(\s*\"([^\"]*)\"" % re.escape(name), src)
    if not m:
        raise KeyError("на странице нет множества %s" % name)
    return set(m.group(1).split())


def js_query_tokens(q):
    """queryTokens() страницы по ПРАВИЛАМ СТРАНИЦЫ и её же константам.

    Нужна, чтобы поймать расхождение не только в словарях, но и в самой логике
    отбора токенов (например, если маркеры перестанут вырезаться или появится
    новый мост, которого нет в зеркале).
    """
    m = q.lower()
    stop = page_set_literal("RU_STOP")
    markers = page_set_literal("RU_MARKERS")
    en = js_value("EN_BRIDGE")
    he = js_value("HE_BRIDGE")
    syn = js_value("RU_SYN")
    toks = set()
    for t in re.findall(r"[а-яё-]{4,}", m):
        if t not in stop:
            toks.add(t)
    for w in re.findall(r"[a-z]{2,}", m):
        if w in en:
            toks.add(en[w])
    for w in re.findall(r"[א-ת]{3,}", m):
        toks.add(w)
        if w in he:
            toks.add(he[w])
    for w in markers:
        toks.discard(w)
    out = set(toks)
    for t in list(toks):
        for g in syn:
            if any(x == t or (len(x) >= 4 and (x in t or t in x)) for x in g):
                out.update(g)
    return out


if __name__ == "__main__":
    sys.exit(run(verbose="--test" in sys.argv or "--quiet" not in sys.argv))
