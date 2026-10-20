"""Сборщик docs/data/nikud.json — огласованные тексты для слоёв «огласовка» в чате.

Восстанавливает провенанс файла, построенного одноразово 2026-10-18 (скрипт не был
заккоммичен — нулевой аудит 2026-10-21 нашёл, что Бытие пропущено целиком: ключ
книги в реестре "genesis" не совпал по регистру с data/tanakh/Genesis.json).

    python scripts/build_nikud.py          # дополнить nikud.json недостающими ключами
    python scripts/build_nikud.py --test   # самопроверка без записи

Формат ключа: "<Книга>|<глава>|<стих>" (имя как в data/tanakh, с заглавной);
значение — text_clean из tanakh (никауд без HTML/масоретских маркеров).
Идемпотентно: существующие ключи не трогаются, добавляются только недостающие.
"""
import glob, io, json, os, sys

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NIKUD = os.path.join(_REPO, "docs", "data", "nikud.json")


def tanakh_path(book_base):
    """data/tanakh/<Книга>.json по имени файла эпизодов без учёта регистра."""
    for p in glob.glob(os.path.join(_REPO, "data", "tanakh", "*.json")):
        if os.path.basename(p).lower() == book_base.lower() + ".json":
            return p
    return None


def build():
    nik = json.load(io.open(NIKUD, encoding="utf-8"))
    before = len(nik)
    added, skipped_books = 0, []
    for p in glob.glob(os.path.join(_REPO, "output", "episodes_*_v2.json")):
        if "TANAKH" in os.path.basename(p):
            continue  # мастер-корпус — словарь по книгам, не список эпизодов
        base = os.path.basename(p)[len("episodes_"):-len("_v2.json")]
        tp = tanakh_path(base)
        if not tp:
            skipped_books.append(base)
            continue
        tan = json.load(io.open(tp, encoding="utf-8"))
        verses = {(v["chapter"], v["verse"]): v.get("text_clean", "") for v in tan["verses"]}
        book_name = tan["book"]  # каноническое имя как в data/tanakh ("Genesis")
        eps = json.load(io.open(p, encoding="utf-8"))
        for e in eps:
            for ref in e.get("god_speech_refs") or []:
                r = str(ref)
                import re
                m = re.match(r"^(\d+):(\d+)$", r)
                if not m:
                    continue
                key = f"{book_name}|{m.group(1)}|{m.group(2)}"
                if key not in nik:
                    txt = verses.get((int(m.group(1)), int(m.group(2))))
                    if txt:
                        nik[key] = txt
                        added += 1
    return nik, before, added, skipped_books


def main():
    selftest = "--test" in sys.argv
    nik, before, added, skipped = build()
    print(f"ключей было {before}, добавлено {added}, всего {len(nik)}")
    if skipped:
        print("книги без tanakh-файла (законно):", ", ".join(skipped))
    ok = True
    if selftest or added:
        # самопроверка: известный ключ Бытия появился и содержит никауд
        import re
        gk = [k for k in nik if k.startswith("Genesis|1|")]
        has_nikud = bool(gk) and bool(re.search(r"[\u0591-\u05C7]", nik[gk[0]]))
        print(("PASS" if has_nikud else "FAIL") + f"  Бытие: ключей {len(gk)}, никауд в {gk[0] if gk else '-'}: {has_nikud}")
        ok = ok and has_nikud
    if selftest:
        print("SELFTEST: режим без записи")
        return 0 if ok else 1
    if added:
        with io.open(NIKUD, "w", encoding="utf-8", newline="\n") as f:
            json.dump(nik, f, ensure_ascii=False, separators=(",", ":"))
        print(f"записано в {NIKUD}")
    else:
        print("изменений нет — файл не тронут")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
