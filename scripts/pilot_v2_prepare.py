"""
pilot_v2_prepare.py
Пилот экстракции v2: подготовка нормализованного входа для агентов-сегментаторов.

Берёт text_he (НЕ text_plain — он битый: макаф склеен), снимает огласовки/теамим,
макаф -> пробел, и пишет батчи глав с перекрытием в 1 главу:
output/pilot_v2/<book>_input/batch_NN.txt  (формат строки: "глава:стих текст")

Usage:
    python pilot_v2_prepare.py --book Exodus
    python pilot_v2_prepare.py --book Genesis
"""
import json
import sys
import argparse
from pathlib import Path
from collections import defaultdict
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

TANAKH_DIR = Path(_REPO + "/data/tanakh")
OUTPUT_BASE = Path(_REPO + "/output/pilot_v2")


def normalize_he(text: str) -> str:
    """Консонантный текст: снять знаки кантилляции и огласовки, макаф -> пробел."""
    out = []
    for ch in text:
        o = ord(ch)
        if 0x0591 <= o <= 0x05BD or o in (0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7):
            continue  # теамим + никуд
        if o == 0x05BE:           # макаф
            out.append(" ")
            continue
        if o in (0x05C0, 0x05C3):  # пасек, соф-пасук
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def compute_batches(num_chapters: int, batch_size: int = 6, overlap: int = 1) -> list[tuple[int, int]]:
    """Вычисляет батчи глав с перекрытием."""
    step = batch_size - overlap
    batches = []
    start = 1
    while start <= num_chapters:
        end = min(start + batch_size - 1, num_chapters)
        batches.append((start, end))
        if end == num_chapters:
            break
        start += step
    return batches


def main():
    parser = argparse.ArgumentParser(description="Подготовка входных батчей для экстракции v2")
    parser.add_argument("--book", required=True, help="Имя книги (например: Genesis, Exodus, Jonah)")
    args = parser.parse_args()

    book = args.book
    book_file = TANAKH_DIR / f"{book}.json"

    if not book_file.exists():
        print(f"ОШИБКА: Файл {book_file} не найден")
        sys.exit(1)

    data = json.load(open(book_file, encoding="utf-8"))
    chapters = defaultdict(list)
    for v in data["verses"]:
        he = v.get("text_he") or v.get("text_clean") or ""
        chapters[v["chapter"]].append((v["verse"], normalize_he(he)))

    num_chapters = len(chapters)
    if num_chapters == 0:
        print(f"ОШИБКА: В {book} нет глав")
        sys.exit(1)

    # Базовые параметры батчей: размер 6 глав, шаг 5 (перекрытие 1 глава)
    BATCHES = compute_batches(num_chapters, batch_size=6, overlap=1)

    out_dir = OUTPUT_BASE / f"{book}_input"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    all_verses = sum(len(v) for v in chapters.values())

    for i, (c1, c2) in enumerate(BATCHES, 1):
        lines = [f"# {book}, главы {c1}-{c2}, консонантный иврит, формат: глава:стих текст"]
        n = 0
        for ch in range(c1, c2 + 1):
            for verse, text in sorted(chapters[ch]):
                lines.append(f"{ch}:{verse} {text}")
                n += 1
        path = out_dir / f"batch_{i:02d}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"batch_{i:02d}: главы {c1}-{c2}, {n} стихов, {path.stat().st_size // 1024} KB")
        total += n

    print(f"Книга: {book}, Глав: {num_chapters}, стихов: {all_verses}, строк в батчах (с перекрытием): {total}")
    assert num_chapters == max(chapters.keys()), f"{book}: количество глав не совпадает"
    assert all_verses > 0, f"{book}: нет стихов"
    print("OK")


if __name__ == "__main__":
    main()