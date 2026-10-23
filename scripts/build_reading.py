"""Сборка данных читалки Танаха: docs/data/tanakh/{ключ}.json + _index.json.

Источник: data/tanakh/{Book}.json (Sefaria, скачано download_tanakh.py).
Выход: {"chapters": [[стих, стих, ...], ...]} — текст с огласовками (text_clean).
_index.json: {ключ: число_глав} — для навигации до загрузки книги.
Ключ книги = ключ BOOK_NAMES страницы (genesis, Judges, Song_of_Songs, ...).
"""
import json, io, os, glob

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(_REPO, "data", "tanakh")
DST = os.path.join(_REPO, "docs", "data", "tanakh")
os.makedirs(DST, exist_ok=True)

# страница хранит Бытие под ключом "genesis", файлы — "Genesis"
def page_key(book):
    return book[0].lower() + book[1:] if book == "Genesis" else book

index, total_verses, total_bytes = {}, 0, 0
for path in sorted(glob.glob(os.path.join(SRC, "*.json"))):
    name = os.path.basename(path)[:-5]
    if name == "_index":
        continue
    d = json.load(io.open(path, encoding="utf-8"))
    assert d.get("complete"), name
    chapters = []
    for v in d["verses"]:
        c = v["chapter"]
        while len(chapters) < c:
            chapters.append([])
        chapters[c - 1].append(v["text_clean"])
        total_verses += 1
    key = page_key(name)
    out = {"chapters": chapters}
    data = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    io.open(os.path.join(DST, key + ".json"), "w", encoding="utf-8", newline="\n").write(data)
    index[key] = len(chapters)
    total_bytes += len(data.encode("utf-8"))

io.open(os.path.join(DST, "_index.json"), "w", encoding="utf-8", newline="\n").write(
    json.dumps(index, ensure_ascii=False, separators=(",", ":")))
print("книг: %d, стихов: %d, размер: %.1f МБ" % (len(index), total_verses, total_bytes / 1e6))
