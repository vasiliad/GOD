"""
linguistics-002: концептуальный анализ речи Бога.
Нормализует кантилляцию и считает ключевые богословские концепты:
חסד (милость), אף (гнев), אמת (истина), שלום (мир), קנא (ревность) и др.

Вход:  output/situations_coded.json
Выход: output/concept_analysis.json
"""
import json
import sys
import unicodedata
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

CODED  = Path("C:/GOD2/output/situations_coded.json")
OUTPUT = Path("C:/GOD2/output/concept_analysis.json")

with open(CODED, encoding="utf-8") as f:
    situations = json.load(f)

total = len(situations)
print(f"Загружено: {total} ситуаций")

# ============================================================
# Нормализация кантилляции — убираем диакритику/огласовки
# чтобы корень אמר и אָמַר считались одним словом
# ============================================================
def strip_cantillation(text: str) -> str:
    """Убирает все Unicode combining characters (огласовки и кантилляция)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) not in ("Mn", "Me")  # Non-spacing / Enclosing marks
    )

# ============================================================
# БОГОСЛОВСКИЕ КОНЦЕПТЫ
# Каждый концепт: базовый корень + все варианты написания без огласовок
# ============================================================
CONCEPTS = {
    # Атрибуты Бога
    "חסד":  {"label": "Милость/Верная любовь (hesed)", "polarity": +2,
              "variants": ["חסד", "חסדי", "חסדך", "חסדו", "חסדים"]},
    "אמת":  {"label": "Истина/Верность (emet)",        "polarity": +2,
              "variants": ["אמת", "אמתך", "באמת"]},
    "שלום": {"label": "Мир/Благополучие (shalom)",     "polarity": +2,
              "variants": ["שלום", "שלומך", "בשלום"]},
    "ברכה": {"label": "Благословение (berakha)",        "polarity": +2,
              "variants": ["ברכה", "ברך", "ברכת", "ויברך"]},
    "אהב":  {"label": "Любовь (ahav)",                  "polarity": +2,
              "variants": ["אהב", "אהבת", "אהבתי", "אהבתך"]},

    # Реакции гнева
    "אף":   {"label": "Гнев/Ноздри (af)",              "polarity": -2,
              "variants": ["אף", "אפו", "אפי", "באפו"]},
    "חמה":  {"label": "Ярость (hema)",                  "polarity": -2,
              "variants": ["חמה", "חמתי", "חמתו"]},
    "קנא":  {"label": "Ревность/Зависть (kina)",        "polarity": -1.5,
              "variants": ["קנא", "קנאה", "קנאתי", "אל קנא"]},
    "שנא":  {"label": "Ненависть (sane)",               "polarity": -2,
              "variants": ["שנא", "שנאתי", "שנאו"]},

    # Действия
    "שפט":  {"label": "Суд/Справедливость (shafat)",   "polarity": 0,
              "variants": ["שפט", "ישפט", "משפט", "שפטים"]},
    "גאל":  {"label": "Избавление/Искупление (gaal)",  "polarity": +2,
              "variants": ["גאל", "גאלתי", "גואל"]},
    "נחם":  {"label": "Сожаление/Утешение (naham)",    "polarity": 0,
              "variants": ["נחם", "ינחם", "וינחם", "נחמתי"]},
    "זכר":  {"label": "Память/Помнить (zakhar)",       "polarity": +1,
              "variants": ["זכר", "זכרתי", "יזכר", "זכרון"]},

    # Завет
    "ברית": {"label": "Завет (brit)",                  "polarity": +1.5,
              "variants": ["ברית", "בריתי", "בריתך", "ויכרת"]},
}

# ============================================================
# ОСНОВНОЙ ПОДСЧЁТ
# ============================================================
concept_counts_total  = Counter()
concept_counts_by_book = {}
concept_by_behavior   = {}  # concept → Counter(behavior_type)

for s in situations:
    text_raw  = s.get("text_plain", "") + " " + s.get("text_he", "")
    text_norm = strip_cantillation(text_raw)
    book      = s.get("book", "unknown")
    btype     = s.get("behavior_type", "other")

    if book not in concept_counts_by_book:
        concept_counts_by_book[book] = Counter()

    for concept, data in CONCEPTS.items():
        found = any(v in text_norm for v in data["variants"])
        if found:
            concept_counts_total[concept] += 1
            concept_counts_by_book[book][concept] += 1
            if concept not in concept_by_behavior:
                concept_by_behavior[concept] = Counter()
            concept_by_behavior[concept][btype] += 1

print(f"\nЧастота концептов (всего):")
for c, cnt in concept_counts_total.most_common():
    pct = cnt / total * 100
    label = CONCEPTS[c]["label"]
    print(f"  {c}  {cnt:>5}  ({pct:.1f}%)  — {label}")

# ============================================================
# СООТНОШЕНИЕ ГНЕВ / МИЛОСТЬ
# ============================================================
anger_total = sum(concept_counts_total[c]
                  for c, d in CONCEPTS.items() if d["polarity"] <= -1.5)
mercy_total = sum(concept_counts_total[c]
                  for c, d in CONCEPTS.items() if d["polarity"] >= 2)
total_both  = max(anger_total + mercy_total, 1)

print(f"\nМилость: {mercy_total} ({mercy_total/total_both*100:.1f}%)")
print(f"Гнев:    {anger_total} ({anger_total/total_both*100:.1f}%)")

# ============================================================
# ТОП КНИГИ ПО КАЖДОМУ КОНЦЕПТУ
# ============================================================
def top_books(concept, n=5):
    return [
        {"book": b, "count": cnt}
        for b, cnt in concept_counts_by_book.items()
        if concept in concept_counts_by_book[b]
        for cnt in [concept_counts_by_book[b][concept]]
        if cnt > 0
    ]

def top_books_sorted(concept, n=5):
    ranked = sorted(
        [(b, concept_counts_by_book[b].get(concept, 0)) for b in concept_counts_by_book],
        key=lambda x: -x[1]
    )
    return [{"book": b, "count": c} for b, c in ranked[:n] if c > 0]

# ============================================================
# ИТОГОВЫЙ JSON
# ============================================================
result = {
    "metadata": {
        "total_situations": total,
        "normalization": "Unicode NFD + strip combining marks (Mn,Me)",
        "concepts_analyzed": list(CONCEPTS.keys()),
    },
    "anger_mercy_ratio": {
        "mercy": mercy_total,
        "anger": anger_total,
        "mercy_pct": round(mercy_total / total_both * 100, 1),
        "anger_pct": round(anger_total / total_both * 100, 1),
        "verdict": "Преобладает милость" if mercy_total > anger_total else "Преобладает гнев",
    },
    "concept_frequencies": {
        c: {
            "label": CONCEPTS[c]["label"],
            "polarity": CONCEPTS[c]["polarity"],
            "count": concept_counts_total[c],
            "pct": round(concept_counts_total[c] / total * 100, 2),
            "top_books": top_books_sorted(c),
            "by_behavior_type": dict(concept_by_behavior.get(c, {})),
        }
        for c in CONCEPTS
    },
    "top_concepts_by_book": {
        book: [
            {"concept": c, "label": CONCEPTS[c]["label"], "count": cnt}
            for c, cnt in data.most_common(5) if cnt > 0
        ]
        for book, data in sorted(concept_counts_by_book.items())
        if sum(data.values()) > 0
    }
}

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\nВыход: {OUTPUT}")
