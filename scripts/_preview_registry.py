from pathlib import Path
import json, sys, io
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

data = json.load(open(_REPO + '/output/situations_registry.json', encoding='utf-8'))

print(f"Всего ситуаций: {len(data)}\n")
print(f"{'ID':<8} {'Ref':<20} {'Категория':<14} {'Кто':<8} {'Имена Бога':<30} {'Эмоции':<20} Текст")
print("-" * 130)

for s in data[:30]:
    names   = ", ".join(s['god_names'][:3])
    emotions = ", ".join(s['emotions']) if s['emotions'] else "-"
    text     = s['text_plain'][:60].replace("\n", " ") if s['text_plain'] else s['text_he'][:60]
    print(f"{s['id']:<8} {s['ref']:<20} {s['category']:<14} {s['who_initiated']:<8} {names:<30} {emotions:<20} {text}")
