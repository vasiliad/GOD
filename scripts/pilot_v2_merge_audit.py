"""
pilot_v2_merge_audit.py
Пилот v2 (Genesis): слияние батчей агентов, дедупликация на перекрытиях глав, аудит качества.

Вход:  output/pilot_v2/episodes_batch_NN.json (10 шт.)
Выход: output/episodes_genesis_v2.json + отчёт в консоль.
Exit 1, если структурные ошибки или покрытие контрольного списка < 85%.
"""
import json
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

PILOT_DIR = Path(_REPO + "/output/pilot_v2")
GENESIS = Path(_REPO + "/data/tanakh/Genesis.json")
OLD_CODED = Path(_REPO + "/output/situations_coded.json")
OUT_FILE = Path(_REPO + "/output/episodes_genesis_v2.json")

REQ_FIELDS = {"span", "direction", "via", "participants", "addressee_type", "trigger",
              "god_speech_refs", "god_speech_plain", "human_speech_refs", "human_speech_plain",
              "god_action", "outcome", "severity", "emotions", "summary_ru", "confidence", "boundary"}

# Контрольный список: стих обязан попасть в какой-то эпизод.
# Помеченные h=True обязаны быть в эпизоде human_initiated ИЛИ с непустым human_speech_refs.
CHECKPOINTS = [
    ("3:9", False), ("4:9", False), ("4:13", True), ("4:26", True), ("6:13", False),
    ("8:1", False), ("8:21", False), ("9:12", False), ("11:6", False), ("12:1", False),
    ("12:8", True), ("15:2", True), ("16:13", True), ("17:18", True), ("18:23", True),
    ("19:18", True), ("20:4", True), ("20:17", True), ("21:17", False), ("22:1", False),
    ("22:11", False), ("24:12", True), ("25:21", True), ("25:22", True), ("26:24", False),
    ("28:13", False), ("28:20", True), ("29:31", False), ("30:22", False), ("31:24", False),
    ("32:10", True), ("32:26", True), ("35:1", False), ("35:10", False), ("38:7", False),
    ("38:10", False), ("39:2", False), ("39:21", False), ("41:25", False), ("46:2", True),
    ("49:18", True),
]

GOD = r"(?:יהוה|אלהים|האלהים|אדני|שדי)"
GOD_SPEAKS = re.compile(r"וי(?:אמר|דבר)\s+" + GOD + r"|כה\s+אמר\s+(?:יהוה|אדני)|נאם\s+יהוה")
APPEALS = re.compile(
    r"קרא\w*\s+(?:אל|בשם)\s+" + GOD +
    r"|תפלל\w*\s+(?:אל|על|לפני)\s+" + GOD +
    r"|[צז]עק\w*\s+אל\s+" + GOD +
    r"|שאל\w*\s+ב" + GOD +
    r"|דרש\w*\s+(?:את\s+)?" + GOD +
    r"|ויעתר\w*\s+ל" + GOD
)


def normalize_he(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if 0x0591 <= o <= 0x05BD or o in (0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7):
            continue
        if o == 0x05BE:
            out.append(" ")
            continue
        if o in (0x05C0, 0x05C3):
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def main():
    errors = []

    # --- линеаризация стихов Genesis ---
    gen = json.load(open(GENESIS, encoding="utf-8"))
    verse_count = defaultdict(int)
    verse_text = {}
    for v in gen["verses"]:
        verse_count[v["chapter"]] = max(verse_count[v["chapter"]], v["verse"])
        verse_text[(v["chapter"], v["verse"])] = normalize_he(v.get("text_he", ""))
    cum = {}
    acc = 0
    for ch in sorted(verse_count):
        cum[ch] = acc
        acc += verse_count[ch]

    def lin(ch, v):
        return cum[ch] + v

    def parse_ref(s):
        m = re.match(r"^(\d+):(\d+)$", str(s).strip())
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    # --- загрузка батчей ---
    episodes = []
    for i in range(1, 11):
        p = PILOT_DIR / f"episodes_batch_{i:02d}.json"
        if not p.exists():
            errors.append(f"нет файла {p.name}")
            continue
        try:
            batch = json.load(open(p, encoding="utf-8"))
        except Exception as ex:
            errors.append(f"{p.name}: JSON ошибка {ex}")
            continue
        for e in batch:
            miss = REQ_FIELDS - set(e.keys())
            if miss:
                errors.append(f"{p.name}: эпизод {e.get('span')} без полей {miss}")
                continue
            s = parse_ref(e["span"]["start"])
            t = parse_ref(e["span"]["end"])
            if not s or not t:
                errors.append(f"{p.name}: кривой span {e['span']}")
                continue
            if s[0] not in cum or t[0] not in cum:
                errors.append(f"{p.name}: глава вне Genesis {e['span']}")
                continue
            a, b = lin(*s), lin(*t)
            if a > b:
                a, b = b, a
            e["_batch"], e["_a"], e["_b"] = i, a, b
            episodes.append(e)

    print(f"Загружено сырых эпизодов: {len(episodes)} из 10 батчей")

    # --- дедупликация (только МЕЖДУ батчами; вложенность внутри батча — намеренная) ---
    def richness(e):
        return ((e.get("confidence") == "high"),
                len(e.get("god_speech_refs", [])) + len(e.get("human_speech_refs", [])),
                e["_b"] - e["_a"],
                -e["_batch"])

    episodes.sort(key=lambda e: (e["_a"], e["_b"]))
    removed = []
    alive = [True] * len(episodes)
    for i in range(len(episodes)):
        if not alive[i]:
            continue
        for j in range(i + 1, len(episodes)):
            if not alive[j]:
                continue
            ei, ej = episodes[i], episodes[j]
            if ej["_a"] > ei["_b"]:
                break
            if ei["_batch"] == ej["_batch"]:
                continue
            inter = min(ei["_b"], ej["_b"]) - max(ei["_a"], ej["_a"]) + 1
            min_len = min(ei["_b"] - ei["_a"], ej["_b"] - ej["_a"]) + 1
            if inter >= 0.5 * min_len:
                loser_idx = i if richness(ei) < richness(ej) else j
                alive[loser_idx] = False
                removed.append(episodes[loser_idx])
                if loser_idx == i:
                    break
    merged = [e for k, e in enumerate(episodes) if alive[k]]
    print(f"Дублей на перекрытиях удалено: {len(removed)} -> итог {len(merged)} эпизодов")

    # --- статистика ---
    print("\n=== СТАТИСТИКА ===")
    for fld in ("direction", "via", "trigger", "outcome", "addressee_type", "confidence"):
        print(f"{fld}: {dict(Counter(e[fld] for e in merged).most_common())}")
    hum = [e for e in merged if e["direction"] == "human_initiated"]
    print(f"human_initiated: {len(hum)}/{len(merged)} = {100*len(hum)/len(merged):.0f}%")
    sil = [e for e in merged if e["outcome"] in ("silence", "delayed")]
    print(f"silence/delayed: {len(sil)}")

    # --- аудит 1: формульные стихи покрыты спанами? ---
    def covered(ch, v):
        x = lin(ch, v)
        return any(e["_a"] <= x <= e["_b"] for e in merged)

    gs_total = gs_cov = ap_total = ap_cov = 0
    gs_miss, ap_miss = [], []
    for (ch, v), t in verse_text.items():
        if GOD_SPEAKS.search(t):
            gs_total += 1
            if covered(ch, v):
                gs_cov += 1
            else:
                gs_miss.append(f"{ch}:{v}")
        if APPEALS.search(t):
            ap_total += 1
            if covered(ch, v):
                ap_cov += 1
            else:
                ap_miss.append(f"{ch}:{v}")
    print("\n=== АУДИТ ПОКРЫТИЯ ===")
    print(f"Формулы 'Бог говорит': {gs_cov}/{gs_total} покрыто ({100*gs_cov/max(1,gs_total):.0f}%), пропущено: {gs_miss}")
    print(f"Формулы обращений к Богу: {ap_cov}/{ap_total} покрыто ({100*ap_cov/max(1,ap_total):.0f}%), пропущено: {ap_miss}")

    # --- аудит 2: покрытие старых записей Genesis ---
    old = [o for o in json.load(open(OLD_CODED, encoding="utf-8")) if o.get("book") == "Genesis"]
    old_cov = sum(1 for o in old if covered(o["chapter"], o["verse"]))
    print(f"Старый реестр (Genesis, {len(old)} записей): покрыто новыми спанами {old_cov} ({100*old_cov/max(1,len(old)):.0f}%)")
    old_miss = [f"{o['chapter']}:{o['verse']}" for o in old if not covered(o["chapter"], o["verse"])]
    if old_miss:
        print(f"  не покрыты: {old_miss}")

    # --- аудит 3: контрольный список ---
    cp_pass = 0
    cp_fail = []
    for ref, need_human in CHECKPOINTS:
        ch, v = parse_ref(ref)
        x = lin(ch, v)
        hits = [e for e in merged if e["_a"] <= x <= e["_b"]]
        ok = bool(hits)
        if ok and need_human:
            ok = any(e["direction"] == "human_initiated" or e.get("human_speech_refs") for e in hits)
        if ok:
            cp_pass += 1
        else:
            cp_fail.append(ref + (" [нужен human]" if need_human and hits else " [не покрыт]"))
    cp_rate = 100 * cp_pass / len(CHECKPOINTS)
    print(f"Контрольный список: {cp_pass}/{len(CHECKPOINTS)} = {cp_rate:.0f}%")
    if cp_fail:
        print(f"  провалено: {cp_fail}")

    # --- запись результата ---
    for k, e in enumerate(sorted(merged, key=lambda e: (e["_a"], e["_b"])), 1):
        e["episode_id"] = f"GenV2_{k:03d}"
        e["book"] = "Genesis"
        e["source_batch"] = e.pop("_batch")
        del e["_a"], e["_b"]
    json.dump(merged, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nЗаписано: {OUT_FILE} ({len(merged)} эпизодов)")

    if errors:
        print("\nСТРУКТУРНЫЕ ОШИБКИ:")
        for e in errors:
            print(" -", e)
    fail = bool(errors) or cp_rate < 85
    print(f"\nИТОГ: {'FAIL' if fail else 'PASS'}")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
