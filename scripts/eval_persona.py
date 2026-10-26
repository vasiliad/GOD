#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ГЕЙТ ПЕРСОНЫ: что даёт «просто промпт “ты — Яхве”» против схемы проекта.

Вопрос владельца: «а что если тупо задать промт дикте на англ — отвечай на
вопросы на базе книг танаха как будто ты яхве». Отвечаем замером, а не мнением.

Руки (один и тот же мозг, одни и те же вопросы, одна и та же сверка):
  A1 — персонаж по-английски, свободный текст: ни корпуса, ни контракта секций;
  A2 — тот же персонаж + контракт шести секций, корпуса нет;
  B  — схема проекта: ретривал → выбор → формулировка → сверка «правило S».

Метрики у всех рук одни и те же:
  * сверка answer_guard по реестру: verified / corpus / reject;
  * доля слов ивритской реплики, встречающихся в корпусе;
  * названные моделью стихи: существует ли стих, есть ли в нём слова реплики,
    есть ли сама книга в Танахе (Откровение/Иоанн — нет).

Замер (2026-10-26, локальный мозг DictaLM 3.0 12B, 5 вопросов):
  A1 — verified/corpus 0, reject 5, слова в корпусе 32 %, 1 цитата в книге вне Танаха;
  A2 — verified/corpus 2, reject 3, слова в корпусе 73 %;
  B  — verified 5/5, слова в корпусе 100 %, все стихи существуют.

Запуск:
  python scripts/eval_persona.py --test          # самопроверка, сети не нужно
  python scripts/eval_persona.py                 # живой замер (нужен мозг)

Ответы кэшируются в .agent/persona_cache.json — повторный прогон не жжёт GPU.
"""
import json
import re
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
import answer_scheme as A          # noqa: E402
import answer_guard as G           # noqa: E402
from eval_topics import parse_sections, prompt_key   # noqa: E402

BRAIN_URL = "http://127.0.0.1:18099/v1/chat/completions"
BRAIN_KEY = "godbrain-v1-vasiliad"
BRAIN_MODEL = "god-brain"
CACHE_FILE = _ROOT / ".agent" / "persona_cache.json"
TOPIC_CACHE = _ROOT / ".agent" / "topic_cache.json"
OUT_FILE = _ROOT / ".agent" / "persona_out.json"

QUESTIONS = [
    "почему ты допустил зло в мире?",
    "утешь меня в скорби",
    "прости мне мой грех",
    "я боюсь умереть",
    "что такое завет с тобой?",
]

PERSONA_SYS = ("You are Yahweh, the God of Israel. Answer the user's question based on the books "
               "of the Tanakh (the Hebrew Bible), as if you were speaking as God.")

# Температура рук A1/A2. По умолчанию 0 — чтобы выборка была воспроизводимой
# (каждый запуск даёт тот же ответ, кэш не расходится). При 0.15 разброс тот же
# по знаку: подтверждённых реестром ответов 0–1 из 5, отклонённых 4–5.
PERSONA_TEMP = 0.0

FORMAT_LINE = ("ФОРМАТ ОТВЕТА — ровно шесть секций, каждая непустая:\n"
               "[HEBREW] 5-12 слов консонантным ивритом (только буквы) из Танаха;\n"
               "[NIKKUD] те же слова с огласовкой;\n"
               "[Russian] перевод той же короткой реплики;\n"
               "[English] дословный английский перевод;\n"
               "[Hebrew Modern] та же реплика на современном иврите;\n"
               "[SOURCES] книга глава:стих.")

RU_BOOKS = {
    "бытие": "genesis", "исход": "exodus", "левит": "leviticus", "числа": "numbers",
    "второзаконие": "deuteronomy", "иисус навин": "joshua", "судьи": "judges", "руфь": "ruth",
    "царств первое": "i_kings", "царств второе": "ii_kings", "царств третье": "i_chronicles",
    "царств четвертое": "ii_chronicles", "ездра": "ezra", "неемия": "nehemiah", "есфирь": "esther",
    "иов": "job", "псалм": "psalms", "псалмов": "psalms", "притчи": "proverbs",
    "екклесиаст": "ecclesiastes", "песни песней": "song_of_songs", "исаия": "isaiah",
    "иеремия": "jeremiah", "плач": "lamentations", "езекииль": "ezekiel", "даниил": "daniel",
    "осия": "hosea", "иоиль": "joel", "амос": "amos", "авдий": "obadiah", "иона": "jonah",
    "михей": "micah", "наум": "nahum", "аввакум": "habakkuk", "софония": "zephaniah",
    "аггей": "haggai", "захария": "zechariah", "малахия": "malachi",
}
HEB_BOOKS = {
    "בראשית": "genesis", "שמות": "exodus", "ויקרא": "leviticus", "במדבר": "numbers",
    "דברים": "deuteronomy", "יהושע": "joshua", "שופטים": "judges", "רות": "ruth",
    "שמואל": "i_samuel", "מלכים": "i_kings", "דניאל": "daniel", "ישעיהו": "isaiah",
    "ירמיהו": "jeremiah", "איכה": "lamentations", "יחזקאל": "ezekiel", "הושע": "hosea",
    "יואל": "joel", "עמוס": "amos", "עבדיה": "obadiah", "יונה": "jonah", "מיכה": "micah",
    "נחום": "nahum", "חבקוק": "habakkuk", "צפניה": "zephaniah", "חגי": "haggai",
    "זכריה": "zechariah", "מלאכי": "malachi", "תהלים": "psalms", "תהילים": "psalms",
    "משלי": "proverbs", "קהלת": "ecclesiastes", "שיר השירים": "song_of_songs",
    "איוב": "job", "עזרא": "ezra", "נחמיה": "nehemiah", "אסתר": "esther",
}
BOOK_ALIASES = {
    "psalm": "psalms", "psalms": "psalms", "song of songs": "song_of_songs",
    "song of solomon": "song_of_songs", "genesis": "genesis",
    "i kings": "i_kings", "ii kings": "ii_kings", "i samuel": "i_samuel",
    "ii samuel": "ii_samuel", "i chronicles": "i_chronicles", "ii chronicles": "ii_chronicles",
}
HEB_DIG = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
           "י": 10, "כ": 20, "ל": 30, "מ": 40, "נ": 50, "ס": 60, "ע": 70, "פ": 80,
           "צ": 90, "ק": 100, "ר": 200, "ש": 300, "ת": 400}
HEB_RUN = re.compile("[֐-׿\\s]{3,}")
CITE_RE = re.compile(r"([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\s]{0,24}?)\s+(\d+):(\d+)")
CITE_RE_HE = re.compile(r"([א-ת]{2,10})\s+([א-ת\"'״]{1,8}):([א-ת\"'״]{1,8})")

TANAKH = {}
TANAKH_FILES = {}


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def heb_num(tok):
    """Ивритское числительное («מ״א» = 41, «כ״ט» = 29) или арабские цифры."""
    t = str(tok or "").replace('"', "").replace("״", "").replace("'", "").replace("’", "").strip()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    total = 0
    for ch in t:
        v = HEB_DIG.get(ch)
        if v is None:
            return None
        total += v
    return total or None


def load_tanakh_files():
    if not TANAKH_FILES:
        for p in (_ROOT / "docs" / "data" / "tanakh").glob("*.json"):
            if p.stem.startswith("_"):
                continue
            TANAKH_FILES[p.stem.lower().replace("_", " ")] = p


def norm_book(s):
    """Имя книги → ключ корпуса (или None: такой книги в Танахе нет)."""
    s = re.sub(r"\s+", " ", str(s or "").lower().replace("_", " ").replace(".", " ")).strip()
    if s in HEB_BOOKS:
        return HEB_BOOKS[s]
    if s in RU_BOOKS:
        return RU_BOOKS[s]
    s = BOOK_ALIASES.get(s, s)
    if s in RU_BOOKS:
        return RU_BOOKS[s]
    load_tanakh_files()
    return s if s in TANAKH_FILES else None


def verse_text(book, chap, verse):
    """Текст стиха из полного Танаха: (статус, текст).

    статусы: ok — стих есть; out_of_range — за пределами книги;
              unknown_book — такой книги в Танахе нет (Откровение, Иоанн…).
    """
    load_tanakh_files()
    b = norm_book(book)
    if b is None:
        return "unknown_book", ""
    if b not in TANAKH:
        f = TANAKH_FILES.get(b.replace("_", " "))
        try:
            TANAKH[b] = json.loads(f.read_text(encoding="utf-8")).get("chapters") or []
        except Exception:
            TANAKH[b] = []
    chapters = TANAKH.get(b) or []
    if chap < 1 or chap > len(chapters):
        return "out_of_range", ""
    vv = chapters[chap - 1]
    if verse < 1 or verse > len(vv):
        return "out_of_range", ""
    return "ok", str(vv[verse - 1])


def citations(text):
    """Список (книга, глава, стих), названных в тексте (латиница, кириллица, иврит)."""
    out = []
    for m in CITE_RE.finditer(text or ""):
        out.append((m.group(1).strip(), int(m.group(2)), int(m.group(3))))
    for m in CITE_RE_HE.finditer(text or ""):
        ch, vs = heb_num(m.group(2)), heb_num(m.group(3))
        if ch and vs:
            out.append((m.group(1).strip(), ch, vs))
    return out


def brain(system, user, max_tokens=900, temperature=0.15, cache=None, ckey=None):
    """Запрос к мозгу с кэшем (повторный прогон не должен жечь GPU)."""
    if cache is not None and ckey and ckey in cache:
        return cache[ckey]
    txt = A.ask_brain(system, user, BRAIN_URL, BRAIN_KEY, timeout=300, model=BRAIN_MODEL,
                      temperature=temperature, max_tokens=max_tokens, retries=1)
    if cache is not None and ckey:
        cache[ckey] = txt
        save_json(CACHE_FILE, cache)
    return txt


def run_test():
    """Самопроверка без сети: числа-источники, цитаты, поведение сверки."""
    checks = []

    def chk(name, cond, extra=""):
        checks.append((name, bool(cond), extra))

    chk("ивритское числительное: מ״א = 41", heb_num('מ"א') == 41)
    chk("ивритское числительное: כ״ט = 29", heb_num('כ"ט') == 29)
    chk("ивритское числительное: נא = 51", heb_num("נא") == 51)
    st, txt = verse_text("Genesis", 1, 1)
    chk("стих Танаха читается", st == "ok" and "בראשית" in G.strip_nikud(txt), st)
    st2, _ = verse_text("ישעיהו", 40, 1)
    chk("стих по ивритскому названию книги", st2 == "ok", st2)
    st3, _ = verse_text("Revelation", 20, 14)
    chk("книга вне Танаха опознаётся", st3 == "unknown_book", st3)
    st4, _ = verse_text("Genesis", 999, 1)
    chk("глава за пределами книги опознаётся", st4 == "out_of_range", st4)
    cites = citations("[SOURCES] ירמיהו ל\"ג:כ\"ה")
    chk("цитата с ивритскими числами разбирается",
        cites and cites[0][1] == 33 and cites[0][2] == 25, str(cites))
    cites2 = citations("as written in Joshua 1:9")
    chk("латинская цитата разбирается", any(c[1] == 1 and c[2] == 9 for c in cites2), str(cites2))
    # сверка: выдуманная реплика не проходит, настоящая — проходит
    eps = A.load_corpus()
    registry = [(e["book"], e) for e in eps.values()]
    bad = G.verify("סלח לי חטאתי", [], registry, [])
    chk("выдуманная реплика отклоняется сверкой", bad["mode"] == "reject", bad["mode"])
    real_ep = next(e for e in eps.values() if (e.get("god_speech_plain") or "").strip())
    frags = [str(real_ep.get("god_speech_plain") or "")[:G.CTX_CHARS]]
    good = G.verify(real_ep["god_speech_plain"], frags, registry, [])
    chk("настоящая цитата проходит сверку", good["mode"] == "verified", good["mode"])

    ok = sum(1 for _, c, _ in checks if c)
    for name, c, extra in checks:
        print(("PASS " if c else "FAIL ") + name + ((" — " + str(extra)) if extra and not c else ""))
    print("\nИТОГ: %d/%d проверок — %s" % (ok, len(checks), "PASS" if ok == len(checks) else "FAIL"))
    return 0 if ok == len(checks) else 1


def main():
    if "--test" in sys.argv:
        sys.exit(run_test())

    eps = A.load_corpus()
    nikud = A.load_nikud()
    prof = A.load_profile()
    registry = [(e["book"], e) for e in eps.values()]
    vocab = set()
    for e in eps.values():
        vocab.update(G.norm_set(G.heb_words(e.get("god_speech_plain") or "")))

    cache = load_json(CACHE_FILE, {})
    topic_cache = load_json(TOPIC_CACHE, {})
    tag = "v4_pool18_menu6_action1_full_spoken"

    def scheme_brain(system, user, max_tokens, temperature, kind, q):
        """Рука B: ответы схемы берём из кэша эталона — GPU не жжём заново."""
        key = prompt_key(tag, kind, q, user)
        if key in topic_cache:
            return topic_cache[key]
        return brain(system, user, max_tokens, temperature, cache, key)

    rows = []
    for q in QUESTIONS:
        print("\n=== %s ===" % q, flush=True)

        t0 = time.time()
        a1 = brain(PERSONA_SYS, q, 900, PERSONA_TEMP, cache, "A1t%g|" % PERSONA_TEMP + q)
        print("A1: %d симв. (%.0f с)" % (len(a1), time.time() - t0), flush=True)

        t0 = time.time()
        a2_user = "ВОПРОС ЧЕЛОВЕКА: " + q + "\n\n" + FORMAT_LINE
        a2 = brain(PERSONA_SYS, a2_user, 900, PERSONA_TEMP, cache, "A2t%g|" % PERSONA_TEMP + q)
        print("A2: %d симв. (%.0f с)" % (len(a2), time.time() - t0), flush=True)

        t0 = time.time()
        trig = A.classify(q)
        cls = A.trig_class(trig)
        ranked = A.rank_episodes(q, trig, eps, 18)
        ctx = A.build_context(eps, nikud, ranked[:18])
        cand = A.spoken_candidates(ctx, 6)
        act = A.action_block(cls, prof)
        sel_user = A.candidate_block(q, cand) + ("\n\n" + act if act else "")
        raw_sel = scheme_brain(A.SYS_SELECT, sel_user, 16, 0.0, "sel", q)
        idx = A.pick_index(raw_sel, len(cand))
        chosen = cand[idx - 1]
        form_user = ("ВОПРОС ЧЕЛОВЕКА: %s\n\n%s\n\nОтветь шестью секциями."
                     % (q, A.episode_block(chosen)))
        raw = scheme_brain(A.SYS_PROMPT, form_user, 900, 0.15, "form", q)
        print("B: эпизод %s|%s (%.0f с)" % (chosen["book"], chosen["span"]["start"],
                                            time.time() - t0), flush=True)

        for arm, text, arm_ctx in (("A1", a1, []), ("A2", a2, []), ("B", raw, [chosen])):
            sections = parse_sections(text)
            heb = sections.get("[HEBREW]", "")
            if not heb:                       # A1: иврит ищем в свободном тексте
                runs = HEB_RUN.findall(text or "")
                heb = max(runs, key=len) if runs else ""
            frags = []
            for c in arm_ctx:
                frags.append(str(c.get("god_speech_plain") or "")[:G.CTX_CHARS])
                frags.append(str(c.get("nikud") or "")[:G.CTX_CHARS])
            v = G.verify(heb, frags, registry, [(c["book"], c) for c in arm_ctx])
            rep = G.heb_words(heb)
            cov = G.coverage(rep, vocab) if rep else 0.0
            cite_rows = []
            for b, c, vv in citations(sections.get("[SOURCES]", "") or text):
                status, vtext = verse_text(b, c, vv)
                in_verse = None
                if status == "ok":
                    in_verse = round(G.coverage(rep, G.norm_set(G.heb_words(vtext))), 3) if rep else 0.0
                cite_rows.append({"book": b, "ch": c, "v": vv, "status": status,
                                  "quote_cov": in_verse})
            reg_src = ["%s|%s" % (b, e["span"]["start"]) for b, e in v["sources"][:2]]
            ep_cov = None
            if arm == "B" and rep:
                full = G._registry_episode(chosen["book"], chosen, registry)
                ep_words = []
                for rr in (full.get("god_speech_refs") or []):
                    m = re.match(r"^(\d+):(\d+)(?:-(\d+):(\d+))?$", str(rr))
                    if not m:
                        continue
                    c1, v1 = int(m.group(1)), int(m.group(2))
                    c2 = int(m.group(3)) if m.group(3) else c1
                    v2 = int(m.group(4)) if m.group(4) else v1
                    for cc in range(c1, c2 + 1):
                        for vs in range(v1 if cc == c1 else 1, v2 + 1):
                            st, txt = verse_text(full["book"], cc, vs)
                            if st == "ok":
                                ep_words.extend(G.heb_words(txt))
                ep_cov = round(G.coverage(rep, G.norm_set(ep_words)), 3)
            rows.append({
                "q": q, "arm": arm, "heb_words": len(rep),
                "corpus_cov": round(cov, 3), "ctx_cov": v["ctx_cov"], "mode": v["mode"],
                "cited": cite_rows, "registry_source": reg_src, "episode_cov": ep_cov,
                "episode": ("%s|%s" % (chosen["book"], chosen["span"]["start"])) if arm == "B" else "",
                "hebrew": heb[:300], "text": text[:4000],
            })
            print("   %-2s иврит:%2d слов, в корпусе %3d%%, сверка=%-8s, реестр=%s%s"
                  % (arm, len(rep), round(cov * 100), v["mode"], ", ".join(reg_src) or "—",
                     ("; в стихах эпизода %d%%" % round(ep_cov * 100)) if ep_cov is not None else ""),
                  flush=True)
            for c in cite_rows:
                print("      цитата %s %d:%d — %s, слова реплики в этом стихе: %s"
                      % (c["book"], c["ch"], c["v"], c["status"],
                         ("%.0f%%" % (c["quote_cov"] * 100)) if c["quote_cov"] is not None else "—"),
                      flush=True)

    save_json(OUT_FILE, rows)
    print("\n\n=== ИТОГ ===")
    for arm in ("A1", "A2", "B"):
        rs = [r for r in rows if r["arm"] == arm]
        heb = sum(1 for r in rs if r["heb_words"] > 0)
        strict = sum(1 for r in rs if r["mode"] in ("verified", "corpus"))
        rej = sum(1 for r in rs if r["mode"] == "reject")
        cov = sum(r["corpus_cov"] for r in rs) / len(rs)
        cites = [c for r in rs for c in r["cited"]]
        ok_c = [c for c in cites if c["status"] == "ok"]
        oor = [c for c in cites if c["status"] == "out_of_range"]
        unk = [c for c in cites if c["status"] == "unknown_book"]
        real_quote = [c for c in ok_c if (c["quote_cov"] or 0) >= 0.5]
        ans_real = sum(1 for r in rs if any((c["quote_cov"] or 0) >= 0.5 for c in r["cited"]))
        print("рука %s: ответов %d | иврит есть %d | сверка verified/corpus %d, reject %d | "
              "слова в корпусе в среднем %.0f%%"
              % (arm, len(rs), heb, strict, rej, cov * 100))
        print("        цитат названо %d: стих существует %d, за пределами книги %d, книги нет в Танахе %d; "
              "слова реплики действительно в названном стихе %d (ответов с такой цитатой %d)"
              % (len(cites), len(ok_c), len(oor), len(unk), len(real_quote), ans_real))
        for c in cites:
            if c["status"] != "ok" or (c["quote_cov"] or 0) < 0.5:
                print("          ✗ %s %d:%d — %s, покрытие %s"
                      % (c["book"], c["ch"], c["v"], c["status"],
                         ("%.0f%%" % (c["quote_cov"] * 100)) if c["quote_cov"] is not None else "—"))


if __name__ == "__main__":
    main()
