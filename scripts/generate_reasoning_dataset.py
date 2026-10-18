"""
generate_reasoning_dataset.py
Этап 2: Учитель (DictaLM 3.0 24B Thinking в LM Studio) пишет учебник.

Запуск:
  python scripts/generate_reasoning_dataset.py [--test]
"""
import json
import re
import sys
import time
import argparse
from pathlib import Path
from openai import OpenAI
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
LM_STUDIO_URL  = "http://localhost:1234/v1"
LM_STUDIO_KEY  = "lm-studio"

CODED    = Path(_REPO + "/output/situations_coded.json")
PROFILE  = Path(_REPO + "/output/god_profile.json")
CONCEPTS = Path(_REPO + "/output/concept_analysis.json")
OUTPUT   = Path(_REPO + "/output/reasoning_dataset.jsonl")
ERRORS   = Path(_REPO + "/output/reasoning_errors.jsonl")

PROMPT_SYS   = Path(_REPO + "/prompts/god_reasoning_sys.md")
PROMPT_JUDGE = Path(_REPO + "/prompts/god_reasoning_judge.md")

MAX_SITUATIONS = 10000
SKIP_BEHAVIORS = {"other"}
REQUEST_DELAY  = 0.1
MAX_RETRIES = 2

# Fail-fast settings (Rule #5)
ERROR_THRESHOLD_PCT = 0.10
MIN_SAMPLES_FOR_FAIL_FAST = 50

# ============================================================
# ИСТОРИЧЕСКИЕ ЯКОРЯ (иврит)
# ============================================================
HISTORICAL_ANCHORS = {
    "Genesis":     "ברית אברהם — זרע, ארץ, ברכת העמים (בר' יב, טו, יז)",
    "Exodus":      "ברית סיני, עשרת הדברות, יציאת מצרים כיסוד הזהות",
    "Leviticus":   "קדושה כמטרה: קְדֹשִׁים תִּהְיוּ כִּי קָדוֹשׁ אֲנִי יְהוָה (ויק' יט:ב)",
    "Numbers":     "אמונה למרות המרד — ארבעים שנות מדבר כפדגוגיה",
    "Deuteronomy": "חידוש הברית, שמע ישראל, אהבה כיסוד לציות",
    "Joshua":      "כיבוש הארץ — קיום שבועת אברהם",
    "Judges":      "מחזור: חטא — עונש — זעקה — מושיע — שלום",
    "I Samuel":    "מעבר למלכות; משיחת דוד",
    "II Samuel":   "ברית עולם עם בית דוד (שמ״ב ז:יב-טז)",
    "I Kings":     "ברית דוד; אזהרה לשלמה",
    "II Kings":    "חורבן כתוצאה מהפרת הברית",
    "Isaiah":      "יציאת מצרים חדשה, עבד יהוה, ברית עולם",
    "Jeremiah":    "ברית חדשה על הלב (יר' לא:לא-לד)",
    "Ezekiel":     "רוח חדשה, תחיית המתים, מקדש חדש",
    "Psalms":      "דיאלוג אמונה: הלל, קינה, ביטחון",
    "Job":         "תיאודיציה: ריבונות האל מול הסבל",
    "default":     "ברית האבות — אברהם, יצחק, יעקב",
}

TRIG_HE = {
    "prayer": "תפילה", "disobedience": "מרי", "idolatry": "עבודה זרה",
    "faithfulness": "נאמנות", "unprompted": "ביוזמת ה׳",
    "intercession": "תחנת מליץ", "covenant": "ברית",
    "distress": "צרה", "divine_test": "ניסיון", "unclear": "לא ברור",
}
BEH_HE = {
    "command": "ציווי", "punishment": "עונש", "blessing": "ברכה",
    "revelation": "התגלות", "promise": "הבטחה", "rescue": "הצלה",
    "covenant": "ברית", "dialogue": "דיאלוג", "other": "אחר",
}
OUT_HE = {
    "punishment": "עונש", "blessing": "ברכה", "covenant": "ברית",
    "rescue": "הצלה", "revelation": "התגלות", "compliance": "ציות",
    "dialogue": "שיח", "silence": "שתיקה", "unclear": "לא מוגדר",
}
BOOK_HE = {
    "Genesis": "בראשית", "Exodus": "שמות", "Leviticus": "ויקרא",
    "Numbers": "במדבר", "Deuteronomy": "דברים", "Joshua": "יהושע",
    "Judges": "שופטים", "I Samuel": "שמואל א", "II Samuel": "שמואל ב",
    "I Kings": "מלכים א", "II Kings": "מלכים ב", "Isaiah": "ישעיהו",
    "Jeremiah": "ירמיהו", "Ezekiel": "יחזקאל", "Psalms": "תהילים",
    "Proverbs": "משלי", "Job": "איוב", "Ruth": "רות",
    "Lamentations": "איכה", "Ecclesiastes": "קהלת",
    "Song of Songs": "שיר השירים", "Daniel": "דניאל",
    "Hosea": "הושע", "Amos": "עמוס", "Jonah": "יונה",
    "Micah": "מיכה", "Zechariah": "זכריה", "Malachi": "מלאכי",
}

def build_user_prompt(s: dict) -> str:
    book_en      = s.get("book", "")
    book         = BOOK_HE.get(book_en, book_en)
    ch           = s.get("chapter", "?")
    v            = s.get("verse", s.get("verse_start", "?"))
    text_he      = s.get("text_he", s.get("text_plain", ""))
    trig         = TRIG_HE.get(s.get("trigger", ""), s.get("trigger", ""))
    beh          = BEH_HE.get(s.get("behavior_type", ""), s.get("behavior_type", ""))
    out          = OUT_HE.get(s.get("outcome", ""), s.get("outcome", ""))
    sev          = s.get("severity", 1)
    anchor       = HISTORICAL_ANCHORS.get(book_en, HISTORICAL_ANCHORS["default"])
    addressee    = s.get("addressee_type", "unclear")

    return (
        f"<situation>\n"
        f"Verse [{book} {ch}:{v}]: {text_he}\n"
        f"Trigger: {trig} | Behavior: {beh} | Outcome: {out} | Severity: {sev}/5\n"
        f"Addressee: {addressee}\n"
        f"Covenant context ({book_en}): {anchor}\n"
        f"</situation>\n\n"
        f"Generate <think>, <voice_hebrew>, <voice_russian>:"
    )

def parse_blocks(raw: str):
    def extract(tag: str) -> str:
        pattern = rf"<{tag}.*?>(.*?)</{tag}>"
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""
    return extract("think"), extract("voice_hebrew"), extract("voice_russian")

def generate_one(situation: dict, client, active_model, sys_prompt, judge_prompt, no_judge=False) -> dict | None:
    for attempt in range(MAX_RETRIES + 1):
        try:
            # PASS 1: GENERATION
            completion = client.chat.completions.create(
                model=active_model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user",   "content": build_user_prompt(situation)},
                ],
                temperature=0.3,
                max_tokens=3000,
                stop=["</voice_russian>"],
            )
            msg = completion.choices[0].message
            raw = msg.content or ""
            if not raw.rstrip().endswith("</voice_russian>"):
                raw += "\n</voice_russian>"

            think, voice_he, voice_ru = parse_blocks(raw)

            # LM Studio routes <think> to reasoning_content field — fallback
            if not think:
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:
                    think = reasoning.strip()

            if not think or not voice_he or not voice_ru:
                if attempt == MAX_RETRIES:
                    return {"error": "Missing blocks", "raw_output": raw[:500], "id": situation.get("id")}
                continue # Retry

            # Если --no-judge — пропускаем Pass 2, возвращаем сразу
            if no_judge:
                return {
                    "situation":     f"[{situation.get('book','')} {situation.get('chapter','')}:{situation.get('verse_start','')}] {situation.get('text_he','')[:120]}",
                    "think":         think,
                    "voice_hebrew":  voice_he,
                    "voice_russian": voice_ru,
                    "metadata": {
                        "book":          situation.get("book"),
                        "trigger":       situation.get("trigger"),
                        "behavior_type": situation.get("behavior_type"),
                        "outcome":       situation.get("outcome"),
                        "severity":      situation.get("severity"),
                        "situation_id":  situation.get("id"),
                    }
                }

            # Пауза между Pass 1 и Pass 2 — чтобы не перегружать LM Studio
            time.sleep(5)

            # PASS 2: LLM-as-a-Judge Validation
            user_context = build_user_prompt(situation)
            eval_prompt = judge_prompt.replace("{{ORIGINAL_CONTEXT}}", user_context).replace("{{GENERATED_TEXT}}", raw)
            
            eval_completion = client.chat.completions.create(
                model=active_model,
                messages=[
                    {"role": "system", "content": "You are a strict data evaluator. Output purely JSON without markdown ticks."},
                    {"role": "user",   "content": eval_prompt},
                ],
                temperature=0.1,
                max_tokens=800,
            )
            eval_raw = eval_completion.choices[0].message.content or ""
            
            # Pydantic-like strict JSON loading
            match = re.search(r'\{.*\}', eval_raw, re.DOTALL)
            if not match:
                if attempt == MAX_RETRIES:
                    return {"error": "Judge failed to output JSON", "raw_output": eval_raw, "id": situation.get("id")}
                continue

            try:
                judge_result = json.loads(match.group(0))
                is_valid = judge_result.get("is_valid", False)
                reason = judge_result.get("reason", "Unknown reason")
                
                if not is_valid:
                    if attempt == MAX_RETRIES:
                        return {"error": f"Judge rejected output: {reason}", "raw_output": raw[:200], "id": situation.get("id")}
                    continue # Retry on hallucination
                
            except json.JSONDecodeError:
                if attempt == MAX_RETRIES:
                    return {"error": "Judge JSON validation error", "id": situation.get("id")}
                continue

            # Return successfully evaluated output
            return {
                "situation":     f"[{situation.get('book','')} {situation.get('chapter','')}:{situation.get('verse_start','')}] {situation.get('text_he','')[:120]}",
                "think":         think,
                "voice_hebrew":  voice_he,
                "voice_russian": voice_ru,
                "metadata": {
                    "book":          situation.get("book"),
                    "trigger":       situation.get("trigger"),
                    "behavior_type": situation.get("behavior_type"),
                    "outcome":       situation.get("outcome"),
                    "severity":      situation.get("severity"),
                    "situation_id":  situation.get("id"),
                }
            }

        except Exception as e:
            err_str = str(e)
            is_connection = "Connection" in err_str or "timeout" in err_str.lower() or "connect" in err_str.lower()
            if attempt == MAX_RETRIES:
                return {"error": err_str, "id": situation.get("id")}
            # Для Connection error ждём дольше
            sleep_time = 30 if is_connection else 2
            print(f" [retry {attempt+1}/{MAX_RETRIES}, sleep {sleep_time}s]", flush=True)
            time.sleep(sleep_time)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run in test mode (5 samples, no file out)")
    parser.add_argument("--no-judge", action="store_true", dest="no_judge",
                        help="Skip Pass2 LLM-Judge (faster, use for bulk generation; audit separately)")
    args = parser.parse_args()

    print("=== GOD2 Reasoning Dataset Generator ===")
    print(f"Test Mode: {'ON' if args.test else 'OFF'}")

    # ============================================================
    # ЗАГРУЗКА И НАСТРОЙКА (Правило #10)
    # ============================================================
    with open(CODED, encoding="utf-8") as f: situations = json.load(f)
    with open(PROFILE, encoding="utf-8") as f: profile = json.load(f)
    with open(CONCEPTS, encoding="utf-8") as f: concepts = json.load(f)
    
    jung   = profile["jung_archetypes"]["dominant"]
    bowlby = profile["bowlby_attachment"]["style"]
    big5_n = profile["big_five_ocean"]["Neuroticism"]
    big5_c = profile["big_five_ocean"]["Conscientiousness"]
    mercy  = concepts["anger_mercy_ratio"]["mercy_pct"]
    anger  = concepts["anger_mercy_ratio"]["anger_pct"]

    # Load prompts
    sys_prompt = PROMPT_SYS.read_text(encoding="utf-8").format(
        jung=jung, bowlby=bowlby, big5_neuroticism=big5_n, big5_conscientiousness=big5_c, mercy=mercy, anger=anger
    )
    judge_prompt = PROMPT_JUDGE.read_text(encoding="utf-8")

    # ============================================================
    # КЛИЕНТ LM STUDIO
    # ============================================================
    client = OpenAI(base_url=LM_STUDIO_URL, api_key=LM_STUDIO_KEY)
    try:
        models = client.models.list()
        active = models.data[0].id if models.data else "unknown"
        print(f"LM Studio: OK | Модель: {active}")
    except Exception as e:
        print(f"Ошибка подключения к LM Studio: {e}")
        sys.exit(1)

    # ============================================================
    # RESUME LOGIC (Immutable pipelines)
    # ============================================================
    done_ids = set()
    if not args.test and OUTPUT.exists():
        with open(OUTPUT, encoding="utf-8") as f:
            for line in f:
                try:
                    ex = json.loads(line)
                    sid = ex.get("metadata", {}).get("situation_id")
                    if sid:
                        done_ids.add(sid)
                except Exception:
                    pass
    
    to_process = [
        s for s in situations
        if s.get("behavior_type", "other") not in SKIP_BEHAVIORS
        and s.get("id", "") not in done_ids
    ]
    
    if args.test:
        to_process = to_process[:5] # Max 5 for dry-run
    else:
        to_process = to_process[:MAX_SITUATIONS]

    print(f"К обработке: {len(to_process)} ситуаций")

    ok = errors = 0

    if not args.test:
        out_f = open(OUTPUT, "a", encoding="utf-8")
        err_f = open(ERRORS, "a", encoding="utf-8")

    try:
        for i, sit in enumerate(to_process):
            result = generate_one(sit, client, active, sys_prompt, judge_prompt, no_judge=args.no_judge)

            if result is None:
                errors += 1
                if not args.test:
                    err_f.write(json.dumps({"id": sit.get("id"), "reason": "parse_fail"}, ensure_ascii=False) + "\n")
            elif "error" in result:
                errors += 1
                if args.test:
                    print(f"[FAIL] {result['error']}")
                else:
                    err_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            else:
                ok += 1
                if args.test:
                    print(f"[OK] {sit.get('id')} - Pass rate 100%")
                else:
                    out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    out_f.flush()

            # Fail-Fast Deep Validation Check (Rule #5)
            total_attempts = ok + errors
            if total_attempts >= MIN_SAMPLES_FOR_FAIL_FAST:
                current_err_rate = errors / total_attempts
                if current_err_rate > ERROR_THRESHOLD_PCT:
                    print(f"\n[КРИТИЧЕСКАЯ ОШИБКА] Процент ошибок ({current_err_rate*100:.1f}%) превысил порог {ERROR_THRESHOLD_PCT*100}%.")
                    print("Срабатывание Fail-Fast. Остановка конвейера для предотвращения токсичности датасета.")
                    sys.exit(1)

            if not args.test and (i + 1) % 10 == 0:
                print(f"[{i+1}/{len(to_process)}] OK={ok} | Errors={errors}")

            time.sleep(REQUEST_DELAY)
    finally:
        if not args.test:
            out_f.close()
            err_f.close()

    print(f"\nГотово: {ok} примеров, {errors} ошибок.")
    if not args.test:
        print(f"Файл: {OUTPUT}")
    else:
        print(f"[DRY-RUN] Test execution completed. To generate real data, remove --test.")

if __name__ == "__main__":
    main()
