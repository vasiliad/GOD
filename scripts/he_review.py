"""DictaLM (носитель иврита) просматривает все HE-строки интерфейса на естественность.

Модель видит каждую строку БЕЗ контекста проекта — только текст UI и просьбу
оценить как носитель. Ненатуральные формулировки помечаются к исправлению.
"""
import io, json, os, sys, time, urllib.request

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRAIN = json.load(io.open(os.path.join(_REPO, "brain", "brain_snapshot.json"), encoding="utf-8"))
URL = BRAIN["url"] + "/v1/chat/completions"
KEY = BRAIN.get("key", "")

REVIEW_PROMPT = """You are a native Hebrew speaker reviewing UI text for a website.
Rate each Hebrew text string for naturalness and correctness on a scale of 1-10.
A 10 means it reads like it was written by a native speaker for a real website.
A 5 means it's grammatically correct but sounds like a translation.
A 1-3 means it has errors or sounds very unnatural.
Reply ONLY with the number (1-10). No explanation."""


def ask(text):
    body = json.dumps({"messages": [
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": text}
    ], "max_tokens": 10, "temperature": 0.1}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.loads(r.read())
    return j["choices"][0]["message"]["content"].strip()


def main():
    # извлечь все HE-строки из index.html
    import re
    s = io.open(os.path.join(_REPO, "docs", "index.html"), encoding="utf-8").read()
    m = re.search(r'he:\{(.*?)\n\}\};', s, re.DOTALL)
    if not m:
        print("HE-словарь не найден")
        return 1
    he_block = m.group(1)
    # распарсить ключи и значения
    pairs = re.findall(r'(\w+):\s*"([^"]*)"', he_block)
    if not pairs:
        print("строки не найдены")
        return 1

    print(f"DictaLM просматривает {len(pairs)} ивритских UI-строк...\n")
    flagged, total, count = [], 0, 0
    for key, text in pairs:
        if not text.strip() or len(text) < 3:
            continue
        count += 1
        try:
            r = ask(f'UI text: "{text}"')
            score = int(r.strip())
            total += score
            mark = "OK " if score >= 8 else "!!!" if score < 6 else "  ~"
            print(f"  {mark} [{score:2d}/10] {key}: {text[:60]}")
            if score < 8:
                flagged.append((key, text, score))
        except Exception as e:
            print(f"  ERR {key}: {e}")
        time.sleep(0.3)

    print(f"\n=== ИТОГ: средняя оценка {total/count:.1f}/10 по {count} строкам ===")
    if flagged:
        print(f"\nНиже 8/10 — {len(flagged)} строк (к исправлению):")
        for key, text, score in flagged:
            print(f"  [{score}] {key}: {text}")
    else:
        print("Все строки ≥8/10 — иврит интерфейса естественный.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
