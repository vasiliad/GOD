import json
from collections import Counter

with open(r'C:\GOD2\output\contacts_registry.json', encoding='utf-8') as f:
    data = json.load(f)

print(f'Всего контактов: {len(data)}')
print()

# Сильные глаголы — явное взаимодействие (Бог говорит/является/повелевает)
strong = ['ויאמר', 'וידבר', 'ויקרא', 'וירא', 'ויצו', 'ויצוהו']
# Слабые  — часто встречаются в любом тексте (иди, делай, сказал вообще)
weak   = ['לך', 'עשה', 'אמר', 'דבר', 'צוה', 'שמע', 'קום']

with_strong = [c for c in data if any(kw in c['interaction_keywords'] for kw in strong)]
weak_only   = [c for c in data if not any(kw in c['interaction_keywords'] for kw in strong)]

print(f'Сильный глагол (явное взаимодействие): {len(with_strong)} ({len(with_strong)*100//len(data)}%)')
print(f'Только слабые глаголы (возм. шум):     {len(weak_only)} ({len(weak_only)*100//len(data)}%)')
print()

# Самые частые keyword-комбинации
kw_counter = Counter()
for c in data:
    kws = tuple(sorted(c['interaction_keywords']))
    kw_counter[kws] += 1

print('Топ-10 комбинаций interaction_keywords:')
for combo, cnt in kw_counter.most_common(10):
    print(f'  {cnt:4d}  {list(combo)}')

print()

# Книги
books_count = Counter(c['book'] for c in data)
print('Топ-10 книг:')
for book, count in books_count.most_common(10):
    print(f'  {book:<25}: {count}')

# Примеры из "слабых" — шум?
print()
print('5 примеров из "только слабые глаголы" (возможный шум):')
for c in weak_only[:5]:
    print(f'  [{c["book"]} {c["chapter"]}:{c["verse"]}] kw={c["interaction_keywords"]} | {c["text_plain"][:80]}')
