"""
audit_phase.py — Обязательный аудит контракта данных между фазами GOD2.

ПРАВИЛО: Запускать ОБЯЗАТЕЛЬНО после каждой LLM-фазы до перехода к следующей.
Если хоть одно критическое поле имеет fill_rate < 95% → sys.exit(1).

Использование:
  python scripts/audit_phase.py --phase 4      # после Фазы 4
  python scripts/audit_phase.py --phase all    # полный аудит всех доступных файлов
"""

import json
import sys
import argparse
from pathlib import Path

# ============================================================
# ТАБЛИЦА КОНТРАКТОВ МЕЖДУ ФАЗАМИ
# Ключ = имя фазы, значение = список полей с порогами fill-rate
# ============================================================
PHASE_CONTRACTS = {

    "phase_3": {
        "file": "C:/GOD2/output/situations_registry.json",
        "description": "Реестр ситуаций (build_registry.py)",
        "fields": {
            "id":          {"threshold": 1.00, "critical": True},
            "book":        {"threshold": 1.00, "critical": True},
            "text_he":     {"threshold": 0.95, "critical": True,  "note": "Semantic Core: иврит"},
            "text_plain":  {"threshold": 0.95, "critical": True},
            "god_speech":  {"threshold": 0.50, "critical": True,  "note": "Semantic Core: прямая речь"},
            "category":    {"threshold": 0.95, "critical": False},
        }
    },

    "phase_4": {
        "file": "C:/GOD2/output/situations_coded.json",
        "description": "LLM-разметка: поведение Бога (code_behaviors.py)",
        "fields": {
            "behavior_type": {"threshold": 0.95, "critical": True,  "note": "Используется: Фаза 5, LLM-датасет"},
            "trigger":       {"threshold": 0.95, "critical": True,  "note": "Используется: Фаза 8, LLM-датасет"},
            "outcome":       {"threshold": 0.90, "critical": True,  "note": "Используется: Фаза 8"},
            "severity":      {"threshold": 0.95, "critical": True,  "note": "Используется: Фаза 6, 7"},
            "addressee_type":{"threshold": 0.90, "critical": True,  "note": "Используется: LLM-датасет"},
            "god_action":    {"threshold": 0.90, "critical": True,  "note": "Используется: LLM-датасет"},
            "participants":  {"threshold": 0.30, "critical": False, "note": "Списочное поле — ok если много пустых"},
        }
    },

    "phase_5": {
        "file": "C:/GOD2/output/god_profile.json",
        "description": "Психологический профиль (psych_analysis.py)",
        "fields": {
            "jung_archetypes":   {"threshold": 1.00, "critical": True},
            "big_five_ocean":    {"threshold": 1.00, "critical": True},
            "bowlby_attachment": {"threshold": 1.00, "critical": True},
        }
    },

    "llm_dataset": {
        "file": "C:/GOD2/output/reasoning_dataset.jsonl",
        "description": "Датасет для fine-tuning (generate_reasoning_dataset.py)",
        "is_jsonl": True,
        "min_records": 300,
        "fields": {
            "instruction": {"threshold": 1.00, "critical": True},
            "output":      {"threshold": 1.00, "critical": True},
            "metadata":    {"threshold": 0.95, "critical": True},
        }
    },
}

# ============================================================
# ЛОГИКА АУДИТА
# ============================================================

def check_nonempty(value) -> bool:
    """True если значение НЕ пустое (не None, не "", не [], не 0 для severity)."""
    if value is None:
        return False
    if isinstance(value, str):
        return len(value.strip()) > 0 and value.strip() not in {"unclear", ""}
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return True

def audit_file(phase_key: str, contract: dict) -> bool:
    """Аудит одного файла. Возвращает True если всё OK, False при критической ошибке."""
    path = Path(contract["file"])
    print(f"\n{'='*60}")
    print(f"[{phase_key.upper()}] {contract['description']}")
    print(f"Файл: {path}")
    print(f"{'='*60}")

    if not path.exists():
        print(f"  ПРОПУСК: файл не найден.")
        return True  # не критично — фаза могла ещё не выполняться

    # Загрузка
    is_jsonl = contract.get("is_jsonl", False)
    records = []
    try:
        if is_jsonl:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        else:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                records = data if isinstance(data, list) else [data]
    except Exception as e:
        print(f"  ОШИБКА загрузки: {e}")
        return False

    total = len(records)
    print(f"  Записей: {total}")

    # Минимальное кол-во записей
    min_records = contract.get("min_records")
    if min_records and total < min_records:
        print(f"  [FAIL] Записей {total} < минимума {min_records}!")
        return False

    # Аудит полей
    has_critical_fail = False

    print(f"\n  {'Поле':<20} {'Заполнено':>10} {'Fill%':>7} {'Порог':>7} {'Статус'}")
    print(f"  {'-'*65}")

    for field, cfg in contract["fields"].items():
        threshold = cfg["threshold"]
        is_critical = cfg["critical"]
        note = cfg.get("note", "")

        filled = sum(1 for r in records if check_nonempty(r.get(field)))
        fill_rate = filled / total if total > 0 else 0
        pct = fill_rate * 100

        status = "OK" if fill_rate >= threshold else ("FAIL" if is_critical else "WARN")
        if status == "FAIL":
            has_critical_fail = True

        marker = "❌" if status == "FAIL" else ("⚠️" if status == "WARN" else "✅")
        print(f"  {field:<20} {filled:>10} {pct:>6.1f}% {threshold*100:>6.0f}%  {status}  {note}")

    if has_critical_fail:
        print(f"\n  *** КРИТИЧЕСКИЙ ПРОВАЛ: fill-rate ниже порога для критических полей! ***")
        print(f"  *** Корни проблем чаще всего: лишний фильтр, пропуск поля в промпте, баг парсера ***")
    else:
        print(f"\n  Все поля в норме. Можно переходить к следующей фазе.")

    return not has_critical_fail

def main():
    parser = argparse.ArgumentParser(description="GOD2 Phase Contract Auditor")
    parser.add_argument("--phase", default="all",
                        help="Фаза для аудита: phase_3, phase_4, phase_5, llm_dataset, all")
    args = parser.parse_args()

    print("=" * 60)
    print("GOD2 — Phase Contract Audit")
    print("=" * 60)

    phases_to_check = list(PHASE_CONTRACTS.keys()) if args.phase == "all" \
        else [args.phase]

    all_ok = True
    for key in phases_to_check:
        if key not in PHASE_CONTRACTS:
            print(f"Неизвестная фаза: {key}. Доступные: {list(PHASE_CONTRACTS.keys())}")
            sys.exit(1)
        ok = audit_file(key, PHASE_CONTRACTS[key])
        if not ok:
            all_ok = False

    print("\n" + "=" * 60)
    if all_ok:
        print("ИТОГ: ВСЕ КОНТРАКТЫ ВЫПОЛНЕНЫ. Можно продолжать пайплайн.")
        sys.exit(0)
    else:
        print("ИТОГ: КОНТРАКТ НАРУШЕН. Исправьте проблемные поля перед продолжением!")
        sys.exit(1)

if __name__ == "__main__":
    main()
