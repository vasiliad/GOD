"""Сборка данных читалки Танаха: docs/data/tanakh/{ключ}.json + _index.json.

Источник: data/tanakh/{Book}.json (Sefaria, скачано download_tanakh.py).
Выход: {"chapters": [[стих, стих, ...], ...]} — текст с огласовками.
_index.json: {ключ: число_глав} — для навигации до загрузки книги.
Ключ книги = ключ BOOK_NAMES страницы (genesis, Judges, Song_of_Songs, ...).

Текст берётся из поля text_he (разметка Sefaria), а не из text_clean:
text_clean выкидывал HTML-сущности вместе с разделителями, из-за чего в
поэтических стихах слова слипались («יְהֹוָהמִי», «עָ֑םיְהֹוָה»). Здесь теги и
сущности превращаются в пробел, поэтический разделитель (&nbsp;) сохраняется,
метка открытой секции {פ} показывается читателю как «¶».
"""
import json, io, os, glob, re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(_REPO, "data", "tanakh")
DST = os.path.join(_REPO, "docs", "data", "tanakh")
os.makedirs(DST, exist_ok=True)

# страница хранит Бытие под ключом "genesis", файлы — "Genesis"
def page_key(book):
    return book[0].lower() + book[1:] if book == "Genesis" else book


def clean_text(raw):
    """Разметка Sefaria -> читаемый текст.

    Инлайновые теги (<big>, <small>, <span>…) убираются БЕЗ пробела: они
    обёртывают буквы («<big>בְּ</big>רֵאשִׁית»), и пробел разорвал бы слово.
    Подстрочные примечания Sefaria (<sup class="footnote-marker">*</sup> +
    <i class="footnote">…</i>) вырезаются целиком: это редакторские
    заметки, а не Писание, и они дублируют имя Бога прямо внутри стиха.
    Сущности (&nbsp;, &thinsp;) заменяются пробелом, а не удаляются: в
    &nbsp;-разделителях проходит стихотворная строка, и удаление склеивает слова
    («יְהֹוָהמִי», «עָ֑םיְהֹוָה»). Метки секций {פ}/{ס} -> «¶».
    """
    text = re.sub(r"<sup class=\"footnote-marker\">.*?</sup>\s*"
                  r"<i class=\"footnote\">.*?</i>", " ", raw, flags=re.S)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"</?(?:span|b|small|big|sup|i)\b[^>]*>", "", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = text.replace("{פ}", " ¶ ").replace("{ס}", " ¶ ")
    text = re.sub(r"[ \u00a0]+", " ", text).strip()
    # мааф (־) в разметке Sefaria обёрнут в <span>: теги->пробел оставил бы его
    # отдельным словом («אַשְׁרֵי ־ הָאִישׁ»), а он соединяет слова
    return re.sub(r"\s*־\s*", "־", text)


index, total_verses, total_bytes = {}, 0, 0
written = set()
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
        chapters[c - 1].append(clean_text(v.get("text_he") or v.get("text_clean", "")))
        total_verses += 1
    key = page_key(name)
    out = {"chapters": chapters}
    data = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    io.open(os.path.join(DST, key + ".json"), "w", encoding="utf-8", newline="\n").write(data)
    written.add(key + ".json")
    index[key] = len(chapters)
    total_bytes += len(data.encode("utf-8"))

# stale-копии: файл книги, которого больше нет в индексе (например Genesis.json
# от старой сборки, где ключ не приводился к регистру страницы) — убираем,
# иначе в опубликованном дереве лежат две копии одной книги
removed = []
for fp in glob.glob(os.path.join(DST, "*.json")):
    if os.path.basename(fp) not in written and os.path.basename(fp) != "_index.json":
        removed.append(os.path.basename(fp))
        os.remove(fp)

io.open(os.path.join(DST, "_index.json"), "w", encoding="utf-8", newline="\n").write(
    json.dumps(index, ensure_ascii=False, separators=(",", ":")))
print("книг: %d, стихов: %d, размер: %.1f МБ" % (len(index), total_verses, total_bytes / 1e6)
      + ("; удалены устаревшие копии: " + ", ".join(removed) if removed else ""))
