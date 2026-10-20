"""Общий запускатель самотестов GOD — один вход для гейта «6/6 PASS».

    python scripts/selftest_all.py [--test]

Знает флаг каждого скрипта (god_chat — --selftest, остальные — --test),
считает провалы и возвращает ненулевой exit code при любом.
Рождён из zero-error аудита 2026-10-21: разнобой флагов раньше прятал,
что «6/6 selftest» реально проходил только god_chat при наивном запуске.
"""
import os, subprocess, sys

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELFTESTS = [
    ("god_chat", "--selftest"),
    ("god_profile", "--test"),
    ("god_behavior", "--test"),
    ("analytics_v2", "--test"),
    ("dedup_overlaps", "--test"),
    ("audit_god_names", "--test"),
]


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
    print(f"\nИТОГ: {len(SELFTESTS) - len(fails)}/{len(SELFTESTS)} PASS"
          + ("" if not fails else "; провалы: " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
