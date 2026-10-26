"""Общий запускатель офлайн-гейтов GOD2 — один вход для CI и для разработки.

    python scripts/selftest_all.py [--test]

Знает флаг каждого скрипта (god_chat — --selftest, остальные — --test),
считает провалы и возвращает ненулевой exit code при любом.
Рождён из zero-error аудита 2026-10-21: разнобой флагов раньше прятал,
что «6/6 selftest» реально проходил только god_chat при наивном запуске.

Состав гейтов расширен под волну «механизм ответа» (2026-10-26): теперь в один
прогон входят сверка ответа с реестром, зеркало схемы, витрина диалогов и
паритет «страница ↔ зеркало» — расхождение между ними означало бы, что
пользователь видит одно, а скрипты-гейты считают другое.

Живой мозг и сеть здесь не участвуют: спящий инстанс не должен ронять гейт.
"""
import os
import subprocess
import sys

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELFTESTS = [
    ("god_chat", "--selftest"),
    ("god_profile", "--test"),
    ("god_behavior", "--test"),
    ("analytics_v2", "--test"),
    ("dedup_overlaps", "--test"),
    ("audit_god_names", "--test"),
    ("answer_guard", "--test"),
    ("answer_scheme", "--test"),
    ("eval_persona", "--test"),
    ("record_dialogues", "--test"),
    ("page_parity", "--test"),
    ("verify_corpus", "--test"),
]


def check_page_js():
    """Синтаксис страницы: страница — источник истины, а опечатка в JS гасит её целиком.

    Гейт появился после правки candidateBlock: скобка вместо скобки сделала страницу
    пустой (в браузере тихо, в CI — ноль ошибок). Теперь это ловится за секунду.
    """
    import io
    import re
    import tempfile
    page = os.path.join(_REPO, "docs", "index.html")
    src = io.open(page, encoding="utf-8").read()
    m = re.search(r"<script>(.*)</script>", src, re.S)
    if not m:
        print("FAIL  page_js — в странице нет тега <script>")
        return False
    fd, path = tempfile.mkstemp(suffix=".js")
    os.close(fd)
    try:
        io.open(path, "w", encoding="utf-8").write(m.group(1))
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        ok = r.returncode == 0
        msg = "JS синтаксис страницы в порядке" if ok else (r.stderr.strip().splitlines() or ["?"])[0]
        print(("PASS" if ok else "FAIL") + "  page_js — " + msg[:90])
        return ok
    except FileNotFoundError:
        print("FAIL  page_js — node не найден (нужен для проверки синтаксиса страницы)")
        return False
    finally:
        os.unlink(path)


def main():
    fails = []
    for name, flag in SELFTESTS:
        script = os.path.join(_REPO, "scripts", name + ".py")
        r = subprocess.run([sys.executable, script, flag], capture_output=True, text=True, timeout=600)
        tail = (r.stdout.strip().splitlines() or ["(нет вывода)"])[-1]
        ok = r.returncode == 0 and ("PASS" in tail.upper() or "OK" in tail.upper())
        print(("PASS" if ok else "FAIL") + f"  {name} ({flag}) — {tail[:90]}")
        if not ok:
            fails.append(name)
    if not check_page_js():
        fails.append("page_js")
    total = len(SELFTESTS) + 1
    print(f"\nИТОГ: {total - len(fails)}/{total} PASS"
          + ("" if not fails else "; провалы: " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
