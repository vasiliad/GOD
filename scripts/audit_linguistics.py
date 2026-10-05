"""
Аудит качества лингвистического анализа:
- Проверяем god_vocabulary.json и speech_patterns.json
- Проверяем реальный контент text_he в реестре
- Проверяем совпадение точечных паттернов с данными
"""
import sys, json, re
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
from pathlib import Path
from collections import Counter

OUTPUT = Path("C:/GOD2/output")

print("=" * 60)
print("АУДИТ КАЧЕСТВА: linguistics-001")
print("=" * 60)

# --- 1. Проверка god_vocabulary.json ---
with open(OUTPUT / "god_vocabulary.json", encoding="utf-8") as f:
    vocab = json.load(f)

print("\n[1] god_vocabulary.json")
print(f"  total_words_analyzed : {vocab['total_words_analyzed']}")
print(f"  unique_words         : {vocab['unique_words']}")

pos = vocab["pos_distribution"]
total_pos = sum(pos.values())
print(f"\n  POS distribution (итого токенов: {total_pos}):")
for tag, cnt in sorted(pos.items(), key=lambda x: -x[1]):
    print(f"    {tag:8} {cnt:6}  ({cnt/total_pos*100:.1f}%)")

print(f"\n  Топ-10 слов:")
for w, c in vocab["top_50_words"][:10]:
    he_ratio = len(re.findall(r'[\u0590-\u05FF]', w)) / max(len(w), 1)
    flag = "OK" if he_ratio > 0.5 else "WARN: не-иврит"
    print(f"    [{w}]{'':5} cnt={c:4}  {flag}")

print(f"\n  Divine constructions counts:")
for name, data in vocab["divine_constructions"].items():
    count = data["count"]
    flag = "✓" if count > 0 else "⚠ нуль — паттерн не совпал с данными"
    print(f"    {name}: {count}  {flag}")

print(f"\n  Теологические слова (частотность в тексте):")
for w in vocab["divine_characteristic_words"]:
    freq = w.get("frequency", 0)
    flag = "✓" if freq > 0 else "⚠ freq=0 — слово не найдено точно"
    print(f"    {w['transliteration']:15} freq={freq}  {flag}")

# --- 2. Проверка speech_patterns.json ---
with open(OUTPUT / "speech_patterns.json", encoding="utf-8") as f:
    patterns = json.load(f)

print("\n[2] speech_patterns.json")
print(f"  style: {patterns['style']}")
print(f"  sentence_types: {list(patterns['sentence_types'].keys())}")
print(f"  rhetorical_devices: {len(patterns['rhetorical_devices'])} шт.")
verbs = sum(len(v) for v in patterns["characteristic_verbs"].values())
print(f"  characteristic_verbs: {verbs} глаголов")
print(f"  unique_self_references: {len(patterns['unique_self_references'])} шт.")

# --- 3. Проверка данных реестра (что реально в text_he) ---
with open(OUTPUT / "situations_registry.json", encoding="utf-8") as f:
    situations = json.load(f)

god_texts = [s for s in situations if s.get("who_initiated") == "God" and s.get("text_he")]
print(f"\n[3] situations_registry.json")
print(f"  Всего ситуаций: {len(situations)}")
print(f"  God-initiated с text_he: {len(god_texts)}")

# Проверяем качество text_he — доля ивритских символов
ratios = []
empty_he = 0
for s in god_texts:
    t = s["text_he"]
    if not t.strip():
        empty_he += 1
        continue
    he = len(re.findall(r'[\u0590-\u05FF]', t))
    total = len(t.replace(" ", ""))
    ratio = he / max(total, 1)
    ratios.append(ratio)

avg_ratio = sum(ratios) / max(len(ratios), 1)
good = sum(1 for r in ratios if r > 0.5)
empty_ratio = sum(1 for r in ratios if r == 0)

print(f"  Пустых text_he: {empty_he}")
print(f"  Средняя доля ивритских символов: {avg_ratio*100:.1f}%")
print(f"  Текстов с >50% иврит: {good}/{len(ratios)}")
print(f"  Текстов с 0% иврит (чисто пунктуация/цифры): {empty_ratio}")

print("\n  Примеры text_he (первые 5):")
for s in god_texts[:5]:
    t = s["text_he"]
    ref = s.get("reference", "?")
    he_cnt = len(re.findall(r'[\u0590-\u05FF]', t))
    print(f"    [{ref}] ({he_cnt} ивр. симв.) {t[:60]!r}")

# --- 4. Итоговый диагноз ---
print("\n" + "=" * 60)
print("ДИАГНОЗ:")
issues = []
if avg_ratio < 0.5:
    issues.append(f"CRITICAL: text_he содержит мало иврита ({avg_ratio*100:.0f}%) — возможно, данные без огласовок/нипреемственности")
if sum(1 for _, d in vocab["divine_constructions"].items() if d["count"] == 0) >= 4:
    issues.append("WARNING: Большинство divine_constructions = 0 — паттерны с никудой не совпадают с текстами без никуды")
if sum(1 for w in vocab["divine_characteristic_words"] if w.get("frequency", 0) == 0) >= 5:
    issues.append("WARNING: Теологические слова freq=0 — поиск точного совпадения с огласовками не работает")

if not issues:
    print("  ✅ Всё в норме, качество достаточное")
for issue in issues:
    print(f"  ⚠ {issue}")

print("=" * 60)
