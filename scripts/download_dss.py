"""
Скачивает доступные тексты Кумранских свитков.
Источник: The Comprehensive Aramaic Lexicon / открытый DSS корпус

⚠ СТАТУС (2026-10-17, аудит v1): ЗАБЛОКИРОВАНО НА ИСТОЧНИКЕ.
Названия в DSS_TEXTS НЕ существуют в Sefaria (проверен весь индекс из 6 610
заголовков — ни одного "Dead Sea Scrolls"/"Qumran"); это была заглушка v1.
Открыто лицензированных транскрипций DSS нет: транскрипции Леона Леви /
Израильского музея / Абегга — под ограничениями (изображения свободны, текст нет).
Публикация соскрейпленных транскрипций в публичный репозиторий недопустима.
Слой DSS ожидает источник с совместимой лицензией. Не запускать без замены источника.
"""
import requests, json, sys, argparse
from pathlib import Path

OUTPUT_DIR = Path("C:/GOD2/data/dss")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Доступные через Sefaria DSS тексты
DSS_TEXTS = [
    "Dead Sea Scrolls, Community Rule",
    "Dead Sea Scrolls, War Scroll",
    "Dead Sea Scrolls, Thanksgiving Hymns",
    "Dead Sea Scrolls, Damascus Document",
    "Dead Sea Scrolls, Temple Scroll",
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    index = {}
    BASE_URL = "https://www.sefaria.org/api/texts/{text}?lang=he&context=0"
    
    texts_to_process = DSS_TEXTS[:1] if args.test else DSS_TEXTS
    total_errors = 0

    print(f"=== DSS Downloader (Test: {args.test}) ===")

    for text in texts_to_process:
        safe_name = text.replace(", ", "_").replace(" ", "_")
        out_file = OUTPUT_DIR / f"{safe_name}.json"
        
        if out_file.exists() and not args.test:
            try:
                with open(out_file, encoding='utf-8') as f:
                    data = json.load(f)
                if data:
                    print(f"[SKIP] {text}")
                    index[text] = str(out_file)
                    continue
            except Exception:
                pass

        url = BASE_URL.format(text=requests.utils.quote(text))
        print(f"[FETCH] {text}...")
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            # Fail-fast on empty data
            if not data or not data.get("he"):
                print(f"  -> ERROR: Пустой ответ API. Заглушка не создается (Правило #7).")
                total_errors += 1
                continue

            if not args.test:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                index[text] = str(out_file)
                print(f"  -> OK")
            else:
                print(f"  [DRY-RUN] Извлечен текст для {text}")
        except Exception as e:
            print(f"  -> ERROR (API недоступно): {e}")
            total_errors += 1
            if total_errors >= 3:
                print("!!! Fail-Fast: Слишком много ошибок Sefaria API. Выход.")
                sys.exit(1)

    if not args.test:
        with open(OUTPUT_DIR / "_index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print(f"\nDSS загрузка завершена. Индекс: data/dss/_index.json")

if __name__ == "__main__":
    main()
