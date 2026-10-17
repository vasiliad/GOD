"""
Строит детальный реестр ситуаций взаимодействия Бога и человека.
Версия 2: быстрая, локальная, использует interaction_keywords + text_plain.
"""
import json
import csv
import sys
import argparse
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

CONTACTS_FILE = Path("C:/GOD2/output/contacts_registry.json")
OUTPUT = Path("C:/GOD2/output")

KEYWORD_TO_CATEGORY = {
    # Речь / повеление
    "ויאמר":    "повеление", "וידבר":    "повеление", "ויצו":     "повеление",
    "צוה":      "повеление", "אמר":      "повеление",
    # Явление / теофания
    "וירא":     "явление", "ויראהו":   "явление", "ויגלה":    "откровение",
    "חזון":     "откровение", "חלום":     "откровение",
    # Завет
    "ברית":     "завет", "כרת":      "завет",
    # Молитва / Взывание
    "ויתפלל":   "молитва", "ויזעק":    "молитва", "ויצעק":    "молитва",
    "ויקרא":    "молитва", "תפלה":     "молитва",
    # Суд / Наказание
    "וישפט":    "суд", "משפט":     "суд", "ויכה":     "наказание",
    "ויאבד":    "наказание", "ויצמח":    "наказание", "עונש":     "наказание",
    # Спасение
    "ויושע":    "спасение", "ויצל":     "спасение", "ישועה":    "спасение",
    # Обещание
    "ויבטח":    "обещание", "הבטחה":    "обещание", "שבע":      "обещание",
}

def categorize(keywords: list, text_plain: str) -> str:
    for kw in keywords:
        kw_clean = kw.strip()
        if kw_clean in KEYWORD_TO_CATEGORY:
            return KEYWORD_TO_CATEGORY[kw_clean]
    for kw, cat in KEYWORD_TO_CATEGORY.items():
        if kw in text_plain:
            return cat
    return "другое"

def detect_initiator(keywords: list, text_plain: str) -> str:
    god_triggers    = {"ויאמר", "וידבר", "ויצו", "ויקרא", "ויגלה"}
    human_triggers  = {"ויתפלל", "ויזעק", "ויצעק", "ויקרא"}

    kw_set = set(k.strip() for k in keywords)
    if kw_set & god_triggers: return "God"
    if kw_set & human_triggers: return "Human"
    
    for kw in god_triggers:
        if kw in text_plain: return "God"
    for kw in human_triggers:
        if kw in text_plain: return "Human"
    return "unclear"

def detect_emotions(text_plain: str) -> list:
    emotion_map = {
        "гнев":        ["אף", "חמה", "קצף", "זעם"],
        "милость":     ["חסד", "רחמים", "חנן", "אהב"],
        "страх":       ["יראה", "פחד", "אימה"],
        "радость":     ["שמחה", "גיל", "ששון"],
        "скорбь":      ["אבל", "בכה", "יבך"],
        "ревность":    ["קנאה", "קנא"],
        "праведность": ["צדק", "צדקה", "ישר"],
    }
    emotions = []
    for emotion, markers in emotion_map.items():
        if any(m in text_plain for m in markers):
            emotions.append(emotion)
    return emotions

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN limit 5")
    args = parser.parse_args()

    print("Строим реестр ситуаций...")

    if not CONTACTS_FILE.exists():
        print(f"ОШИБКА: Файл {CONTACTS_FILE} не найден. Сначала запустите Фазу 2.")
        sys.exit(1)

    with open(CONTACTS_FILE, encoding="utf-8") as f:
        contacts = json.load(f)

    if args.test:
        contacts = contacts[:5]
        print("[DRY-RUN] Режим тестирования. Обрабатываем первые 5 записей.")

    registry = []
    for contact in contacts:
        text_he    = contact.get("text_he", "")
        text_plain = contact.get("text_plain", "")
        
        verb = contact.get("matched_verb", "")
        keywords = contact.get("interaction_keywords", [verb] if verb else [])

        category      = categorize(keywords, text_plain)
        who_initiated = detect_initiator(keywords, text_plain)
        emotions      = detect_emotions(text_plain)

        situation = {
            "id":                   contact.get("id"),
            "book":                 contact.get("book"),
            "chapter":              contact.get("chapter"),
            "verse":                contact.get("verse"),
            "ref":                  contact.get("ref", ""),
            "category":             category,
            "interaction_keywords": keywords,
            "god_names":            contact.get("god_names_found", [contact.get("matched_name")] if contact.get("matched_name") else []),
            "text_he":              text_he,
            "text_plain":           text_plain,
            "who_initiated":        who_initiated,
            # BUGFIX: retain god_speech extracted earlier!
            "god_speech":           contact.get("god_speech", ""),
            "human_speech":         "",
            "situation_start":      "",
            "situation_end":        "",
            "god_action":           "",
            "participants":         [],
            "emotions":             emotions,
            "analyzed_psych":       False,
            "analyzed_linguistics": False,
        }
        registry.append(situation)

    if not args.test:
        out_json = OUTPUT / "situations_registry.json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
        print(f"JSON: {out_json}  ({len(registry)} записей)")

        csv_fields = [
            "id", "book", "chapter", "verse", "ref",
            "category", "who_initiated",
            "god_names", "interaction_keywords",
            "text_plain",
            "god_action", "situation_start", "situation_end",
        ]
        out_csv = OUTPUT / "situations.csv"
        with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
            writer.writeheader()
            for row in registry:
                row_copy = dict(row)
                row_copy["god_names"]            = ", ".join(row_copy.get("god_names", []))
                row_copy["interaction_keywords"] = ", ".join(row_copy.get("interaction_keywords", []))
                writer.writerow(row_copy)
        print(f"CSV:  {out_csv}")
    else:
        for r in registry:
            print(f"- {r['id']} | Cat: {r['category']} | Init: {r['who_initiated']} | Emot: {r['emotions']} | Speech len: {len(r['god_speech'])}")
        print("\n[DRY-RUN] Тест успешно завершён. Файлы не перезаписаны.")

    cats     = Counter(s["category"] for s in registry)
    init     = Counter(s["who_initiated"] for s in registry)
    
    print("\nСтатистика выборки:")
    for cat, cnt in cats.most_common(5): print(f"  {cat:<15} {cnt}")

if __name__ == "__main__":
    main()
