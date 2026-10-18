"""
extract_address_names.py — имена и эпитеты Бога, которыми люди ОБРАЩАЮТСЯ к Нему в Танахе.

Эвристика v1 (до готовности v2-эпизодов):
  стих содержит глагол обращения/взыва к Богу (или адресные конструкции "אתה X" / "לך X") —
  собираем все божественные обозначения этого стиха.

Выход: output/address_names.json + отчёт в консоль.

Запуск: python scripts/extract_address_names.py
"""
import json
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

TANAKH_DIR = Path(_REPO + "/data/tanakh")
OUT_FILE = Path(_REPO + "/output/address_names.json")
GOD_NAMES_FILE = Path(_REPO + "/data/god_names.json")

# --- нормализация: консонантный текст (та же, что в merge_audit_v2) ---
def normalize_he(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if 0x0591 <= o <= 0x05BD or o in (0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7):
            continue
        if o == 0x05BE:
            out.append(" ")
            continue
        if o in (0x05C0, 0x05C3):
            continue
        out.append(ch)
    return " ".join("".join(out).split())

# --- глаголы/конструкции обращения человека к Богу ---
APPEAL = re.compile(
    r"ויקרא|ותקרא|ואקרא|אקרא|קראתי|קורא|קרוא"          # звать
    r"|ויזעק|ותזעק|[צז]עקתי|וצעק|שועתי|ואשוע|אשוע|תשועתי"  # взывать/вопить
    r"|ויתפלל|ותתפלל|התפללתי|תפלתי|אתפלל|ואתפלל"        # молиться
    r"|ויעתר|ואעתר|העתירו|העתיר|מעתיר|העתר"            # умолять
    r"|ואנחו|נאקת|אנקה"                                  # стенать
    r"|שמעני|האזינה|האזינו|ענני|חנני|הושיעה|הושעה נא|רחם עלי|עננו"
    r"|אתה יהוה|אתה אלהים|אתה אל|לך יהוה|לך אדני|אדני מה|אל תחרש|אל תסתר"
    # гимновый слой (Псалмы, Плач): доверие/хвала во 2-м лице
    r"|בך יהוה|בך אדני|בך אלהי|בך השבתי|יהוה אלי|אלי אתה|אלהי אתה|אתה מגני|אתה ישעי"
    r"|עזרי|משגבי|מגדלי|מלטני|פדני|האזינה יהוה|שמעה יהוה|ראה יהוה|טה אזנך|גל עיניך"
)

# --- лексемы-обозначения Бога (точные токены после нормализации) ---
LEXEMES = {
    "יהוה": "YHWH",
    "יה": "Yah (краткая форма)",
    "אדני": "Adonai (Господин мой)",
    "אלהים": "Elohim",
    "האלהים": "ha-Elohim (с определённым артиклем)",
    "אלהי": "Elohai (Бог мой / Бог + род. падеж)",
    "אלהינו": "Eloheinu (Бог наш)",
    "אלוה": "Eloah",
    "אלוהי": "Elohai (вариант אלוה+суффикс)",
    "שדי": "Shaddai",
    "עליון": "Elyon (Всевышний)",
    "צבאות": "Tzvaot (Воинств)",
    "אביר": "Avir (Могучий, 'Бык Иакова')",
    "קדוש": "Kadosh (Святой)",
    "צור": "Tzur (Скала)",
    "מלך": "Melekh (Царь; шум: и людские цари)",
    "מלכי": "Malki (Царь мой)",
    "גואל": "Go'el (Искупитель)",
    "גואלי": "Go'ali (Искупитель мой)",
    "רועי": "Ro'i (Пастырь мой)",
    "מגני": "Mageni (Щит мой)",
    "מחסי": "Machsi (Прибежище моё)",
    "ישעי": "Yish'i (Спасение моё)",
    "מושיע": "Moshia (Спаситель)",
}
# отдельные אל (предлог 'к') и אבи (букв. 'отец') исключены как шум; אל учитывается только в сочетаниях

# --- устойчивые сочетания (поиск в строке стиха) ---
BIGRAMS = {
    "אדני יהוה": "Adonai YHWH",
    "יהוה אלהי": "YHWH Elohai",
    "יהוה אלהינו": "YHWH Eloheinu",
    "יהוה צבאות": "YHWH Tzvaot",
    "אדני צבאות": "Adonai Tzvaot",
    "אל עליון": "El Elyon",
    "אל שדי": "El Shaddai",
    "אלהי אברהם": "Elohei Avraham",
    "אלהי יצחק": "Elohei Yitzchak",
    "אלהי יעקב": "Elohei Yaakov",
    "אלהי אבי": "Elohei avi (Бог отца моего)",
    "אלהי אבתי": "Elohei avotai (Бог отцов моих)",
    "קדוש ישראל": "Kadosh Yisrael",
    "אביר יעקב": "Avir Yaakov",
    "מלך כבוד": "Melekh ha-Kavod",
    "מלך עולם": "Melekh Olam",
}

# "El" считаем только в составе сочетаний (отдельный токен слишком многозначен)
EL_COMBOS = re.compile(r"אל (?:עליון|שדי|אמת|גבור|נורא|משפט|ישועתי|אל חי)")


def main():
    lex_counter = Counter()
    bigram_counter = Counter()
    book_lex = defaultdict(Counter)
    examples = defaultdict(list)

    books = sorted(p.stem for p in TANAKH_DIR.glob("*.json") if p.stem != "_index")
    for book in books:
        data = json.load(open(TANAKH_DIR / f"{book}.json", encoding="utf-8"))
        for v in data["verses"]:
            t = normalize_he(v.get("text_he", ""))
            if not APPEAL.search(t):
                continue
            ref = f"{book} {v['chapter']}:{v['verse']}"
            tokens = set(t.split())
            for lex in LEXEMES:
                if lex in tokens:
                    lex_counter[lex] += 1
                    book_lex[lex][book] += 1
                    if len(examples[lex]) < 5:
                        examples[lex].append(ref)
            for bg in BIGRAMS:
                if bg in t:
                    bigram_counter[bg] += 1
                    book_lex[bg][book] += 1
                    if len(examples[bg]) < 5:
                        examples[bg].append(ref)
            if "אל" in tokens and EL_COMBOS.search(t):
                lex_counter["אל (в сочетаниях)"] += 1
                book_lex["אל (в сочетаниях)"][book] += 1

    # сверка со списком 59 имён из SPEC
    known = []
    try:
        gn = json.load(open(GOD_NAMES_FILE, encoding="utf-8"))
        known = json.dumps(gn, ensure_ascii=False)[:200]
    except Exception:
        pass

    result = {
        "method": "эвристика v1: стихи с глаголами обращения; финальная атрибуция — после v2-эпизодов",
        "appeal_verses_total": sum(lex_counter.values()),
        "lexemes": {lex: {"count": c, "books": book_lex[lex], "examples": examples[lex]}
                    for lex, c in lex_counter.most_common()},
        "bigrams": {bg: {"count": c, "books": book_lex[bg], "examples": examples[bg]}
                    for bg, c in bigram_counter.most_common()},
    }
    json.dump(result, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"Стихов с обращениями обработано: {len(books)} книг")
    print("\n=== ЛЕКСЕМЫ (в стихах-обращениях, по частоте) ===")
    for lex, c in lex_counter.most_common():
        print(f"{lex:20s} {c:5d}  [{LEXEMES.get(lex, 'сочетание с אל')}]  напр.: {', '.join(examples[lex][:3])}")
    print("\n=== УСТОЙЧИВЫЕ СОЧЕТАНИЯ ===")
    for bg, c in bigram_counter.most_common():
        print(f"{bg:20s} {c:5d}  [{BIGRAMS[bg]}]  напр.: {', '.join(examples[bg][:3])}")
    print(f"\nЗаписано: {OUT_FILE}")


if __name__ == "__main__":
    main()
