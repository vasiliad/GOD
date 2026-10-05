"""
Скачивает все книги Танаха на иврите через Sefaria API.
Сохраняет в data/tanakh/{book}.json
"""
import requests, json, re, time, sys, argparse
from pathlib import Path

OUTPUT_DIR = Path("C:/GOD2/data/tanakh")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TANAKH_BOOKS = {
    "Genesis": 50, "Exodus": 40, "Leviticus": 27, "Numbers": 36, "Deuteronomy": 34,
    "Joshua": 24, "Judges": 21, "I Samuel": 31, "II Samuel": 24,
    "I Kings": 22, "II Kings": 25,
    "Isaiah": 66, "Jeremiah": 52, "Ezekiel": 48,
    "Hosea": 14, "Joel": 4, "Amos": 9, "Obadiah": 1, "Jonah": 4, "Micah": 7,
    "Nahum": 3, "Habakkuk": 3, "Zephaniah": 3, "Haggai": 2, "Zechariah": 14, "Malachi": 3,
    "Psalms": 150, "Proverbs": 31, "Job": 42,
    "Song of Songs": 8, "Ruth": 4, "Lamentations": 5,
    "Ecclesiastes": 12, "Esther": 10, "Daniel": 12, "Ezra": 10, "Nehemiah": 13,
    "I Chronicles": 29, "II Chronicles": 36
}

STRIP_HTML = re.compile(r'<[^>]+>')
STRIP_ENTITIES = re.compile(r'&[a-zA-Z]+;|&#[0-9]+;')

def clean_text(text):
    text = STRIP_HTML.sub('', text)
    text = STRIP_ENTITIES.sub('', text)
    return text.strip()

def strip_nikud(text):
    return re.sub(r'[\u05B0-\u05C7\u05BD\u05BF\u05C1\u05C2\u0591-\u05AF]', '', text)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Сгенерировать только первые 2 главы Genesis")
    args = parser.parse_args()

    BASE_URL = "https://www.sefaria.org/api/texts/{ref}?lang=he&context=0"
    index = {}
    total_errors = 0
    MAX_ERRORS = 5

    books_to_process = {"Genesis": 2} if args.test else TANAKH_BOOKS

    print(f"=== Sefaria Downloader (Test: {args.test}) ===")

    for book, num_chapters in books_to_process.items():
        out_file = OUTPUT_DIR / f"{book.replace(' ', '_')}.json"
        
        if out_file.exists() and not args.test:
            try:
                with open(out_file, encoding='utf-8') as f:
                    existing = json.load(f)
                if existing.get('complete') and len(existing.get('verses', [])) > 0:
                    print(f"[SKIP] {book}")
                    index[book] = str(out_file)
                    continue
            except Exception:
                pass # Re-download if file is corrupted

        print(f"[FETCH] {book} ({num_chapters} глав)...")
        all_verses = []

        for ch in range(1, num_chapters + 1):
            ref = f"{book} {ch}"
            url = BASE_URL.format(ref=requests.utils.quote(ref))
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                he_texts = data.get("he", [])
                
                if isinstance(he_texts, str):
                    he_texts = [he_texts]
                    
                for vi, verse_text in enumerate(he_texts):
                    if not isinstance(verse_text, str) or not verse_text.strip():
                        continue
                    clean = clean_text(verse_text)
                    plain = strip_nikud(clean)
                    all_verses.append({
                        "chapter": ch,
                        "verse": vi + 1,
                        "text_he": verse_text,
                        "text_clean": clean,
                        "text_plain": plain
                    })
                time.sleep(0.3)
            except Exception as e:
                print(f"  -> ERROR {book} ch{ch}: {e}")
                total_errors += 1
                time.sleep(1)
                if total_errors >= MAX_ERRORS:
                    print("!!! Срабатывание Fail-Fast: Превышен лимит ошибок API. Остановка !!!")
                    sys.exit(1)

        if not all_verses:
            print(f"  -> FATAL: У книги {book} пустой массив стихов. Защита от мусора включена.")
            total_errors += 1
            continue

        if not args.test:
            result = {"book": book, "complete": True, "verses": all_verses}
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            index[book] = str(out_file)
            print(f"  -> OK, сохранено {len(all_verses)} стихов")
        else:
            print(f"  [DRY-RUN] Извлечено {len(all_verses)} стихов для книги {book}")

    if not args.test:
        with open(OUTPUT_DIR / "_index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print(f"\nЗавершено: собрано {len(index)} книг")
        print("Индекс: data/tanakh/_index.json")
    else:
        print("\n[DRY-RUN] Test execution completed.")

if __name__ == "__main__":
    main()
