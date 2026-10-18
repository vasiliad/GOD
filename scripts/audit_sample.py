import json
from pathlib import Path, random, sys
sys.stdout.reconfigure(encoding='utf-8')

with open(str(Path(__file__).resolve().parents[1] / 'output' / 'situations_coded.json'), encoding='utf-8') as f:
    data = json.load(f)

random.seed(42)
sample = random.sample(data, 15)

for i, s in enumerate(sample, 1):
    print(f"--- [{i}] {s.get('book')} {s.get('verse')} ---")
    print(f"  behavior_type : {s.get('behavior_type')}")
    print(f"  trigger       : {s.get('trigger')}")
    print(f"  outcome       : {s.get('outcome')}")
    print(f"  participants  : {s.get('participants')}")
    print(f"  target        : {s.get('target')}")
    print(f"  god_action    : {str(s.get('god_action',''))[:100]}")
    print(f"  god_speech    : {str(s.get('god_speech',''))[:100]}")
    print(f"  text_he       : {str(s.get('text_he',''))[:80]}")
    print()
