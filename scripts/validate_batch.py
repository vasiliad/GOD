"""
validate_batch.py — структурная проверка одного батча эпизодов против контракта v2.

Проверяет: JSON парсится, 17 полей, форматы span/refs, диапазон глав, enum-поля.
Запуск: python scripts/validate_batch.py <path_to_episodes_batch_NN.json> [max_chapter]
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REQ = {
    "span", "direction", "via", "participants", "addressee_type", "trigger",
    "god_speech_refs", "god_speech_plain", "human_speech_refs", "human_speech_plain",
    "god_action", "outcome", "severity", "emotions", "summary_ru", "confidence", "boundary",
}
DIRECTIONS = {"god_initiated", "human_initiated", "divine_action"}
OUTCOMES = {"blessing", "compliance", "silence", "answer_granted", "punishment",
            "revelation", "rescue", "covenant", "delayed", "unclear", "refusal"}
TRIGGERS = {"unprompted", "covenant_follow_up", "distress", "disobedience", "gratitude",
            "faithfulness", "prayer", "vow", "intercession", "complaint", "divine_test", "inquiry"}
ADDRESSEES = {"patriarch", "individual", "family", "nation", "humanity",
              "foreign_individual", "self"}
VIAS = {"direct", "dream", "vision", "angel", "prophet", "internal", "unclear"}


def main():
    path = Path(sys.argv[1])
    max_ch = int(sys.argv[2]) if len(sys.argv) > 2 else None
    data = json.load(open(path, encoding="utf-8"))
    if not isinstance(data, list):
        print(f"{path.name}: FAIL — корень не массив")
        sys.exit(1)
    errs = []
    chapters = set()
    for e in data:
        tag = e.get("span", "?")
        miss = REQ - set(e.keys())
        extra = set(e.keys()) - REQ
        if miss:
            errs.append(f"{tag}: нет полей {sorted(miss)}")
        if extra:
            errs.append(f"{tag}: лишние поля {sorted(extra)}")
        for fld, allowed in (("direction", DIRECTIONS), ("outcome", OUTCOMES),
                             ("trigger", TRIGGERS), ("addressee_type", ADDRESSEES),
                             ("via", VIAS), ("confidence", {"high", "low"})):
            if e.get(fld) not in allowed:
                errs.append(f"{tag}: {fld}={e.get(fld)!r} вне словаря")
        s, t = e.get("span", {}).get("start"), e.get("span", {}).get("end")
        m1, m2 = re.match(r"^\d+:\d+$", str(s or "")), re.match(r"^\d+:\d+$", str(t or ""))
        if not m1 or not m2:
            errs.append(f"{tag}: кривой span")
            continue
        ch = int(s.split(":")[0])
        chapters.add(ch)
        if max_ch and ch > max_ch:
            errs.append(f"{tag}: глава {ch} вне батча (> {max_ch})")
        for fld in ("god_speech_refs", "human_speech_refs"):
            for r in e.get(fld, []):
                if not re.match(r"^\d+:\d+$", str(r)):
                    errs.append(f"{tag}: {fld} кривая ссылка {r!r}")
        if not isinstance(e.get("severity"), int) or not 1 <= e.get("severity", 0) <= 5:
            errs.append(f"{tag}: severity={e.get('severity')!r}")
    print(f"{path.name}: эпизодов {len(data)}, главы {sorted(chapters)}, ошибок {len(errs)}")
    for x in errs[:30]:
        print(" -", x)
    print("OK" if not errs else "FAIL")
    sys.exit(0 if not errs else 1)


if __name__ == "__main__":
    main()
