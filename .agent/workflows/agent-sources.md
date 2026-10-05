---
description: Source Hypothesis — классификация ситуаций по источникам J/E/D/P + психопрофиль в разрезе источников
---

# /agent-sources — Источниковая гипотеза J/E/D/P

## Контекст
Задача: `sources-001`
Зависит от: `registry-001` (done)
Выходные файлы: `output/source_hypothesis.json`, `output/god_profile_by_source.json`

## Данные
- `C:/GOD2/output/situations_coded.json` — реестр с behavior_type
- `C:/GOD2/data/tanakh/*.json` — тексты книг
- `C:/GOD2/output/god_profile.json` — базовый психопрофиль

## Шаг 1 — Создать `scripts/source_analysis.py`

### Правила классификации источников:

```python
# Первичная классификация по книге
BOOK_SOURCE = {
    "Deuteronomy": "D",
    "Leviticus":   "P",
    "Numbers":     "P",  # большая часть
}

# Вторичная по имени Бога в тексте
def classify_source(text_he, text_plain, book):
    if book in BOOK_SOURCE:
        return BOOK_SOURCE[book]
    
    yhwh_count  = text_he.count("יהוה") + text_plain.count("יהוה")
    elohim_count = text_he.count("אלהים") + text_plain.count("אלהים")
    
    # Антропоморфные маркеры (J-источник)
    anthropomorphic = any(m in text_he for m in [
        "וילך", "וירד", "ויאמר אל", "רוח", "פנים"
    ])
    
    if elohim_count > yhwh_count and not anthropomorphic:
        return "E"  # Элогистический — трансцендентный
    elif anthropomorphic or yhwh_count > elohim_count:
        return "J"  # Яхвистский — антропоморфный
    return "unclear"
```

### Выход `source_hypothesis.json`:
Обновлённый `situations_coded.json` с добавленным полем `source` (J/E/D/P).

### Выход `god_profile_by_source.json`:
Для каждого источника отдельный психопрофиль:
```json
{
  "J": {"behavior_type_dist": {...}, "avg_severity": ..., "dominant_trigger": ...},
  "E": {"behavior_type_dist": {...}, "avg_severity": ..., "dominant_trigger": ...},
  "D": {"behavior_type_dist": {...}, "avg_severity": ..., "dominant_trigger": ...},
  "P": {"behavior_type_dist": {...}, "avg_severity": ..., "dominant_trigger": ...}
}
```

## Шаг 2 — Запустить
```powershell
cd C:\GOD2
python scripts\source_analysis.py
```

## Шаг 3 — Сигнал завершения
```powershell
Set-Content "C:\GOD2\.agent\signals\sources-001.done" "done"
```

## Завершение
Задача выполнена когда существуют:
- `output/source_hypothesis.json`
- `output/god_profile_by_source.json`
