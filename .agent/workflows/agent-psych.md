---
description: Агент психологического анализа образа Бога (5 методик + FBI)
---

# /agent-psych — Психологический анализ

Зависит от: **registry-001 (должен быть DONE)**

## Шаг 1 — Создать `scripts\psych_analysis.py`

```python
"""
Психологический анализ образа Бога по 5 методикам + FBI профайлинг.
Вход: output/situations_registry.json
Выход: output/god_profile.json, output/behavior_patterns.json
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

REGISTRY_FILE = Path("C:/GOD2/output/situations_registry.json")
OUTPUT = Path("C:/GOD2/output")

with open(REGISTRY_FILE, encoding="utf-8") as f:
    situations = json.load(f)

total = len(situations)
cats = Counter(s["category"] for s in situations)
initiators = Counter(s["who_initiated"] for s in situations)

# ============================================================
# 1. ЮНГ — Архетипы (Юнг 1968, Collected Works)
# Четыре архетипа по категориям поведения
# ============================================================
jung_archetypes = {
    "Отец (Власть и закон)": cats.get("повеление", 0) + cats.get("суд", 0) + cats.get("наказание", 0),
    "Мудрец (Откровение)": cats.get("откровение", 0) + cats.get("завет", 0),
    "Герой/Защитник": cats.get("спасение", 0),
    "Трикстер (Испытание)": cats.get("другое", 0),
}
dominant_jung = max(jung_archetypes, key=jung_archetypes.get)

# ============================================================
# 2. БЕРН — Транзактный анализ (эго-состояния)
# Родитель-Взрослый-Ребёнок по стилю взаимодействия
# ============================================================
berne_states = {
    "Родитель Контролирующий": cats.get("повеление", 0) + cats.get("наказание", 0) + cats.get("суд", 0),
    "Родитель Питающий": cats.get("спасение", 0) + cats.get("обещание", 0),
    "Взрослый": cats.get("завет", 0) + cats.get("откровение", 0),
    "Ребёнок (реактивный)": cats.get("вопрос", 0),
}
dominant_berne = max(berne_states, key=berne_states.get)
god_initiative_pct = round(initiators.get("God", 0) / max(total, 1) * 100, 1)

# ============================================================
# 3. BIG FIVE (OCEAN) — Пятифакторная модель личности
# Оценки 1-10 на основе поведенческих паттернов
# ============================================================
big_five = {
    "Openness": round(min(10, (cats.get("откровение", 0) / max(total, 1)) * 100 + 3), 1),
    "Conscientiousness": round(min(10, (cats.get("завет", 0) + cats.get("повеление", 0)) / max(total, 1) * 100 + 5), 1),
    "Extraversion": round(min(10, god_initiative_pct / 10 + 4), 1),
    "Agreeableness": round(min(10, cats.get("спасение", 0) / max(total, 1) * 100 + 2), 1),
    "Neuroticism": round(min(10, cats.get("наказание", 0) / max(total, 1) * 100 + 3), 1),
}

# ============================================================
# 4. БОУЛБИ — Стиль привязанности
# Secure / Anxious / Avoidant / Disorganized
# ============================================================
punishment_ratio = cats.get("наказание", 0) / max(total, 1)
salvation_ratio = cats.get("спасение", 0) / max(total, 1)
covenant_ratio = cats.get("завет", 0) / max(total, 1)

if covenant_ratio > 0.15 and salvation_ratio > 0.10:
    bowlby_style = "Secure with conditional elements"
elif punishment_ratio > 0.20:
    bowlby_style = "Anxious-Ambivalent (high expectations, reactive punishment)"
else:
    bowlby_style = "Secure-Authoritative"

# ============================================================
# 5. АДЛЕР — Индивидуальная психология
# Стремление к превосходству, телеология, компенсация
# ============================================================
adler_analysis = {
    "striving_for_superiority": {
        "score": round(min(10, (cats.get("суд", 0) + cats.get("наказание", 0)) / max(total, 1) * 100 + 6), 1),
        "evidence": "Частое подчёркивание уникальности и верховности: 'Нет бога кроме Меня'"
    },
    "teleology": {
        "description": "Действия направлены к финальной цели (освящение народа, установление Царства)",
        "dominant_goal": "Создание избранного народа — носителя Заветных обязательств"
    },
    "inferiority_compensation": {
        "note": "Применимо обратно: человек компенсирует ничтожность через избранность",
        "god_response": "Усиление требований при нарушении — как реакция на угрозу авторитету"
    },
    "social_interest": {
        "score": round(cats.get("спасение", 0) / max(total, 1) * 100, 1),
        "description": "Gemeinschaftsgefühl — Бог как образец совершенного социального существа"
    }
}

# ============================================================
# 6. FBI ViCAP — Поведенческий профайлинг
# Паттерны ситуационного поведения
# ============================================================
fbi_profile = {
    "trigger_conditions": {
        "idolatry": "Немедленная карательная реакция (Числа 25)",
        "disobedience": "Эскалация наказания (Египетские казни)",
        "prayer": "Высокая отзывчивость, особенно в кризис",
        "covenant_breach": "Долгосрочные последствия (изгнание, рассеяние)",
    },
    "behavioral_consistency": "Высокая — паттерны повторяются между книгами",
    "escalation_pattern": "Предупреждение → малое наказание → катастрофа",
    "de_escalation_trigger": "Раскаяние + молитва + возврат к Завету",
    "modus_operandi": [
        "Использование посредников (пророки, ангелы)",
        "Природные явления как инструмент",
        "Прямое откровение — только к избранным",
        "Испытание перед благословением (Авраам, Иов)",
    ]
}

# ============================================================
# СВОДНЫЙ ПРОФИЛЬ
# ============================================================
god_profile = {
    "metadata": {
        "total_situations_analyzed": total,
        "categories_distribution": dict(cats),
        "initiative_distribution": dict(initiators),
        "methodology": ["Jung", "Berne", "Big Five", "Bowlby", "Adler", "FBI ViCAP"]
    },
    "jung_archetypes": {
        "scores": jung_archetypes,
        "dominant": dominant_jung,
        "interpretation": f"Доминирует архетип '{dominant_jung}' — подтверждается {jung_archetypes[dominant_jung]} ситуациями"
    },
    "berne_transactional": {
        "ego_states": berne_states,
        "dominant": dominant_berne,
        "god_initiative_percent": god_initiative_pct,
        "interpretation": "Бог выступает преимущественно из позиции Контролирующего Родителя"
    },
    "big_five_ocean": big_five,
    "bowlby_attachment": {
        "style": bowlby_style,
        "analysis": "Избранничество создаёт условия для тревожной привязанности у человека"
    },
    "adler_individual_psychology": adler_analysis,
    "fbi_behavioral_profile": fbi_profile,
    "summary": {
        "core_personality": "Авторитарная личность с высоким conscientiousness, чётким кодексом, вариативным милосердием",
        "relational_style": "Иерархический — Отец/Судья/Защитник, редко Партнёр",
        "predictability": "Высокая в рамках Завета, низкая вне его",
        "key_pattern": "Завет → Нарушение → Предупреждение → Наказание → Раскаяние → Восстановление"
    }
}

# ============================================================
# КАРТА ПАТТЕРНОВ ПОВЕДЕНИЯ
# ============================================================
behavior_patterns = {
    "primary_cycle": {
        "name": "Цикл Завета",
        "steps": ["Установление Завета", "Нарушение человеком", "Предупреждение (пророк)", "Наказание", "Раскаяние", "Восстановление"],
        "frequency": "Повторяется во всех основных нарративах"
    },
    "communication_patterns": {
        "preferred_medium": ["Прямое откровение (пророкам)", "Ангел-вестник", "Огонь/гром/природа", "Сон/видение"],
        "preferred_recipients": ["Основатели (Авраам, Моисей)", "Судьи и цари", "Пророки", "Редко — народ напрямую"]
    },
    "response_triggers": [
        {"trigger": "Молитва в кризис", "response": "Помощь/спасение", "probability": "high"},
        {"trigger": "Идолопоклонство", "response": "Немедленное наказание", "probability": "very_high"},
        {"trigger": "Верность Завету", "response": "Благословение", "probability": "high"},
        {"trigger": "Раскаяние", "response": "Прощение", "probability": "moderate"},
        {"trigger": "Заступничество праведника", "response": "Смягчение наказания", "probability": "moderate"},
    ],
    "emotional_register": {
        "anger": "Быстро возгорается, долго помнит (Амалик)",
        "love": "Постоянная, но условная ('любящий и наказывающий Отец')",
        "jealousy": "Центральная черта: אֵל קַנָּא (El Kana — Бог ревнивый)",
        "compassion": "Активируется раскаянием и молитвой"
    }
}

# Сохранить
with open(OUTPUT / "god_profile.json", "w", encoding="utf-8") as f:
    json.dump(god_profile, f, ensure_ascii=False, indent=2)

with open(OUTPUT / "behavior_patterns.json", "w", encoding="utf-8") as f:
    json.dump(behavior_patterns, f, ensure_ascii=False, indent=2)

print(f"Психологический анализ завершён!")
print(f"Проанализировано ситуаций: {total}")
print(f"Доминирующий архетип (Юнг): {dominant_jung}")
print(f"Доминирующее эго-состояние (Берн): {dominant_berne}")
print(f"Big Five: {big_five}")
print(f"Стиль привязанности (Боулби): {bowlby_style}")
print(f"\nПрофиль: output/god_profile.json")
print(f"Паттерны: output/behavior_patterns.json")
```

Запустить:
```powershell
cd C:\GOD2
python scripts\psych_analysis.py
```

## Шаг 2 — Верификация
```powershell
cd C:\GOD2\.agent
.\task_manager.ps1 verify
```
