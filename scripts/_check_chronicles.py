import json, sys
sys.stdout.reconfigure(encoding="utf-8")
from openai import OpenAI
import re

data = json.load(open("c:/GOD2/output/situations_coded.json", encoding="utf-8"))
chron_empty = [s for s in data if "Chronicles" in s.get("book","") and not s.get("god_action","").strip()]
chron_filled = [s for s in data if "Chronicles" in s.get("book","") and s.get("god_action","").strip()]

print(f"II Chronicles всего: {len([s for s in data if 'Chronicles' in s.get('book','')])} ")
print(f"  Заполнено god_action: {len(chron_filled)}")
print(f"  Пустых:               {len(chron_empty)}")
print()

# Тест на первых 3 пустых из Chronicles
if not chron_empty:
    print("Все Chronicles уже заполнены!")
    sys.exit(0)

SYSTEM_PROMPT = """You are an expert biblical scholar.
Read the provided Hebrew verse and answer with a single JSON object ONLY.
No markdown, no explanations.
{"god_action": "<5-12 word description in Russian of WHAT GOD DOES in this verse>"}"""

client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
active = client.models.list().data[0].id
print(f"LM Studio: OK | {active}")
print()

for sit in chron_empty[:3]:
    ref = f"{sit['book']} {sit['chapter']}:{sit['verse']}"
    text = sit.get("text_he", sit.get("text_plain",""))
    speech = sit.get("god_speech","")
    prompt = f"Reference: {ref}\nHebrew text: {text}"
    if speech:
        prompt += f"\nGod's speech: {speech}"
    
    print(f"  {ref:<35}", end="", flush=True)
    try:
        resp = client.chat.completions.create(
            model=active,
            messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":prompt}],
            temperature=0.1, max_tokens=3000, timeout=600
        )
        raw = resp.choices[0].message.content or ""
        raw = re.sub(r"<think>.*?</think>","",raw,flags=re.DOTALL).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            action = d.get("god_action","").strip()
            print(f"OK -> {action[:60]}")
        else:
            print(f"PARSE FAIL | raw: {raw[:80]}")
    except Exception as e:
        print(f"ERROR: {e}")

print("\n[DRY-RUN] Файл не изменён.")
