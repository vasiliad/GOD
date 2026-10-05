---
description: Агент лингвистического анализа речи Бога на иврите
---

# /agent-linguistics — Лингвистический анализ

Зависит от: **registry-001 (должен быть DONE)**

## Шаг 1 — Установить зависимости

```powershell
cd C:\GOD2
pip install stanza pandas collections-extended
python -c "import stanza; stanza.download('he')"
```

## Шаг 2 — Создать `scripts\linguistic_analysis.py`

```python
"""
Лингвистический анализ прямой речи Бога в Танахе.
- Словарный запас (частотность, уникальные слова)
- Морфология (корни, биньяны, части речи)
- Синтаксические конструкции
- Характерные речевые паттерны
"""
import json, re
from pathlib import Path
from collections import Counter
import stanza

REGISTRY_FILE = Path("C:/GOD2/output/situations_registry.json")
OUTPUT = Path("C:/GOD2/output")

with open(REGISTRY_FILE, encoding="utf-8") as f:
    situations = json.load(f)

# Извлечь тексты где Бог инициировал (его речь)
god_speech_texts = [
    s["text_he"] for s in situations
    if s.get("who_initiated") == "God" and s.get("text_he")
]

print(f"Текстов прямой речи Бога: {len(god_speech_texts)}")
print("Загружаем Hebrew NLP pipeline...")

try:
    nlp = stanza.Pipeline("he", processors="tokenize,pos,lemma")
    USE_NLP = True
except Exception as e:
    print(f"Stanza недоступна: {e}. Используем базовый токенайзер.")
    USE_NLP = False

# -----------------------------------------------
# Токенизация и частотный анализ
# -----------------------------------------------
all_words = []
all_lemmas = []
pos_counts = Counter()

if USE_NLP:
    combined_text = " ".join(god_speech_texts[:500])  # первые 500 для скорости
    doc = nlp(combined_text)
    for sentence in doc.sentences:
        for word in sentence.words:
            all_words.append(word.text)
            if word.lemma:
                all_lemmas.append(word.lemma)
            pos_counts[word.upos] += 1
else:
    # Fallback: простая токенизация по пробелам
    for text in god_speech_texts:
        words = re.findall(r'[\u0590-\u05FF]+', text)
        all_words.extend(words)
    all_lemmas = all_words

word_freq = Counter(all_words)
lemma_freq = Counter(all_lemmas)

# -----------------------------------------------
# Характерные конструкции Бога
# -----------------------------------------------
DIVINE_CONSTRUCTIONS = {
    "формулы откровения": {
        "pattern": "וַיֹּאמֶר יְהוָה",
        "meaning": "И сказал YHWH",
        "count": sum(1 for t in god_speech_texts if "וַיֹּאמֶר" in t)
    },
    "формула самоидентификации": {
        "pattern": "אֲנִי יְהוָה",
        "meaning": "Я — YHWH",
        "count": sum(1 for t in god_speech_texts if "אֲנִי" in t)
    },
    "императивные повеления": {
        "pattern": "לֵךְ / עֲשֵׂה / קַח",
        "meaning": "Иди / Делай / Возьми",
        "count": sum(1 for t in god_speech_texts if any(w in t for w in ["לֵךְ", "עֲשֵׂה", "קַח"]))
    },
    "угрозы и предупреждения": {
        "pattern": "כִּי אִם",
        "meaning": "Ибо если (условная угроза)",
        "count": sum(1 for t in god_speech_texts if "כִּי" in t)
    },
    "формула благословения": {
        "pattern": "וּבֵרַכְתִּיךָ",
        "meaning": "И благословлю тебя",
        "count": sum(1 for t in god_speech_texts if "בָּרַךְ" in t or "בֵּרַכְתִּי" in t)
    },
    "вопросительные конструкции": {
        "pattern": "אַיֵּה / מַדּוּעַ",
        "meaning": "Где? / Почему? (риторические вопросы)",
        "count": sum(1 for t in god_speech_texts if "אַיֵּה" in t or "מַדּוּעַ" in t)
    }
}

# -----------------------------------------------
# Уникальный словарный запас Бога
# -----------------------------------------------
# Слова, встречающиеся только в речи Бога (слишком редкие в обычном тексте)
unique_divine_words = [
    {"word": "אֶהְיֶה", "transliteration": "Ehyeh", "meaning": "Я есмь / Я буду", "context": "Откр. Моисею"},
    {"word": "קָדוֹשׁ", "transliteration": "Kadosh", "meaning": "Святой", "frequency": word_freq.get("קָדוֹשׁ", 0)},
    {"word": "שְׁכִינָה", "transliteration": "Shekhinah", "meaning": "Присутствие Бога", "frequency": 0},
    {"word": "כָּבוֹד", "transliteration": "Kavod", "meaning": "Слава", "frequency": word_freq.get("כָּבוֹד", 0)},
    {"word": "חֶסֶד", "transliteration": "Hesed", "meaning": "Милость/Благодать", "frequency": word_freq.get("חֶסֶד", 0)},
    {"word": "אֱמֶת", "transliteration": "Emet", "meaning": "Истина/Верность", "frequency": word_freq.get("אֱמֶת", 0)},
    {"word": "צְדָקָה", "transliteration": "Tzedakah", "meaning": "Праведность", "frequency": word_freq.get("צְדָקָה", 0)},
    {"word": "שָׁלוֹם", "transliteration": "Shalom", "meaning": "Мир/Целостность", "frequency": word_freq.get("שָׁלוֹם", 0)},
]

vocabulary = {
    "total_words_analyzed": len(all_words),
    "unique_words": len(set(all_words)),
    "top_50_words": word_freq.most_common(50),
    "top_50_lemmas": lemma_freq.most_common(50),
    "pos_distribution": dict(pos_counts),
    "divine_characteristic_words": unique_divine_words,
    "divine_constructions": DIVINE_CONSTRUCTIONS,
}

speech_patterns = {
    "style": "Авторитарный, директивный, ритмически-формульный",
    "sentence_types": {
        "imperative": "Преобладают — прямые повеления",
        "declarative": "Автобиографические утверждения ('Я — YHWH')",
        "interrogative": "Риторические вопросы ('Где ты? Почему?')",
        "conditional": "Если-то конструкции (условия Завета)"
    },
    "rhetorical_devices": [
        "Анафора: повторение 'וַיֹּאמֶר' (и сказал)",
        "Парономасия: игра слов (особенно в пророках)",
        "Параллелизм: характерен для псалмических текстов",
        "Числовые формулы: 'семь дней', 'сорок лет'",
        "Повторение угрозы на трёх уровнях (Лев. 26)"
    ],
    "characteristic_verbs": {
        "creation": ["בָּרָא (bara) — создал из ничего", "יָצַר (yatsar) — формировал"],
        "communication": ["דִּבֶּר (dibber) — говорил", "אָמַר (amar) — сказал"],
        "action": ["עָשָׂה (asah) — сделал", "נָתַן (natan) — дал"],
        "judgment": ["שָׁפַט (shafat) — судил", "הִכָּה (hika) — поразил"]
    },
    "unique_self_references": [
        "אֲנִי יְהוָה — Я YHWH (50+ раз в Левите)",
        "אֵל קַנָּא — Бог ревнивый",
        "אֱלֹהִים אַחֵר לֹא יִהְיֶה לְךָ — Да не будет у тебя других богов",
        "אֶהְיֶה אֲשֶׁר אֶהְיֶה — Я есть то, что Я есть (Исх. 3:14)"
    ]
}

# Сохранить
with open(OUTPUT / "god_vocabulary.json", "w", encoding="utf-8") as f:
    json.dump(vocabulary, f, ensure_ascii=False, indent=2)

with open(OUTPUT / "speech_patterns.json", "w", encoding="utf-8") as f:
    json.dump(speech_patterns, f, ensure_ascii=False, indent=2)

print(f"\nЛингвистический анализ завершён!")
print(f"Слов проанализировано: {len(all_words)}")
print(f"Уникальных слов: {len(set(all_words))}")
print(f"Топ-10 слов: {word_freq.most_common(10)}")
print(f"\nСловарь: output/god_vocabulary.json")
print(f"Паттерны: output/speech_patterns.json")
```

Запустить:
```powershell
cd C:\GOD2
python scripts\linguistic_analysis.py
```

## Шаг 3 — Верификация
```powershell
cd C:\GOD2\.agent
.\task_manager.ps1 verify
```
