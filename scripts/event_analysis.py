"""
Event-Driven Analysis — behavioral loops & stimulus-response matrix
Task: events-001
Input:  output/situations_coded.json (8444 records)
Output: output/behavioral_loops.json
        output/stimulus_response_matrix.json
"""

import json
import os
import sys
import argparse
from collections import Counter, defaultdict

# ── paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_PATH  = os.path.join(BASE_DIR, "output", "situations_coded.json")
OUT_LOOPS   = os.path.join(BASE_DIR, "output", "behavioral_loops.json")
OUT_MATRIX  = os.path.join(BASE_DIR, "output", "stimulus_response_matrix.json")

# ── load data ──────────────────────────────────────────────────────────────────
print("Loading situations_coded.json ...")
if not os.path.exists(INPUT_PATH):
    print(f"ОШИБКА: {INPUT_PATH} не найден. Сначала выполните Фазу 4.")
    sys.exit(1)

with open(INPUT_PATH, "r", encoding="utf-8") as f:
    situations = json.load(f)

parser = argparse.ArgumentParser()
parser.add_argument("--test", action="store_true")
args = parser.parse_args()

if args.test:
    situations = situations[:20]
    print("[DRY-RUN] Тестовый режим. Обрабатываем 20 записей.")

print(f"  loaded {len(situations)} records")
if not situations:
    print("ОШИБКА: массив situations пуст! Fail-Fast.")
    sys.exit(1)


# ── Step 1 — Build per-chapter event sequences ─────────────────────────────────
chapter_sequences = defaultdict(list)
for s in situations:
    key = (s.get("book", ""), s.get("chapter", 0))
    chapter_sequences[key].append({
        "id":            s.get("id", ""),
        "ref":           s.get("ref", ""),
        "book":          s.get("book", ""),
        "chapter":       s.get("chapter", 0),
        "verse":         s.get("verse", 0),
        "trigger":       s.get("trigger", "unclear"),
        "behavior_type": s.get("behavior_type", "other"),
        "behavior_subtype": s.get("behavior_subtype", ""),
        "outcome":       s.get("outcome", "unclear"),
        "severity":      s.get("severity", 1),
    })

print(f"  chapters/sections indexed: {len(chapter_sequences)}")


# ── Step 2 — Find repeated patterns (sliding window 2–5 events) ───────────────
loop_counter: Counter = Counter()
loop_refs: dict       = defaultdict(set)   # pattern → set of books

for (book, chapter), seq in chapter_sequences.items():
    n = len(seq)
    for window in range(2, 6):           # windows of size 2, 3, 4, 5
        for i in range(n - window + 1):
            pattern = tuple(
                (e["trigger"], e["behavior_type"], e["outcome"])
                for e in seq[i : i + window]
            )
            loop_counter[pattern] += 1
            loop_refs[pattern].add(book)

print(f"  distinct patterns found: {len(loop_counter)}")


# ── Step 3 — Build helpers for pattern metadata ───────────────────────────────

def find_books_for_pattern(pattern: tuple) -> list[str]:
    return sorted(loop_refs[pattern])


def pattern_label(pattern: tuple) -> str:
    """Human-readable arrow chain: trigger/behavior→outcome → trigger/behavior→outcome …"""
    parts = []
    for trigger, btype, outcome in pattern:
        parts.append(f"{trigger}/{btype}->{outcome}")
    return " -> ".join(parts)


def avg_severity_for_pattern(pattern: tuple) -> float:
    """Average severity of all matching occurrences (approximate)."""
    sev_sum = 0
    count   = 0
    for seq in chapter_sequences.values():
        n = len(seq)
        w = len(pattern)
        for i in range(n - w + 1):
            if tuple((e["trigger"], e["behavior_type"], e["outcome"]) for e in seq[i:i+w]) == pattern:
                for e in seq[i:i+w]:
                    sev_sum += e["severity"]
                    count += 1
    return round(sev_sum / count, 2) if count else 0.0


# ── Step 4 — Filter & rank top loops (frequency > 3) ─────────────────────────
MIN_FREQ = 3
top_loops = []
for pattern, cnt in loop_counter.most_common(100):
    if cnt <= MIN_FREQ:
        break
    top_loops.append({
        "label":        pattern_label(pattern),
        "frequency":    cnt,
        "length":       len(pattern),
        "books":        find_books_for_pattern(pattern),
        "pattern":      [list(step) for step in pattern],
        "avg_severity": avg_severity_for_pattern(pattern),
    })

print(f"  top loops (freq > {MIN_FREQ}): {len(top_loops)}")


# ── Step 5 — Build Stimulus → Response transition matrix ─────────────────────
# trigger → outcome → next_trigger transitions
# AND full trigger → behavior_type → outcome → next_trigger chain

transition_matrix: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

for seq in chapter_sequences.values():
    for i in range(len(seq) - 1):
        curr   = seq[i]
        nxt    = seq[i + 1]
        # trigger[t] → outcome[t] → trigger[t+1]
        transition_matrix[curr["trigger"]][curr["outcome"]][nxt["trigger"]] += 1

# Convert to serializable dict with sorted totals
matrix_out = {}
for trigger, outcomes in transition_matrix.items():
    matrix_out[trigger] = {}
    for outcome, next_triggers in outcomes.items():
        matrix_out[trigger][outcome] = {
            "next_triggers": dict(sorted(next_triggers.items(), key=lambda x: -x[1])),
            "total":         sum(next_triggers.values()),
        }

# Also build: behavior_type → outcome frequency
behavior_outcomes: dict = defaultdict(lambda: defaultdict(int))
trigger_behaviors:  dict = defaultdict(lambda: defaultdict(int))

for s in situations:
    b = s.get("behavior_type", "other")
    o = s.get("outcome", "unclear")
    t = s.get("trigger", "unclear")
    behavior_outcomes[b][o] += 1
    trigger_behaviors[t][b] += 1

# Summary stats
summary_stats = {
    "total_situations":  len(situations),
    "chapters_indexed":  len(chapter_sequences),
    "patterns_found":    len(loop_counter),
    "top_loops_count":   len(top_loops),
    "unique_triggers":   sorted(trigger_behaviors.keys()),
    "unique_behaviors":  sorted(behavior_outcomes.keys()),
    "trigger_frequency": {t: sum(bs.values()) for t, bs in trigger_behaviors.items()},
    "behavior_frequency": {b: sum(os.values()) for b, os in behavior_outcomes.items()},
    "behavior_outcome_matrix": {b: dict(o) for b, o in behavior_outcomes.items()},
    "trigger_behavior_matrix":  {t: dict(b) for t, b in trigger_behaviors.items()},
}


# ── Step 6 — Save outputs ─────────────────────────────────────────────────────
loops_output = {
    "metadata": {
        "task":        "events-001",
        "description": "Behavioral loops / Stimulus-Response patterns in Tanakh narrative",
        "total_situations": len(situations),
        "min_frequency_filter": MIN_FREQ,
    },
    "summary_stats": summary_stats,
    "top_loops":     top_loops,
}

if not args.test:
    with open(OUT_LOOPS, "w", encoding="utf-8") as f:
        json.dump(loops_output, f, ensure_ascii=False, indent=2)
    print(f"  saved -> {OUT_LOOPS}")

    matrix_output = {
        "metadata": {
            "task":        "events-001",
            "description": "Stimulus → Response transition matrix (trigger→outcome→next_trigger)",
        },
        "transition_matrix": matrix_out,
    }
    with open(OUT_MATRIX, "w", encoding="utf-8") as f:
        json.dump(matrix_output, f, ensure_ascii=False, indent=2)
    print(f"  saved -> {OUT_MATRIX}")
else:
    print("  [DRY-RUN] Файлы не сохранены.")

# ── Step 7 — Print top-10 results preview ─────────────────────────────────────
print("\n=== TOP 10 BEHAVIORAL LOOPS ===")
for i, loop in enumerate(top_loops[:10], 1):
    books_str = ", ".join(loop["books"][:5])
    if len(loop["books"]) > 5:
        books_str += f" +{len(loop['books'])-5} more"
    print(f"{i:2}. freq={loop['frequency']:4d}  len={loop['length']}  "
          f"avg_sev={loop['avg_severity']:.1f}  [{books_str}]")
    print(f"    {loop['label']}")

print("\n=== TRIGGER FREQUENCY ===")
for t, cnt in sorted(summary_stats["trigger_frequency"].items(), key=lambda x: -x[1])[:10]:
    print(f"  {t:25s}: {cnt}")

print("\n=== BEHAVIOR -> MOST COMMON OUTCOME ===")
for b, outcomes in sorted(summary_stats["behavior_outcome_matrix"].items()):
    top_outcome = max(outcomes.items(), key=lambda x: x[1])
    print(f"  {b:20s}: -> {top_outcome[0]} ({top_outcome[1]})")

print("\nDone. events-001 outputs saved.")
