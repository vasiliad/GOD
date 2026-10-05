---
description: Network Analysis — граф взаимодействий Бога с персонажами и народами
---

# /agent-network — Сетевой анализ

## Контекст
Задача: `network-001`
Зависит от: `psych-001` (done) — `situations_coded.json` готов
Выходные файлы: `output/god_network.json`, `output/god_network.gexf`, `output/network_stats.json`

## Зависимости
```powershell
pip install networkx
```

## Шаг 1 — Создать `scripts/network_analysis.py`

### Узлы графа:
- `GOD` — центральный узел
- Все персонажи из `INDIVIDUAL_MARKERS` в ситуациях
- Все народы из `NATION_MARKERS`

### Рёбра графа:
Каждая ситуация из `situations_coded.json` создаёт ребро:
```python
G.add_edge(
    "GOD",
    target_node,
    behavior_type=s["behavior_type"],
    severity=s["severity"],
    trigger=s["trigger"],
    book=s["book"],
    weight=s["severity"]  # вес = тяжесть взаимодействия
)
```

### Персонажи для обнаружения (расширенный список):
```python
CHARACTERS = {
    "אברהם": "Abraham", "משה": "Moses", "דוד": "David",
    "שלמה": "Solomon", "נח": "Noah", "יוסף": "Joseph",
    "אליהו": "Elijah", "ירמיהו": "Jeremiah", "יחזקאל": "Ezekiel",
    "ישעיהו": "Isaiah", "גדעון": "Gideon", "שמואל": "Samuel",
    "אברם": "Abram", "יצחק": "Isaac", "יעקב": "Jacob",
    "אדם": "Adam", "חוה": "Eve", "קין": "Cain",
    "יהושע": "Joshua", "שאול": "Saul", "אליהו": "Elijah",
}
NATIONS = {
    "ישראל": "Israel", "מצרים": "Egypt", "כנען": "Canaan",
    "פלשת": "Philistia", "בבל": "Babylon", "אשור": "Assyria",
}
```

### Метрики для `network_stats.json`:
```python
stats = {
    "degree_centrality": nx.degree_centrality(G),
    "betweenness_centrality": nx.betweenness_centrality(G),
    "god_neighbors": list(G.neighbors("GOD")),
    "most_connected": sorted(G.degree(), key=lambda x: -x[1])[:10],
    "proximity_over_time": {  # прямой диалог vs через ангела по периодам
        "Genesis": direct_contact_pct(G, "Genesis"),
        "Prophets": direct_contact_pct(G, "prophets"),
    },
    "edge_type_distribution": Counter(d["behavior_type"] for _,_,d in G.edges(data=True)),
}
```

### Экспорт:
```python
import networkx as nx
from networkx.readwrite import json_graph

# JSON для визуализации
data = json_graph.node_link_data(G)
with open("output/god_network.json", "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# GEXF для Gephi
nx.write_gexf(G, "output/god_network.gexf")
```

## Шаг 2 — Запустить
```powershell
cd C:\GOD2
python scripts\network_analysis.py
```

## Шаг 3 — Сигнал
```powershell
Set-Content "C:\GOD2\.agent\signals\network-001.done" "done"
```

## Завершение
Задача выполнена когда существуют:
- `output/god_network.json`
- `output/god_network.gexf`
- `output/network_stats.json`
