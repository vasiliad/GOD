"""Быстрый тест extract_contacts.py на первых 3 книгах."""
import json, re, sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

# Временно ограничиваем до 3 книг
import scripts.extract_contacts as ec

TANAKH_DIR  = Path("C:/GOD2/data/tanakh")
index = json.load(open(TANAKH_DIR / "_index.json", encoding="utf-8"))

results = []
books = list(index.items())[:3]

for book_name, book_path in books:
    for verse in ec.iter_verses(Path(book_path), book_name):
        m = ec.SUBJECT_RE.search(verse["text_plain"])
        if not m:
            continue
        speech = ec.extract_god_speech(verse["text_plain"], verse["text_original"], m)
        results.append({
            "ref": f"{book_name} {verse['chapter']}:{verse['verse']}",
            "verb": m.group("verb"),
            "name": m.group("name"),
            "god_speech": speech[:60] if speech else "",
            "text": verse["text_plain"][:70],
        })

print(f"Первые 3 книги: найдено {len(results)} ситуаций\n")
for r in results[:15]:
    speech_mark = "💬" if r["god_speech"] else "  "
    print(f"{speech_mark} [{r['ref']:20}] {r['verb']} + {r['name']}")
    if r["god_speech"]:
        print(f"   речь: {r['god_speech']}")
    print(f"   стих: {r['text']}")
    print()
