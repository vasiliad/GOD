---
description: Агент построения реестра ситуаций с подробным описанием
---

# /agent-registry — Реестр ситуаций

Зависит от: **contacts-001 (должен быть DONE)**

## Шаг 1 — Создать `scripts\build_registry.py`

```python
"""
Строит детальный реестр ситуаций взаимодействия Бога и человека.
Только иврит — без запросов переводов.
"""
import json, csv
from pathlib import Path
from collections import Counter
from tqdm import tqdm

CONTACTS_FILE = Path("C:/GOD2/output/contacts_registry.json")
OUTPUT = Path("C:/GOD2/output")
OUTPUT.mkdir(parents=True, exist_ok=True)

with open(CONTACTS_FILE, encoding="utf-8") as f:
    contacts = json.load(f)

# Категоризация по ключевым словам (иврит)
CATEGORY_MAP = {
    "завет":     ["בְּרִית"],
    "суд":       ["מִשְׁפָּט"],
    "спасение":  ["יְשׁוּעָה", "הוֹשַׁע"],
    "наказание": ["עֹנֶשׁ", "וַיַּךְ", "וַיִּשְׁלַח"],
    "откровение":["וַיֵּרָא", "חָזוֹן"],
    "молитва":   ["וַיִּתְפַּלֵּל", "וַיִּצְעַק"],
    "повеление": ["צִוָּה", "לֵךְ", "עֲשֵׂה", "קַח"],
    "обещание":  ["אֶתֵּן", "בֵּרַכְתִּי"],
}

def categorize(text):
    for cat, keywords in CATEGORY_MAP.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "другое"

registry = []

print(f"Строим реестр для {len(contacts)} контактов...")

for contact in tqdm(contacts):
    category = categorize(contact["text_he"])

    # Кто инициировал по базовой эвристике
    who = "unknown"
    if any(w in contact["text_he"] for w in ["וַיֹּאמֶר", "וַיְדַבֵּר", "וַיְצַו"]):
        who = "God"
    elif any(w in contact["text_he"] for w in ["וַיִּצְעַק", "וַיִּתְפַּלֵּל", "וַיֹּאמֶר אֵלָיו"]):
        who = "Human"

    registry.append({
        "id":              contact["id"],
        "book":            contact["book"],
        "verse_index":     contact["verse_index"],
        "category":        category,
        "god_names":       contact["god_name_found"],
        "text_he":         contact["text_he"],
        "who_initiated":   who,
        "god_speech":      "",
        "human_speech":    "",
        "situation_start": "",
        "situation_end":   "",
        "god_action":      "",
        "participants":    [],
        "analyzed_psych":  False,
        "analyzed_linguistics": False
    })

# Сохранить JSON
with open(OUTPUT / "situations_registry.json", "w", encoding="utf-8") as f:
    json.dump(registry, f, ensure_ascii=False, indent=2)

# Сохранить CSV (Excel, UTF-8 BOM)
csv_fields = ["id", "book", "verse_index", "category", "who_initiated",
              "text_he", "god_action", "situation_start", "situation_end"]
with open(OUTPUT / "situations.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(registry)

# Статистика
cats = Counter(s["category"] for s in registry)
print(f"\nРеестр построен: {len(registry)} ситуаций")
print("JSON: output/situations_registry.json")
print("CSV:  output/situations.csv")
print("\nКатегории:")
for cat, count in cats.most_common():
    print(f"  {cat}: {count}")
```

Запустить:
```powershell
cd C:\GOD2
python scripts\build_registry.py
```

Работает **мгновенно** — нет сетевых запросов.

## Шаг 2 — Верификация
```powershell
cd C:\GOD2\.agent
.\task_manager.ps1 verify
```

Открыть CSV в Excel:
```powershell
Start-Process "C:\GOD2\output\situations.csv"
```
