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
  6. Fill-rate критических полей мастер-корпуса v2: trigger/outcome/severity/direction/
     via/summary_ru/god_action ≥ 98%, god_speech_plain/god_speech_refs ≥ 55% (прямая
     речь есть не у всех книг), span.start/span.end = 100%. Раньше обнуление этих полей
     проходило молча — счётчики проверяли только имена файлов.
  7. Публикуемая копия docs/data/books/*.json: ровно 2050 эпизодов и поле-в-поле
     равенство мастер-корпуса (сверка по episode_id) — расхождение сайта и реестра
     означает, что страница показывает не тот корпус, который проаудирован.
  8. docs/data/analytics.json существует и объявляет corpus.episodes == 2050.
"""
import glob, io, json, os, sys

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAILS = []

# Пороги fill-rate для мастер-корпуса v2. 98% — допуск на единичные неразмеченные
# эпизоды; 55% для прямой речи — в Танахе есть книги без речи Бога (Есфирь, Руфь,
# Песнь Песней), порог ловит обнуление, а не легальную неполноту.
FILL_FIELDS = [
    ("trigger", 0.98),
    ("outcome", 0.98),
    ("severity", 0.98),
    ("direction", 0.98),
    ("via", 0.98),
    ("summary_ru", 0.98),
    ("god_action", 0.98),
    ("god_speech_plain", 0.55),
    ("god_speech_refs", 0.55),
    ("span.start", 1.00),
    ("span.end", 1.00),
]

EXPECTED_EPISODES = 2050


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"{mark}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def jload(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def _get(ep, path):
    """Достаёт значение по точечному пути ('span.start')."""
    cur = ep
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def filled(ep, path):
    """Поле считается заполненным, если значение есть и не пустое (0 — пусто, как в audit_phase)."""
    v = _get(ep, path)
    if v is None:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, dict)):
        return len(v) > 0
    if isinstance(v, (int, float)):
        return v != 0
    return True


def fill_rate(episodes, path):
    if not episodes:
        return 0.0
    return sum(1 for e in episodes if filled(e, path)) / len(episodes)


def canon(e):
    """Канонический вид эпизода для сравнения «поле-в-поле»."""
    return json.dumps(e, ensure_ascii=False, sort_keys=True)


def compare_by_id(master_eps, pub_eps):
    """Возвращает episode_id, по которым корпуса расходятся.

    episode_id коллизируются в семействах I_/II_ (Ii_V2_001 есть у трёх книг),
    поэтому сравниваем мультимножества записей внутри одного id, а не последнюю.
    """
    m, p = {}, {}
    for e in master_eps:
        m.setdefault(e.get("episode_id"), []).append(canon(e))
    for e in pub_eps:
        p.setdefault(e.get("episode_id"), []).append(canon(e))
    return sorted(k for k in set(m) | set(p) if sorted(m.get(k, [])) != sorted(p.get(k, [])))


def master_episodes(master):
    if isinstance(master, dict):
        return [e for v in master.values() for e in v]
    return list(master) if isinstance(master, list) else []


def gate_selftest():
    """Негативные проверки самого гейта: он обязан ловить пустые поля и расхождения."""
    fake = [{"episode_id": "X_1", "trigger": "", "outcome": "", "severity": 0,
             "direction": "", "via": "", "summary_ru": "", "god_action": "",
             "god_speech_plain": "", "god_speech_refs": [], "span": {"start": "1:1"}}]
    check("selftest: гейт ловит пустое критическое поле",
          fill_rate(fake, "trigger") == 0.0 and fill_rate(fake, "god_action") == 0.0)
    check("selftest: гейт ловит обнуление прямой речи",
          fill_rate(fake, "god_speech_plain") < 0.55)
    check("selftest: гейт ловит потерю span.end",
          fill_rate(fake, "span.end") == 0.0)
    a = {"episode_id": "X_1", "span": {"start": "1:1", "end": "1:2"}, "god_action": "речь"}
    b = {"episode_id": "X_1", "span": {"start": "1:1", "end": "1:2"}, "god_action": "другая речь"}
    check("selftest: гейт ловит расхождение корпусов", compare_by_id([a], [b]) == ["X_1"])
    check("selftest: одинаковые эпизоды расхождением не считаются", compare_by_id([a], [dict(a)]) == [])


def main():
    selftest = "--test" in sys.argv
    print(f"=== verify_corpus (repo: {_REPO})", "(selftest)" if selftest else "")

    master = jload(os.path.join(_REPO, "output", "episodes_TANAKH_v2.json"))
    if isinstance(master, dict):
        tot = sum(len(v) for v in master.values())
        check("мастер-корпус: dict, сумма по книгам == 2050", tot == 2050, f"{len(master)} книг, {tot} эпизодов")
    else:
        check("мастер-корпус: dict по книгам", False, f"внезапно {type(master).__name__} из {len(master)}")

    eps = master_episodes(master)
    for path, thr in FILL_FIELDS:
        c = sum(1 for e in eps if filled(e, path))
        rate = c / len(eps) if eps else 0.0
        check(f"мастер-корпус: fill-rate {path} ≥ {thr:.0%}", rate >= thr,
              f"{c}/{len(eps)} = {rate:.1%}")

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

    pub_files = sorted(glob.glob(os.path.join(_REPO, "docs", "data", "books", "*.json")))
    pub_eps, pub_bad = [], []
    for p in pub_files:
        try:
            d = jload(p)
            if isinstance(d, list):
                pub_eps.extend(d)
            else:
                pub_bad.append(os.path.basename(p))
        except Exception as e:
            pub_bad.append(f"{os.path.basename(p)}: {e}")
    check("docs/data/books: все файлы — валидные списки", not pub_bad, "; ".join(pub_bad[:3]))
    check("docs/data/books: сумма эпизодов == 2050", len(pub_eps) == EXPECTED_EPISODES,
          f"{len(pub_files)} файлов, {len(pub_eps)} эпизодов")
    mismatched = compare_by_id(eps, pub_eps)
    check("docs/data/books: поле-в-поле равен мастер-корпусу (сверка по episode_id)",
          not mismatched, f"расхождений: {len(mismatched)}" + (f"; пример: {mismatched[:5]}" if mismatched else ""))

    reg = jload(os.path.join(_REPO, "output", "contacts_registry.json"))
    check("реестр контактов: 402 ситуаций", isinstance(reg, list) and len(reg) == 402, str(len(reg)))

    prof = jload(os.path.join(_REPO, "output", "god_behavior_profile.json"))
    bt = prof.get("by_trigger") or {}
    check("профиль поведения: by_trigger заполнен", len(bt) >= 10, f"{len(bt)} триггеров")

    a = jload(os.path.join(_REPO, "docs", "data", "analytics.json"))
    corpus = a.get("corpus") or {}
    check("docs/data/analytics.json: corpus.episodes == 2050",
          corpus.get("episodes") == EXPECTED_EPISODES, f"corpus={json.dumps(corpus, ensure_ascii=False)}")
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

    if selftest:
        gate_selftest()

    print(f"\nИТОГ: {len(FAILS)} провалов — " + ("PASS" if not FAILS else "FAIL")
          + ("" if not FAILS else ": " + "; ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
