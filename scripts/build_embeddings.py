"""Сборщик векторного индекса корпуса — docs/data/embeddings.json.

Задача: качество подбора эпизода для «голоса Бога» (лексический retrieval
промахивается на абстракциях вроде «сотворение мира»). Эмбеддинги считаются
локально моделью intfloat/multilingual-e5-small (RU/EN/HE, 384 dim), складываются
в quantized-виде (int8 на вектор) и отдаются статикой; запрос посетителя
эмбеддится в браузере теми же весами (transformers.js, Xenova/multilingual-e5-small)
— корпусный режим остаётся полностью статичным.

    python scripts/build_embeddings.py            # полный прогон → docs/data/embeddings.json
    python scripts/build_embeddings.py --test     # самопроверка: размерность, норма, семантика

Порядок строк = порядку обхода страницы: book_order → книга → эпизоды по порядку.
Каждая строка несёт (book, span.start, span.end) для сверки на странице.

Источник эпизодов — МАСТЕР output/episodes_TANAKH_v2.json (словарь {книга: [эп]}),
тот же корпус, что опубликован в docs/data/books/*.json и на странице (2050 эпизодов
после дедупликации перекрытий). Файлы по книгам (2056) больше не читаются: они содержат
6 дублирующихся эпизодов, слитых dedup_overlaps.py, и строки для них не нужны.
"""
import base64, io, json, math, os, sys

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(_REPO, "docs", "data", "embeddings.json")
MASTER = os.path.join(_REPO, "output", "episodes_TANAKH_v2.json")
ANALYTICS = os.path.join(_REPO, "docs", "data", "analytics.json")
MODEL = "intfloat/multilingual-e5-small"
DIM = 384


def episode_text(e):
    """Только семантически плотное ядро: длинные склейки с речью/действием
    размывают mean-pooling — косинусы запроса слипаются в полосу (аудит 2026-10-21)."""
    return ("passage: " + e.get("trigger", "") + " | " + e.get("summary_ru", ""))[:280].strip()


def rows_in_order():
    """[(book, episode)] в том же порядке, что и everyBook() на странице:
    book_order из analytics.json → книга → эпизоды мастер-корпуса по порядку."""
    a = json.load(io.open(ANALYTICS, encoding="utf-8"))
    master = json.load(io.open(MASTER, encoding="utf-8"))
    order = [book for era in a["book_order"].values() for book in era]
    missing = [b for b in master if b not in order]
    if missing:
        raise SystemExit("книги мастера отсутствуют в book_order: " + ", ".join(missing))
    out = []
    for book in order:
        for e in master.get(book, []):
            out.append((book, e))
    return out


def encode(model, tok, texts):
    import torch
    res = []
    with torch.no_grad():
        for i in range(0, len(texts), 64):
            batch = texts[i:i + 64]
            enc = tok(batch, padding=True, truncation=True, max_length=256, return_tensors="pt")
            out = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            mean = (out * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            res.append(mean)
    x = torch.cat(res)
    return x / x.norm(dim=1, keepdim=True).clamp(min=1e-9)  # L2-норма


def quantize_rows(x):
    """int8 на вектор: q = round(x/scale*127), scale=max|x|; b64-строки (знаковые байты,
    на странице читаются Int8Array — знак сохраняется)."""
    import struct
    rows = []
    for v in x.tolist():
        s = max(abs(t) for t in v) or 1.0
        q = struct.pack(f"<{len(v)}b", *[max(-127, min(127, round(t / s * 127))) for t in v])
        rows.append({"s": round(s, 5), "q": base64.b64encode(q).decode()})
    return rows


def main():
    selftest = "--test" in sys.argv
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL)
    model.eval()

    if selftest:
        texts = ["query: сотворение мира", "query: создал небо и землю и человека",
                 "query: царь Арама заболел"]
        x = encode(model, tok, texts)
        ok_dim = x.shape[1] == DIM
        ok_norm = all(abs(math.sqrt(sum(t * t for t in v)) - 1) < 1e-3 for v in x.tolist())
        cos = lambda a, b: sum(p * q for p, q in zip(a, b))
        good = cos(x[0], x[1]) > cos(x[0], x[2])
        print(("PASS" if ok_dim else "FAIL"), f"— dim {x.shape[1]}")
        print(("PASS" if ok_norm else "FAIL"), "— L2-норма единичная")
        print(("PASS" if good else "FAIL"), f"— семантика: creation-pair {cos(x[0], x[1]):.3f} > off-topic {cos(x[0], x[2]):.3f}")
        return 0 if (ok_dim and ok_norm and good) else 1

    rows_src = rows_in_order()
    print("эпизодов в порядке обхода:", len(rows_src))
    # страница ищет вектор по ключу book|span.start (map-indexed): дубль ключа
    # сделал бы одну строку недостижимой — проверяем до записи
    keys = [b + "|" + e["span"]["start"] for b, e in rows_src]
    if len(set(keys)) != len(keys):
        seen, dup = set(), []
        for k in keys:
            if k in seen:
                dup.append(k)
            seen.add(k)
        raise SystemExit("дубли ключей book|span.start: " + ", ".join(dup[:10]))
    x = encode(model, tok, [episode_text(e) for _, e in rows_src])
    meta = [{"b": b, "s1": e["span"]["start"], "s2": e["span"]["end"]} for b, e in rows_src]
    payload = {"model": MODEL, "dim": DIM, "meta": meta, "rows": quantize_rows(x)}
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"записано {OUT}: {len(payload['rows'])} строк, {os.path.getsize(OUT) // 1024} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
