---
description: Агент сбора данных — скачивает Танах и DSS
---

# /agent-data — Сбор текстов

Ты агент сбора данных для проекта GOD2. Твоя задача — скачать и подготовить тексты Танаха и Кумранских свитков.

## Задачи: data-001, data-002, data-003

## Шаг 1 — Установить зависимости
```powershell
cd C:\GOD2
pip install requests tqdm
```

## Шаг 2 — Создать скрипты и запустить загрузку

Создай `C:\GOD2\scripts\download_tanakh.py` со следующим кодом:

```python
"""
Скачивает все книги Танаха на иврите через Sefaria API.
Сохраняет в data/tanakh/{book}.json
"""
import requests, json, os, time
from pathlib import Path

OUTPUT_DIR = Path("C:/GOD2/data/tanakh")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Все книги Танаха (39 книг)
TANAKH_BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "I Samuel", "II Samuel", "I Kings", "II Kings",
    "Isaiah", "Jeremiah", "Ezekiel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Psalms", "Proverbs", "Job", "Song of Songs", "Ruth", "Lamentations",
    "Ecclesiastes", "Esther", "Daniel", "Ezra", "Nehemiah",
    "I Chronicles", "II Chronicles"
]

BASE_URL = "https://www.sefaria.org/api/texts/{book}?lang=he&context=0"
index = {}

for book in TANAKH_BOOKS:
    out_file = OUTPUT_DIR / f"{book.replace(' ', '_')}.json"
    if out_file.exists():
        print(f"[SKIP] {book} already downloaded")
        index[book] = str(out_file)
        continue

    url = BASE_URL.format(book=requests.utils.quote(book))
    print(f"[FETCH] {book}...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        index[book] = str(out_file)
        print(f"  -> OK, {len(str(data))} chars")
        time.sleep(0.5)  # вежливо к API
    except Exception as e:
        print(f"  -> ERROR: {e}")

# Сохранить индекс
with open(OUTPUT_DIR / "_index.json", "w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False, indent=2)

print(f"\nДонвлоад завершён: {len(index)} книг")
print("Индекс: data/tanakh/_index.json")
```

Запустить:
```powershell
cd C:\GOD2
python scripts\download_tanakh.py
```

## Шаг 3 — Скачать DSS

Создай `C:\GOD2\scripts\download_dss.py`:

```python
"""
Скачивает доступные тексты Кумранских свитков.
Источник: The Comprehensive Aramaic Lexicon / открытый DSS корпус
"""
import requests, json, os
from pathlib import Path

OUTPUT_DIR = Path("C:/GOD2/data/dss")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Доступные через Sefaria DSS тексты
DSS_TEXTS = [
    "Dead Sea Scrolls, Community Rule",
    "Dead Sea Scrolls, War Scroll",
    "Dead Sea Scrolls, Thanksgiving Hymns",
    "Dead Sea Scrolls, Damascus Document",
    "Dead Sea Scrolls, Temple Scroll",
]

index = {}
BASE_URL = "https://www.sefaria.org/api/texts/{text}?lang=he&context=0"

for text in DSS_TEXTS:
    safe_name = text.replace(", ", "_").replace(" ", "_")
    out_file = OUTPUT_DIR / f"{safe_name}.json"
    url = BASE_URL.format(text=requests.utils.quote(text))
    print(f"[FETCH] {text}...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        index[text] = str(out_file)
        print(f"  -> OK")
    except Exception as e:
        print(f"  -> ERROR (возможно недоступно через Sefaria): {e}")
        # Создать заглушку
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump({"title": text, "text": [], "note": "not available via Sefaria API"}, f)
        index[text] = str(out_file)

with open(OUTPUT_DIR / "_index.json", "w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False, indent=2)

print(f"\nDSS загрузка завершена. Индекс: data/dss/_index.json")
```

Запустить:
```powershell
python scripts\download_dss.py
```

## Шаг 4 — Создать god_names.json

Создай `C:\GOD2\data\god_names.json` с полным списком 59 имён из SPEC.md (уже присутствует там).

Пример структуры файла:
```python
import json
from pathlib import Path

names = [
    {"hebrew": "יהוה", "transliteration": "YHWH", "meaning": "Сущий, Вечный"},
    {"hebrew": "אֱלֹהִים", "transliteration": "Elohim", "meaning": "Бог (мн.ч. величия)"},
    {"hebrew": "אֵל", "transliteration": "El", "meaning": "Бог, Сильный"},
    {"hebrew": "אֵל שַׁדַּי", "transliteration": "El Shaddai", "meaning": "Бог Всемогущий"},
    {"hebrew": "אֵל עֶלְיוֹן", "transliteration": "El Elyon", "meaning": "Бог Всевышний"},
    {"hebrew": "אֲדֹנָי", "transliteration": "Adonai", "meaning": "Господь"},
    {"hebrew": "יָהּ", "transliteration": "Yah", "meaning": "Сокращённое YHWH"},
    {"hebrew": "אֶהְיֶה אֲשֶׁר אֶהְיֶה", "transliteration": "Ehyeh Asher Ehyeh", "meaning": "Я есть то, что Я есть"},
    {"hebrew": "צְבָאוֹת", "transliteration": "Tzvaot", "meaning": "Воинств"},
    {"hebrew": "הַשֵּׁם", "transliteration": "HaShem", "meaning": "Имя"},
    # ... остальные 49 имён
]

Path("C:/GOD2/data").mkdir(parents=True, exist_ok=True)
with open("C:/GOD2/data/god_names.json", "w", encoding="utf-8") as f:
    json.dump(names, f, ensure_ascii=False, indent=2)
print("god_names.json создан")
```

Запустить этот Python код напрямую.

## Шаг 5 — Сигнал завершения

```powershell
cd C:\GOD2\.agent
.\task_manager.ps1 verify
```

Задачи data-001, data-002, data-003 должны стать DONE автоматически.
