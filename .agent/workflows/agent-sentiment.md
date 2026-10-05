---
description: Sentiment Analysis — эмоциональная кривая речи Бога по книгам Танаха
---

# /agent-sentiment — Анализ тональности речи Бога

## Контекст
Задача: `sentiment-001`
Зависит от: `psych-001` (done) — `output/situations_coded.json` уже существует
Выходные файлы: `output/sentiment_timeline.json`, `output/sentiment_by_book.json`

## Данные
- Основной вход: `C:/GOD2/output/situations_coded.json`
- Поля для анализа: `god_action`, `behavior_type`, `severity`, `book`
- Дополнительно: `output/speech_patterns.json` (риторические паттерны)

## Шаг 1 — Установить зависимости
```powershell
pip install vaderSentiment
```

## Шаг 2 — Создать скрипт `scripts/sentiment_analysis.py`

Логика:
1. Для каждой ситуации вычислить `sentiment_score`:
   - Базовая оценка из `behavior_type`: punishment=-2, salvation=+2, covenant=+1, command=0, question=-0.5
   - Модификатор severity: severity 5 → -1.5, severity 1 → +0.5
   - Если `god_action` заполнен → запустить VADER на тексте
2. Агрегировать по книгам → `sentiment_by_book.json`
3. Агрегировать по хронологии (Genesis→Malachi) → `sentiment_timeline.json`

Полярность иврит-лексики (добавить вручную):
```python
HEBREW_POLARITY = {
    "חסד": +2,   # милость
    "אהב": +2,   # любовь
    "ברך": +2,   # благословение
    "קנא": -1.5, # ревность
    "אף":  -2,   # гнев
    "שחת": -3,   # уничтожение
    "שלום": +2,  # мир
    "טוב":  +1,  # хорошо
}
```

4. Сохранить результаты:
   - `output/sentiment_timeline.json` — список: `{book, chapter, avg_sentiment, dominant_emotion}`
   - `output/sentiment_by_book.json` — сводка по книгам

## Шаг 3 — Создать сигнал завершения
```powershell
New-Item -Path "C:\GOD2\.agent\signals" -ItemType Directory -Force
Set-Content "C:\GOD2\.agent\signals\sentiment-001.done" "done"
```

## Шаг 4 — Отчёт координатору
```powershell
# Запустить скрипт для отправки статуса (если есть msg.ps1)
# Иначе просто создать сигнал выше
```

## Завершение
Задача считается выполненной когда существуют оба файла:
- `output/sentiment_timeline.json`
- `output/sentiment_by_book.json`
