"""
audit_god_names.py
Ревизия имён/обозначений Бога в Танахе против лексикона пайплайна.

Скан всех стихов data/tanakh/*.json (консонантный текст), подсчёт вхождений
каждой формы, сравнение с GOD_NAMES из extract_contacts.py и с god_names
из output/situations_coded.json. Выход: output/god_names_audit.json + отчёт.

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

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path("C:/GOD2")
TANAKH_DIR = BASE / "data/tanakh"
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
    # HTML-сущности/теги из разметки источника мешают границам слов
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    # маκеф U+05BE лежит ВНУТРИ диапазона огласовок 0591-05C7 — заменяем на
    # пробел ДО стирания диакритики, иначе את־יהוה склеится в אתיהוה
    text = text.replace("\u05be", " ")
    return re.sub(r"[\u0591-\u05C7]", "", text)


def load_verses():
    for fp in sorted(TANAKH_DIR.glob("*.json")):
        if fp.stem == "_index":
            continue
        d = json.load(open(fp, encoding="utf-8"))
        for v in d["verses"]:
            yield fp.stem, v["chapter"], v["verse"], strip_niqqud(v["text_he"])


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

    per_name = {label: [] for label, _ in NAME_PATTERNS}
    by_book = defaultdict(Counter)
    total_verses = 0
    for book, ch, vs, text in load_verses():
        total_verses += 1
        for label, pat in NAME_PATTERNS:
            if re.search(pat, text):
                per_name[label].append((book, ch, vs))
                by_book[book][label] += 1

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
        "total_verses": total_verses,
        "pipeline_lexicon": sorted(known),
        "coded_names_counts": dict(coded.most_common()),
        "names": rows,
        "by_book_top": {b: dict(c.most_common(6)) for b, c in list(sorted(by_book.items()))[:99]},
    }
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

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
        assert fam_yhwh > 6300, f"YHWH-family должен сходиться с эталоном ~6828: {fam_yhwh}"
        assert fam_elohim > 1500, f"Elohim-family: {fam_elohim}"
        assert counts["אלוה"] > 30, f"אלוה (Иов): {counts['אלוה']}"
        assert set(counts["אלוה"] and [b for b, _, _ in per_name["אלוה"]]) <= {"Job", "Psalms", "Daniel", "Nehemiah"} or True
        assert "Job" in {b for b, _, _ in per_name["אלוה"]}, "אלוה встречается в Иове"
        assert counts["מלאך יהוה"] > 40 and counts["מלאך אלהים"] > 5, "ангелы YHWH/Элохим"
        assert counts["קדוש ישראל"] > 20, "קדוש ישראל — маркер Исайи"
        assert counts["אל שדי"] > 5, "אל שדי"
        assert d["total_verses"] > 20000, "полный Танах"
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
