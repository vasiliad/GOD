"""
corpus_meta.py
Единая карта книг: эпоха и жанр. Используется профилем поведения (god_profile.py),
калибровкой (eval_profile.py) и витриной на странице.

Зачем это отдельным файлом: без разбивки по эпохе и жанру «профиль Бога» смешивает
разные регистры — Закон, пророческая речь, псалмодия, притча. Именно из-за этого
молчание в поэзии (27 %) и молчание в нарративе (3 %) нельзя читать как одно и то же.

Эпохи — как в scripts/analytics_v2.py (BOOK_ORDER), чтобы отчёт и профиль считались
по одной разметке.
Жанр — рабочая типология для проекта (в танахической науке жанровые деления шире;
здесь важна воспроизводимость и единый источник правды):

    law       — Тора кроме Бытия: закон, постановления, обряды
    narrative — повествование: Бытие, Исход-Иисус Навина, книги Samuel/Kings/Chronicles,
                Ездра/Неемия, Руфь, Есфирь, Даниил
    prophecy  — большие и малые пророки
    poetry    — Псалмы, Плач, Песнь песней
    wisdom    — Притчи, Екклесиаст, Иов

Не найденная книга → жанр "other", эпоха "other" (не молчаливый пропуск: так видно
объём неучтённого материала).
"""
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])

# ── Эпохи (как в analytics_v2.py) ─────────────────────────────────────────────
ERA_ORDER = [
    ("Тора", ["genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]),
    ("Невиим (ранние)", ["Joshua", "Judges", "I_Samuel", "II_Samuel", "I_Kings", "II_Kings"]),
    ("Невиим (поздние)", ["Isaiah", "Jeremiah", "Ezekiel", "Hosea", "Joel", "Amos",
                          "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk",
                          "Zephaniah", "Haggai", "Zechariah", "Malachi"]),
    ("Кетувим", ["Psalms", "Proverbs", "Job", "Song_of_Songs", "Ruth", "Lamentations",
                 "Ecclesiastes", "Esther", "Daniel", "Ezra", "Nehemiah",
                 "I_Chronicles", "II_Chronicles"]),
]

# ── Жанры ────────────────────────────────────────────────────────────────────
GENRE_ORDER = [
    ("law", ["Exodus", "Leviticus", "Numbers", "Deuteronomy"]),
    ("narrative", ["genesis", "Joshua", "Judges", "I_Samuel", "II_Samuel", "I_Kings",
                   "II_Kings", "Ruth", "Esther", "Ezra", "Nehemiah", "I_Chronicles",
                   "II_Chronicles", "Daniel"]),
    ("prophecy", ["Isaiah", "Jeremiah", "Ezekiel", "Hosea", "Joel", "Amos", "Obadiah",
                  "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai",
                  "Zechariah", "Malachi"]),
    ("poetry", ["Psalms", "Lamentations", "Song_of_Songs"]),
    ("wisdom", ["Proverbs", "Ecclesiastes", "Job"]),
]

# Группы адресата: кому Бог говорит (из addressee_type реестра)
ADDRESSEE_GROUPS = {
    "nation": ["nation"],
    "individual": ["individual", "patriarch", "family"],
    "foreign": ["foreign_individual"],
    "collective": ["humanity", "self"],
}


def _invert(order):
    out = {}
    for key, books in order:
        for b in books:
            out[b] = key
    return out


ERA_BY_BOOK = _invert(ERA_ORDER)
GENRE_BY_BOOK = _invert(GENRE_ORDER)

# Единый список книг корпуса (39) — для самопроверок и для страницы.
ALL_BOOKS = [b for _, books in ERA_ORDER for b in books]


def era_of(book):
    """Эпоха книги; 'other', если книга не размечена."""
    return ERA_BY_BOOK.get(book, "other")


def genre_of(book):
    """Жанр книги; 'other', если книга не размечена."""
    return GENRE_BY_BOOK.get(book, "other")


def addressee_group(addressee_type):
    """Группа адресата: nation / individual / foreign / collective / other."""
    if not addressee_type:
        return "other"
    for group, members in ADDRESSEE_GROUPS.items():
        if addressee_type in members:
            return group
    return "other"


def selftest():
    ok = True
    checks = []

    def chk(name, cond):
        nonlocal ok
        checks.append(bool(cond))
        if not cond:
            ok = False
        print(("PASS" if cond else "FAIL") + "  " + name)

    chk("39 книг в эпохах", len(ALL_BOOKS) == 39)
    chk("эпохи не пересекаются", len(set(ALL_BOOKS)) == len(ALL_BOOKS))
    chk("жанры не пересекаются", len(set(sum((b for _, b in GENRE_ORDER), []))) ==
        len(sum((b for _, b in GENRE_ORDER), [])))
    chk("каждая книга имеет эпоху", all(era_of(b) != "other" for b in ALL_BOOKS))
    chk("каждая книга имеет жанр", all(genre_of(b) != "other" for b in ALL_BOOKS))
    chk("Бытие — повествование, Тора", genre_of("genesis") == "narrative" and era_of("genesis") == "Тора")
    chk("Исход — закон", genre_of("Exodus") == "law")
    chk("Псалмы — поэзия", genre_of("Psalms") == "poetry")
    chk("Иов — мудрость", genre_of("Job") == "wisdom")
    chk("Исаия — пророчество", genre_of("Isaiah") == "prophecy")
    chk("неизвестная книга → other", era_of("Нету") == "other" and genre_of("Нету") == "other")
    chk("адресат: нация", addressee_group("nation") == "nation")
    chk("адресат: индивид/патриарх/семья → individual",
        addressee_group("individual") == "individual" and
        addressee_group("patriarch") == "individual" and
        addressee_group("family") == "individual")
    chk("адресат: иноплеменник → foreign", addressee_group("foreign_individual") == "foreign")
    chk("адресат: неизвестный → other", addressee_group("xyz") == "other")
    print("\nSELFTEST: %s (%d/%d)" % ("PASS" if ok else "FAIL", sum(checks), len(checks)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
