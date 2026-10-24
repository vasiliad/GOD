"""Русский перевод для читалки: Синодальный (1876), общественное достояние.

Источник: api.getbible.net/v2/synodal/{книга}.json (ВЗ переводился с масоретского
иврита). Выравнивание по числу стихов: равны — впрямую; RU на 1 больше — первый
стих это заглавие (сбрасываем); иначе null (глава без перевода — честно).
Особые случаи: Псалмы — славянская нумерация (евр.9+10 = Пс.9, сдвиг заглавия);
Малахия — евр. 3 = синод. 3+4; Иоиль — евр. 2 = синод.2[:27], евр. 3 = хвост
синод.2, евр. 4 = синод.3; Есфирь/Даниил — греческие добавления отсекаются.
Выход: docs/data/tanakh-ru/{key}.json = {"chapters": [null | [стих, ...], ...]}
"""
import io, json, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "docs", "data", "tanakh-ru")
os.makedirs(DST, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ключ страницы → номер книги ВЗ в synodal
BOOKS = {
    "genesis": 1, "Exodus": 2, "Leviticus": 3, "Numbers": 4, "Deuteronomy": 5,
    "Joshua": 6, "Judges": 7, "Ruth": 8, "I_Samuel": 9, "II_Samuel": 10,
    "I_Kings": 11, "II_Kings": 12, "I_Chronicles": 13, "II_Chronicles": 14,
    "Ezra": 15, "Nehemiah": 16, "Esther": 17, "Job": 18, "Psalms": 19,
    "Proverbs": 20, "Ecclesiastes": 21, "Song_of_Songs": 22, "Isaiah": 23,
    "Jeremiah": 24, "Lamentations": 25, "Ezekiel": 26, "Daniel": 27,
    "Hosea": 28, "Joel": 29, "Amos": 30, "Obadiah": 31, "Jonah": 32,
    "Micah": 33, "Nahum": 34, "Habakkuk": 35, "Zephaniah": 36, "Haggai": 37,
    "Zechariah": 38, "Malachi": 39,
}


def fetch(nr):
    req = urllib.request.Request("https://api.getbible.net/v2/synodal/%d.json" % nr, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def align(ru_verses, he_count):
    """→ [тексты] или None: равны — впрямую; RU на 1 больше — заглавие сброшено."""
    if ru_verses is None:
        return None
    n = len(ru_verses)
    if n == he_count:
        return ru_verses
    if n == he_count + 1:
        return ru_verses[1:]
    return None


def main():
    he = {}
    for k in BOOKS:
        he[k] = json.load(io.open(os.path.join(ROOT, "docs", "data", "tanakh", k + ".json"),
                                  encoding="utf-8"))["chapters"]
    total, covered = 0, 0
    for key, nr in BOOKS.items():
        d = fetch(nr)
        ru = [[v["text"].strip() for v in c["verses"]] for c in d["chapters"]]
        chapters = []
        if key == "Psalms":
            for n_h, he_ps in enumerate(he[key], start=1):
                if n_h <= 8:
                    m = ru[n_h - 1]
                elif n_h == 9:
                    m = None                       # синод. Пс.9 = евр.9+10 с потерей стиха — честный null
                elif n_h == 10:
                    m = ru[8][21:39]                # Пс.9:22–39 = евр. Пс.10
                elif n_h in (114, 115):
                    m = ru[112][:8] if n_h == 114 else ru[112][8:]   # слав.113 = евр.114+115
                elif n_h == 116:
                    m = ru[113] + ru[114]           # слав.114+115 = евр.116
                elif n_h == 147:
                    m = ru[145] + ru[146]           # слав.146+147 = евр.147
                elif n_h <= 147:
                    m = ru[n_h - 2]                 # слав. = евр. − 1
                else:
                    m = ru[n_h - 1]
                chapters.append(align(m, len(he_ps)))
        elif key == "Malachi":
            for i, ch in enumerate(he[key]):
                m = ru[i] if i < 2 else ru[2] + ru[3]   # евр.3 = синод.3+4
                chapters.append(align(m, len(ch)))
        elif key == "Joel":
            for i, ch in enumerate(he[key]):
                m = [ru[0], ru[1][:27], ru[1][27:], ru[2]][i]
                chapters.append(align(m, len(ch)))
        else:
            for i, ch in enumerate(he[key]):
                chapters.append(align(ru[i] if i < len(ru) else [], len(ch)))
        n_ok = sum(1 for c in chapters if c)
        total += len(chapters)
        covered += n_ok
        if len(chapters) != n_ok:
            miss = [i + 1 for i, c in enumerate(chapters) if not c]
            print("%s: %d/%d глав, без перевода: %s" % (key, n_ok, len(chapters), miss[:12]))
        io.open(os.path.join(DST, key + ".json"), "w", encoding="utf-8", newline="\n").write(
            json.dumps({"chapters": chapters}, ensure_ascii=False, separators=(",", ":")))
        time.sleep(1)
    print("\nИТОГ: %d/%d глав с переводом" % (covered, total))


if __name__ == "__main__":
    sys.exit(main())
