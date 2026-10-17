"""
judge_audit.py — Pass2: постфактум LLM-as-a-Judge валидация reasoning_dataset.jsonl.

Запуск ПОСЛЕ завершения generate_reasoning_dataset.py --no-judge.
Читает reasoning_dataset.jsonl, прогоняет каждую запись через Judge,
помечает невалидные и сохраняет чистый датасет в reasoning_dataset_clean.jsonl.

Запуск:
  python scripts/judge_audit.py --test   # 5 записей, файл не сохраняется
  python scripts/judge_audit.py          # боевой прогон
"""
import json
import re
import sys
import time
import argparse
from pathlib import Path
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")

LM_STUDIO_URL = "http://localhost:1234/v1"
LM_API_KEY    = "lm-studio"
INPUT_FILE    = Path("C:/GOD2/output/reasoning_dataset.jsonl")
OUTPUT_CLEAN  = Path("C:/GOD2/output/reasoning_dataset_clean.jsonl")
OUTPUT_REJECT = Path("C:/GOD2/output/reasoning_dataset_rejected.jsonl")
PROMPT_JUDGE  = Path("C:/GOD2/prompts/god_reasoning_judge.md")
API_TIMEOUT   = 600
MAX_TOKENS    = 800
SLEEP_BETWEEN = 3   # пауза между запросами (один вызов, нет перегрузки)
SAVE_EVERY    = 20

def run_judge(record: dict, client, active_model: str, judge_prompt: str):
    """Прогнать одну запись через Judge. Вернуть (is_valid, reason)."""
    # Собираем контекст из метаданных записи
    meta = record.get("metadata", {})
    context = (
        f"Book: {meta.get('book','')} | "
        f"Behavior: {meta.get('behavior_type','')} | "
        f"Trigger: {meta.get('trigger','')} | "
        f"Outcome: {meta.get('outcome','')}\n"
        f"Situation: {record.get('situation','')}"
    )
    generated = (
        f"<think>{record.get('think','')}</think>\n"
        f"<voice_hebrew>{record.get('voice_hebrew','')}</voice_hebrew>\n"
        f"<voice_russian>{record.get('voice_russian','')}</voice_russian>"
    )
    prompt = judge_prompt.replace("{{ORIGINAL_CONTEXT}}", context).replace("{{GENERATED_TEXT}}", generated)

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=active_model,
                messages=[
                    {"role": "system", "content": "You are a strict data evaluator. Output ONLY valid JSON, no markdown."},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.1,
                max_tokens=MAX_TOKENS,
                timeout=API_TIMEOUT,
            )
            raw = resp.choices[0].message.content or ""
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                if attempt == 2:
                    return False, f"Judge no JSON: {raw[:80]}"
                time.sleep(10)
                continue
            result = json.loads(m.group(0))
            return result.get("is_valid", False), result.get("reason", "")
        except Exception as e:
            if attempt == 2:
                return False, f"Exception: {e}"
            time.sleep(15)

    return False, "All retries failed"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN: 5 записей, файл не сохраняется")
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        print(f"ОШИБКА: {INPUT_FILE} не найден! Сначала запустите Pass1.")
        sys.exit(1)

    records = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    print(f"=== GOD2 Judge Audit Pass2 ===")
    print(f"Записей для валидации: {len(records)}")

    if args.test:
        records = records[:5]
        print(f"[DRY-RUN] Проверяем {len(records)} записей")

    judge_prompt = PROMPT_JUDGE.read_text(encoding="utf-8")

    client = OpenAI(base_url=LM_STUDIO_URL, api_key=LM_API_KEY)
    try:
        models = client.models.list()
        active = models.data[0].id if models.data else "unknown"
        print(f"LM Studio: OK | Модель: {active}")
    except Exception as e:
        print(f"ОШИБКА: LM Studio недоступен — {e}")
        sys.exit(1)

    valid = rejected = 0

    if not args.test:
        clean_f  = open(OUTPUT_CLEAN,  "w", encoding="utf-8")
        reject_f = open(OUTPUT_REJECT, "w", encoding="utf-8")

    for i, rec in enumerate(records, 1):
        sid = rec.get("metadata", {}).get("situation_id", f"#{i}")
        print(f"  [{i:3}/{len(records)}] {sid:<12}", end="", flush=True)

        is_valid, reason = run_judge(rec, client, active, judge_prompt)

        if is_valid:
            print(f"✓ VALID")
            valid += 1
            if not args.test:
                clean_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                clean_f.flush()
        else:
            print(f"✗ REJECTED: {reason[:60]}")
            rejected += 1
            if not args.test:
                rec["judge_reason"] = reason
                reject_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                reject_f.flush()

        if not args.test and i % SAVE_EVERY == 0:
            print(f"  [checkpoint {i}/{len(records)}] Valid={valid} Rejected={rejected}")

        time.sleep(SLEEP_BETWEEN)

    total = valid + rejected
    pct = valid / total * 100 if total else 0
    print(f"\nРезультат: {valid} valid, {rejected} rejected ({pct:.1f}% pass rate)")

    if not args.test:
        clean_f.close()
        reject_f.close()
        print(f"Чистый датасет: {OUTPUT_CLEAN}")
        print(f"Отклонённые:    {OUTPUT_REJECT}")
        print()
        # Fill-rate аудит
        import subprocess
        subprocess.run([sys.executable, "scripts/audit_phase.py", "--phase", "llm_dataset"])
    else:
        print("[DRY-RUN] Файлы не изменены.")

if __name__ == "__main__":
    main()
