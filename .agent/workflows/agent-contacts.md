---
description: Агент анализа контактов Бога и человека в текстах
---

# /agent-contacts — Извлечение контактов

Зависит от: **data-001, data-002, data-003 (должны быть DONE)**

Проверь наличие сигналов:
```powershell
Test-Path "C:\GOD2\.agent\signals\data-001.done"
Test-Path "C:\GOD2\.agent\signals\data-002.done"
Test-Path "C:\GOD2\.agent\signals\data-003.done"
```

## Шаг 1 — Установить зависимости
```powershell
cd C:\GOD2
pip install stanza pandas tqdm
```

## Шаг 2 — Создать `scripts\extract_contacts.py`

```python
"""
Извлекает эпизоды контакта Бога и человека из текстов Танаха.
Фильтрует: только прямое взаимодействие (диалог, явление, повеление, суд).
"""
import json, re
from pathlib import Path
from tqdm import tqdm

TANAKH_DIR = Path("C:/GOD2/data/tanakh")
DSS_DIR = Path("C:/GOD2/data/dss")
OUTPUT = Path("C:/GOD2/output")
OUTPUT.mkdir(parents=True, exist_ok=True)

# Загрузить имена Бога
with open("C:/GOD2/data/god_names.json", encoding="utf-8") as f:
    god_names_data = json.load(f)

# Ивритские варианты имён для поиска
GOD_PATTERNS = [n["hebrew"].replace(".", "").strip() for n in god_names_data]
# Добавить транслитерационные паттерны
GOD_PATTERNS += ["YHWH", "Elohim", "Adonai", "El Shaddai"]

# Ключевые слова взаимодействия (иврит)
INTERACTION_KEYWORDS_HE = [
    "וַיֹּאמֶר",  # и сказал
    "וַיְדַבֵּר",  # и говорил
    "וַיִּקְרָא",  # и призвал
    "וַיֵּרָא",   # и явился
    "וַיְצַו",    # и повелел
    "שְׁמַע",     # слушай
    "לֵךְ",       # иди
    "עֲשֵׂה",     # делай
]

contacts = []
contact_id = 0

def extract_text_from_sefaria(data):
    """Извлекает список стихов из JSON Sefaria"""
    texts = data.get("he", data.get("text", []))
    if isinstance(texts, str):
        return [texts]
    result = []
    def flatten(item):
        if isinstance(item, list):
            for i in item: flatten(i)
        elif isinstance(item, str):
            result.append(item)
    flatten(texts)
    return result

def has_god_name(verse):
    """Проверяет наличие имени Бога в стихе"""
    for pattern in GOD_PATTERNS:
        if pattern in verse:
            return True
    return False

def has_interaction(verse):
    """Проверяет наличие интерактивного глагола"""
    for kw in INTERACTION_KEYWORDS_HE:
        if kw in verse:
            return True
    return False

index_file = TANAKH_DIR / "_index.json"
if not index_file.exists():
    print("ERROR: Сначала запусти download_tanakh.py")
    exit(1)

with open(index_file, encoding="utf-8") as f:
    book_index = json.load(f)

print(f"Обрабатываем {len(book_index)} книг...")

for book_name, book_path in tqdm(book_index.items()):
    if not Path(book_path).exists():
        continue
    with open(book_path, encoding="utf-8") as f:
        data = json.load(f)

    verses = extract_text_from_sefaria(data)

    for i, verse in enumerate(verses):
        if not verse or len(verse) < 5:
            continue
        if has_god_name(verse) and has_interaction(verse):
            contact_id += 1
            contacts.append({
                "id": f"C{contact_id:04d}",
                "book": book_name,
                "verse_index": i,
                "text_he": verse,
                "text_en": "",  # заполняется позже
                "god_name_found": [p for p in GOD_PATTERNS if p in verse],
                "interaction_type": "unknown",  # заполняется в registry
                "category": "",
                "analyzed": False
            })

# Сохранить
with open(OUTPUT / "contacts_registry.json", "w", encoding="utf-8") as f:
    json.dump(contacts, f, ensure_ascii=False, indent=2)

print(f"\nНайдено контактов: {len(contacts)}")
print(f"Сохранено: output/contacts_registry.json")
```

Запустить:
```powershell
cd C:\GOD2
python scripts\extract_contacts.py
```

## Шаг 3 — Верификация
```powershell
cd C:\GOD2\.agent
.\task_manager.ps1 verify
```
