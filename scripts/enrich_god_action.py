"""
enrich_god_action.py — Точечное обогащение situations_coded.json полем god_action.

НЕ перегоняет всю Фазу 4. Читает situations_coded.json,
находит записи где god_action пустое и дозаполняет только их.

Запуск:
  python scripts/enrich_god_action.py --test   # 5 записей, файл не сохраняется
  python scripts/enrich_god_action.py          # боевой прогон
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
CODED_FILE    = Path("C:/GOD2/output/situations_coded.json")
API_TIMEOUT   = 600
MAX_TOKENS    = 3000
SLEEP_BETWEEN = 0.5
SAVE_EVERY    = 10

SYSTEM_PROMPT = """You are an expert biblical scholar.
Read the provided Hebrew verse and answer with a single JSON object ONLY.
No markdown, no explanations, no <think> tags outside your reasoning.

The JSON must contain exactly ONE key:
{
  "god_action": "<a concise 5-12 word description in Russian of WHAT GOD PHYSICALLY OR VERBALLY DOES in this verse>"
}

Examples of god_action:
- "произносит творческое повеление да будет свет"
- "открывает завет с Авраамом обетование потомства"
- "насылает казни на Египет за отказ отпустить народ"
- "призывает Моисея из горящего куста"
- "молчит не отвечает на вопли народа"
"""

def extract_god_action(raw: str) -> str:
    """Извлечь god_action из сырого ответа LLM."""
    if not raw:
        return ""
    # Убрать <think>...</think>
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    raw = re.sub(r'```(?:json)?\s*', '', raw).replace('```', '').strip()
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return ""
    try:
        data = json.loads(m.group(0))
        action = str(data.get("god_action", "")).strip()
        return action if len(action) > 3 else ""
    except json.JSONDecodeError:
        return ""

def build_prompt(sit: dict) -> str:
    ref  = f"{sit.get('book', '')} {sit.get('chapter', '')}:{sit.get('verse', '')}"
    text = sit.get('text_he', sit.get('text_plain', ''))
    speech = sit.get('god_speech', '')
    p = f"Reference: {ref}\nHebrew text: {text}"
    if speech:
        p += f"\nGod's speech: {speech}"
    return p

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN: 5 записей, файл не сохраняется")
    args = parser.parse_args()

    if not CODED_FILE.exists():
        print(f"ОШИБКА: {CODED_FILE} не найден.")
        sys.exit(1)

    with open(CODED_FILE, encoding="utf-8") as f:
        situations = json.load(f)

    # Найти только те где god_action пустое
    to_enrich = [s for s in situations if not s.get("god_action", "").strip()]
    print(f"Всего записей: {len(situations)}")
    print(f"Требуют обогащения (god_action пустой): {len(to_enrich)}")

    if len(to_enrich) == 0:
        print("Все записи уже имеют god_action. Обогащение не требуется.")
        sys.exit(0)

    if args.test:
        # Берём по одной записи из 5 разных книг — не первые Genesis подряд
        seen_books = {}
        for s in to_enrich:
            book = s.get("book", "")
            if book not in seen_books:
                seen_books[book] = s
            if len(seen_books) >= 5:
                break
        to_enrich = list(seen_books.values())
        print(f"[DRY-RUN] Обрабатываем {len(to_enrich)} записей из {len(seen_books)} разных книг: {list(seen_books.keys())}")

    # Проверка LM Studio
    client = OpenAI(base_url=LM_STUDIO_URL, api_key=LM_API_KEY)
    try:
        models = client.models.list()
        active = models.data[0].id if models.data else "unknown"
        print(f"LM Studio: OK | Модель: {active}")
    except Exception as e:
        print(f"ОШИБКА: LM Studio недоступен — {e}")
        sys.exit(1)

    # Индекс situaions по id для быстрого патча
    id_to_idx = {s.get("id"): i for i, s in enumerate(situations)}

    ok = errors = 0

    for idx_proc, sit in enumerate(to_enrich, 1):
        sit_id = sit.get("id", "?")
        ref = f"{sit.get('book', '')} {sit.get('chapter', '')}:{sit.get('verse', '')}"
        print(f"  [{idx_proc:3}/{len(to_enrich)}] {ref:<30}", end="", flush=True)

        try:
            resp = client.chat.completions.create(
                model=active,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": build_prompt(sit)},
                ],
                temperature=0.1,
                max_tokens=MAX_TOKENS,
                timeout=API_TIMEOUT,
            )
            raw = resp.choices[0].message.content or ""
            action = extract_god_action(raw)

            if not action:
                print(f"✗  ПУСТОЙ ОТВЕТ")
                errors += 1
            else:
                print(f"✓  {action[:60]}")
                ok += 1
                if not args.test:
                    # Патчим оригинальный список
                    orig_idx = id_to_idx.get(sit_id)
                    if orig_idx is not None:
                        situations[orig_idx]["god_action"] = action

        except Exception as e:
            print(f"✗  ОШИБКА: {e}")
            errors += 1

        # Периодическое сохранение
        if not args.test and idx_proc % SAVE_EVERY == 0:
            with open(CODED_FILE, "w", encoding="utf-8") as f:
                json.dump(situations, f, ensure_ascii=False, indent=2)
            print(f"  [saved {idx_proc}/{len(to_enrich)}]")

        time.sleep(SLEEP_BETWEEN)

    # Финальное сохранение
    if not args.test and ok > 0:
        with open(CODED_FILE, "w", encoding="utf-8") as f:
            json.dump(situations, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] Сохранено в {CODED_FILE}")

    total_rate = ok / (ok + errors) if (ok + errors) > 0 else 0
    print(f"\nРезультат: {ok} OK, {errors} ошибок ({total_rate*100:.1f}% успех)")

    if args.test:
        print("[DRY-RUN] Файл не изменён.")
        # Запускаем аудит чтобы показать текущее состояние
        print("\nАудит Phase 4 (god_action всё ещё пустой — это DRY-RUN):")
    else:
        # Автоматический аудит после обогащения
        import subprocess
        print("\nЗапускаем audit_phase.py --phase phase_4 для проверки...")
        result = subprocess.run(
            [sys.executable, "scripts/audit_phase.py", "--phase", "phase_4"],
            capture_output=False
        )
        if result.returncode != 0:
            print("АУДИТ ПРОВАЛЕН. Нужно дополнительное исправление.")
            sys.exit(1)

if __name__ == "__main__":
    main()
