from pathlib import Path
﻿import json
_REPO = str(Path(__file__).resolve().parents[1])  # корень репозитория, без машинных путей

paths = {
    'ext': _REPO + '/output/situations_extracted.json',
    'coded': _REPO + '/output/situations_coded.json'
}

with open(paths['ext'], 'r', encoding='utf-8') as f:
    extracted = json.load(f)

# Создаём маппинг по id и по составному ключу
speech_map = {}
for item in extracted:
    sp = item.get('god_speech')
    if sp:
        speech_map[item.get('id')] = sp
        key = f"{item.get('book')}_{item.get('chapter')}_{item.get('verse')}"
        speech_map[key] = sp

with open(paths['coded'], 'r', encoding='utf-8') as f:
    coded = json.load(f)

updated = 0
for sit in coded:
    sid = sit.get('id')
    b = sit.get('book')
    c = sit.get('chapter')
    v = sit.get('verse', sit.get('verse_start'))
    comp_key = f"{b}_{c}_{v}"
    
    match = speech_map.get(sid) or speech_map.get(comp_key)
    if match:
        # Поскольку ранее поле было типом [], положим туда строку массива.
        # В python type [] может значить список реплик
        sit['god_speech'] = [match]
        updated += 1
    else:
        # Для тех где речи нет, гарантируем пустой список
        sit['god_speech'] = []

with open(paths['coded'], 'w', encoding='utf-8') as f:
    json.dump(coded, f, ensure_ascii=False, indent=2)

print(f"Успешно восстановлено: {updated} случаев прямой речи Бога.")
