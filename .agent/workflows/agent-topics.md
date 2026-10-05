---
description: Topic Modeling — тематическое моделирование законодательных текстов (Левит, Второзаконие, Иов)
---

# /agent-topics — Topic Modeling

## Контекст
Задача: `topics-001`
Зависит от: `data-001` (done) — тексты Танаха готовы
Выходные файлы: `output/topics_leviticus.json`, `output/topics_deuteronomy.json`, `output/topics_profile.json`

## Зависимости
```powershell
pip install gensim pyldavis
```

## Шаг 1 — Создать `scripts/topic_modeling.py`

### Алгоритм:

```python
from gensim import corpora, models
import json

BOOKS_TO_ANALYZE = {
    "Leviticus": "output/topics_leviticus.json",
    "Deuteronomy": "output/topics_deuteronomy.json",
    "Job": "output/topics_job.json",
}

# Стоп-слова иврита (частицы, предлоги)
HEBREW_STOPWORDS = [
    "ו", "ה", "ב", "ל", "מ", "כ", "ש", "את", "אל",
    "על", "עם", "אשר", "כי", "לא", "אם", "כל",
]

def analyze_book(book_name, texts):
    # Токенизация (split по пробелам, убрать стоп-слова)
    cleaned = [
        [w for w in verse.split() if w not in HEBREW_STOPWORDS and len(w) > 2]
        for verse in texts if verse
    ]
    
    dictionary = corpora.Dictionary(cleaned)
    corpus = [dictionary.doc2bow(doc) for doc in cleaned]
    
    # LDA: 8 тем
    lda = models.LdaModel(corpus, num_topics=8, id2word=dictionary, passes=20)
    
    topics = []
    for idx, topic in lda.print_topics(num_words=10):
        topics.append({
            "topic_id": idx,
            "keywords": topic,
            "label": label_topic(topic),  # ручная маркировка
        })
    
    return topics

def label_topic(keywords):
    # Автоматическая маркировка по ключевым словам
    labels = {
        "ritual": ["קרבן", "עלה", "זבח", "מזבח", "כהן"],
        "social_justice": ["גר", "אביון", "יתום", "אלמנה", "עני"],
        "purity": ["טמא", "טהור", "נגע", "טהרה", "מצרע"],
        "punishment": ["מות", "כרת", "שרף", "סקל"],
        "covenant_law": ["חקה", "משפט", "מצוה", "תורה"],
    }
    for label, words in labels.items():
        if any(w in keywords for w in words):
            return label
    return "other"
```

### `topics_profile.json` — Обобщающий профиль:
```json
{
  "dominant_topics_in_gods_speech": [...],
  "ritual_vs_ethics_ratio": 0.6,
  "most_regulated_domains": ["ritual purity", "social justice", "punishment"],
  "thematic_distribution": {
    "Leviticus": {"ritual": 45, "punishment": 30, "purity": 25},
    "Deuteronomy": {"covenant_law": 40, "social_justice": 35, "punishment": 25},
    "Job": {"theodicy": 50, "suffering": 30, "cosmos": 20}
  }
}
```

## Шаг 2 — Запустить
```powershell
cd C:\GOD2
python scripts\topic_modeling.py
```

## Шаг 3 — Сигнал
```powershell
Set-Content "C:\GOD2\.agent\signals\topics-001.done" "done"
```

## Завершение
- `output/topics_leviticus.json`
- `output/topics_deuteronomy.json`
- `output/topics_profile.json`
