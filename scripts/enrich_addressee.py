"""
enrich_addressee.py
Классификатор addressee_type для situations_coded.json.

Режимы:
  python enrich_addressee.py --test     # тест на 20 ситуациях, результат в консоль
  python enrich_addressee.py            # полный прогон с resume и сохранением каждые 50

LM Studio: Start Server → порт 1234, любая модель (DictaLM рекомендована).
"""
import json
import re
import sys
import time
import argparse
from pathlib import Path
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
LM_STUDIO_URL = "http://localhost:1234/v1"
LM_STUDIO_KEY = "lm-studio"

INPUT_FILE    = Path("C:/GOD2/output/situations_coded.json")
OUTPUT_FILE   = Path("C:/GOD2/output/situations_coded_enriched.json")
BACKUP_FILE   = Path("C:/GOD2/output/situations_coded_backup.json")

SAVE_EVERY    = 50
REQUEST_DELAY = 0.05
API_TIMEOUT   = 45
LOG_EVERY     = 10
TEST_SIZE     = 20   # количество ситуаций для тестового прогона

# ============================================================
# ПРОМПТ — двуязычный (иврит + английский), few-shot
# ============================================================
CLASSIFIER_PROMPT = """\
אתה מסווג מידע מקראי. תפקידך לקבוע מי מקבל את התגובה האלוהית במצב הנתון.

Classify who receives God's response. Answer with EXACTLY ONE English word only:
- prophet  → God speaks directly to a prophet, leader or mediator (Moses, Abraham, Isaiah, Jeremiah, Ezekiel, Samuel, Elijah, Joshua)
- nation   → God addresses a collective: Israel, a people, an army, a city (Nineveh, Jerusalem, Egypt)
- individual → God responds to a private person, foreigner, or individual sinner (Hagar, Hannah, Job, Cain)

Few-shot examples (input → answer):
[Genesis, Moses, command, Abraham receives promise] → prophet
[Exodus, Israel, punishment, nation rebels] → nation
[Genesis, Hagar, rescue, individual in desert] → individual
[I Kings, Elijah, revelation, prophet at Horeb] → prophet
[Jeremiah, Jerusalem, punishment, city under siege] → nation
[Job, Job, dialogue, individual questions God] → individual

CRITICAL: Reply with ONLY the single English word: prophet | nation | individual
Do NOT use Hebrew. Do NOT explain. Do NOT add punctuation.\
"""

# Маппинг ивритских ответов (на случай если модель всё равно отвечает на иврите)
HEBREW_MAP = {
    "נביא": "prophet", "נָבִיא": "prophet",
    "עם": "nation",   "עַם": "nation",   "גוי": "nation", "גּוֹי": "nation",
    "יחיד": "individual", "יָחִיד": "individual", "איש": "individual", "אִישׁ": "individual",
}
VALID = {"prophet", "nation", "individual"}


def extract_label(raw: str) -> str:
    """Извлекает метку из ответа модели (включая thinking-модели с <think> блоками)."""
    # 1. Убираем <think>...</think>
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # 2. Ищем английское слово
    for label in VALID:
        if re.search(rf"\b{label}\b", cleaned, re.IGNORECASE):
            return label

    # 3. Ищем ивритский эквивалент
    for heb, eng in HEBREW_MAP.items():
        if heb in cleaned:
            return eng

    # 4. Фолбэк — ищем в исходном тексте включая <think>
    for label in VALID:
        if re.search(rf"\b{label}\b", raw, re.IGNORECASE):
            return label
    for heb, eng in HEBREW_MAP.items():
        if heb in raw:
            return eng

    return "unclear"


def build_user_message(s: dict) -> str:
    book        = s.get("book", "")
    verse       = s.get("verse", s.get("verse_start", ""))
    text        = s.get("text_he", s.get("text_plain", ""))[:300]
    behavior    = s.get("behavior_type", "")
    trigger     = s.get("trigger", "")
    participants = s.get("participants", "")
    target      = s.get("target", "")

    return (
        f"[{book} {verse}]\n"
        f"Text: {text}\n"
        f"Behavior: {behavior} | Trigger: {trigger}\n"
        f"Participants: {participants} | Target: {target}"
    )


def classify_one(client, model_name: str, s: dict) -> str:
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user",   "content": build_user_message(s)},
            ],
            temperature=0.0,
            max_tokens=50,
            timeout=API_TIMEOUT,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return extract_label(raw), raw
    except Exception as e:
        return "unclear", f"ERROR: {e}"


def connect(url: str, key: str):
    client = OpenAI(base_url=url, api_key=key)
    try:
        models = client.models.list()
        active = models.data[0].id if models.data else "local-model"
        print(f"LM Studio: OK | Модель: {active}")
        return client, active
    except Exception:
        print("Ошибка: LM Studio не отвечает (порт 1234)")
        sys.exit(1)


def save(situations: list, path: Path):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(situations, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def print_stats(situations: list):
    counts: dict = {}
    for s in situations:
        t = s.get("addressee_type", "—")
        counts[t] = counts.get(t, 0) + 1
    print("\nСтатистика addressee_type:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<12}: {v:>5} ({v*100//len(situations)}%)")


# ============================================================
# РЕЖИМ: ТЕСТ (20 ситуаций)
# ============================================================
def run_test(client, active_model: str, situations: list):
    # Берём разнообразную выборку: первые 5, средние 5, последние 5, случайных 5
    import random
    n = len(situations)
    sample_idx = list(range(0, 5)) + list(range(n//2, n//2+5)) + list(range(n-5, n)) + \
                 random.sample(range(5, n-5), 5)
    sample = [situations[i] for i in sorted(set(sample_idx))[:TEST_SIZE]]

    print(f"\n{'='*60}")
    print(f"ТЕСТ: {len(sample)} ситуаций")
    print(f"{'='*60}\n")

    results = []
    for i, s in enumerate(sample):
        label, raw = classify_one(client, active_model, s)
        results.append(label)

        # Компактный вывод: ref + participants + label + сырой ответ (50 chars)
        ref  = f"{s.get('book','?')} {s.get('verse','')}"
        part = str(s.get("participants", ""))[:30]
        raw_short = re.sub(r"<think>.*?</think>", "[think]", raw, flags=re.DOTALL)[:60]
        status = "✓" if label != "unclear" else "?"
        print(f"[{i+1:02d}] {status} {label:<12} | {ref:<25} | {part:<30} | raw: {raw_short}")
        time.sleep(REQUEST_DELAY)

    unclear_n = results.count("unclear")
    print(f"\n{'='*60}")
    print(f"Результат: {len(results) - unclear_n}/{len(results)} успешно классифицировано")
    print(f"Unclear: {unclear_n} | Prophet: {results.count('prophet')} | "
          f"Nation: {results.count('nation')} | Individual: {results.count('individual')}")
    print(f"{'='*60}")
    print("\nЕсли результат хороший → запусти без --test для полного прогона.")


# ============================================================
# РЕЖИМ: ПОЛНЫЙ ПРОГОН
# ============================================================
def run_full(client, active_model: str, situations: list):
    # Resume с enriched-файла
    if OUTPUT_FILE.exists():
        print(f"Найден {OUTPUT_FILE.name} — продолжаем...")
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            situations = json.load(f)

    already = sum(1 for s in situations if s.get("addressee_type") in VALID | {"unclear"})
    todo    = len(situations) - already
    print(f"Всего: {len(situations)} | Уже готово: {already} | Осталось: {todo}\n")

    if todo == 0:
        print("Все записи обработаны!")
        print_stats(situations)
        return

    processed = 0
    for s in situations:
        if s.get("addressee_type") in VALID | {"unclear"}:
            continue

        label, _ = classify_one(client, active_model, s)
        s["addressee_type"] = label
        processed += 1
        total = already + processed

        if processed % LOG_EVERY == 0:
            pct = total * 100 // len(situations)
            print(f"  [{total}/{len(situations)}] {pct}% | {label} | "
                  f"{s.get('book','')} {s.get('verse','')}")

        if processed % SAVE_EVERY == 0:
            save(situations, OUTPUT_FILE)
            print(f"  >>> Сохранено ({total} записей)")

        time.sleep(REQUEST_DELAY)

    save(situations, OUTPUT_FILE)
    print(f"\nГотово! Обработано: {processed}")
    print_stats(situations)
    print(f"\nФайл: {OUTPUT_FILE}")


# ============================================================
# ТОЧКА ВХОДА
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Тест на 20 ситуациях")
    args = parser.parse_args()

    print(f"Загружаем {INPUT_FILE}...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        situations = json.load(f)
    print(f"Загружено: {len(situations)} ситуаций")

    client, active_model = connect(LM_STUDIO_URL, LM_STUDIO_KEY)

    if args.test:
        run_test(client, active_model, situations)
    else:
        # Бэкап перед полным прогоном (только если ещё нет enriched-файла)
        if not OUTPUT_FILE.exists() and not BACKUP_FILE.exists():
            save(situations, BACKUP_FILE)
            print(f"Бэкап: {BACKUP_FILE}")
        run_full(client, active_model, situations)


if __name__ == "__main__":
    main()
