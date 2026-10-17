"""
Network Analysis — граф взаимодействий Бога с персонажами и народами Танаха.
Задача: network-001
Входные данные: output/situations_coded.json
Выходные данные: output/god_network.json, output/god_network.gexf, output/network_stats.json
"""

import json
import os
from collections import Counter, defaultdict

import networkx as nx
from networkx.readwrite import json_graph

# ─── Пути ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "output", "situations_coded.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Таблицы маркеров ────────────────────────────────────────────────────────
CHARACTERS = {
    "אברהם": "Abraham",
    "אברם":  "Abram",
    "משה":   "Moses",
    "דוד":   "David",
    "שלמה":  "Solomon",
    "נח":    "Noah",
    "יוסף":  "Joseph",
    "אליהו": "Elijah",
    "ירמיהו":"Jeremiah",
    "יחזקאל":"Ezekiel",
    "ישעיהו":"Isaiah",
    "גדעון": "Gideon",
    "שמואל": "Samuel",
    "יצחק":  "Isaac",
    "יעקב":  "Jacob",
    "ישראל": "Israel_person",  # отдельно от народа
    "אדם":   "Adam",
    "חוה":   "Eve",
    "קין":   "Cain",
    "יהושע": "Joshua",
    "שאול":  "Saul",
    "אליעזר":"Eliezer",
    "לוט":   "Lot",
    "בלעם":  "Balaam",
    "פינחס": "Phinehas",
    "אהרן":  "Aaron",
    "מרים":  "Miriam",
    "יונה":  "Jonah",
    "אסתר":  "Esther",
    "דניאל": "Daniel",
    "רות":   "Ruth",
    "חנה":   "Hannah",
    "איוב":  "Job",
    "שמשון": "Samson",
}

NATIONS = {
    "ישראל":    "Israel",
    "מצרים":   "Egypt",
    "כנען":    "Canaan",
    "פלשת":    "Philistia",
    "בבל":     "Babylon",
    "אשור":    "Assyria",
    "מואב":    "Moab",
    "אדום":    "Edom",
    "עמון":    "Ammon",
    "ארם":     "Aram",
    "פרס":     "Persia",
    "מדין":    "Midian",
    "עמלק":    "Amalek",
}

# Известные English-названия в поле target
TARGET_EN_CHARS = {
    "Abraham", "Abram", "Moses", "David", "Solomon", "Noah", "Joseph",
    "Elijah", "Jeremiah", "Ezekiel", "Isaiah", "Gideon", "Samuel",
    "Isaac", "Jacob", "Adam", "Eve", "Cain", "Joshua", "Saul",
    "Eliezer", "Lot", "Balaam", "Phinehas", "Aaron", "Miriam",
    "Jonah", "Esther", "Daniel", "Ruth", "Hannah", "Job", "Samson",
}
TARGET_EN_NATIONS = {
    "Israel", "Egypt", "Canaan", "Philistia", "Babylon", "Assyria",
    "Moab", "Edom", "Ammon", "Aram", "Persia", "Midian", "Amalek",
}

# Cardinality: наборы "общего" target-а
SKIP_TARGETS = {"unclear", "all_humanity", "", None}

# ─── Список Пятикнижий и Пророков (canonical groupings) ─────────────────────
GENESIS_BOOKS = {"Genesis"}
PROPHETS_BOOKS = {
    "Joshua", "Judges", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings",
    "Isaiah", "Jeremiah", "Ezekiel", "Hosea", "Joel", "Amos", "Obadiah",
    "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai",
    "Zechariah", "Malachi",
}

# ─── Вспомогательные ─────────────────────────────────────────────────────────

def detect_target(situation: dict) -> str | None:
    """
    Определяет узел-цель для ситуации.
    Приоритет: поле target → Hebrew в text_plain → participants.
    """
    raw_target = situation.get("target", "")

    # 1. Уже известный English персонаж или народ
    if raw_target in TARGET_EN_CHARS:
        return raw_target
    if raw_target in TARGET_EN_NATIONS:
        return raw_target

    # 2. Поле target может быть Hebrew именем
    if raw_target and raw_target not in SKIP_TARGETS:
        if raw_target in CHARACTERS:
            return CHARACTERS[raw_target]
        if raw_target in NATIONS:
            return NATIONS[raw_target]

    # 3. Ищем упоминания в тексте
    text = situation.get("text_plain", "")
    # персонажи
    for he, en in CHARACTERS.items():
        if he in text:
            return en
    # народы
    for he, en in NATIONS.items():
        if he in text:
            return en

    # 4. participants
    for p in situation.get("participants", []):
        if isinstance(p, str):
            p_clean = p.strip()
            if p_clean in CHARACTERS:
                return CHARACTERS[p_clean]
            if p_clean in NATIONS:
                return NATIONS[p_clean]
            if p_clean in TARGET_EN_CHARS:
                return p_clean
            if p_clean in TARGET_EN_NATIONS:
                return p_clean

    return None


def book_group(book: str) -> str:
    if book in GENESIS_BOOKS:
        return "Genesis"
    if book in PROPHETS_BOOKS:
        return "Prophets"
    return "Torah/Writings"


def direct_contact_pct(G: nx.MultiDiGraph, group: str) -> dict:
    """Процент прямого контакта vs через посредника для группы книг."""
    direct = 0
    total = 0
    for u, v, data in G.edges(data=True):
        if data.get("book_group") == group:
            total += 1
            if data.get("who_initiated") == "God" or data.get("behavior_type") in (
                "command", "revelation", "promise", "question", "warning",
            ):
                direct += 1
    return {
        "direct": direct,
        "total": total,
        "direct_pct": round(direct / total * 100, 1) if total else 0,
    }


# ─── Основной граф ───────────────────────────────────────────────────────────

def build_graph(situations: list) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    G.add_node("GOD", node_type="deity", label="God")

    skipped = 0
    added = 0

    for s in situations:
        target = detect_target(s)
        if target is None:
            skipped += 1
            continue

        # Добавить узел, если нового персонажа/народа ещё нет
        if target not in G.nodes:
            node_type = "nation" if target in TARGET_EN_NATIONS else "character"
            G.add_node(target, node_type=node_type, label=target)

        # Ребро
        G.add_edge(
            "GOD",
            target,
            behavior_type=s.get("behavior_type", "other"),
            behavior_subtype=s.get("behavior_subtype", ""),
            severity=s.get("severity", 1),
            trigger=s.get("trigger", "unclear"),
            outcome=s.get("outcome", "unclear"),
            book=s.get("book", ""),
            book_group=book_group(s.get("book", "")),
            ref=s.get("ref", ""),
            who_initiated=s.get("who_initiated", "unclear"),
            situation_id=s.get("id", ""),
        )
        added += 1

    print(f"  Edges added: {added}, skipped (no target): {skipped}")
    return G


# ─── Статистика ──────────────────────────────────────────────────────────────

def compute_stats(G: nx.MultiDiGraph) -> dict:
    # Для некоторых метрик используем простой DiGraph (без мультирёбер)
    simple_G = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        if simple_G.has_edge(u, v):
            simple_G[u][v]["weight"] += data.get("severity", 1)
        else:
            simple_G.add_edge(u, v, weight=data.get("severity", 1))
    for n, d in G.nodes(data=True):
        simple_G.add_node(n, **d)

    degree_cent = nx.degree_centrality(simple_G)
    try:
        between_cent = nx.betweenness_centrality(simple_G, weight="weight")
    except Exception:
        between_cent = {}

    # Число взаимодействий на каждого adресата
    interaction_counts: dict[str, int] = Counter(
        v for _, v in G.edges()
    )

    # Распределение типов рёбер
    edge_type_dist = Counter(
        data.get("behavior_type", "other") for _, _, data in G.edges(data=True)
    )

    # Средняя тяжесть по персонажу
    severity_by_target: dict[str, list] = defaultdict(list)
    for _, v, data in G.edges(data=True):
        severity_by_target[v].append(data.get("severity", 1))
    avg_severity = {
        k: round(sum(v) / len(v), 2) for k, v in severity_by_target.items()
    }

    # Топ-10 по числу взаимодействий
    most_connected = sorted(
        interaction_counts.items(), key=lambda x: -x[1]
    )[:15]

    # Прямой контакт по периодам
    proximity = {
        "Genesis":         direct_contact_pct(G, "Genesis"),
        "Prophets":        direct_contact_pct(G, "Prophets"),
        "Torah/Writings":  direct_contact_pct(G, "Torah/Writings"),
    }

    # Взаимодействия по книгам
    by_book: dict[str, int] = Counter(
        data.get("book", "") for _, _, data in G.edges(data=True)
    )

    # Триггеры
    trigger_dist = Counter(
        data.get("trigger", "unclear") for _, _, data in G.edges(data=True)
    )

    # Исходы
    outcome_dist = Counter(
        data.get("outcome", "unclear") for _, _, data in G.edges(data=True)
    )

    # Тяжёлые взаимодействия (severity >= 8)
    heavy_interactions = [
        {
            "target": v,
            "ref": data.get("ref"),
            "behavior_type": data.get("behavior_type"),
            "severity": data.get("severity"),
            "trigger": data.get("trigger"),
        }
        for _, v, data in G.edges(data=True)
        if data.get("severity", 0) >= 8
    ]
    heavy_interactions.sort(key=lambda x: -x["severity"])

    return {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "god_neighbors": sorted(set(G.successors("GOD"))),
        "most_connected": [{"target": t, "count": c} for t, c in most_connected],
        "degree_centrality": {k: round(v, 4) for k, v in sorted(
            degree_cent.items(), key=lambda x: -x[1])[:20]},
        "betweenness_centrality": {k: round(v, 4) for k, v in sorted(
            between_cent.items(), key=lambda x: -x[1])[:20]},
        "avg_severity_by_target": dict(
            sorted(avg_severity.items(), key=lambda x: -x[1])[:20]
        ),
        "edge_type_distribution": dict(edge_type_dist.most_common()),
        "trigger_distribution":   dict(trigger_dist.most_common()),
        "outcome_distribution":   dict(outcome_dist.most_common()),
        "interactions_by_book":   dict(by_book.most_common(30)),
        "proximity_over_time":    proximity,
        "heavy_interactions":     heavy_interactions[:30],
    }


# ─── Запись GEXF без мультирёбер (Gephi не поддерживает MultiDiGraph) ────────

def export_gexf(G: nx.MultiDiGraph, path: str):
    """Агрегирует мультирёбра в одно с суммарным весом severity."""
    simple_G = nx.DiGraph()
    for n, d in G.nodes(data=True):
        simple_G.add_node(n, **d)

    aggregated: dict[tuple, dict] = {}
    for u, v, data in G.edges(data=True):
        key = (u, v, data.get("behavior_type", "other"))
        if key not in aggregated:
            aggregated[key] = {
                "behavior_type": data.get("behavior_type", "other"),
                "weight": 0,
                "count": 0,
                "books": set(),
            }
        agg = aggregated[key]
        agg["weight"] += data.get("severity", 1)
        agg["count"] += 1
        agg["books"].add(data.get("book", ""))

    for (u, v, btype), agg in aggregated.items():
        simple_G.add_edge(
            u, v,
            behavior_type=btype,
            weight=agg["weight"],
            count=agg["count"],
            books=",".join(sorted(agg["books"])),
        )

    nx.write_gexf(simple_G, path)
    print(f"  GEXF saved: {path} ({simple_G.number_of_edges()} aggregated edges)")


# ─── Точка входа ─────────────────────────────────────────────────────────────

def main():
    print("=== GOD2 Network Analysis ===")

    # 1. Загрузка данных
    print(f"Loading situations from {INPUT_FILE}...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        situations = json.load(f)
    print(f"  Total situations: {len(situations)}")

    # 2. Построение графа
    print("Building interaction graph...")
    G = build_graph(situations)
    print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")

    # 3. JSON для визуализации (node-link format)
    json_path = os.path.join(OUTPUT_DIR, "god_network.json")
    print(f"Saving god_network.json...")
    data = json_graph.node_link_data(G)
    # Конвертируем неJSON-сериализуемые типы
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Saved: {json_path}")

    # 4. GEXF для Gephi
    gexf_path = os.path.join(OUTPUT_DIR, "god_network.gexf")
    print(f"Saving god_network.gexf...")
    export_gexf(G, gexf_path)

    # 5. Статистика
    stats_path = os.path.join(OUTPUT_DIR, "network_stats.json")
    print(f"Computing network statistics...")
    stats = compute_stats(G)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Saved: {stats_path}")

    # 6. Краткий отчёт
    print("\n=== Summary ===")
    print(f"  Unique targets (characters+nations): {G.number_of_nodes() - 1}")
    print(f"  Total interactions mapped: {G.number_of_edges()}")
    print(f"  Top-5 most connected:")
    for item in stats["most_connected"][:5]:
        print(f"    {item['target']:20s} — {item['count']} interactions")
    print(f"\n  Edge type distribution:")
    for btype, cnt in list(stats["edge_type_distribution"].items())[:8]:
        print(f"    {btype:25s}: {cnt}")
    print(f"\n  Direct contact (Genesis):  {stats['proximity_over_time']['Genesis']['direct_pct']}%")
    print(f"  Direct contact (Prophets): {stats['proximity_over_time']['Prophets']['direct_pct']}%")
    print("\nDONE.")


if __name__ == "__main__":
    main()
