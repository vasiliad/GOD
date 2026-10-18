"""
Глубокий аудит качества god_vocabulary.json — смысловая проверка
"""
import json, re, sys
from pathlib import Path
from collections import Counter
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT = Path(_REPO + "/output")

with open(OUTPUT / "god_vocabulary.json", encoding="utf-8") as f:
    vocab = json.load(f)

with open(OUTPUT / "situations_registry.json", encoding="utf-8") as f:
    situations = json.load(f)

def strip_diacritics(text):
    return re.sub(r'[\u0591-\u05C7\u05F3\u05F4]', '', text)

god_texts = [s["text_he"] for s in situations if s.get("who_initiated") == "God" and s.get("text_he")]
god_stripped = [strip_diacritics(t) for t in god_texts]

print("=" * 60)
print("БЛОК 1: ТОПОВЫЕ ТОКЕНЫ — что реально считается")
print("=" * 60)

top_words = vocab["top_50_words"]
print(f"\nТОП-30 слов по частоте:")
hebrew_letters = re.compile(r'^[\u05D0-\u05EA\u05BE]+$')
only_diacritic = re.compile(r'^[\u0591-\u05C7\u05F0-\u05F4]+$')
maqaf = '\u05BE'

letter_tokens = []
punct_diacrit = []
maqaf_tokens = []

for w, c in top_words:
    stripped = strip_diacritics(w)
    if stripped == maqaf or stripped == '':
        maqaf_tokens.append((w, c))
    elif only_diacritic.match(w):
        punct_diacrit.append((w, c))
    elif re.search(r'[\u05D0-\u05EA]', stripped):
        letter_tokens.append((w, c, stripped))

print(f"\n  Полноценные ивритские лексемы (топ-20):")
for w, c, s in letter_tokens[:20]:
    print(f"    {s:15} freq={c:4}")

print(f"\n  Мусорные токены (maqaf, диакритики отдельно):")
print(f"    maqaf U+05BE:    {sum(c for w,c in maqaf_tokens)} вхождений (Stanza токенизировал дефис-разделитель)")
print(f"    чистые диакрит.:  {sum(c for w,c in punct_diacrit)} вхождений")

print(f"\n  Итого слов-лексем из топ-50: {len(letter_tokens)}/50")
noise_ratio = (len(maqaf_tokens) + len(punct_diacrit)) / 50
print(f"  Доля шума в топ-50: {noise_ratio*100:.0f}%")

print("\n" + "=" * 60)
print("БЛОК 2: POS-РАСПРЕДЕЛЕНИЕ — лингвистический смысл")
print("=" * 60)

pos = vocab["pos_distribution"]
total_pos = sum(pos.values())
print(f"\n  Всего токенов с POS: {total_pos}")
print(f"  {'POS':<10} {'Count':>6} {'%':>6}  {'Оценка'}")
print(f"  {'-'*45}")
expected_hebrew = {
    'NOUN': ('30-40%', 28, 45),
    'VERB': ('15-25%', 15, 28),
    'ADP':  ('15-20%', 10, 22),
    'CCONJ':('5-10%', 4, 12),
    'DET':  ('3-7%', 2, 9),
    'PRON': ('2-5%', 1, 6),
    'PUNCT':('любое', 0, 99),
}
for tag, count in sorted(pos.items(), key=lambda x: -x[1]):
    pct = count / total_pos * 100
    exp = expected_hebrew.get(tag)
    if exp:
        lo, hi = exp[1], exp[2]
        status = "OK" if lo <= pct <= hi else f"ВЫХОД ({exp[0]})"
    else:
        status = ""
    print(f"  {tag:<10} {count:>6} {pct:>5.1f}%  {status}")

print("\n" + "=" * 60)
print("БЛОК 3: DIVINE CONSTRUCTIONS — реальные числа")
print("=" * 60)

dc = vocab["divine_constructions"]
for name, data in dc.items():
    safe = name.encode('ascii', 'replace').decode()
    pat_safe = data['pattern'].encode('ascii', 'replace').decode()
    cnt = data['count']
    pct = cnt / len(god_texts) * 100
    print(f"  {safe:40} count={cnt:4} ({pct:.1f}% текстов)")

print("\n" + "=" * 60)
print("БЛОК 4: THEOLOGICAL WORDS — реальные частоты")
print("=" * 60)

divine_words = vocab["divine_characteristic_words"]
print(f"\n  {'Word':20} {'Translit':12} {'Freq':>6}  {'Оценка'}")
print(f"  {'-'*55}")
for w in divine_words:
    freq = w.get("frequency", 0)
    word_safe = w["word"].encode('ascii', 'replace').decode()
    translit = w["transliteration"]
    expected = {
        "Ehyeh": (0, 5, "редко — только Исх.3:14"),
        "Kadosh": (0, 20, "встречается в Ис, Лев"),
        "Kavod": (0, 15, "Ис, Иез"),
        "Hesed": (0, 20, "очень частое слово"),
        "Emet": (0, 10, "умеренное"),
        "Tzedakah": (0, 15, "пр. тексты"),
        "Shalom": (0, 15, "частое"),
        "Shekhinah": (0, 2, "позднее слово, редко/нет"),
    }.get(translit, (0, 999, ""))
    lo, hi, note = expected
    status = "OK" if lo <= freq <= hi else f"ВЫХОД ({expected[2]})"
    if freq == 0:
        status = "⚠ 0 — требует проверки"
    print(f"  {word_safe:20} {translit:12} {freq:>6}  {status}  {note}")

print("\n" + "=" * 60)
print("БЛОК 5: ПОКРЫТИЕ — сколько Танаха реально обработано")
print("=" * 60)

total_in_registry = len(situations)
god_initiated = len(god_texts)
texts_analyzed_nlp = min(500, god_initiated)
pct_nlp = texts_analyzed_nlp / god_initiated * 100

print(f"  Всего ситуаций в реестре: {total_in_registry}")
print(f"  God-initiated: {god_initiated}")
print(f"  Отдано в NLP Stanza: {texts_analyzed_nlp} ({pct_nlp:.0f}%)")

if pct_nlp < 100:
    print(f"  ⚠ NLP покрыл только {pct_nlp:.0f}% текстов (лимит 500 в скрипте)")
    print(f"    Это {god_initiated - texts_analyzed_nlp} текстов БЕЗ морфологии")
else:
    print("  ✓ NLP покрыл 100% текстов")

print("\n" + "=" * 60)
print("ИТОГ")
print("=" * 60)

issues = []
if noise_ratio > 0.1:
    issues.append(f"Maqaf (U+05BE) попал в топ как самый частый токен ({maqaf_tokens[0][1] if maqaf_tokens else 0}x) — это артефакт токенизации")
if pct_nlp < 80:
    issues.append(f"NLP покрыл только {pct_nlp:.0f}% текстов — топ-слова неполные")
zero_freq = [w["transliteration"] for w in divine_words if w.get("frequency", 0) == 0]
if zero_freq:
    issues.append(f"Theological words с frequency=0: {zero_freq}")

print(f"\n⚠ Найдено проблем: {len(issues)}")
for i in issues:
    print(f"  - {i}")

score = 10 - len(issues)
print(f"\nОценка: {score}/10")
