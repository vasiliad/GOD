"""
dedup_overlaps.py
Глобальная дедупликация перекрытий эпизодов по всем книгам Танаха.

merge_audit_v2.py удаляет только точные дубли на границах батчей; внутри
объединённых файлов эпизоды могут перекрываться по стихам (разная гранулярность
агентов на перекрытиях глав). Скрипт: обнаруживает перекрытия, сливает
пересекающиеся эпизоды (объединение спана, конкатенация ссылок/цитат/эмоций),
пишет мастер-корпус без перекрытий.

Выход: output/episodes_TANAKH_v2.json + отчёт.

Usage:
    python scripts/dedup_overlaps.py
    python scripts/dedup_overlaps.py --test
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path("C:/GOD2")
GLOB = "output/episodes_*_v2.json"
OUT = BASE / "output/episodes_TANAKH_v2.json"

SPAN_RE = re.compile(r"(\d+):(\d+)")


def span_bounds(span):
    m1, m2 = SPAN_RE.match(span["start"]), SPAN_RE.match(span["end"])
    return (int(m1.group(1)), int(m1.group(2))), (int(m2.group(1)), int(m2.group(2)))


def overlap(a, b):
    try:
        (a1c, a1v), (a2c, a2v) = span_bounds(a["span"])
        (b1c, b1v), (b2c, b2v) = span_bounds(b["span"])
    except AttributeError:
        print("DEBUG bad span:", repr(a.get("span")), repr(b.get("span")), flush=True)
        raise    # перекрытие в линейном порядке (глава, стих); главы ≤999, стихи ≤999
    ka1, ka2, kb1, kb2 = a1c * 1000 + a1v, a2c * 1000 + a2v, b1c * 1000 + b1v, b2c * 1000 + b2v
    return max(ka1, kb1) <= min(ka2, kb2)


def merge_pair(a, b):
    """Слияние двух пересекающихся эпизодов: больший поглощает меньший."""
    big, small = (a, b) if len(a.get("god_speech_refs", [])) + len(a.get("human_speech_refs", [])) >= len(b.get("god_speech_refs", [])) + len(b.get("human_speech_refs", [])) else (b, a)
    a1, a2 = span_bounds(big["span"])
    b1, b2 = span_bounds(small["span"])
    start = min(a1, b1)
    end = max(a2, b2)
    big["span"] = {"start": f"{start[0]}:{start[1]}", "end": f"{end[0]}:{end[1]}"}
    for field in ("god_speech_refs", "human_speech_refs"):
        seen = list(big.get(field, []))
        for r in small.get(field, []):
            if r not in seen:
                seen.append(r)
        big[field] = seen
    for field in ("god_speech_plain", "human_speech_plain"):
        add = small.get(field, "")
        if add and add not in big.get(field, ""):
            big[field] = (big.get(field, "") + " ... " + add).strip(" .")
    big["emotions"] = (big.get("emotions") or []) + (small.get("emotions") or [])
    big["dedup_note"] = f"merged overlapping episode {small['span']['start']}-{small['span']['end']}"
    return big


def dedup_book(book, eps):
    eps = sorted(eps, key=lambda e: span_bounds(e["span"]))
    out = []
    merged_count = 0
    for e in eps:
        if out and overlap(out[-1], e):
            out[-1] = merge_pair(out[-1], e)
            merged_count += 1
        else:
            out.append(e)
    # второй проход: слияния могли создать новые перекрытия
    i = 1
    while i < len(out):
        if overlap(out[i - 1], out[i]):
            out[i - 1] = merge_pair(out[i - 1], out[i])
            del out[i]
            merged_count += 1
        else:
            i += 1
    return out, merged_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    master = {}
    report = {}
    for fp in sorted(BASE.glob(GLOB)):
        if fp.name == "episodes_TANAKH_v2.json":
            continue  # это ВЫХОД скрипта (словарь), а не вход
        book = fp.stem.replace("episodes_", "").replace("_v2", "")
        eps = json.load(open(fp, encoding="utf-8"))
        try:
            deduped, n = dedup_book(book, eps)
        except Exception:
            print("CRASH IN BOOK:", book, flush=True)
            raise
        master[book] = deduped
        report[book] = {"before": len(eps), "after": len(deduped), "merged": n}

    OUT.write_text(json.dumps(master, ensure_ascii=False, indent=1), encoding="utf-8")

    total_before = sum(r["before"] for r in report.values())
    total_after = sum(r["after"] for r in report.values())
    print(f"Книг: {len(master)}  эпизодов: {total_before} -> {total_after} (слито {total_before - total_after} перекрытий)")
    for b, r in sorted(report.items(), key=lambda x: -x[1]["merged"]):
        if r["merged"]:
            print(f"  {b:<15} {r['before']} -> {r['after']} (слито {r['merged']})")

    if args.test:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        assert len(d) == 39, f"книг в мастере: {len(d)}"
        # после слияния перекрытий смежные эпизоды не пересекаются
        for book, eps in d.items():
            bounds = [span_bounds(e["span"]) for e in eps]
            for i in range(1, len(bounds)):
                (p1c, p1v), (p2c, p2v) = bounds[i - 1]
                (c1c, c1v), (c2c, c2v) = bounds[i]
                kend, kstart = p2c * 1000 + p2v, c1c * 1000 + c1v
                assert kend < kstart, f"{book}: перекрытие на эпизодах {i-1}/{i}"
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
