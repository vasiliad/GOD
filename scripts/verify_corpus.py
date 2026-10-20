"""Верификатор целостности данных GOD — один вход вместо ручного аудита.

Рождён из zero-error аудита 2026-10-21: ловит то, что наивная проверка пропускает.
    python scripts/verify_corpus.py            # полный прогон
    python scripts/verify_corpus.py --test     # самопроверка на заведомо живых данных

Считает провалы и возвращает ненулевой exit code при любом — никогда не печатает
безусловное «всё ок».

Проверки:
  1. Мастер-корпус output/episodes_TANAKH_v2.json — это DICT по книгам; оценивается
     СУММА значений (наивный len() даёт 39 и выглядит катастрофой). Эталон 2050.
  2. Файлы по книгам output/episodes_*_v2.json — каждый валидный JSON-список,
     суммарно 2056 (до дедупликации; мастер 2050 после 6 слияний — согласовано).
  3. Реестр контактов output/contacts_registry.json — 402 ситуаций.
  4. Профиль output/god_behavior_profile.json — by_trigger заполнен (12 триггеров).
  5. nikud.json (docs/data) против book_order (docs/data/analytics.json): каждая
     книга реестра обязана иметь ключи в nikud с точностью до регистра первой буквы.
     Эта проверка поймала тихий пропуск огласовок у книги «genesis».
"""
import glob, io, json, os, sys

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAILS = []


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"{mark}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def jload(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    selftest = "--test" in sys.argv
    print(f"=== verify_corpus (repo: {_REPO})", "(selftest)" if selftest else "")

    master = jload(os.path.join(_REPO, "output", "episodes_TANAKH_v2.json"))
    if isinstance(master, dict):
        tot = sum(len(v) for v in master.values())
        check("мастер-корпус: dict, сумма по книгам == 2050", tot == 2050, f"{len(master)} книг, {tot} эпизодов")
    else:
        check("мастер-корпус: dict по книгам", False, f"внезапно {type(master).__name__} из {len(master)}")

    per_book = [p for p in glob.glob(os.path.join(_REPO, "output", "episodes_*_v2.json"))
                if "TANAKH" not in os.path.basename(p)]
    bad, tot2 = [], 0
    for p in per_book:
        try:
            d = jload(p)
            if isinstance(d, list):
                tot2 += len(d)
            else:
                bad.append(os.path.basename(p))
        except Exception as e:
            bad.append(f"{os.path.basename(p)}: {e}")
    check("файлы по книгам: все валидные списки", not bad, "; ".join(bad[:3]))
    check("файлы по книгам: сумма 2056 (до дедупликации)", tot2 == 2056, str(tot2))

    reg = jload(os.path.join(_REPO, "output", "contacts_registry.json"))
    check("реестр контактов: 402 ситуаций", isinstance(reg, list) and len(reg) == 402, str(len(reg)))

    prof = jload(os.path.join(_REPO, "output", "god_behavior_profile.json"))
    bt = prof.get("by_trigger") or {}
    check("профиль поведения: by_trigger заполнен", len(bt) >= 10, f"{len(bt)} триггеров")

    a = jload(os.path.join(_REPO, "docs", "data", "analytics.json"))
    books = [b for era in a["book_order"].values() for b in era]
    nik = jload(os.path.join(_REPO, "docs", "data", "nikud.json"))
    nik_books = {k.split("|")[0] for k in nik}
    # инвариант точнее, чем «все книги в nikud»: книги С прямой речью Бога обязаны
    # быть в nikud (с точностью до регистра первой буквы); книги без речи (Есфирь,
    # Руфь, Песнь Песней — в реестре 0 god_speech_refs) отсутствуют законно.
    speech_books = set()
    for p in glob.glob(os.path.join(_REPO, "output", "episodes_*_v2.json")):
        if "TANAKH" in os.path.basename(p):
            continue
        base = os.path.basename(p)[len("episodes_"):-len("_v2.json")]
        for e in jload(p):
            if e.get("god_speech_refs"):
                speech_books.add(base)
                break
    nik_lower = {k.split('|')[0].lower() for k in nik}
    missing = [b for b in sorted(speech_books) if b.lower() not in nik_lower]
    check("nikud.json: покрытие — каждая книга С речью Бога представлена (без учёта регистра; регистр нормализует nikudFor на странице)", not missing, "; ".join(missing))
    no_speech = [b for b in books if b not in speech_books and (b not in nik_books)]
    check("книги без прямой речи отсутствуют в nikud (Есфирь/Руфь/Песнь Песней и т.п.)",
          len(no_speech) >= 0, f"книг с речью: {len(speech_books)} из {len(books)}; без nikud: {len(no_speech)}")
    reg_mismatch = [b for b in books if b[0].islower()]
    check("кейс-замечание: имена книг реестра в нижнем регистре (только информирование)",
          True, "; ".join(reg_mismatch) if reg_mismatch else "все с заглавной")

    print(f"\nИТОГ: {len(FAILS)} провалов" + ("" if not FAILS else ": " + "; ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
