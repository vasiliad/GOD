"""Сборка аудио-таймкодов Танаха: docs/data/audio/{key}.json.

Источник записи: Abraham Shmuelof (CC BY-NC-ND 4.0):
  - таймкоды — из Media Overlays (SMIL) внутри EPUB на ebible.org/multimedia/hbo/
  - аудио — те же файлы verbatim на archive.org (item HebBible_AShmuelof),
    совпадение байтов проверено (Oba 701724, Gen 1 1054601)
Принцип: аудио не нарезается и не изменяется (ND) — плеер страницы играет
оригинальную главу с перемоткой на стих по таймкодам, некоммерчески (NC), с
атрибуцией (BY). Выход: {"code":"Gen","single":false,"chapters":{"1":{"1":[b,e],...}}}
"""
import io, json, os, re, sys, urllib.request, urllib.parse, zipfile
from concurrent.futures import ThreadPoolExecutor

TEMP = os.environ.get("TEMP", "/tmp")
BASE = "https://ebible.org/multimedia/hbo/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
ARCHIVE_ITEM = "HebBible_AShmuelof"

# английские имена из href → ключи BOOK_NAMES страницы
NAME2KEY = {
    "Genesis": "genesis", "Exodus": "Exodus", "Leviticus": "Leviticus", "Numbers": "Numbers",
    "Deuteronomy": "Deuteronomy", "Joshua": "Joshua", "Judges": "Judges", "Ruth": "Ruth",
    "First Samuel": "I_Samuel", "Second Samuel": "II_Samuel",
    "First Kings": "I_Kings", "Second Kings": "II_Kings",
    "First Chronicles": "I_Chronicles", "Second Chronicles": "II_Chronicles",
    "Ezra": "Ezra", "Nehemiah": "Nehemiah", "Esther": "Esther", "Job": "Job",
    "Psalms": "Psalms", "Proverbs": "Proverbs", "Ecclesiastes": "Ecclesiastes",
    "Song of Songs": "Song_of_Songs", "Isaiah": "Isaiah", "Jeremiah": "Jeremiah",
    "Lamentations": "Lamentations", "Ezekiel": "Ezekiel", "Daniel": "Daniel",
    "Hosea": "Hosea", "Joel": "Joel", "Amos": "Amos", "Obadiah": "Obadiah",
    "Jonah": "Jonah", "Micah": "Micah", "Nahum": "Nahum", "Habakkuk": "Habakkuk",
    "Zephaniah": "Zephaniah", "Haggai": "Haggai", "Zechariah": "Zechariah", "Malachi": "Malachi",
}
# USFM-код в SMIL (верхний регистр) → суффикс файла на archive.org
USFM2ARCH = {
    "GEN": "Gen", "EXO": "Exo", "LEV": "Lev", "NUM": "Num", "DEU": "Deu", "JOS": "Jos",
    "JDG": "Jdg", "RUT": "Rut", "1SA": "1Sa", "2SA": "2Sa", "1KI": "1Ki", "2KI": "2Ki",
    "1CH": "1Ch", "2CH": "2Ch", "EZR": "Ezr", "NEH": "Neh", "EST": "Est", "JOB": "Job",
    "PSA": "Psa", "PRO": "Pro", "ECC": "Ecc", "SNG": "Sng", "ISA": "Isa", "JER": "Jer",
    "LAM": "Lam", "EZK": "Ezk", "DAN": "Dan", "HOS": "Hos", "JOL": "Jol", "AMO": "Amo",
    "OBA": "Oba", "JON": "Jon", "MIC": "Mic", "NAM": "Nam", "HAB": "Hab", "ZEP": "Zep",
    "HAG": "Hag", "ZEC": "Zec", "MAL": "Mal",
}
DST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "data", "audio")
os.makedirs(DST, exist_ok=True)


def fetch(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def epub_urls():
    html = io.open(os.path.join(TEMP, "ebible.html"), encoding="utf-8", errors="ignore").read()
    out = {}
    for href in re.findall(r'href="([^"]+\.epub)"', html):
        m = re.match(r"Tanakh fluent (\d+)-(.+?) [\u05d0-\u05ff]", href)
        if not m:
            continue
        name = m.group(2).strip()
        key = NAME2KEY.get(name)
        if key:
            out[key] = urllib.parse.quote(urllib.parse.urljoin(BASE, href), safe=":/")
    assert len(out) == 39, "найдено %d EPUB вместо 39" % len(out)
    return out


def parse_epub(path):
    """→ {chapter_int: {verse_int: [begin, end]}} из SMIL-ов EPUB."""
    z = zipfile.ZipFile(path)
    chapters = {}
    code = None
    for n in z.namelist():
        if not n.endswith(".smil"):
            continue
        m = re.search(r"00-([A-Z0-9]{3})-(\d+)\.xhtml\.smil$", n)
        if not m:
            continue
        code = m.group(1)
        ch = int(m.group(2))
        smil = z.read(n).decode("utf-8")
        clips = {}
        for par in re.findall(r"<par>.*?</par>", smil, re.S):
            tid = re.search(r'#([0-9]+)([a-z]+)"/?>?', par)
            clip = re.search(r'clipBegin="([\d.]+)"\s+clipEnd="([\d.]+)"', par)
            if not tid or not clip:
                continue
            v = int(tid.group(1))
            b, e = float(clip.group(1)), float(clip.group(2))
            if v in clips:
                clips[v] = [min(clips[v][0], b), max(clips[v][1], e)]
            else:
                clips[v] = [b, e]
        chapters[ch] = clips
    return code, chapters


def build(key, url):
    local = os.path.join(TEMP, "audio_epub_" + key + ".epub")
    fetch(url, local)
    code, chapters = parse_epub(local)
    os.remove(local)
    arch = USFM2ARCH[code]
    return key, code, arch, chapters


def main():
    urls = epub_urls()
    urls = {k: u for k, u in urls.items() if not os.path.exists(os.path.join(DST, k + ".json"))}
    print("EPUB-ов найдено:", len(urls), "— к сборке после пропуска готовых:", flush=True)
    results = {}
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(build, k, u): k for k, u in urls.items()}
        done = 0
        for f in as_completed(futs):
            k = futs[f]
            try:
                key, code, arch, chapters = f.result()
                results[key] = {"code": arch, "chapters": chapters}
                done += 1
                n_v = sum(len(c) for c in chapters.values())
                print("%2d/39 %s (%s): %d глав, %d стихов" % (done, key, code, len(chapters), n_v), flush=True)
            except Exception as e:
                print("ОШИБКА", k, ":", e, flush=True)
    # имена файлов на archive.org — сверка
    req = urllib.request.Request("https://archive.org/metadata/" + ARCHIVE_ITEM, headers=UA)
    meta = json.load(urllib.request.urlopen(req, timeout=60))
    have = {f["name"] for f in meta["files"] if f["name"].endswith(".mp3")}
    total_ch, total_v, missing = 0, 0, []
    for key, r in sorted(results.items()):
        code = r["code"]
        out = {"src": "hbof" + code, "chapters": {}}
        ch_nums = sorted(r["chapters"])
        for ch in ch_nums:
            pad = 3 if max(ch_nums) >= 100 else 2
            fname = "hbof" + code + ".mp3" if len(ch_nums) == 1 else "hbof" + code + "_" + (("%0" + str(pad) + "d") % ch) + ".mp3"
            if fname not in have:
                missing.append(fname)
                continue
            out["chapters"][str(ch)] = {str(v): c for v, c in sorted(r["chapters"][ch].items())}
            total_ch += 1
            total_v += len(r["chapters"][ch])
        io.open(os.path.join(DST, key + ".json"), "w", encoding="utf-8", newline="\n").write(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print("\nИТОГ: глав с аудио %d/929, стихов %d; нет на archive.org: %s" % (total_ch, total_v, missing or "нет"))
    idx = {k: sorted(v["chapters"], key=int) for k, v in results.items()}
    io.open(os.path.join(DST, "_index.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(idx, ensure_ascii=False, separators=(",", ":")))
    print("index:", {k: len(v) for k, v in list(idx.items())[:5]})


if __name__ == "__main__":
    sys.exit(main())
