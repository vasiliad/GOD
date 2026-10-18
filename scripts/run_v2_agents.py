"""
run_v2_agents.py
Запуск агентов-сегментаторов v2 для заданной книги.

Создаёт папки для эпизодов и запускает агентов параллельно (по одному на батч).
Каждый агент читает input/batch_NN.txt и пишет episodes/episodes_batch_NN.json.

Usage:
    python run_v2_agents.py --book Exodus
    python run_v2_agents.py --book Genesis --max-parallel 5
"""
import sys
import argparse
import subprocess
import json
from pathlib import Path
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_BASE = Path(_REPO + "/output/pilot_v2")
AGENT_PROMPT_FILE = Path(_REPO + "/prompts/segment_agent_v2.txt")


def compute_batches(num_chapters: int, batch_size: int = 6, overlap: int = 1) -> list[tuple[int, int]]:
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
    parser = argparse.ArgumentParser(description="Запуск агентов-сегментаторов v2")
    parser.add_argument("--book", required=True, help="Имя книги (например: Exodus, Genesis)")
    parser.add_argument("--max-parallel", type=int, default=10, help="Макс. параллельных агентов")
    parser.add_argument("--dry-run", action="store_true", help="Только показать команды, не запускать")
    args = parser.parse_args()

    book = args.book
    input_dir = OUTPUT_BASE / f"{book}_input"
    episodes_dir = OUTPUT_BASE / f"{book}_episodes"

    if not input_dir.exists():
        print(f"ОШИБКА: Входная директория {input_dir} не найдена")
        print(f"Сначала запустите: python scripts/pilot_v2_prepare.py --book {book}")
        sys.exit(1)

    episodes_dir.mkdir(parents=True, exist_ok=True)

    # Подсчёт батчей
    batch_files = sorted(input_dir.glob("batch_*.txt"))
    if not batch_files:
        print(f"ОШИБКА: В {input_dir} нет батчей")
        sys.exit(1)

    print(f"Книга: {book}")
    print(f"Батчей к обработке: {len(batch_files)}")
    print(f"Макс. параллельно: {args.max_parallel}")
    print(f"Эпизоды будут в: {episodes_dir}")

    if args.dry_run:
        print("\n=== DRY RUN — команды для запуска ===")
        for i, bf in enumerate(batch_files, 1):
            out_file = episodes_dir / f"episodes_batch_{i:02d}.json"
            print(f"  Agent {i}: {bf} -> {out_file}")
        return

    # Запуск агентов параллельно (в фоне)
    procs = []
    for i, bf in enumerate(batch_files, 1):
        out_file = episodes_dir / f"episodes_batch_{i:02d}.json"
        # Читаем батч для контекста
        batch_content = bf.read_text(encoding="utf-8")

        # Читаем промпт из файла (один источник истины)
        agent_prompt_template = AGENT_PROMPT_FILE.read_text(encoding="utf-8")
        prompt = f"""Ты — сегментатор библейских текстов v2. Твоя задача: разделить текст на эпизоды взаимодействия Человек↔Бог.

ВХОДНЫЕ ДАННЫЕ (батч {i} из {len(batch_files)} книги {book}):
{batch_content}

{agent_prompt_template}"""

        # Запускаем через claude CLI (агент)
        # Для реального запуска нужен доступ к claude CLI или API
        # Здесь создаём файл с промптом для ручного/параллельного запуска
        prompt_file = episodes_dir / f"prompt_batch_{i:02d}.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        print(f"[Agent {i:02d}] Промпт готов: {prompt_file}")
        print(f"[Agent {i:02d}] Вход: {bf}")
        print(f"[Agent {i:02d}] Выход: {out_file}")

    print(f"\nСоздано {len(batch_files)} файлов промптов в {episodes_dir}")
    print("Для запуска агентов используйте:")
    print("  - Параллельно в разных терминалах/сессиях Claude Code")
    print("  - Или через скрипт оркестрации (если настроен)")
    print("\nПосле завершения всех агентов запустите аудит:")
    print(f"  python scripts/merge_audit_v2.py --book {book}")


if __name__ == "__main__":
    main()