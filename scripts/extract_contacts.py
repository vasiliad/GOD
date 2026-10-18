"""
extract_contacts.py
Этап 2 пайплайна: Извлечение контактов Бога и человека.

⚠ ОБЛАСТЬ ПОКРЫТИЯ (урок v1, см. docs/retrospective_v1.md): этот экстрактор
ловит ТОЛЬКО формулы «глагол+имя» — речевые акты. Полное покрытие взаимодействий
Человек↔Бог (включая действия без речи, человеческую инициативу, молчание)
находится в эпизодах v2: output/episodes_TANAKH_v2.json (2050 эпизодов).
Использовать этот реестр для статистики ВСЕХ контактов нельзя — только для
статистики речевых формул.

Извлекает из Танаха ситуации, где Бог является активным субъектом.
Ожидаемый выход: output/contacts_registry.json (для task_manager)
"""
import json
import re
import sys
import argparse
from pathlib import Path
from collections import Counter
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# ПУТИ
# ============================================================
TANAKH_DIR  = Path(_REPO + "/data/tanakh")
OUTPUT_FILE = Path(_REPO + "/output/contacts_registry.json")

# ============================================================
# 1. ОЧИСТКА ОТ ОГЛАСОВОК
# ============================================================
def strip_niqqud(text: str) -> str:
    # маκеф U+05BE лежит внутри диапазона 0591-05C7 — на пробел ДО стирания,
    # иначе את־יהוה склеивается в אתיהוה и контакт теряется
    text = text.replace('\u05be', ' ')
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    return re.sub(r'[\u0591-\u05C7]', '', text)

# ============================================================
# 2. СПИСОК ИМЁН БОГА (расширен по аудиту god_names_audit.json)
# ============================================================
GOD_NAMES = [
    "יהוה צבאות",  # YHWH Tzvaot
    "יהוה אלהים",  # YHWH Elohim
    "אל שדי",      # El Shaddai
    "אדני יהוה",   # Adonai YHWH
    "מלאך יהוה",   # angel of YHWH
    "מלאך אלהים",  # angel of Elohim
    "שר צבא יהוה", # commander of YHWH's host
    "קדוש ישראל",  # Holy One of Israel (Isaiah/II Kings)
    "אביר יעקב",   # Mighty One of Jacob
    "אל עליון",    # God Most High
    "אל עולם",     # Everlasting God
    "אל ראי",      # God of Seeing (Beer-lahai-roi)
    "יהוה ירה",    # YHWH will provide
    "יהוה נסי",    # YHWH my banner
    "יהוה שלום",   # YHWH is peace
    "יהוה צדקנו",  # YHWH our righteousness
    "יהוה",        # YHWH (без префиксов)
    "אלוה",        # Eloah (Иов и др.)
    "אלהים",       # Elohim
    "אלהי",        # Elohai + суффиксы (אלהיך/אלהיכם/אלהינו/אלהיו ловятся префиксом)
    "אדני",        # Adonai
    "יה",          # Yah
]

# ============================================================
# 3. WAW-CONSECUTIVE ГЛАГОЛЫ
# ============================================================
WAW_VERBS = [
    "ויאמר", "וידבר", "וירא", "ויצו", "וישמע", 
    "ויקרא", "ויעש", "ויברך", "ויחר", "ויכה"
]
SPEECH_VERBS = frozenset(["ויאמר", "וידבר"])

# ============================================================
# КОМПИЛЯЦИЯ REGEX
# ============================================================
_names_pat = "|".join(re.escape(n) for n in GOD_NAMES)
_verbs_pat = "|".join(re.escape(v) for v in WAW_VERBS)

SUBJECT_RE = re.compile(
    rf'(?<!\S)(?P<verb>{_verbs_pat})\s+(?P<name>{_names_pat})(?!\S)',
    re.UNICODE,
)

# ============================================================
# 4. ИЗВЛЕЧЕНИЕ ПРЯМОЙ РЕЧИ БОГА
# ============================================================
def _make_niqqud_pattern(word: str) -> str:
    niq = r'[\u0591-\u05C7]*'
    return niq + niq.join(re.escape(c) for c in word) + niq

def extract_god_speech(text_plain: str, text_original: str, verb_match: re.Match) -> str:
    if verb_match.group("verb") not in SPEECH_VERBS:
        return ""
    after_plain = text_plain[verb_match.end():].strip()
    if not after_plain:
        return ""
    words = after_plain.split()
    if not words:
        return ""
    pattern = r'(?<!\S)' + _make_niqqud_pattern(words[0])
    m = re.search(pattern, text_original, re.UNICODE)
    if m:
        return text_original[m.start():].strip()
    return after_plain

# ============================================================
# 5. ИТЕРАТОР СТИХОВ
# ============================================================
def iter_verses(book_path: Path, book_name: str):
    try:
        with open(book_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [ОШИБКА] {book_path.name}: {e}")
        return

    for verse_obj in data.get("verses", []):
        text_original = verse_obj.get("text_clean") or verse_obj.get("text_he", "")
        text_plain    = verse_obj.get("text_plain") or strip_niqqud(text_original)
        if len(text_plain) < 5:
            continue
        yield {
            "book":          book_name,
            "chapter":       verse_obj.get("chapter"),
            "verse":         verse_obj.get("verse"),
            "text_original": text_original,
            "text_plain":    text_plain,
        }

# ============================================================
# 6. ОСНОВНОЙ ЦИКЛ
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Прогон только по первой книге")
    args = parser.parse_args()

    index_file = TANAKH_DIR / "_index.json"
    if not index_file.exists():
        print("ОШИБКА: Сначала запусти download_tanakh.py")
        sys.exit(1)

    with open(index_file, encoding="utf-8") as f:
        book_index = json.load(f)

    if args.test:
        print("[DRY-RUN] Режим тестирования: обработка только первой книги")
        first_key = list(book_index.keys())[0]
        book_index = {first_key: book_index[first_key]}

    contacts   = []
    total_vers = 0

    for book_name, book_path in book_index.items():
        book_path = Path(book_path)
        if not book_path.exists():
            continue

        book_hits = 0
        for verse in iter_verses(book_path, book_name):
            total_vers += 1
            m = SUBJECT_RE.search(verse["text_plain"])
            if not m:
                continue

            matched_verb = m.group("verb")
            matched_name = m.group("name")
            god_speech   = extract_god_speech(verse["text_plain"], verse["text_original"], m)

            contacts.append({
                "id":           f"{book_name}_{verse['chapter']}_{verse['verse']}",
                "book":         book_name,
                "chapter":      verse["chapter"],
                "verse":        verse["verse"],
                "text_he":      verse["text_original"],
                "text_plain":   verse["text_plain"],
                "matched_verb": matched_verb,
                "matched_name": matched_name,
                "god_speech":   god_speech,
            })
            book_hits += 1

        if book_hits > 0:
            print(f"  {book_name:<25}: {book_hits:>4} ситуаций")

    if not args.test:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(contacts, f, ensure_ascii=False, indent=2)
        print(f"\nСохранено в файл: {OUTPUT_FILE}")
    else:
        print("\n[DRY-RUN] Тестовое извлечение завершено. Файлы не сохранены.")

    print(f"Ситуаций извлечено: {len(contacts)}")

if __name__ == "__main__":
    main()
