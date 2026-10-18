"""
Sentiment Analysis of God's Speech/Actions across Tanakh
Task: sentiment-001
Output: output/sentiment_timeline.json, output/sentiment_by_book.json
"""

import json
import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    vader_available = True
except ImportError:
    vader_available = False
    print("[WARN] vaderSentiment not available, using rule-based only")

HEBREW_POLARITY = {
    "חסד": +2.0, "אהב": +2.0, "ברך": +2.0, "שלום": +2.0, "טוב": +1.0, "ישע": +1.5,
    "רחם": +1.5, "נחם": +0.5, "קנא": -1.5, "אף": -2.0, "שחת": -3.0, "מות": -2.0,
    "קלל": -2.0, "שפט": -1.0, "ענש": -1.5, "שכח": -0.5,
}

BEHAVIOR_SCORES = {
    "punishment":   -2.0, "judgment":     -1.5, "warning":      -1.0, "rebuke":       -1.0,
    "command":       0.0, "question":     -0.3, "covenant":     +1.5, "promise":      +1.5,
    "blessing":     +2.0, "rescue":       +2.0, "protection":   +1.5, "revelation":   +0.5,
    "teaching":     +0.5, "divine_test":  -0.5, "calling":      +0.5, "healing":      +1.5,
    "forgiveness":  +2.0, "comfort":      +1.5, "anger":        -2.0, "destruction":  -3.0,
    "lament":       -1.0, "other":         0.0, "dialogue":      0.0, "unclear":       0.0,
}

BOOK_ORDER = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth", "I Samuel", "II Samuel",
    "I Kings", "II Kings", "Isaiah", "Jeremiah", "Ezekiel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Psalms", "Proverbs", "Job", "Song of Songs", "Ecclesiastes",
    "Lamentations", "Esther", "Daniel", "Ezra", "Nehemiah",
    "I Chronicles", "II Chronicles",
]

def book_index(book_name: str) -> int:
    for i, b in enumerate(BOOK_ORDER):
        if b.lower() in book_name.lower() or book_name.lower() in b.lower():
            return i
    return 99

def score_hebrew(text: str) -> float:
    if not text: return 0.0
    total = sum(score for word, score in HEBREW_POLARITY.items() if word in text)
    return max(-3.0, min(3.0, total))

def score_vader(text: str, analyzer) -> float:
    if not text or not analyzer: return 0.0
    return analyzer.polarity_scores(str(text))["compound"] * 3.0

def dominant_emotion(score: float, behavior_type: str) -> str:
    if score >= 2.0: return "joy/blessing"
    elif score >= 1.0: return "loving-kindness"
    elif score >= 0.3: return "neutral-positive"
    elif score >= -0.3: return "neutral"
    elif score >= -1.0: return "displeasure"
    elif score >= -2.0: return "anger/wrath"
    else: return "fury/destruction"

def severity_modifier(severity) -> float:
    try:
        s = int(severity)
        return 0.5 - (s - 1) * 0.5
    except (TypeError, ValueError):
        return 0.0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN limit 10")
    args = parser.parse_args()

    ROOT = Path(_REPO)
    INPUT  = ROOT / "output" / "situations_coded.json"
    OUT_TL = ROOT / "output" / "sentiment_timeline.json"
    OUT_BK = ROOT / "output" / "sentiment_by_book.json"

    if not INPUT.exists():
        print(f"ОШИБКА: {INPUT} не найден. Сначала выполните Фазу 4 (code_behaviors).")
        sys.exit(1)

    with open(INPUT, encoding="utf-8") as f:
        situations = json.load(f)

    if args.test:
        situations = situations[:10]
        print("[DRY-RUN] Режим тестирования. Обрабатываем до 10 записей.")

    print(f"Loaded {len(situations)} situations")
    analyzer = SentimentIntensityAnalyzer() if vader_available else None

    entries = []
    for sit in situations:
        book    = sit.get("book", "Unknown")
        chapter = sit.get("chapter", 0)
        verse   = sit.get("verse", 0)
        btype   = str(sit.get("behavior_type", "other")).lower().strip()
        severity = sit.get("severity", 3)
        # BUGFIX: target text_plain instead of missing god_action
        text_plain = sit.get("text_plain", "") or ""
        god_speech = sit.get("god_speech", "") or sit.get("direct_speech", "") or ""

        base = BEHAVIOR_SCORES.get(btype, 0.0)
        sev_mod = severity_modifier(severity)
        heb_score = score_hebrew(text_plain) * 0.3
        vader_score = score_vader(god_speech, analyzer) * 0.2

        total = round(max(-3.0, min(3.0, base + sev_mod + heb_score + vader_score)), 3)
        emotion = dominant_emotion(total, btype)

        entries.append({
            "book": book, "chapter": int(chapter) if chapter else 0, "verse": int(verse) if verse else 0,
            "behavior_type": btype, "severity": severity, "sentiment_score": total,
            "dominant_emotion": emotion, "book_order": book_index(book),
        })

    entries.sort(key=lambda x: (x["book_order"], x["chapter"], x["verse"]))

    chapter_groups = defaultdict(list)
    for e in entries:
        chapter_groups[(e["book"], e["chapter"], e["book_order"])].append(e["sentiment_score"])

    timeline = []
    for (book, chapter, order), scores in sorted(chapter_groups.items(), key=lambda x: (x[0][2], x[0][1])):
        avg = round(sum(scores) / len(scores), 3)
        timeline.append({
            "book": book, "chapter": chapter, "book_order": order,
            "avg_sentiment": avg, "dominant_emotion": dominant_emotion(avg, ""), "n_situations": len(scores),
        })

    book_groups = defaultdict(list)
    for e in entries:
        book_groups[(e["book"], e["book_order"])].append(e["sentiment_score"])

    by_book = []
    for (book, order), scores in sorted(book_groups.items(), key=lambda x: x[0][1]):
        avg  = round(sum(scores) / len(scores), 3)
        pos  = sum(1 for s in scores if s > 0.3)
        neg  = sum(1 for s in scores if s < -0.3)
        neu  = len(scores) - pos - neg
        by_book.append({
            "book": book, "book_order": order, "avg_sentiment": avg, "dominant_emotion": dominant_emotion(avg, ""),
            "n_situations": len(scores), "positive_pct": round(pos / len(scores) * 100, 1) if scores else 0,
            "negative_pct": round(neg / len(scores) * 100, 1) if scores else 0,
            "neutral_pct":  round(neu / len(scores) * 100, 1) if scores else 0,
            "min_score": round(min(scores), 3) if scores else 0, "max_score": round(max(scores), 3) if scores else 0,
        })

    if not args.test:
        with open(OUT_TL, "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        print(f"[OK] Saved sentiment_timeline.json ({len(timeline)} chapters)")

        with open(OUT_BK, "w", encoding="utf-8") as f:
            json.dump(by_book, f, ensure_ascii=False, indent=2)
        print(f"[OK] Saved sentiment_by_book.json ({len(by_book)} books)")

    all_scores = [e["sentiment_score"] for e in entries]
    global_avg = round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0
    pos_total  = sum(1 for s in all_scores if s > 0.3)
    neg_total  = sum(1 for s in all_scores if s < -0.3)

    print("\n=== SENTIMENT SUMMARY ===")
    print(f"Total situations analyzed : {len(all_scores)}")
    print(f"Global average sentiment  : {global_avg}")
    if args.test:
        print("\n[DRY-RUN] Тест успешен. Файлы не перезаписаны.")

if __name__ == "__main__":
    main()
