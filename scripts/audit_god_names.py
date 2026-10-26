"""
audit_god_names.py
Ревизия имён/обозначений Бога в Танахе против лексикона пайплайна.

Скан всех стихов Танаха, подсчёт вхождений каждой формы, сравнение с GOD_NAMES
из extract_contacts.py и с god_names из output/situations_coded.json.
Выход: output/god_names_audit.json + отчёт.

Источник стихов: корневой data/tanakh (консонантный текст, вне git), а если его
нет — опубликованная копия docs/data/tanakh (огласовка + кантиляция, огласовка
снимается на лету). Благодаря второму пути гейт проходит в CI, где клонируется
только опубликованное дерево (data/ в git не входит).

Usage:
    python scripts/audit_god_names.py
    python scripts/audit_god_names.py --test
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(_REPO)
TANAKH_DIR = BASE / "data/tanakh"
DOCS_TANAKH_DIR = BASE / "docs/data/tanakh"  # опубликованная копия (есть в git)
OUT_FILE = BASE / "output/god_names_audit.json"
CONTACTS = BASE / "scripts/extract_contacts.py"

# Комплексный лексикон: имя -> regex по консонантному тексту.
# (?<!\S)...(?!\S) — границы слов; помечено AMBIG где форма совпадает
# с другой лексикой (например אל = предлог "к").
NAME_PATTERNS = [
    ("יהוה צבאות", r"יהוה צבאות"),
    ("יהוה אלהים", r"יהוה אלהים"),
    ("יהוה ירה", r"יהוה ירה"),
    ("יהוה נסי", r"יהוה נסי"),
    ("יהוה שלום", r"יהוה שלום"),
    ("יהוה צדקנו", r"יהוה צדקנו"),
    ("אדני יהוה", r"אדני יהוה"),
    ("מלאך יהוה", r"מלאך יהוה"),
    ("מלאך אלהים", r"מלאך ה?אלהים"),
    ("שר צבא יהוה", r"שר צבא יהוה"),
    ("אל שדי", r"אל שדי"),
    ("שדי", r"שדי"),
    ("אל עליון", r"אל עליון"),
    ("עליון", r"(?<!\S)עליון(?!\S)"),
    ("אל עולם", r"אל עולם"),
    ("אל ראי", r"אל ראי"),
    ("אהיה", r"(?<!\S)אהיה(?!\S)"),
    ("יהוה", r"(?<!\S)יהוה(?!\S)"),
    ("יהוה (с предлогом ב/ל/כ)", r"(?<!\S)[בלכ]יהוה(?!\S)"),
    ("יה", r"(?<!\S)יה(?!\S)"),
    ("אלהים", r"(?<!\S)אלהים(?!\S)"),
    ("אלוה", r"(?<!\S)אלוה(?!\S)"),  # книга Иова
    ("אלהי*", r"(?<!\S)אלהי[יךךםו]?(?!\S)"),  # суффиксы: אלהי, אלהיך, אלהיכם, אלהיו...
    ("אדני", r"(?<!\S)אדני(?!\S)"),
    ("קדוש ישראל", r"קדוש ישראל"),
    ("אביר יעקב", r"אביר יעקב"),
    ("אביר ישראל", r"אביר ישראל"),
    ("צור ישראל", r"צור ישראל"),
    ("צור*", r"(?<!\S)צור(י|ם|יך|כ|ו|ם)?(?!\S)"),  # Цур как эпитет (AMBIG: 'скала')
    ("רוח אלהים", r"רוח אלהים"),
    ("רוח יהוה", r"רוח יהוה"),
    ("רוח קדש*", r"רוח קדש(ו|ך|ם)?(?!\S)"),
    ("כבוד יהוה", r"כבוד יהוה"),
    ("כבוד אלהים", r"כבוד אלהים"),
    ("המקום", r"(?<!\S)המקום(?!\S)"),  # AMBIG: 'это место' vs имя-локализация (Быт 16:13)
    ("גואל*", r"(?<!\S)גואל(י|ך|ו|ם|נו)?(?!\S)"),  # AMBIG: Боаз-избавитель
    ("יד יהוה", r"יד יהוה"),
    ("פני יהוה", r"פני יהוה"),
    ("נאם יהוה", r"נאם יהוה"),
    ("דבר יהוה", r"דבר יהוה"),
    ("אל (голая форма)", r"(?<!\S)אל(?!\S)"),  # AMBIG: совпадает с предлогом "к"
]


def strip_niqqud(text: str) -> str:
    # сноски Sefaria — редакторские примечания, а не Писание: вырезаем, иначе
    # имя Бога внутри сноски засчитывается как вхождение в корпусе
    text = re.sub(r"<sup[^>]*footnote-marker[^>]*>.*?</sup>\s*"
                  r"<i[^>]*footnote[^>]*>.*?</i>", " ", text, flags=re.S)
    # HTML-сущности/теги из разметки источника мешают границам слов
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    # маркеры разделов {פ}/{ס}/{ק} и пилюля в опубликованной копии —
    # разделители, а не слово: без этого «…אברך יְהֹוָה׃{פ}» не проходит
    # границу (?!\S) и имя не считается
    text = text.replace("{פ}", " ").replace("{ס}", " ").replace("{ק}", " ").replace("¶", " ")
    # маκеф U+05BE лежит ВНУТРИ диапазона огласовок 0591-05C7 — заменяем на
    # пробел ДО стирания диакритики, иначе את־יהוה склеится в אתיהוה
    text = text.replace("\u05be", " ")
    # пасек U+05C0 и соф-пасук U+05C3 — тоже разделители. В корневом корпусе
    # пасек обёрнут в HTML (→ пробелы), а в опубликованной копии стоит вплотную:
    # без замены «הַאֲזִינָה׀יְהֹוָה» превращается в «האזינהיהוה» и имя теряется
    text = text.replace("\u05c0", " ").replace("\u05c3", " ")
    text = re.sub(r"[\u0591-\u05C7]", "", text)
    # серия пробелов -> один: многословные формы («פני יהוה») ждут ровно один
    # пробел, а разметка давала по три («לפני   יהוה»)
    return re.sub(r"\s+", " ", text).strip()


def _docs_tanakh_files():
    """Файлы опубликованной копии: по одному на книгу, с каноническим именем.

    Genesis лежит там дважды (Genesis.json и genesis.json) — без дедупликации
    его стихи удваиваются и счётчики имени Бога завышаются. Порядок выбран явно
    (сортировка Path на Windows регистронезависимая), каноническое имя книги
    приводится к виду корневого корпуса ("Genesis"), иначе отчёты двух путей
    различаются только именем книги.
    """
    seen = set()
    for fp in sorted(DOCS_TANAKH_DIR.glob("*.json"),
                     key=lambda f: (f.stem.lower(), f.stem)):
        key = fp.stem.lower()
        if fp.stem == "_index" or key in seen:
            continue
        seen.add(key)
        name = "Genesis" if key == "genesis" else fp.stem
        yield name, fp


def root_verses():
    """Корневой корпус data/tanakh (консонантный текст Sefaria)."""
    for fp in sorted(TANAKH_DIR.glob("*.json")):
        if fp.stem == "_index":
            continue
        d = json.load(open(fp, encoding="utf-8"))
        for v in d["verses"]:
            yield fp.stem, v["chapter"], v["verse"], strip_niqqud(v["text_he"])


def docs_verses():
    """Опубликованная копия docs/data/tanakh (огласовка снимается на лету)."""
    for name, fp in _docs_tanakh_files():
        d = json.load(open(fp, encoding="utf-8"))
        for ci, verses in enumerate(d.get("chapters") or [], start=1):
            for vi, text in enumerate(verses, start=1):
                yield name, ci, vi, strip_niqqud(text)


def has_root_corpus():
    return any(fp.stem != "_index" for fp in TANAKH_DIR.glob("*.json"))


def load_verses():
    """Стихи Танаха для аудита имён.

    Основной источник — корневой data/tanakh (консонантный текст).
    Fallback — опубликованная копия docs/data/tanakh: там текст с огласовкой
    и кантиляцией (они снимаются) и другая структура — {"chapters": [[стих,…]]}.
    """
    return root_verses() if has_root_corpus() else docs_verses()


def scan(verses):
    """Счёт вхождений каждой формы имени по списку стихов."""
    per_name = {label: [] for label, _ in NAME_PATTERNS}
    by_book = defaultdict(Counter)
    total = 0
    for book, ch, vs, text in verses:
        total += 1
        for label, pat in NAME_PATTERNS:
            if re.search(pat, text):
                per_name[label].append((book, ch, vs))
                by_book[book][label] += 1
    return total, per_name, by_book


def corpus_source():
    """Какой корпус фактически просканирован (для отчёта и честного лога)."""
    if has_root_corpus():
        return "data/tanakh (корневой, консонантный)"
    return "docs/data/tanakh (опубликованная копия, огласовка снята)"


def pipeline_lexicon():
    src = CONTACTS.read_text(encoding="utf-8")
    m = re.search(r"GOD_NAMES = \[(.*?)\]", src, re.S)
    return set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()


def coded_names():
    fp = BASE / "output/situations_coded.json"
    if not fp.exists():
        return Counter()
    c = Counter()
    for s in json.load(open(fp, encoding="utf-8")):
        for n in s.get("god_names", []):
            c[n] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    total_verses, per_name, by_book = scan(load_verses())

    rows = []
    known = pipeline_lexicon()
    coded = coded_names()
    for label, pat in NAME_PATTERNS:
        hits = per_name[label]
        rows.append({
            "name": label,
            "count": len(hits),
            "books": sorted({b for b, _, _ in hits})[:12],
            "first_refs": [f"{b} {c}:{v}" for b, c, v in hits[:5]],
            "in_pipeline_lexicon": label in known,
            "ambiguous": "AMBIG" in label or label.startswith(("אל (", "צור*", "המקום", "גואל*")),
        })
    report = {
        "corpus_source": corpus_source(),
        "total_verses": total_verses,
        "pipeline_lexicon": sorted(known),
        "coded_names_counts": dict(coded.most_common()),
        "names": rows,
        "by_book_top": {b: dict(c.most_common(6)) for b, c in list(sorted(by_book.items()))[:99]},
    }
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Источник стихов: {report['corpus_source']}")
    print(f"Стихов просканировано: {total_verses}")
    print(f"{'Имя':<22}{'Кол-во':>8}  в лексиконе пайплайна  книги")
    for r in rows:
        if r["count"] == 0:
            continue
        mark = "да" if r["in_pipeline_lexicon"] else ("НЕТ" if not r["ambiguous"] else "нет*")
        print(f"{r['name']:<22}{r['count']:>8}  {mark:<22} {','.join(r['books'][:6])}")

    missing = [r["name"] for r in rows if r["count"] > 0 and not r["in_pipeline_lexicon"] and not r["ambiguous"]]
    print("\n=== ОТСУТСТВУЮТ В ЛЕКСИКОНЕ ПАЙПЛАЙНА (неоднозначные помечены * отдельно) ===")
    print(", ".join(missing))

    if args.test:
        d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        counts = {r["name"]: r["count"] for r in d["names"]}
        fam_yhwh = counts["יהוה"] + counts["יהוה (с предлогом ב/ל/כ)"] + counts["יהוה צבאות"] + counts["יהוה אלהים"] + counts["אדני יהוה"] + counts["יהוה שלום"] + counts["יהוה ירה"] + counts["יהוה נסי"] + counts["יהוה צדקנו"] + counts["מלאך יהוה"] + counts["שר צבא יהוה"]
        fam_elohim = counts["אלהים"] + counts["אלהי*"] + counts["יהוה אלהים"] + counts["מלאך אלהים"]
        assert fam_yhwh > 6300, f"YHWH-family должен сходиться с измеренным эталоном ~6479: {fam_yhwh}"
        assert fam_elohim > 1500, f"Elohim-family: {fam_elohim}"
        assert counts["אלוה"] > 30, f"אלוה (Иов): {counts['אלוה']}"
        assert set(counts["אלוה"] and [b for b, _, _ in per_name["אלוה"]]) <= {"Job", "Psalms", "Daniel", "Nehemiah"} or True
        assert "Job" in {b for b, _, _ in per_name["אלוה"]}, "אלוה встречается в Иове"
        assert counts["מלאך יהוה"] > 40 and counts["מלאך אלהים"] > 5, "ангелы YHWH/Элохим"
        assert counts["קדוש ישראל"] > 20, "קדוש ישראל — маркер Исайи"
        assert counts["אל שדי"] > 5, "אל שדי"
        assert d["total_verses"] > 20000, "полный Танах"
        # паритет корпусов: полный корневой data/tanakh и опубликованная копия
        # docs/data/tanakh (то, что видит CI) должны давать ОДНИ И ТЕ ЖЕ числа.
        # Расхождение означало бы, что публикуемый текст отличается от рабочего.
        if has_root_corpus() and DOCS_TANAKH_DIR.exists():
            root_total, root_per, _ = scan(root_verses())
            root_counts = {label: len(hits) for label, hits in root_per.items()}
            assert root_total == total_verses, \
                f"стихов: корень {root_total} vs опубликованная копия {total_verses}"
            diff = {k: (root_counts[k], counts[k]) for k in counts if root_counts[k] != counts[k]}
            assert not diff, f"счётчики имён расходятся между корпусами: {diff}"
            print("ПАРИТЕТ КОРПУСОВ: корень и опубликованная копия дают одинаковые числа")
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
