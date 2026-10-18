"""
Source Hypothesis Analysis - J/E/D/P Classification
"""
import sys
import json
import os
import argparse
from collections import defaultdict, Counter
from pathlib import Path
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(_REPO)
INPUT     = BASE_DIR / "output" / "situations_coded.json"
TANAKH    = BASE_DIR / "data" / "tanakh"
PROFILE   = BASE_DIR / "output" / "god_profile.json"
OUT_HYP   = BASE_DIR / "output" / "source_hypothesis.json"
OUT_PROF  = BASE_DIR / "output" / "god_profile_by_source.json"

NUMBERS_CHAPTERS_J = {10, 11, 12, 13, 14, 16, 21, 25}
ANTHROPOMORPHIC_MARKERS = ["וילך", "וירד", "ויאמר אל", "רוח", "פנים", "אף", "ויחר"]
ELOHISTIC_MARKERS = ["מלאך", "חלום", "בחלום", "נראה", "מראה"]

def load_tanakh_index():
    index = {}
    if TANAKH.exists():
        for f in TANAKH.glob("*.json"):
            if f.name == "_index.json": continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                book = data.get("book", f.stem)
                texts_he = []
                for ch in data.get("chapters", []):
                    if isinstance(ch, list):
                        texts_he.extend(ch)
                    elif isinstance(ch, dict):
                        texts_he.extend(ch.values())
                index[book] = " ".join(str(t) for t in texts_he)
            except Exception as e:
                print(f"  [WARN] {f.name}: {e}")
    return index

def classify_source(sit: dict, tanakh_idx: dict) -> str:
    book = sit.get("book", "")
    reference = sit.get("ref", "")
    text_he   = sit.get("text_he", "") or ""
    text_plain = sit.get("text", "") or ""

    if book == "Deuteronomy": return "D"
    if book == "Leviticus": return "P"
    if book == "Numbers":
        try:
            chap = int(str(sit.get("chapter", "0")))
            if chap in NUMBERS_CHAPTERS_J:
                return "J"
        except Exception:
            pass
        return "P"

    book_text = tanakh_idx.get(book, "")
    combined  = text_he + " " + text_plain + " " + book_text[:500]

    yhwh_count    = combined.count("יהוה")
    elohim_count  = combined.count("אלהים")
    anthropo      = any(m in combined for m in ANTHROPOMORPHIC_MARKERS)
    elohi_markers = any(m in combined for m in ELOHISTIC_MARKERS)

    ritual_words = ["קרבן", "עולה", "זבח", "מנחה", "שבת", "כהן", "מקדש", "חוקה", "משפט"]
    ritual_count = sum(1 for w in ritual_words if w in combined)
    if ritual_count >= 3 and elohim_count >= yhwh_count: return "P"

    if anthropo or (yhwh_count > 0 and yhwh_count >= elohim_count and not elohi_markers): return "J"
    if elohi_markers or (elohim_count > yhwh_count): return "E"

    if book == "Genesis": return "J"
    if book == "Exodus": return "J"
    return "unclear"

def build_source_profile(situations: list) -> dict:
    source_sits = defaultdict(list)
    for s in situations:
        src = s.get("source", "unclear")
        source_sits[src].append(s)

    profiles = {}
    for src, sits in sorted(source_sits.items()):
        if not sits: continue
        
        bt_counter = Counter(s.get("behavior_type", "unknown") for s in sits)
        total = len(sits)
        bt_dist = {k: round(v / total, 3) for k, v in bt_counter.most_common()}

        # BUGFIX: severity, not severity_score
        severities = [s.get("severity", 3) for s in sits if "severity" in s]
        avg_sev = round(sum(severities) / len(severities), 2) if severities else None

        # BUGFIX: trigger, not trigger_type
        triggers = [s.get("trigger") for s in sits if s.get("trigger")]
        dom_trigger = Counter(triggers).most_common(1)[0][0] if triggers else None

        books = Counter(s.get("book", "?") for s in sits)
        top_books = dict(books.most_common(5))

        # BUGFIX: emotions is a list
        em_list = []
        for s in sits:
            for e in s.get("emotions", []):
                em_list.append(e)
        emotions = Counter(em_list)
        top_emotions = dict(emotions.most_common(3))

        profiles[src] = {
            "total_situations": total,
            "pct_of_all":       round(total / max(len(situations), 1), 3),
            "behavior_type_dist": bt_dist,
            "avg_severity":     avg_sev,
            "dominant_trigger": dom_trigger,
            "top_books":        top_books,
            "top_emotions":     top_emotions,
        }
    return profiles

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN limit 15")
    args = parser.parse_args()

    print("=== Source Hypothesis Analysis (J/E/D/P) ===\n")

    if not INPUT.exists():
        print(f"ОШИБКА: {INPUT} не найден. Требуется Фаза 4.")
        sys.exit(1)

    print(f"[1/4] Загрузка situations_coded.json …")
    situations = json.loads(INPUT.read_text(encoding="utf-8"))
    
    if args.test:
        situations = situations[:15]
        print("[DRY-RUN] Тестовый режим: 15 записей.")

    print(f"      Загружено {len(situations)} ситуаций")

    print(f"[2/4] Загрузка текстов Танаха …")
    tanakh_idx = load_tanakh_index()
    print(f"      Индексировано книг: {len(tanakh_idx)}")

    print(f"[3/4] Классификация по источникам …")
    source_counts = Counter()
    for sit in situations:
        src = classify_source(sit, tanakh_idx)
        sit["source"] = src
        source_counts[src] += 1

    print("      Распределение:")
    for src, cnt in sorted(source_counts.items()):
        pct = cnt / len(situations) * 100
        print(f"        {src:8s}: {cnt:4d}  ({pct:.1f}%)")

    profiles = build_source_profile(situations)

    if not args.test:
        print(f"\n[4/4] Сохранение результатов …")
        OUT_HYP.write_text(json.dumps(situations, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"      [OK] {OUT_HYP}")
        OUT_PROF.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"      [OK] {OUT_PROF}")
    else:
        print("\n[DRY-RUN] Сохранение пропущено.")

    print("\n=== Психопрофиль по источникам ===")
    for src, p in profiles.items():
        dom_bt = list(p["behavior_type_dist"].keys())[0] if p["behavior_type_dist"] else "—"
        print(f"\n  [{src}] n={p['total_situations']}, "
              f"avg_severity={p['avg_severity']}, "
              f"dominant_behavior={dom_bt}, "
              f"dominant_trigger={p['dominant_trigger']}")
        bks = ", ".join(p["top_books"].keys())
        print(f"       top_books: {bks}")
        if p["top_emotions"]:
            em = ", ".join(f"{k}({v})" for k, v in p["top_emotions"].items())
            print(f"       top_emotions: {em}")

    print("\n=== DONE ===")

if __name__ == "__main__":
    main()
