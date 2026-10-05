---
description: Event-Driven Analysis — поиск поведенческих циклов Stimulus-Response в нарративе
---

# /agent-events — Циклы поведения

## Контекст
Задача: `events-001`
Зависит от: `psych-001` (done)
Выходные файлы: `output/behavioral_loops.json`, `output/stimulus_response_matrix.json`

## Данные
- `C:/GOD2/output/situations_coded.json` — 8444 записей с trigger, outcome, behavior_type

## Шаг 1 — Создать `scripts/event_analysis.py`

### Алгоритм поиска циклов:
Используем sliding window (размер 2–5 стихов) по каждой книге+главе.
Ищем повторяющиеся последовательности trigger→behavior_type→outcome.

```python
# Построить цепочки событий по каждой книге
from collections import Counter, defaultdict

# 1. Собрать последовательности по главам
chapter_sequences = defaultdict(list)
for s in situations:
    key = (s["book"], s["chapter"])
    chapter_sequences[key].append({
        "trigger": s["trigger"],
        "behavior_type": s["behavior_type"],
        "outcome": s["outcome"],
        "severity": s["severity"],
    })

# 2. Найти паттерны длиной 2-4 события
loop_counter = Counter()
for seq in chapter_sequences.values():
    for window in range(2, 5):
        for i in range(len(seq) - window):
            pattern = tuple(
                (e["trigger"], e["behavior_type"], e["outcome"])
                for e in seq[i:i+window]
            )
            loop_counter[pattern] += 1

# 3. Топ паттерны с частотой > 3
top_loops = [
    {
        "pattern": list(p),
        "frequency": cnt,
        "length": len(p),
        "books": find_books_for_pattern(p)
    }
    for p, cnt in loop_counter.most_common(50)
    if cnt > 3
]
```

### Матрица Stimulus→Response:
```python
# trigger -> behavior_type -> outcome -> next_trigger
transition_matrix = defaultdict(lambda: defaultdict(Counter))
for seq in chapter_sequences.values():
    for i in range(len(seq) - 1):
        curr = seq[i]
        next_e = seq[i+1]
        transition_matrix[curr["trigger"]][curr["outcome"]][next_e["trigger"]] += 1
```

## Шаг 2 — Запустить
```powershell
cd C:\GOD2
python scripts\event_analysis.py
```

Ожидаемые топ-паттерны (классический цикл Судей):
```
disobedience → punishment → prayer → salvation → faithfulness
```

## Шаг 3 — Сигнал
```powershell
Set-Content "C:\GOD2\.agent\signals\events-001.done" "done"
```

## Завершение
- `output/behavioral_loops.json` — топ паттерны с частотой и книгами
- `output/stimulus_response_matrix.json` — полная матрица переходов
