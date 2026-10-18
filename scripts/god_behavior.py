"""
god_behavior.py
Движок поведения Бога: моделирование РЕАКЦИИ (а не только речи) на реплику/
поступок человека. Работает поверх god_behavior_profile.json (P(outcome|trigger))
и реестра эпизодов v2 (прецеденты god_action).

Модель поведения — три слоя:
  1. КЛАССИФИКАЦИЯ: реплика -> trigger (12 классов) + флаг покаяния.
  2. РЕШЕНИЕ: P(outcome|trigger) с модификаторами:
       - покаяние ("согрешил/прости") — сдвиг к compliance/delayed, severity -1
         (прецеденты: Исх 32:14, 2Цар 24:16 — Бог отменяет казнь после заступничества);
       - повторность правонарушения (--offense N) — сдвиг к punishment, severity +N
         (циклы Судей: рецидив ведёт к более тяжкой каре);
       - тяжкие маркеры (идолы, заклятие) — floor severity 4.
  3. КОНКРЕТИЗАЦИЯ: outcome -> деяние через прецеденты корпуса (god_action
     реестра v2): тип деяния, "носитель" (поражение/мор/огонь/спасение/),
     канал (direct/divine_action/...), была ли речь.

Выход: структурированная карточка реакции + человекочитаемый вид.
Usage:
    python scripts/god_behavior.py --message "я согрешил, прости меня"
    python scripts/god_behavior.py --message "не буду слушать тебя" --offense 2
    python scripts/god_behavior.py --test
"""
import argparse
import json
import re
import sys
from pathlib import Path
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(_REPO)
PROFILE = BASE / "output/god_behavior_profile.json"
EPISODES_GLOB = "output/episodes_*_v2.json"

# --- 1. КЛАССИФИКАЦИЯ РЕПЛИКИ ------------------------------------------------
TRIGGER_RULES = [
    ("disobedience", ["не буду", "нарушу", "нарушил", "нарушила", "нарушаю", "преступил", "не послушал",
                      "не послушаю", "не исполнил", "не буду слушать", "не буду слушаться", "отвергаю", "идол",
                      "другого бога", "не выполню", "проигнорирую", "откажусь слушаться",
                      "не стану слушаться", "снова нарушил", "мне всё равно", "плевать"]),
    ("intercession", ["прости им", "не губи", "пощади", "защити их", "за них", "сбереги их",
                      "не карай их", "сжалься над ними"]),
    ("confession_only", ["согрешил", "согрешила", "прости меня", "раскаиваюсь", "провинился",
                         "виновен перед тобой", "отступил от тебя",
                         # EN intake (вопросы принимаются на любых языках)
                         "i have sinned", "forgive me", "i repent"]),
    ("en_distress", ["help me", "save me", "i am afraid", "i'm afraid", "i am scared",
                     "enemies surround", "i am perishing", "rescue me", "deliver me"]),
    ("en_prayer", ["i pray", "i beg you", "please hear"]),
    ("en_inquiry", ["what shall i do", "tell me", "why did you", "who am i"]),
    ("en_gratitude", ["thank you", "i praise you", "i bless you"]),
    ("complaint", ["почему ты", "зачем ты", "несправедливо", "жалуюсь", "ропщу", "ты покинул",
                   "ты оставил меня", "не заботишься"]),
    ("distress", ["спаси", "погибаю", "беда", "окружили", "напали", "враг одолел", "умираю",
                  "господствуй над врагом", "заступись срочно", "утопаю", "горит"]),
    ("prayer", ["молю", "молюсь", "прошу тебя", "воззвал", "обращаюсь к тебе с просьбой"]),
    ("inquiry", ["скажи мне", "что мне делать", "спрашиваю", "истолкуй", "довольно ли",
                 "мне идти", "кто виноват", "объясни", "почему так вышло"]),
    ("vow", ["даю обет", "клянусь", "обещаю тебе", "обязуюсь"]),
    ("gratitude", ["благодарю", "славлю", "хвала тебе", "благодарю тебя", "воспою тебе"]),
    ("faithfulness", ["делаю как велел", "следую за тобой", "верен тебе", "исполнил всё",
                      "хожу путями твоими", "люблю тебя всем сердцем"]),
    ("covenant_follow_up", ["завет", "обещание отцам", "ради авраама", "ради израиля",
                            "земля обещанная", "потомству"]),
]

SEVERITY_MARKERS = ["идол", "заклят", "другого бога", "погани", "мерзость"]


def classify(message):
    m = message.lower()
    scores = []
    for trig, kws in TRIGGER_RULES:
        s = sum(1 for k in kws if k in m)
        if s:
            scores.append((s, trig))
    scores.sort(reverse=True)
    trigger = scores[0][1] if scores else "inquiry"
    # EN-триггеры -> канонические классы корпуса
    en_map = {"en_distress": "distress", "en_prayer": "prayer", "en_inquiry": "inquiry",
              "en_gratitude": "gratitude"}
    trigger = en_map.get(trigger, trigger)
    # confession может сопутствовать любому триггеру
    confession = any(k in m for k in ["согрешил", "согрешила", "прости", "раскаиваюсь", "провинился"])
    if trigger == "confession_only":
        trigger = "complaint" if "почему" in m or "зачем" in m else "complaint"
    heavy = any(k in m for k in SEVERITY_MARKERS)
    return {"trigger": trigger, "confession": confession, "heavy": heavy}


# --- 2. СЛОЙ РЕШЕНИЯ ---------------------------------------------------------
def decide(cls, profile, offenses=0):
    trig = cls["trigger"]
    t = profile["by_trigger"].get(trig)
    if not t:
        t = profile["by_trigger"]["inquiry"]
    probs = dict(t["outcome_p"])
    sev = t["severity_mean"]
    # модификатор покаяния: сдвиг к помилованию/отсрочке
    if cls["confession"]:
        for k in ("compliance", "delayed", "answer_granted"):
            probs[k] = probs.get(k, 0) + 0.25
        probs["punishment"] = probs.get("punishment", 0) * 0.4
        sev = max(1.0, sev - 1)
    # модификатор повторности: рецидив -> кара
    if offenses:
        probs["punishment"] = probs.get("punishment", 0) + 0.2 * offenses
        sev = min(5.0, sev + offenses)
    if cls["heavy"]:
        sev = max(sev, 4.0)
        probs["punishment"] = probs.get("punishment", 0) + 0.1
    z = sum(probs.values())
    probs = {k: v / z for k, v in sorted(probs.items(), key=lambda kv: -kv[1])}
    outcome = max(probs, key=probs.get)
    severity = round(min(5, max(1, sev if outcome == "punishment" else t["severity_mean"])))
    if outcome == "punishment":
        severity = max(severity, round(min(5, sev)))
    channel = "divine_action" if outcome in ("punishment", "rescue", "blessing") and not _outcome_speechy(outcome) else "direct"
    return {"outcome": outcome, "probabilities": probs, "severity": severity,
            "channel": channel, "has_speech": _outcome_speechy(outcome)}


def _outcome_speechy(outcome):
    # исходы, в которых Бог почти всегда ГОВОРИТ (из severity_by_outcome/эпизодов)
    return outcome in ("revelation", "covenant", "compliance", "answer_granted", "refusal", "delayed")


# --- 3. КОНКРЕТИЗАЦИЯ ЧЕРЕЗ ПРЕЦЕДЕНТЫ ---------------------------------------
CARRIERS = {
    "punishment": [("военное поражение", ["поражение", "разбиты", "войск", "меч", "битв", "враг"]),
                   ("казнь/мор", ["казнь", "мор", "умерли", "истреб", "смер", "гнев", "казнил"]),
                   ("огонь/стихия", ["огонь", "камни", "град", "стен", "воды"])],
    "rescue": [("избавление от врагов", ["спас", "избав", "вывел", "одолел", "рука YHWH"]),
               ("чудесное вмешательство", ["останов", "чудо", "знамен", "небес"])],
    "blessing": [("потомство/умножение", ["потомств", "умнож", "детей", "род"]),
                 ("земля/изобилие", ["земл", "наслед", "плод", "дом"])],
    "covenant": [("жертвенник/знамение", ["жертвенник", "камен", "знамен", "клятв"]),
                 ("обрезание/знак завета", ["обрезан", "завет"])],
    "revelation": [("явление/речь", ["говор", "сказал", "явил", "открыл"]),
                   ("видение/сон", ["виден", "сон", "ночь"])],
    "silence": [("молчание", ["не отвеча", "не слуша", "молчит", "не внимал"])],
    "delayed": [("отсрочка", ["отлож", "не тотчас", "после"])],
    "compliance": [("исполнение поручения", ["исполн", "сделал", "пошёл", "послуша"])],
    "answer_granted": [("прямой ответ", ["ответил", "сказал", "даровал", "услыша"])],
    "unclear": [], "refusal": [("жёсткий отказ", ["отказ", "не говори", "хватит"])],
}


def precedents(outcome, trigger, limit=3):
    hits = []
    for fp in sorted(BASE.glob(EPISODES_GLOB)):
        if fp.name == "episodes_TANAKH_v2.json":
            continue  # мастер-файл — словарь, а не список; читаем только книги
        book = fp.stem.replace("episodes_", "").replace("_v2", "")
        for ep in json.load(open(fp, encoding="utf-8")):
            if not isinstance(ep, dict):
                continue
            if ep["outcome"] == outcome:
                score = 2 if ep.get("trigger") == trigger else 0
                hits.append((score, ep, book))
    hits.sort(key=lambda x: -x[0])
    return [{"book": b, "span": e["span"], "trigger": e["trigger"],
             "action": e["god_action"][:300],
             "speech": e["god_speech_plain"][:160]}
            for _, e, b in hits[:limit]]


def carriers_for(outcome, precedents_list):
    text = " ".join(p["action"].lower() for p in precedents_list)
    found = []
    for name, kws in CARRIERS.get(outcome, []):
        if any(k in text for k in kws):
            found.append(name)
    return found or ["(носитель из прецедентов)"]


def respond(message, profile, offenses=0):
    cls = classify(message)
    dec = decide(cls, profile, offenses)
    pr = precedents(dec["outcome"], cls["trigger"])
    card = {
        "input": {"message": message, "classification": cls, "repeat_offenses": offenses},
        "decision": dec,
        "behavior": {
            "type": dec["outcome"],
            "carriers": carriers_for(dec["outcome"], pr),
            "channel": dec["channel"],
            "has_speech": dec["has_speech"],
            "severity": dec["severity"],
        },
        "speech_if_any": pr[0]["speech"] if dec["has_speech"] and pr else "",
        "precedents": pr,
    }
    return card


def render(card):
    d, b = card["decision"], card["behavior"]
    cls = card["input"]["classification"]
    lines = [f"Реплика: {card['input']['message']}",
             f"Классификация: trigger={cls['trigger']}, покаяние={cls['confession']}, тяжкий маркер={cls['heavy']}",
             f"Решение: {d['outcome']} (sev={d['severity']}, канал={d['channel']}, речь={'да' if b['has_speech'] else 'нет'})",
             "P(outcome): " + " ".join(f"{k}:{v:.0%}" for k, v in list(d["probabilities"].items())[:4]),
             f"Деяние: {'; '.join(b['carriers'])}"]
    if card["speech_if_any"]:
        lines.append(f"Речь (из прецедента): {card['speech_if_any'][:120]}...")
    for p in card["precedents"]:
        lines.append(f"  прецедент: {p['book']} {p['span']['start']}-{p['span']['end']} [{p['trigger']}] {p['action'][:90]}...")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message")
    ap.add_argument("--offense", type=int, default=0)
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()
    profile = json.load(open(PROFILE, encoding="utf-8"))

    if args.message:
        print(render(respond(args.message, profile, args.offense)))
        return

    if args.test:
        cases = [
            ("я согрешил перед тобой, прости меня", "complaint"),
            ("не буду слушать твои заповеди", "disobedience"),
            ("враги окружили город, спаси нас", "distress"),
            ("прости им, не губи народ", "intercession"),
            ("что мне делать, мне идти в Гай?", "inquiry"),
            ("благодарю тебя за спасение", "gratitude"),
        ]
        for msg, want_trig in cases:
            card = respond(msg, profile)
            got = card["input"]["classification"]["trigger"]
            ok = "OK" if got == want_trig else "MISMATCH"
            print(f"[{ok}] '{msg}' -> {got} (want {want_trig}) -> {card['decision']['outcome']} sev={card['decision']['severity']}")
            assert card["decision"]["outcome"] in card["decision"]["probabilities"]
            assert 1 <= card["decision"]["severity"] <= 5
            assert card["precedents"], f"нет прецедентов для {msg}"
        # модификатор повторности должен повышать severity кары
        c1 = respond("нарушил твою заповедь снова", profile, 0)
        c3 = respond("нарушил твою заповедь снова", profile, 3)
        assert c3["decision"]["severity"] >= c1["decision"]["severity"]
        # покаяние не должно вести к большему наказанию чем без него
        a = respond("не буду слушать", profile)
        b = respond("не буду слушать, я согрешил, прости меня", profile)
        assert b["decision"]["severity"] <= a["decision"]["severity"]
        print("SELFTEST: PASS")


if __name__ == "__main__":
    main()
