"""Сборщик векторного индекса корпуса — docs/data/embeddings*.{json,bin}.

Задача: качество подбора эпизода для «голоса Бога» (лексический retrieval
промахивается на абстракциях вроде «сотворение мира»).

Два индекса, два назначения:

  1) intfloat/multilingual-e5-small (384 dim) — БРАУЗЕРНЫЙ путь. Страница грузит
     Xenova/multilingual-e5-small (int8-WASM, 118 МБ) и считает вектор запроса
     сама; индекс лежит в docs/data/embeddings.json (base64 int8). Это запасной
     путь: работает без сервера, но посетитель тянет модель.

  2) nvidia/nemotron-3-embed-1b (2048 dim) — СЕРВЕРНЫЙ путь. Вектор запроса
     считает сервис на своём сервере (NVIDIA NIM, ключ только там), страница
     спрашивает у него один вектор. Индекс — docs/data/embeddings_nemotron.bin
     (int8, 2050×2048 = 4.0 МБ) + docs/data/embeddings_nemotron.json (ключи и
     масштабы). Модель посетителю качать не нужно.

Порядок строк = порядку обхода страницы: book_order → книга → эпизоды по порядку.
Каждая строка несёт (book, span.start, span.end) для сверки на странице.

Источник эпизодов — МАСТЕР output/episodes_TANAKH_v2.json (словарь {книга: [эп]}),
тот же корпус, что опубликован в docs/data/books/*.json и на странице (2050 эпизодов
после дедупликации перекрытий). Файлы по книгам (2056) больше не читаются: они содержат
6 дублирующихся эпизодов, слитых dedup_overlaps.py, и строки для них не нужны.

    python scripts/build_embeddings.py                    # e5-small → docs/data/embeddings.json
    python scripts/build_embeddings.py --model nemotron   # Nemotron → .bin + .json
    python scripts/build_embeddings.py --test             # самопроверка e5-small
"""
import base64, io, json, math, os, struct, sys, time

_REPO = str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(_REPO, "docs", "data", "embeddings.json")
OUT_BIN = os.environ.get("GOD_NEM_BIN") or os.path.join(
    _REPO, "docs", "data", "embeddings_nemotron.bin")
OUT_META = os.environ.get("GOD_NEM_META") or os.path.join(
    _REPO, "docs", "data", "embeddings_nemotron.json")
MASTER = os.path.join(_REPO, "output", "episodes_TANAKH_v2.json")
ANALYTICS = os.path.join(_REPO, "docs", "data", "analytics.json")
CACHE = os.path.join(_REPO, ".agent", "emb_cache")
MODEL = "intfloat/multilingual-e5-small"
DIM = 384
NIM_MODEL = os.environ.get("GOD_NIM_MODEL", "nvidia/nemotron-3-embed-1b")
NIM_DIM = 0          # размерность берём из ответа NIM (у разных моделей она разная)
NIM_URL = "https://integrate.api.nvidia.com/v1/embeddings"
# Инструкция запроса Nemotron (как в семействе nv-embed): должна совпадать с той,
# что применяет серверный сервис scripts/embed_service.py, — иначе вектор запроса
# и вектор пассажа окажутся в разных пространствах.
NIM_INSTRUCT = ("Instruct: Given a user question, retrieve passages from the Hebrew Bible "
                "that answer it\nQuery: ")


def episode_text(e, mode="A1", model=MODEL):
    """Текст пассажа для векторизации.

    mode A1 — прод: «trigger | summary_ru» (только семантически плотное ядро:
    длинные склейки с речью/действием размывают mean-pooling — косинусы запроса
    слипаются в полосу, аудит 2026-10-21);
    mode A5 — плюс действие и исход; mode A6 — плюс дословная речь Бога (иврит).

    Для e5 префикс «passage: » обязателен (разделяет запрос и документ),
    для Nemotron (nv-embed) — нет.
    """
    trig = e.get("trigger", "") or ""
    summ = e.get("summary_ru", "") or ""
    act = e.get("god_action", "") or ""
    out = str(e.get("outcome", "") or "")
    sp = e.get("god_speech_plain", "") or ""
    if mode == "A1":
        t = trig + " | " + summ
    elif mode == "A5":
        t = trig + " | " + summ + " | " + act + " | " + out
    elif mode == "A6":
        t = trig + " | " + summ + " | " + act + " | " + out + " | " + sp
    else:
        raise ValueError(mode)
    if model == MODEL:
        return ("passage: " + t)[:280].strip()
    return t[:900].strip()


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
    rows = []
    for v in x.tolist():
        s = max(abs(t) for t in v) or 1.0
        q = struct.pack(f"<{len(v)}b", *[max(-127, min(127, round(t / s * 127))) for t in v])
        rows.append({"s": round(s, 5), "q": base64.b64encode(q).decode()})
    return rows


# ── Nemotron через NVIDIA NIM ────────────────────────────────────────────────
def nim_tag(base):
    """Имя кэша: у каждой модели свой (иначе векторы разных моделей смешаются)."""
    if NIM_MODEL == "nvidia/nemotron-3-embed-1b":
        return base
    return base + "_" + NIM_MODEL.split("/")[-1]


def nim_key():
    p = os.path.join(_REPO, ".agent", "nvidia_keys")
    with io.open(p, encoding="utf-8") as f:
        return f.read().split("\n")[0].strip()


def nim_embed(texts, input_type, tag, instruction=""):
    """Векторы NIM с кэшем на диске. Отсюда — только через локальный Xray SOCKS5:
    прямой доступ к integrate.api.nvidia.com с этой машины закрыт гео-блокировкой."""
    import subprocess
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, tag + ".json")
    if os.path.exists(path):
        return json.load(io.open(path, encoding="utf-8"))
    key = nim_key()
    vecs = []
    B = 32
    body_path = os.path.join(CACHE, "_body.json")
    for start in range(0, len(texts), B):
        chunk = texts[start:start + B]
        if input_type == "query":
            chunk = [instruction + t for t in chunk]
        body = json.dumps({"model": NIM_MODEL, "input": chunk, "input_type": input_type,
                           "encoding_format": "float", "truncate": "NONE"})
        with io.open(body_path, "w", encoding="utf-8") as f:
            f.write(body)
        got = None
        for attempt in range(4):
            proc = subprocess.run(
                ["curl", "-s", "--max-time", "180", "--socks5-hostname", "127.0.0.1:10808",
                 "-X", "POST", NIM_URL, "-H", "Authorization: Bearer " + key,
                 "-H", "Content-Type: application/json", "--data-binary", "@" + body_path],
                capture_output=True, text=True)
            try:
                d = json.loads(proc.stdout)
            except Exception:
                d = None
            if d and "data" in d:
                got = [x["embedding"] for x in d["data"]]
                break
            print("   retry %d: %s" % (attempt + 1, (proc.stdout or proc.stderr)[:160]), flush=True)
            time.sleep(4)
        if got is None:
            raise SystemExit("NIM не ответил (батч %d)" % start)
        vecs.extend(got)
        if start % 320 == 0:
            print("   %d/%d" % (start + len(chunk), len(texts)), flush=True)
    json.dump(vecs, io.open(path, "w", encoding="utf-8"))
    return vecs


def build_nemotron(rows_src, mode="A1"):
    """Индекс Nemotron: .bin (int8) + .json (мета). Тот же текст пассажа, что
    замеряли: A1 — trigger | summary_ru, без префикса «passage: »."""
    texts = [episode_text(e, mode, NIM_MODEL) for _, e in rows_src]
    vecs = nim_embed(texts, "passage", nim_tag("nemotron_%s_corpus" % mode))
    if len(vecs) != len(rows_src):
        raise SystemExit("размер корпуса не совпал: %d против %d" % (len(vecs), len(rows_src)))
    keys = ["%s|%s" % (b, e["span"]["start"]) for b, e in rows_src]
    if len(set(keys)) != len(keys):
        raise SystemExit("дубли ключей book|span.start")
    dim = len(vecs[0]) if vecs else 0
    blob = bytearray()
    scales = []
    for v in vecs:
        s = max(abs(x) for x in v) or 1.0
        scales.append(round(s, 6))
        for x in v:
            q = max(-127, min(127, round(x / s * 127)))
            blob.append(q & 0xFF)          # знаковый int8: байт 0x80..0xFF = −128..−1
    with open(OUT_BIN, "wb") as f:
        f.write(bytes(blob))
    meta = {"model": NIM_MODEL, "dim": dim, "n": len(keys), "mode": mode,
            "format": "int8-rowwise", "keys": keys, "scales": scales,
            "built": time.strftime("%Y-%m-%d")}
    with io.open(OUT_META, "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    print("записано %s: %d строк × %d (%.1f МБ) + мета %d КБ"
          % (OUT_BIN, len(keys), dim, os.path.getsize(OUT_BIN) / 1048576.0,
             os.path.getsize(OUT_META) // 1024))
    return meta


def main():
    selftest = "--test" in sys.argv
    model = "e5-small"
    if "--model" in sys.argv:
        model = sys.argv[sys.argv.index("--model") + 1]
    mode = "A1"
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]

    rows_src = rows_in_order()
    print("эпизодов в порядке обхода:", len(rows_src))
    keys = ["%s|%s" % (b, e["span"]["start"]) for b, e in rows_src]
    if len(set(keys)) != len(keys):
        seen, dup = set(), []
        for k in keys:
            if k in seen:
                dup.append(k)
            seen.add(k)
        raise SystemExit("дубли ключей book|span.start: " + ", ".join(dup[:10]))

    if model == "nemotron":
        build_nemotron(rows_src, mode)
        return 0

    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL)
    mdl = AutoModel.from_pretrained(MODEL)
    mdl.eval()

    if selftest:
        texts = ["query: сотворение мира", "query: создал небо и землю и человека",
                 "query: царь Арама заболел"]
        x = encode(mdl, tok, texts)
        ok_dim = x.shape[1] == DIM
        ok_norm = all(abs(math.sqrt(sum(t * t for t in v)) - 1) < 1e-3 for v in x.tolist())
        cos = lambda a, b: sum(p * q for p, q in zip(a, b))
        good = cos(x[0], x[1]) > cos(x[0], x[2])
        print(("PASS" if ok_dim else "FAIL"), f"— dim {x.shape[1]}")
        print(("PASS" if ok_norm else "FAIL"), "— L2-норма единичная")
        print(("PASS" if good else "FAIL"), f"— семантика: creation-pair {cos(x[0], x[1]):.3f} > off-topic {cos(x[0], x[2]):.3f}")
        return 0 if (ok_dim and ok_norm and good) else 1

    x = encode(mdl, tok, [episode_text(e, mode, MODEL) for _, e in rows_src])
    meta_rows = [{"b": b, "s1": e["span"]["start"], "s2": e["span"]["end"]} for b, e in rows_src]
    payload = {"model": MODEL, "dim": DIM, "meta": meta_rows, "rows": quantize_rows(x)}
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"записано {OUT}: {len(payload['rows'])} строк, {os.path.getsize(OUT) // 1024} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
