"""
merge_audit_v2.py
Экстракция v2: слияние батчей агентов, дедупликация на перекрытиях глав, аудит качества.

Вход:  output/pilot_v2/<book>_episodes/episodes_batch_NN.json
Выход: output/episodes_<book>_v2.json + отчёт в консоль.
Exit 1, если структурные ошибки или покрытие контрольного списка < 85%.

Аудит покрытия: формулы 'Бог говорит', обращения к Богу,
молчание в ответ на зов (категория B), действие Бога без речи (категория C).

Usage:
    python merge_audit_v2.py --book Exodus
    python merge_audit_v2.py --book Genesis
"""
import json
import re
import sys
import argparse
from pathlib import Path
from collections import Counter, defaultdict
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_BASE = Path(_REPO + "/output/pilot_v2")
TANAKH_DIR = Path(_REPO + "/data/tanakh")
OLD_CODED = Path(_REPO + "/output/situations_coded.json")

REQ_FIELDS = {
    "span", "direction", "via", "participants", "addressee_type", "trigger",
    "god_speech_refs", "god_speech_plain", "human_speech_refs", "human_speech_plain",
    "god_action", "outcome", "severity", "emotions", "summary_ru", "confidence", "boundary"
}

# Контрольные списки по книгам: стих обязан попасть в эпизод.
# (chapter:verse, need_human_initiated_or_human_speech)
CHECKPOINTS = {
    "Genesis": [
        ("3:9", False), ("4:9", False), ("4:13", True), ("4:26", True), ("6:13", False),
        ("8:1", False), ("8:21", False), ("9:12", False), ("11:6", False), ("12:1", False),
        ("12:8", True), ("15:2", True), ("16:13", True), ("17:18", True), ("18:23", True),
        ("19:18", True), ("20:4", True), ("20:17", True), ("21:17", False), ("22:1", False),
        ("22:11", False), ("24:12", True), ("25:21", True), ("25:22", True), ("26:24", False),
        ("28:13", False), ("28:20", True), ("29:31", False), ("30:22", False), ("31:24", False),
        ("32:10", True), ("32:26", True), ("35:1", False), ("35:10", False), ("38:7", False),
        ("38:10", False), ("39:2", False), ("39:21", False), ("41:25", False), ("46:2", True),
        ("49:18", True),
        # категория C: действие без речи (поражение фараона, посещение Сарры)
        ("12:17", False), ("21:1", False),
    ],
    "Exodus": [
        # Горящий куст: 3:1-4:17 — многораундовый спор Моисея с Богом
        ("3:2", False), ("3:4", True), ("3:6", False), ("3:11", True), ("3:13", True),
        ("3:14", False), ("4:1", True), ("4:2", False), ("4:10", True), ("4:13", True),
        ("4:14", False), ("4:15", False), ("4:17", False),
        # Десять казней: формулы "Бог говорит"
        ("7:17", False), ("8:1", False), ("8:12", False), ("9:1", False), ("9:8", False),
        ("9:22", False), ("10:1", False), ("10:12", False), ("10:21", False), ("11:4", False),
        # Заповеди на Синае
        ("19:3", False), ("19:9", False), ("20:1", False), ("20:2", False), ("20:22", False),
        # Золотой телёнок
        ("32:1", False), ("32:7", False), ("32:11", True), ("32:14", False), ("33:12", True),
        ("33:13", True), ("33:18", True), ("34:6", False), ("34:10", False),
        # категория C: Бог нападает на Моисея ночью без слов
        ("4:24", False),
    ],
    "Jonah": [
        ("1:1", False), ("1:2", False), ("1:14", True), ("2:1", False), ("2:2", True),
        ("2:10", False), ("3:1", False), ("3:2", False), ("3:10", False), ("4:1", True),
        ("4:2", True), ("4:4", False), ("4:10", False), ("4:11", False),
        # категория C: буря послана без слов
        ("1:4", False),
    ],
    "Habakkuk": [
        ("1:2", True), ("1:5", False), ("1:13", True), ("2:1", True), ("2:2", False),
        ("2:4", False), ("3:2", True), ("3:19", True),
    ],
    "I_Samuel": [
        ("3:4", True), ("3:8", True), ("3:10", True), ("3:11", False), ("8:5", True),
        ("8:6", True), ("8:7", False), ("9:15", False), ("9:17", False), ("10:1", False),
        ("15:10", False), ("15:11", False), ("15:16", True), ("15:22", False), ("16:1", False),
        ("16:7", False), ("16:12", False), ("16:13", False),
        # категория B: вопрошения без ответа (14:37, 28:6); категория C: злой дух (16:14), гибель Навала (25:38)
        ("14:37", True), ("28:6", True), ("16:14", False), ("25:38", False),
    ],
    "Isaiah": [
        ("6:1", False), ("6:5", True), ("6:8", True), ("7:14", False), ("38:1", False),
        ("38:5", False), ("40:1", False), ("40:3", False), ("42:1", False), ("53:1", True),
        ("55:6", True), ("65:24", False),
        # категория C: ангел поражает ассирийцев
        ("37:36", False),
    ],
    "Jeremiah": [
        ("1:4", False), ("1:6", True), ("1:9", False), ("7:1", False), ("7:13", False),
        ("11:1", False), ("15:1", True), ("15:15", True), ("18:1", False), ("20:7", True),
        ("23:5", False), ("31:31", False), ("33:3", True),
    ],
    "Ezekiel": [
        ("1:1", False), ("1:3", False), ("2:1", False), ("3:1", False), ("3:16", False),
        ("8:1", False), ("11:19", False), ("18:1", False), ("33:1", False), ("36:26", False),
        ("37:1", False), ("37:15", False),
    ],
    "Leviticus": [
        ("1:1", False), ("4:1", False), ("9:23", False), ("10:1", False), ("16:1", False),
        ("19:1", False), ("24:10", True), ("26:3", False),
    ],
    "Numbers": [
        ("1:1", False), ("6:22", False), ("11:1", True), ("12:1", True), ("14:1", True),
        ("14:11", False), ("16:1", True), ("20:1", True), ("21:4", True), ("22:2", False),
        ("27:15", True),
        # категория C: земля поглощает Корея, огненные змеи
        ("16:31", False), ("21:6", False),
    ],
    "Deuteronomy": [
        ("1:6", False), ("4:1", False), ("5:1", False), ("6:4", False), ("18:15", False),
        ("31:14", False), ("34:1", False),
    ],
    "Joshua": [
        ("1:1", False), ("3:7", False), ("5:13", False), ("10:12", True), ("24:1", False),
        # категория C: камни с небес
        ("10:11", False),
    ],
    "Judges": [
        ("2:1", False), ("6:11", False), ("6:22", False), ("13:3", False),
    ],
    # --- книги, ожидающие экстракции: контрольные точки заданы заранее ---
    "II_Samuel": [
        # категория C: гибель Уззы (6:7), мор за перепись (24:15)
        ("6:7", False), ("24:15", False),
    ],
    "I_Kings": [
        # категория C: иссохшая рука (13:4)
        ("13:4", False),
    ],
    "II_Kings": [
        # категория C: медведицы (2:24), ангел поражает ассирийцев (19:35)
        ("2:24", False), ("19:35", False),
    ],
    "Ruth": [
        # категория C: Бог посетил народ (1:6)
        ("1:6", False),
    ],
    "Job": [
        # категория B: вопль без ответа (30:20); категория A: ответ из бури (38:1)
        ("30:20", True), ("38:1", False),
    ],
    "Lamentations": [
        # категория B: затворённая молитва (3:8)
        ("3:8", True),
    ],
    "Micah": [
        # категория B: воззовут — и не ответит (3:4)
        ("3:4", True),
    ],
}

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

# Категория B: человек взывает, а Бог не отвечает (формулы молчания при имени Бога в стихе)
SILENCE_CORE = re.compile(
    r"(?:לא|בלי|בל)\s+[יע]?ענ\w*"      # לא ענהו / לא יענה / בלי ענות
    r"|(?:לא|בלי|בל)\s+א?שמע"          # לא שמע / לא אשמע / לא תשמע
    r"|אל\s+תחרש"                       # אל תחרש ממני (Пс 28:1)
)
# Категория C: действие Бога без речи (глагол действия при имени Бога в стихе)
DIVINE_ACT_CORE = re.compile(
    r"ויגע|ויגף|הכות|מכה|הכה|ויכה|ויך"  # поразил
    r"|וישלח|ויפקד|פקד"                # послал / посетил
)
# יד/מאת — только непосредственно перед именем Бога (иначе ציד и מאת שקל дают ложные срабатывания)
DIVINE_ACT_ATTACHED = re.compile(r"יד\s+" + GOD + r"|מאת\s+" + GOD)
# строгие имена для гейта глаголов: без אדני (в повествовании это часто "господин мой" о человеке)
STRICT_GOD = r"(?:יהוה|אלהים|האלהים|שדי)"


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


def parse_ref(s):
    m = re.match(r"^(\d+):(\d+)$", str(s).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def compute_batches(num_chapters: int, batch_size: int = 6, overlap: int = 1) -> list[tuple[int, int]]:
    step = batch_size - overlap
    batches = []
    start = 1
    while start <= num_chapters:
        end = min(start + batch_size - 1, num_chapters)
        batches.append((start, end))
        if end == num_chapters:
            break
        start += step
    return batches


def main():
    parser = argparse.ArgumentParser(description="Слияние и аудит эпизодов v2")
    parser.add_argument("--book", required=True, help="Имя книги (например: Genesis, Exodus, Jonah)")
    args = parser.parse_args()

    book = args.book
    book_file = TANAKH_DIR / f"{book}.json"
    episodes_dir = OUTPUT_BASE / f"{book}_episodes"
    out_file = Path(f_REPO + "/output/episodes_{book}_v2.json")

    if not book_file.exists():
        print(f"ОШИБКА: Файл {book_file} не найден")
        sys.exit(1)
    if not episodes_dir.exists():
        print(f"ОШИБКА: Директория эпизодов {episodes_dir} не найдена")
        print(f"Сначала запустите агентов-сегментаторов на батчах из {OUTPUT_BASE / f'{book}_input'}")
        sys.exit(1)

    # --- линеаризация стихов книги ---
    gen = json.load(open(book_file, encoding="utf-8"))
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

    # --- загрузка батчей ---
    BATCHES = compute_batches(len(verse_count))
    episodes = []
    errors = []

    for i in range(1, len(BATCHES) + 1):
        p = episodes_dir / f"episodes_batch_{i:02d}.json"
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
                errors.append(f"{p.name}: глава вне {book} {e['span']}")
                continue
            a, b = lin(*s), lin(*t)
            if a > b:
                a, b = b, a
            e["_batch"], e["_a"], e["_b"] = i, a, b
            episodes.append(e)

    print(f"Загружено сырых эпизодов: {len(episodes)} из {len(BATCHES)} батчей")

    # --- дедупликация (только МЕЖДУ батчами; вложенность внутри батча — намеренная) ---
    def richness(e):
        return (
            (e.get("confidence") == "high"),
            len(e.get("god_speech_refs", [])) + len(e.get("human_speech_refs", [])),
            e["_b"] - e["_a"],
            -e["_batch"]
        )

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
    if merged:
        hum = [e for e in merged if e["direction"] == "human_initiated"]
        print(f"human_initiated: {len(hum)}/{len(merged)} = {100*len(hum)/len(merged):.0f}%")
        sil = [e for e in merged if e["outcome"] in ("silence", "delayed")]
        print(f"silence/delayed: {len(sil)}")
    else:
        print("human_initiated: 0/0 = 0%")
        print("silence/delayed: 0")

    # --- аудит 1: формульные стихи покрыты спанами? ---
    def covered(ch, v):
        x = lin(ch, v)
        return any(e["_a"] <= x <= e["_b"] for e in merged)

    gs_total = gs_cov = ap_total = ap_cov = 0
    sil_total = sil_cov = da_total = da_cov = 0
    gs_miss, ap_miss, sil_miss, da_miss = [], [], [], []
    for (ch, v), t in verse_text.items():
        has_god = re.search(GOD, t) is not None
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
        if has_god and SILENCE_CORE.search(t):
            sil_total += 1
            if covered(ch, v):
                sil_cov += 1
            else:
                sil_miss.append(f"{ch}:{v}")
        if (re.search(STRICT_GOD, t) and DIVINE_ACT_CORE.search(t)) or DIVINE_ACT_ATTACHED.search(t):
            da_total += 1
            if covered(ch, v):
                da_cov += 1
            else:
                da_miss.append(f"{ch}:{v}")
    print("\n=== АУДИТ ПОКРЫТИЯ ===")
    print(f"Формулы 'Бог говорит': {gs_cov}/{gs_total} покрыто ({100*gs_cov/max(1,gs_total):.0f}%), пропущено: {gs_miss}")
    print(f"Формулы обращений к Богу: {ap_cov}/{ap_total} покрыто ({100*ap_cov/max(1,ap_total):.0f}%), пропущено: {ap_miss}")
    print(f"Формулы 'Бог молчит' (не отвечает на зов + имя Бога): {sil_cov}/{sil_total} покрыто ({100*sil_cov/max(1,sil_total):.0f}%), пропущено: {sil_miss}")
    print(f"Формулы 'действие Бога без речи' (поразил/послал/посетил + имя Бога): {da_cov}/{da_total} покрыто ({100*da_cov/max(1,da_total):.0f}%), пропущено: {da_miss}")

    # --- аудит 2: покрытие старых записей (если есть для этой книги) ---
    if OLD_CODED.exists():
        old_all = json.load(open(OLD_CODED, encoding="utf-8"))
        old = [o for o in old_all if o.get("book") == book]
        if old:
            old_cov = sum(1 for o in old if covered(o["chapter"], o["verse"]))
            print(f"Старый реестр ({book}, {len(old)} записей): покрыто новыми спанами {old_cov} ({100*old_cov/max(1,len(old)):.0f}%)")
            old_miss = [f"{o['chapter']}:{o['verse']}" for o in old if not covered(o["chapter"], o["verse"])]
            if old_miss:
                print(f"  не покрыты: {old_miss}")

    # --- аудит 3: контрольный список (если задан для книги) ---
    cp_pass = 0
    cp_fail = []
    checkpoints = CHECKPOINTS.get(book, [])
    for ref, need_human in checkpoints:
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
    if checkpoints:
        cp_rate = 100 * cp_pass / len(checkpoints)
        print(f"Контрольный список: {cp_pass}/{len(checkpoints)} = {cp_rate:.0f}%")
        if cp_fail:
            print(f"  провалено: {cp_fail}")
    else:
        print(f"Контрольный список для {book}: не задан (пропущен)")

    # --- запись результата ---
    for k, e in enumerate(sorted(merged, key=lambda e: (e["_a"], e["_b"])), 1):
        e["episode_id"] = f"{book[:3].capitalize()}V2_{k:03d}"
        e["book"] = book
        e["source_batch"] = e.pop("_batch")
        del e["_a"], e["_b"]
    json.dump(merged, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nЗаписано: {out_file} ({len(merged)} эпизодов)")

    if errors:
        print("\nСТРУКТУРНЫЕ ОШИБКИ:")
        for e in errors:
            print(" -", e)
    fail = bool(errors) or (checkpoints and cp_rate < 85)
    print(f"\nИТОГ: {'FAIL' if fail else 'PASS'}")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()