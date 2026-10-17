import json, sys
sys.stdout.reconfigure(encoding="utf-8")
from collections import Counter

errors = []
try:
    with open("c:/GOD2/output/reasoning_errors.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                errors.append(json.loads(line))
except FileNotFoundError:
    print("reasoning_errors.jsonl не найден")
    sys.exit(1)

print(f"Ошибок в файле: {len(errors)}")
types = Counter(e.get("error", "?").split(":")[0] for e in errors)
print("Типы ошибок:", dict(types))
print()
for e in errors[:5]:
    eid = e.get("id", "?")
    err = e.get("error", "?")
    raw = str(e.get("raw_output", ""))[:100]
    print(f"  id={eid} | {err}")
    if raw:
        print(f"    raw: {raw}")
