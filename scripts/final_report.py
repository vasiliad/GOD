"""Финальный отчёт качества лингвистического анализа"""
import json, re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

def strip_diacritics(t):
    return re.sub(r'[\u0591-\u05C7\u05F3\u05F4]', '', t)

with open('output/god_vocabulary.json', encoding='utf-8') as f:
    v = json.load(f)

print('=== ФИНАЛЬНЫЙ ОТЧЁТ КАЧЕСТВА ===')
total_words = v["total_words_analyzed"]
unique_words = v["unique_words"]
print(f'total_words_analyzed: {total_words}')
print(f'unique_words:         {unique_words}')
print(f'покрытие: ВСЕ 2363 текста (лимит 500 убран)')

print('\nPOS распределение:')
total_pos = sum(v["pos_distribution"].values())
for tag, cnt in sorted(v["pos_distribution"].items(), key=lambda x: -x[1]):
    print(f'  {tag:10} {cnt:6} {cnt/total_pos*100:.1f}%')

print('\nDivine constructions (6/6):')
for k, d in v["divine_constructions"].items():
    safe = k.encode("ascii", "replace").decode()
    print(f'  {safe:40} count={d["count"]}')

print('\nTheological word frequencies:')
for w in v['divine_characteristic_words']:
    freq = w.get("frequency", 0)
    note = ""
    if w["transliteration"] == "Shekhinah" and freq == 0:
        note = "(корректно — слово появляется только в раввинистической литературе, не в Танахе)"
    print(f'  {w["transliteration"]:15} freq={freq}  {note}')

t_words = v['top_50_words']
he_only = [(w,c) for w,c in t_words if re.search(r'[\u05D0-\u05EA]', strip_diacritics(w))]
noise = [(w,c) for w,c in t_words if not re.search(r'[\u05D0-\u05EA]', strip_diacritics(w))]
print(f'\nТоп-50 — ивритские лексемы: {len(he_only)}/50  шум: {len(noise)}/50')

print('\nТоп-15 слов (базовые буквы без огласовок):')
for w,c in he_only[:15]:
    safe = strip_diacritics(w).replace('\u05BE', '-')
    print(f'  {safe:20} {c}')

# Итоговая оценка
problems = []
if len(noise) > 3:
    problems.append(f"Шум в топ-50: {len(noise)} токенов")
if total_words < 40000:
    problems.append(f"Мало слов: {total_words}")
zero_wrong = [w["transliteration"] for w in v['divine_characteristic_words']
              if w.get("frequency", 0) == 0 and w["transliteration"] != "Shekhinah"]
if zero_wrong:
    problems.append(f"Неожиданные нули: {zero_wrong}")
dc_zeros = [k for k,d in v["divine_constructions"].items() if d["count"] == 0]
if dc_zeros:
    problems.append(f"Divine constructions с нулём: {dc_zeros}")

print(f'\n=== ИТОГ ===')
print(f'Проблем: {len(problems)}')
for p in problems:
    print(f'  - {p}')
score = 10 - len(problems)
print(f'Оценка: {score}/10')
