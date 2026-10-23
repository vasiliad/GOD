"""Сборка аудио-таймкодов и медленных mp3 Танаха.

Запись: Abraham Shmuelof, CC BY-NC-ND 4.0.
  - fluent: verbatim с archive.org (item HebBible_AShmuelof, hbof...mp3), байтовое
    совпадение с EPUB проверено при верификации источника
  - slower: mp3 извлекаются из slower-EPUB ebible.org verbatim (переименование
    контейнера — не переработка) и заливаются на HF-датасет arabyan/tanakh-audio
Таймкоды обоих вариантов — из SMIL (Media Overlays) внутри EPUB; фрагменты —
полустишия "1a/1b", у коротких стихов буквы нет ("13") — регэксп учитывает оба вида.
Выход: docs/data/audio/{key}.json =
  {"fluent": {"chapters": {"1": {"a": "<mp3-url>", "1": [b,e], ...}}}, "slower": {...}}
Кэш EPUB: data/audio_cache/, извлечённые slower-mp3: data/slow_mp3/ (оба gitignored).
"""
import io, json, os, re, sys, urllib.request, urllib.parse, zipfile

TEMP = os.environ.get("TEMP", "/tmp")
BASE = "https://ebible.org/multimedia/hbo/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
ARCHIVE_ITEM = "HebBible_AShmuelof"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "audio_cache")
SLOW_MP3 = os.path.join(ROOT, "data", "slow_mp3")
DST = os.path.join(ROOT, "docs", "data", "audio")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(SLOW_MP3, exist_ok=True)
os.makedirs(DST, exist_ok=True)

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
USFM2ARCH = {
    "GEN": "Gen", "EXO": "Exo", "LEV": "Lev", "NUM": "Num", "DEU": "Deu", "JOS": "Jos",
    "JDG": "Jdg", "RUT": "Rut", "1SA": "1Sa", "2SA": "2Sa", "1KI": "1Ki", "2KI": "2Ki",
    "1CH": "1Ch", "2CH": "2Ch", "EZR": "Ezr", "NEH": "Neh", "EST": "Est", "JOB": "Job",
    "PSA": "Psa", "PRO": "Pro", "ECC": "Ecc", "SNG": "Sng", "ISA": "Isa", "JER": "Jer",
    "LAM": "Lam", "EZK": "Ezk", "DAN": "Dan", "HOS": "Hos", "JOL": "Jol", "AMO": "Amo",
    "OBA": "Oba", "JON": "Jon", "MIC": "Mic", "NAM": "Nam", "HAB": "Hab", "ZEP": "Zep",
    "HAG": "Hag", "ZEC": "Zec", "MAL": "Mal",
}
HF_SLOWER_BASE = "https://huggingface.co/datasets/arabyan/tanakh-audio/resolve/main/slower/"


def fetch(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=900) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def epub_urls():
    html = io.open(os.path.join(TEMP, "ebible.html"), encoding="utf-8", errors="ignore").read()
    out = {}
    for href in re.findall(r'href="([^"]+\.epub)"', html):
        m = re.match(r"Tanakh (fluent|slower) (\d+)-(.+?) [\u05d0-\u05ff]", href)
        if not m:
            continue
        key = NAME2KEY.get(m.group(3).strip())   # группа 3 — имя книги (2 — номер)
        if key:
            out.setdefault(m.group(1), {})[key] = urllib.parse.quote(
                urllib.parse.urljoin(BASE, href), safe=":/")
    assert len(out.get("fluent", {})) == 39, "fluent: %d" % len(out.get("fluent", {}))
    assert len(out.get("slower", {})) == 39, "slower: %d" % len(out.get("slower", {}))
    return out


def parse_epub(path):
    """→ (USFM-код, {глава: {стих: [begin, end]}}) из SMIL-ов."""
    z = zipfile.ZipFile(path)
    chapters, code = {}, None
    for n in z.namelist():
        m = re.search(r"00-([A-Z0-9]{3})-(\d+)\.xhtml\.smil$", n)
        if not m:
            continue
        code = m.group(1)
        ch = int(m.group(2))
        smil = z.read(n).decode("utf-8")
        clips = {}
        for par in re.findall(r"<par>.*?</par>", smil, re.S):
            tid = re.search(r'#(\d+)([a-z]*)"/?>?', par)          # буквы может не быть ("13")
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


def chapter_file(code, ch, ch_count):
    """Имя mp3: Oba одним файлом, Псалтирь — 3 цифры, остальные — 2."""
    if ch_count == 1:
        return code + ".mp3"
    pad = 3 if ch_count >= 100 else 2
    return code + "_" + ("%0" + str(pad) + "d") % ch + ".mp3"


def extract_slow_mp3(path, key):
    """Извлечь mp3 slower-EPUB verbatim → data/slow_mp3/{key}_{NNN}.mp3."""
    z = zipfile.ZipFile(path)
    saved = []
    for n in z.namelist():
        if not n.lower().endswith(".mp3"):
            continue
        m = re.search(r"00-[A-Z0-9]{3}-(\d+)\.mp3$", n)
        if not m:
            continue
        target = os.path.join(SLOW_MP3, "%s_%s.mp3" % (key, m.group(1)))
        with z.open(n) as src, open(target, "wb") as dst:
            while True:
                chunk = src.read(1 << 16)
                if not chunk:
                    break
                dst.write(chunk)
        saved.append(int(m.group(1)))
    return saved


def build_variant(variant, key, url):
    local = os.path.join(CACHE, variant + "_" + key + ".epub")

    def valid(p):
        try:
            return os.path.getsize(p) > 10000 and zipfile.is_zipfile(p)
        except OSError:
            return False

    if not valid(local):                    # битый недокачанный файл — перекачать
        fetch(url, local)
    if not valid(local):
        try:
            os.remove(local)
        except OSError:
            pass
        raise RuntimeError("битый EPUB после загрузки: " + key)
    code, chapters = parse_epub(local)
    if variant == "slower":
        extract_slow_mp3(local, key)
    return code, chapters


def main():
    urls = epub_urls()
    print("EPUB: fluent %d, slower %d" % (len(urls["fluent"]), len(urls["slower"])), flush=True)
    parsed = {}
    for variant in ("fluent", "slower"):
        for i, (key, url) in enumerate(sorted(urls[variant].items()), 1):
            try:
                code, chapters = build_variant(variant, key, url)
                parsed.setdefault(key, {})[variant] = {"code": code, "chapters": chapters}
                print("%s %2d/39 %s (%s): %d глав, %d стихов" % (
                    variant[:3], i, key, code, len(chapters),
                    sum(len(c) for c in chapters.values())), flush=True)
            except Exception as e:
                print("ОШИБКА", variant, key, ":", repr(e), flush=True)
    # сверка fluent-имён с archive.org
    req = urllib.request.Request("https://archive.org/metadata/" + ARCHIVE_ITEM, headers=UA)
    meta = json.load(urllib.request.urlopen(req, timeout=60))
    have = {f["name"] for f in meta["files"] if f["name"].endswith(".mp3")}
    total, missing = 0, []
    for key, pv in sorted(parsed.items()):
        out = {}
        for variant in ("fluent", "slower"):
            if variant not in pv:
                continue
            code = pv[variant]["code"]
            arch = USFM2ARCH[code]
            ch_nums = sorted(pv[variant]["chapters"])
            chmap = {}
            for ch in ch_nums:
                if variant == "fluent":
                    fname = chapter_file(arch, ch, len(ch_nums))
                    if ("hbof" + fname) not in have:
                        missing.append("hbof" + fname)
                        continue
                    url = "https://archive.org/download/%s/hbof%s" % (ARCHIVE_ITEM, fname)
                else:
                    url = HF_SLOWER_BASE + key + "_" + ("%03d" % ch) + ".mp3"   # имена как в extract_slow_mp3
                chmap[str(ch)] = {"a": url}
                for v, clip in pv[variant]["chapters"][ch].items():
                    chmap[str(ch)][str(v)] = clip
            out[variant] = {"chapters": chmap}
        io.open(os.path.join(DST, key + ".json"), "w", encoding="utf-8", newline="\n").write(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")))
        if "fluent" in out:
            total += len(out["fluent"]["chapters"])
    slow_files = len([f for f in os.listdir(SLOW_MP3) if f.endswith(".mp3")])
    print("\nИТОГ: fluent %d/929 глав; slower mp3 извлечено %d; нет на archive.org: %s"
          % (total, slow_files, missing or "нет"), flush=True)


if __name__ == "__main__":
    sys.exit(main())
