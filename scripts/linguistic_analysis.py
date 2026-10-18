"""
Лингвистический анализ прямой речи Бога в Танахе.
"""
import json, re, sys, argparse
from pathlib import Path
from collections import Counter
import stanza
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

def strip_diacritics(text: str) -> str:
    return re.sub(r'[\u0591-\u05C7\u05F3\u05F4]', '', text)

REGISTRY_FILE = Path(_REPO + "/output/situations_registry.json")
OUTPUT = Path(_REPO + "/output")

def freq_by_root(root_stripped: str, freq_dict: Counter) -> int:
    total = 0
    for k, v in freq_dict.items():
        k_stripped = strip_diacritics(k)
        if k_stripped == root_stripped or k_stripped.startswith(root_stripped + '\u05BE') or k_stripped.endswith('\u05BE' + root_stripped):
            total += v
    return total

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN limit 10")
    args = parser.parse_args()

    if not REGISTRY_FILE.exists():
        print(f"ОШИБКА: {REGISTRY_FILE} не найден.")
        sys.exit(1)

    with open(REGISTRY_FILE, encoding="utf-8") as f:
        situations = json.load(f)

    god_speech_texts = [
        s["text_he"] for s in situations
        if s.get("who_initiated") == "God" and s.get("text_he")
    ]

    print(f"Текстов прямой речи Бога: {len(god_speech_texts)}")
    
    # FAIL FAST
    if not god_speech_texts:
        print("ОШИБКА: Массив текстов прямой речи пуст! Fail-Fast.")
        sys.exit(1)

    if args.test:
        god_speech_texts = god_speech_texts[:10]
        print("[DRY-RUN] Режим тестирования. Обрабатываем первые 10 текстов.")

    print("Загружаем Hebrew NLP pipeline...")
    try:
        nlp = stanza.Pipeline("he", processors="tokenize,pos,lemma", logging_level="ERROR")
        USE_NLP = True
    except Exception as e:
        print(f"Stanza недоступна: {e}. Используем базовый токенайзер.")
        USE_NLP = False

    all_words = []
    all_lemmas = []
    pos_counts = Counter()

    MUNT = re.compile(r'^[\u05BE\u0591-\u05C7\u0591-\u05AF]+$')

    if USE_NLP:
        combined_text = " ".join(god_speech_texts)
        if combined_text.strip():
            doc = nlp(combined_text)
            for sentence in doc.sentences:
                for word in sentence.words:
                    stripped = strip_diacritics(word.text)
                    if not re.search(r'[\u05D0-\u05EA]', stripped):
                        continue
                    all_words.append(word.text)
                    if word.lemma and re.search(r'[\u05D0-\u05EA]', strip_diacritics(word.lemma)):
                        all_lemmas.append(word.lemma)
                    pos_counts[word.upos] += 1
    else:
        for text in god_speech_texts:
            words = re.findall(r'[\u0590-\u05FF]+', text)
            all_words.extend(words)
        all_lemmas = all_words

    word_freq = Counter(all_words)
    lemma_freq = Counter(all_lemmas)

    god_speech_stripped = [strip_diacritics(t) for t in god_speech_texts]

    DIVINE_CONSTRUCTIONS = {
        "формулы откровения": { "meaning": "И сказал YHWH", "count": sum(1 for t in god_speech_stripped if "ויאמר" in t) },
        "формула самоидентификации": { "meaning": "Я — YHWH", "count": sum(1 for t in god_speech_stripped if "אני" in t) },
        "императивные повеления": { "meaning": "Иди / Делай / Возьми", "count": sum(1 for t in god_speech_stripped if any(w in t for w in ["לך", "עשה", "קח"])) },
        "угрозы и предупреждения": { "meaning": "Ибо если (условная угроза)", "count": sum(1 for t in god_speech_stripped if "כי" in t) },
        "формула благословения": { "meaning": "И благословлю тебя", "count": sum(1 for t in god_speech_stripped if "ברך" in t or "ברכתי" in t) },
        "вопросительные конструкции": { "meaning": "Где? / Почему?", "count": sum(1 for t in god_speech_stripped if "איה" in t or "מדוע" in t) }
    }

    unique_divine_words = [
        {"word": "אהיה", "meaning": "Я есмь / Я буду", "frequency": freq_by_root("אהיה", word_freq)},
        {"word": "קדוש", "meaning": "Святой", "frequency": freq_by_root("קדוש", word_freq)},
        {"word": "שכינה", "meaning": "Присутствие Бога", "frequency": sum(1 for t in god_speech_stripped if "שכינה" in t)},
        {"word": "כבוד", "meaning": "Слава", "frequency": freq_by_root("כבוד", word_freq)},
        {"word": "חסד", "meaning": "Милость/Благодать", "frequency": freq_by_root("חסד", word_freq)},
        {"word": "אמת", "meaning": "Истина/Верность", "frequency": freq_by_root("אמת", word_freq)},
        {"word": "צדקה", "meaning": "Праведность", "frequency": freq_by_root("צדקה", word_freq)},
        {"word": "שלום", "meaning": "Мир/Целостность", "frequency": freq_by_root("שלום", word_freq)},
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

    if not args.test:
        with open(OUTPUT / "god_vocabulary.json", "w", encoding="utf-8") as f:
            json.dump(vocabulary, f, ensure_ascii=False, indent=2)

        with open(OUTPUT / "speech_patterns.json", "w", encoding="utf-8") as f:
            json.dump(speech_patterns, f, ensure_ascii=False, indent=2)

        print(f"\nЛингвистический анализ завершён!")
    else:
        print("\n[DRY-RUN] Тест успешно завершён. Файлы не перезаписались.")

    print(f"Слов проанализировано: {len(all_words)}")
    print(f"Уникальных слов: {len(set(all_words))}")

if __name__ == "__main__":
    main()
