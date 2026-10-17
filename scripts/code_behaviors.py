"""
code_behaviors.py
Этап 3 пайплайна "Tanakh Reasoning Model"

Семантически размечает 396 ситуаций взаимодействия Бога через LM Studio.
"""
import json
import re
import sys
import time
import argparse
from pathlib import Path
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")

INPUT_FILE    = Path("C:/GOD2/output/situations_registry.json")
OUTPUT_FILE   = Path("C:/GOD2/output/situations_coded.json")
PROMPT_FILE   = Path("C:/GOD2/prompts/god_behavior_sys.md")
LM_STUDIO_URL = "http://localhost:1234/v1"
LM_API_KEY    = "lm-studio"

TEMPERATURE   = 0.1
SLEEP_BETWEEN = 0.5
API_TIMEOUT   = 600
SAVE_EVERY    = 10

VALID = {
    "behavior_type": ["command", "punishment", "blessing", "revelation",
                      "promise", "rescue", "covenant", "dialogue"],
    "trigger":       ["prayer", "disobedience", "idolatry", "faithfulness",
                      "unprompted", "intercession", "distress", "divine_test"],
    "outcome":       ["punishment", "blessing", "covenant", "rescue",
                      "revelation", "compliance", "dialogue", "silence"],
    "addressee_type": ["prophet", "nation", "individual"],
}

def build_user_prompt(situation: dict) -> str:
    ref   = f"{situation['book']} {situation['chapter']}:{situation['verse']}"
    text  = situation.get("text_he", situation.get("text_plain", ""))
    val_names = situation.get("god_names", [])
    name = val_names[0] if val_names else ""
    verb = ""
    # In registry, interaction_keywords is a list. Take the first.
    kw = situation.get("interaction_keywords", [])
    verb = kw[0] if kw else ""
    speech = situation.get("god_speech", "")

    prompt = f"Reference: {ref}\nHebrew text: {text}\nGod's active verb: {verb}\nGod's name used: {name}"
    if speech:
        prompt += f"\nGod's speech: {speech}"
    return prompt

def extract_json_from_response(raw: str) -> dict:
    if not raw: return {}
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    raw = re.sub(r'```(?:json)?\s*', '', raw).replace('```', '').strip()
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m: return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}

def validate_and_clean(data: dict) -> dict:
    result = {}
    for field, allowed in VALID.items():
        val = data.get(field, "unclear")
        result[field] = val if val in allowed else "unclear"
    sev = data.get("severity", 0)
    try:
        sev = int(sev)
        result["severity"] = max(1, min(5, sev))
    except (TypeError, ValueError):
        result["severity"] = 0
    parts = data.get("participants", [])
    if isinstance(parts, list):
        result["participants"] = [str(p) for p in parts if p]
    elif isinstance(parts, str) and parts:
        result["participants"] = [parts]
    else:
        result["participants"] = []
    return result

def load_progress() -> dict:
    if not OUTPUT_FILE.exists(): return {}
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {item["id"]: item for item in data}
    except (json.JSONDecodeError, KeyError):
        return {}

def save_results(results: list):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN 3 записи")
    parser.add_argument("--reset", action="store_true", help="Игнорировать прогресс")
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        print(f"ОШИБКА: {INPUT_FILE} не найден.")
        sys.exit(1)

    with open(INPUT_FILE, encoding="utf-8") as f:
        situations = json.load(f)

    if args.test:
        # Берём по одной ситуации из разных книг для разнообразия
        books_seen = {}
        for s in situations:
            b = s.get("book", "")
            if b not in books_seen:
                books_seen[b] = s
            if len(books_seen) >= 3:
                break
        situations = list(books_seen.values())

    done = {} if args.reset else load_progress()
    skipped = len([s for s in situations if s.get("id") in done])

    client = OpenAI(base_url=LM_STUDIO_URL, api_key=LM_API_KEY)
    
    # Load system prompt
    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            SYSTEM_PROMPT = f.read()
    except Exception as e:
        print(f"ОШИБКА загрузки промпта: {e}")
        sys.exit(1)

    print(f"\nПроверяем LM Studio на {LM_STUDIO_URL}...")
    try:
        models = client.models.list()
        model_names = [m.id for m in models.data]
        active_model = model_names[0] if model_names else "local-model"
        print(f"Используем: {active_model}\n")
    except Exception as e:
        print(f"ОШИБКА: LM Studio недоступен — {e}")
        sys.exit(1)

    print(f"Ситуаций к обработке: {len(situations)} (пропускаем {skipped})\n")

    results = list(done.values())
    errors  = 0
    processed = 0

    for i, situation in enumerate(situations, 1):
        sit_id = situation.get("id")
        ref    = f"{situation.get('book')} {situation.get('chapter')}:{situation.get('verse')}"

        if sit_id in done and not args.test:
            print(f"  [{i:>3}/{len(situations)}] {ref:<30} ⏭")
            continue

        print(f"  [{i:>3}/{len(situations)}] {ref:<30} ", end="", flush=True)

        user_prompt = build_user_prompt(situation)
        try:
            response = client.chat.completions.create(
                model=active_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=TEMPERATURE,
                max_tokens=3000,
                timeout=API_TIMEOUT,
            )

            raw = (response.choices[0].message.content or "").strip()
            parsed = extract_json_from_response(raw)

            if parsed:
                coded_fields = validate_and_clean(parsed)
                bt = coded_fields.get("behavior_type", "?")
                sev = coded_fields.get("severity", "?")
                print(f"✓  [{bt}, sev={sev}]")
            else:
                raise ValueError(f"Невалидный JSON: {raw[:80]}")

        except Exception as e:
            coded_fields = {
                "behavior_type":  "unclear",
                "trigger":        "unclear",
                "outcome":        "unclear",
                "severity":       0,
                "participants":   [],
                "addressee_type": "unclear",
            }
            print(f"✗  ОШИБКА: {str(e)[:60]}")
            errors += 1
            if errors >= 5:
                print("!!! FAIL-FAST: Превышен лимит ошибок API. Остановка pipeline.")
                if not args.test: save_results(results)
                sys.exit(1)

        enriched = {**situation, **coded_fields}
        results.append(enriched)
        done[sit_id] = enriched
        processed += 1

        if not args.test and processed % SAVE_EVERY == 0:
            save_results(results)

    if not args.test:
        save_results(results)
        print(f"\nСохранено: {OUTPUT_FILE} ({processed} новых)")
    else:
        print("\n[DRY RUN] Файл не сохранён.\n")
        print("Пример извлеченного JSON результата:")
        print(json.dumps(results[-1] if results else {}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
