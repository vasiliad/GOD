"""
psych_analysis.py v3 — психологический профиль из реальных поведенческих кодов.
Работает с situations_coded.json.
Вход:  output/situations_coded.json
Выход: output/god_profile.json, output/behavior_patterns.json
"""
import json
import sys
import argparse
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

CODED_FILE = Path("C:/GOD2/output/situations_coded.json")
OUTPUT     = Path("C:/GOD2/output")

def pct(key, dist, total_n=None):
    n = total_n or max(sum(dist.values()), 1)
    return round(dist.get(key, 0) / max(n, 1) * 100, 2)

def ocean(raw_pct, pop_mean, pop_sd):
    z = (raw_pct - pop_mean) / max(pop_sd, 0.01)
    return round(max(1.0, min(10.0, 5.0 + z * 2.0)), 1)

def top_books_for_type(btype, situations, n=3):
    book_counts = Counter(s.get("book") for s in situations if s.get("behavior_type") == btype)
    return [f"{b} ({cnt})" for b, cnt in book_counts.most_common(n)]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="DRY-RUN")
    args = parser.parse_args()

    if not CODED_FILE.exists():
        print(f"ОШИБКА: {CODED_FILE} не найден.")
        sys.exit(1)

    with open(CODED_FILE, encoding="utf-8") as f:
        situations = json.load(f)

    if args.test:
        situations = situations[:10]
        print("[DRY-RUN] Режим тестирования. Обрабатываем до 10 записей.")

    total = len(situations)
    print(f"Загружено закодированных ситуаций: {total}")

    btype_dist   = Counter(s.get("behavior_type", "unclear") for s in situations)
    severity_dist = Counter(s.get("severity", 0) for s in situations)
    target_dist  = Counter(s.get("addressee_type", "unclear") for s in situations)
    trigger_dist = Counter(s.get("trigger", "unclear") for s in situations)
    outcome_dist = Counter(s.get("outcome", "unclear") for s in situations)
    initiator_dist = Counter(s.get("who_initiated", "unclear") for s in situations)

    # BUGFIX: Use behavior_type != unclear instead of removed god_action
    real = [s for s in situations if s.get("behavior_type") not in ("unclear", "?", "", None)]
    total_real = max(len(real), 1)

    trigger_outcome = Counter(
        (s.get("trigger", "unclear"), s.get("outcome", "unclear")) for s in real
    )

    god_initiative_pct = round(initiator_dist.get("God", 0) / max(total, 1) * 100, 1)

    severe_punishment = sum(1 for s in situations if s.get("behavior_type") == "punishment" and s.get("severity", 0) >= 4)

    jung_archetypes = {
        "Отец (Власть и закон)": btype_dist["command"] + btype_dist["punishment"],
        "Мудрец (Откровение)":   btype_dist["revelation"] + btype_dist["covenant"],
        "Герой/Защитник":        btype_dist["rescue"],  # Was salvation
        "Трикстер (Испытание)":  btype_dist["divine_test"], # Was question
        "Разрушитель (Теневой)": severe_punishment,
    }
    total_jung = max(sum(jung_archetypes.values()), 1)
    jung_pct = {k: round(v / total_jung * 100, 1) for k, v in jung_archetypes.items()}
    dominant_jung = max(jung_archetypes, key=jung_archetypes.get) if total_jung > 1 else "Unknown"

    ctrl_parent = btype_dist["command"] + btype_dist["punishment"]
    nurturing_parent = btype_dist["rescue"] + btype_dist["promise"]
    adult = btype_dist["covenant"] + btype_dist["revelation"]
    child = btype_dist.get("divine_test", 0) + btype_dist.get("unclear", 0)

    berne_states = {
        "Родитель Контролирующий": ctrl_parent,
        "Родитель Питающий":       nurturing_parent,
        "Взрослый":                adult,
        "Ребёнок (реактивный)":    child,
    }
    total_berne = max(sum(berne_states.values()), 1)
    berne_pct_d = {k: round(v / total_berne * 100, 1) for k, v in berne_states.items()}
    dominant_berne = max(berne_states, key=berne_states.get) if total_berne > 1 else "Unknown"

    big_five = {
        "Openness":          ocean(pct("revelation", btype_dist, total_real), pop_mean=3.0, pop_sd=2.0),
        "Conscientiousness": ocean(pct("command", btype_dist, total_real) + pct("covenant", btype_dist, total_real),
                                   pop_mean=15.0, pop_sd=5.0),
        "Extraversion":      ocean(god_initiative_pct, pop_mean=20.0, pop_sd=8.0),
        "Agreeableness":     ocean(pct("rescue", btype_dist, total_real) + pct("promise", btype_dist, total_real),
                                   pop_mean=5.0, pop_sd=3.0),
        "Neuroticism":       ocean(pct("punishment", btype_dist, total_real), pop_mean=3.0, pop_sd=2.0),
    }

    total_triggers = max(sum(trigger_outcome.values()), 1)
    prayer_rescue = trigger_outcome.get(("prayer","rescue"), 0) + trigger_outcome.get(("prayer","blessing"), 0)
    dis_pun = trigger_outcome.get(("disobedience","punishment"), 0) + trigger_outcome.get(("idolatry","punishment"), 0)

    prayer_rescue_pct  = prayer_rescue / total_triggers * 100
    dis_pun_pct        = dis_pun / total_triggers * 100
    covenant_count     = btype_dist.get("covenant", 0)

    if covenant_count > 50 and prayer_rescue_pct > 5:
        bowlby_style = "Secure with conditional elements"
    elif dis_pun_pct > 3:
        bowlby_style = "Anxious-Ambivalent (high expectations, reactive punishment)"
    else:
        bowlby_style = "Secure-Authoritative"

    unprompted_count = trigger_dist.get("unprompted", 0)
    nation_count     = target_dist.get("nation", 0) + target_dist.get("all_humanity", 0)
    
    adler_analysis = {
        "striving_for_superiority": {
            "score": round(min(10, 5 + (btype_dist["punishment"] + unprompted_count) / max(total_real, 1) * 30), 1),
        },
        "teleology": {
            "dominant_goal": "Создание народа-носителя Завета (covenant_count={})".format(covenant_count),
        },
        "inferiority_compensation": {
            "god_response": "Ужесточение при нарушении (disobedience→punishment: {}%)".format(round(dis_pun_pct,1)),
        },
        "social_interest": {
            "score": round(pct("rescue", btype_dist, total_real) + pct("promise", btype_dist, total_real), 2),
        }
    }

    def top_trigger_outcomes(n=5):
        return [
            {"trigger": t, "outcome": o, "count": cnt, "pct": round(cnt/total_triggers*100, 1)}
            for (t, o), cnt in trigger_outcome.most_common(n)
        ]

    fbi_profile = {
        "trigger_outcome_matrix_top10": top_trigger_outcomes(10),
        "trigger_distribution": dict(trigger_dist.most_common()),
        "outcome_distribution": dict(outcome_dist.most_common()),
        "escalation_evidence": {
            "severe_punishments": severe_punishment,
            "severe_pct": round(severe_punishment / max(total_real, 1) * 100, 1),
        },
        "modus_operandi": {
            "command_pct":    pct("command", btype_dist, total_real),
            "punishment_pct": pct("punishment", btype_dist, total_real),
            "rescue_pct":     pct("rescue", btype_dist, total_real),
        }
    }

    god_profile = {
        "metadata": {
            "version": "v3 — behavioral coding",
            "total_situations": total,
            "real_actions_coded": total_real,
        },
        "jung_archetypes": {
            "scores_raw": jung_archetypes,
            "scores_pct": jung_pct,
            "dominant": dominant_jung,
        },
        "berne_transactional": {
            "ego_states_raw": berne_states,
            "ego_states_pct": berne_pct_d,
            "dominant": dominant_berne,
        },
        "big_five_ocean": big_five,
        "bowlby_attachment": {
            "style": bowlby_style,
        },
        "adler_individual_psychology": adler_analysis,
        "fbi_behavioral_profile": fbi_profile,
    }

    behavior_patterns = {
        "trigger_response_patterns": top_trigger_outcomes(10),
        "severity_profile": {
            "catastrophic_5": severity_dist.get(5, 0),
            "mild_1": severity_dist.get(1, 0),
        },
        "target_profile": dict(target_dist.most_common()),
    }

    if not args.test:
        with open(OUTPUT / "god_profile.json", "w", encoding="utf-8") as f:
            json.dump(god_profile, f, ensure_ascii=False, indent=2)

        with open(OUTPUT / "behavior_patterns.json", "w", encoding="utf-8") as f:
            json.dump(behavior_patterns, f, ensure_ascii=False, indent=2)

        print(f"\npsych_analysis v3 завершён!")
        print(f"Юнг:      {dominant_jung}")
        print(f"Берн:     {dominant_berne}")
        print(f"Big Five: {big_five}")
    else:
        print("\n[DRY-RUN] Тест успешен. Файлы не перезаписались.")
        print(f"Юнг:      {dominant_jung}")
        print(f"Берн:     {dominant_berne}")
        print(f"Big Five: {big_five}")

if __name__ == "__main__":
    main()
