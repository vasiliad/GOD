#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ВЕКТОРНЫЙ ПУТЬ ПРОДА: какое меню из шести эпизодов получится, когда лексика молчит.

Зачем этот скрипт. Страница показывает посетителю меню из шести эпизодов; меню
собирает scripts/answer_scheme.py — зеркало страницы, тем же кодом, что и
docs/index.html. Вектор подключается ТОЛЬКО когда лексика не нашла ни одного
слова, и тогда он — единственный тематический сигнал. Значит честный вопрос не
«какая модель лучше ранжирует корпус вообще», а «что покажут шесть карточек,
когда лексика выключена, а решает вектор».

Метрика (золотой эталон scripts/topic_gold.json, 14 вопросов):
  меню-6   — ожидаемое место Танаха попало в шесть показанных эпизодов;
  пул-18   — попало в 18 кандидатов (из них мозг выбирает один);
  ядро-6   — попало именно «сердце» места (core);
  MRR      — средняя обратная ранга позиция попадания.
Плюс «спасательные» вопросы из scripts/page_menus.json: там эталон — меню живой
страницы, меряем пересечение (сколько из шести показанных ею эпизодов нашёл вектор).

Кандидаты:
  e5-small   — текущий прод: int8-ONNX Xenova/multilingual-e5-small (тот же граф,
               что грузит браузер), запрос эмбеддится тем же ONNX;
  e5-large   — intfloat/multilingual-e5-large, torch fp32 (серверный вариант);
  nemotron   — nvidia/nemotron-3-embed-1b через NVIDIA NIM (серверный вариант,
               ключ только на сервере; здесь — для замера);
  bge-m3     — BAAI/bge-m3, torch fp32 (запасной кандидат).

Текст пассажа (--mode) — это ТОЖЕ часть модели, а не украшение:
  A1 — прод сейчас: «passage: trigger | summary_ru»;
  A5 — «trigger | summary_ru | god_action | outcome»;
  A6 — A5 + дословная речь Бога (иврит).

Запуск:
    python scripts/eval_vector.py --model e5-small --mode A1
    python scripts/eval_vector.py --model nemotron --mode A5 --lang en
    python scripts/eval_vector.py --model e5-small --mode A5 --json .agent/vec_a5.json
"""
import argparse
import base64
import io
import json
import math
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import answer_scheme as A   # noqa: E402

GOLD = _ROOT / "scripts" / "topic_gold.json"
MENUS = _ROOT / "scripts" / "page_menus.json"
PARAPHRASES = _ROOT / "scripts" / "vector_paraphrases.json"
CACHE = _ROOT / ".agent" / "emb_cache"

# Инструкция для Nemotron: как в семействе nv-embed, запрос требует инструкции.
NEM_INSTR = ("Instruct: Given a user question, retrieve passages from the Hebrew Bible "
             "that answer it\nQuery: ")
NIM_URL = "https://integrate.api.nvidia.com/v1/embeddings"
NIM_MODEL = os.environ.get("GOD_NIM_MODEL", "nvidia/nemotron-3-embed-1b")
NIM_SLUG = NIM_MODEL.split("/")[-1]


def nim_tag(base):
    """Имя кэша: у каждой модели свой (иначе векторы разных моделей смешаются)."""
    if NIM_MODEL == "nvidia/nemotron-3-embed-1b":
        return base
    return base + "_" + NIM_SLUG

EN_Q = {
    "как тебя зовут?": "What is your name?",
    "почему ты допустил зло в мире?": "Why did you allow evil in the world?",
    "что такое завет с тобой?": "What is the covenant with you?",
    "благодарю тебя за всё": "I thank you for everything",
    "почему праведники страдают?": "Why do the righteous suffer?",
    "хочу узнать твою волю": "I want to know your will",
    "я боюсь умереть": "I am afraid to die",
    "сотворение мира": "the creation of the world",
    "прости мне мой грех": "forgive me my sin",
    "сохрани меня от врагов": "save me from my enemies",
    "дай мне силы идти дальше": "give me strength to go on",
    "утешь меня в скорби": "comfort me in my sorrow",
    "научи меня твоему пути": "teach me your way",
    "покажи мне путь к тебе": "show me the way to you",
}


# ── текст пассажа ────────────────────────────────────────────────────────────
def passage_text(e, mode, model):
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
    t = t.strip()
    # e5 требует префикс «passage: » для документов; nv-embed/nemotron — нет.
    if model == "e5-small":
        t = ("passage: " + t)[:280].strip()
    else:
        t = t[:900].strip()
    return t


# ── векторизаторы ───────────────────────────────────────────────────────────
def _cache_path(tag):
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / (tag + ".json")


def corpus_e5_small(episodes, mode):
    """Тот же int8-ONNX, что грузит браузер (Xenova/multilingual-e5-small)."""
    p = _cache_path("e5small_%s_corpus" % mode)
    if p.exists():
        return json.load(io.open(p, encoding="utf-8"))
    import numpy as np
    import browser_embedder as be
    tok = be._tokenizer()
    sess = be._session()
    texts = [passage_text(e, mode, "e5-small") for e in episodes.values()]
    out = []
    t0 = time.time()
    for i in range(0, len(texts), 32):
        batch = texts[i:i + 32]
        enc = tok(batch, padding=True, truncation=True, max_length=192, return_tensors="np")
        feed = {"input_ids": enc["input_ids"].astype(np.int64),
                "attention_mask": enc["attention_mask"].astype(np.int64)}
        if "token_type_ids" in enc:
            feed["token_type_ids"] = enc["token_type_ids"].astype(np.int64)
        else:
            feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
        h = sess.run(["last_hidden_state"], feed)[0]
        mask = feed["attention_mask"][..., None].astype(np.float32)
        v = (h * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
        v = v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)
        out.extend([row.tolist() for row in v])
        if i % 320 == 0:
            print("   %d/%d (%.0f с)" % (i + len(batch), len(texts), time.time() - t0), flush=True)
    json.dump(out, io.open(p, "w", encoding="utf-8"))
    return out


def corpus_torch(episodes, mode, hf_model, tag):
    """Локальная torch-модель (e5-large / bge-m3): mean pooling + L2."""
    p = _cache_path(tag)
    if p.exists():
        return json.load(io.open(p, encoding="utf-8"))
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(max(4, os.cpu_count() or 8))
    tok = AutoTokenizer.from_pretrained(hf_model)
    mdl = AutoModel.from_pretrained(hf_model)
    mdl.eval()
    texts = [passage_text(e, mode, "torch") for e in episodes.values()]
    out = []
    t0 = time.time()
    with torch.no_grad():
        for i in range(0, len(texts), 16):
            b = texts[i:i + 16]
            enc = tok(b, padding=True, truncation=True, max_length=256, return_tensors="pt")
            h = mdl(**enc).last_hidden_state
            m = enc["attention_mask"].unsqueeze(-1).float()
            v = (h * m).sum(1) / m.sum(1).clamp(min=1e-9)
            out.extend((v / v.norm(dim=1, keepdim=True).clamp(min=1e-9)).tolist())
            if i % 320 == 0:
                print("   %d/%d (%.0f с)" % (i + len(b), len(texts), time.time() - t0), flush=True)
    json.dump(out, io.open(p, "w", encoding="utf-8"))
    del mdl
    return out


def nim_corpus(episodes, mode, tag):
    """Корпус через NVIDIA NIM (с этой машины — через локальный Xray SOCKS5)."""
    p = _cache_path(tag)
    if p.exists():
        return json.load(io.open(p, encoding="utf-8"))
    texts = [passage_text(e, mode, "nemotron") for e in episodes.values()]
    return nim_call(texts, "passage", tag)


def nim_call(texts, input_type, tag, instruction=""):
    p = _cache_path(tag)
    if p.exists():
        return json.load(io.open(p, encoding="utf-8"))
    key = os.path.join(str(_ROOT), ".agent", "nvidia_keys")
    KEY = io.open(key, encoding="utf-8").read().split("\n")[0].strip()
    vecs = []
    B = 32
    for start in range(0, len(texts), B):
        chunk = [(instruction + t) if input_type == "query" else t for t in texts[start:start + B]]
        body = json.dumps({"model": NIM_MODEL, "input": chunk, "input_type": input_type,
                           "encoding_format": "float", "truncate": "NONE"})
        bf = str(CACHE / "_body.json")
        io.open(bf, "w", encoding="utf-8").write(body)
        got = None
        for attempt in range(4):
            proc = subprocess.run(
                ["curl", "-s", "--max-time", "180", "--socks5-hostname", "127.0.0.1:10808",
                 "-X", "POST", NIM_URL, "-H", "Authorization: Bearer " + KEY,
                 "-H", "Content-Type: application/json", "--data-binary", "@" + bf],
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
            raise SystemExit("NIM не ответил: " + NIM_MODEL + " (батч %d)" % start)
        vecs.extend(got)
        if start % 320 == 0:
            print("   %d/%d" % (start + len(chunk), len(texts)), flush=True)
    json.dump(vecs, io.open(p, "w", encoding="utf-8"))
    return vecs


def query_e5_small(text):
    import browser_embedder as be
    return be.query_vector(text)


def query_torch(text, hf_model, tag):
    p = _cache_path(tag)
    if p.exists():
        return json.load(io.open(p, encoding="utf-8"))[0]
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(hf_model)
    mdl = AutoModel.from_pretrained(hf_model)
    mdl.eval()
    enc = tok(["query: " + text], padding=True, truncation=True, max_length=64, return_tensors="pt")
    with torch.no_grad():
        h = mdl(**enc).last_hidden_state
        m = enc["attention_mask"].unsqueeze(-1).float()
        v = (h * m).sum(1) / m.sum(1).clamp(min=1e-9)
        v = (v / v.norm(dim=1, keepdim=True).clamp(min=1e-9)).tolist()[0]
    json.dump([v], io.open(p, "w", encoding="utf-8"))
    del mdl
    return v


# ── int8-публикация индекса (как в проде) ────────────────────────────────────
def quantize_rows(mat):
    rows = []
    for v in mat:
        s = max(abs(x) for x in v) or 1.0
        q = struct.pack("<%db" % len(v), *[max(-127, min(127, round(x / s * 127))) for x in v])
        rows.append({"s": round(s, 5), "q": base64.b64encode(q).decode()})
    return rows


def vectors_from_mat(keys, mat, quant=True):
    """Индекс → {key: вектор} тем же способом, что страница (int8 → float32)."""
    if not quant:
        return {k: list(v) for k, v in zip(keys, mat)}
    out = {}
    for k, v in zip(keys, mat):
        s = max(abs(x) for x in v) or 1.0
        q = [max(-127, min(127, round(x / s * 127))) for x in v]
        w = [A._f32(x * s / 127.0) for x in q]
        n = math.sqrt(sum(x * x for x in w)) or 1.0
        out[k] = [x / n for x in w]
    return out


# ── метрика ──────────────────────────────────────────────────────────────────
def verse_key(ref):
    try:
        c, v = str(ref).split(":")
        return (int(c), int(v))
    except Exception:
        return None


def covers(e, place):
    try:
        book, cv = place.rsplit(" ", 1)
    except Exception:
        return False
    pv = verse_key(cv)
    if pv is None:
        return False
    s = verse_key(e["span"].get("start"))
    t = verse_key(e["span"].get("end")) or s
    if s is None:
        return False
    return s <= pv <= t


def forced_menu(q, trigger, episodes, vectors, qvec, k=6):
    """Меню страницы при выключенной лексике: тот же rank_episodes, но без слов."""
    saved = (A.query_tokens, A.is_proper, A.load_vectors, A.embed_query)
    A.query_tokens = lambda _q: []
    A.is_proper = lambda _w: False
    A.load_vectors = lambda: vectors
    A.embed_query = lambda _q: qvec
    try:
        return A.rank_episodes(q, trigger, episodes, k=k, hybrid=True)
    finally:
        (A.query_tokens, A.is_proper, A.load_vectors, A.embed_query) = saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="e5-small",
                    choices=["e5-small", "e5-large", "nemotron", "bge-m3"])
    ap.add_argument("--mode", default="A5", choices=["A1", "A5", "A6"])
    ap.add_argument("--lang", default="ru", choices=["ru", "en"])
    ap.add_argument("--quant", default="1", choices=["0", "1"],
                    help="1 — индекс публикуется int8 (как в проде)")
    ap.add_argument("--json", default="")
    ap.add_argument("--paraphrase", action="store_true",
                    help="добавить перефразы (scripts/vector_paraphrases.json)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    episodes = A.load_corpus()
    keys = list(episodes.keys())

    # корпус
    if args.model == "e5-small":
        mat = corpus_e5_small(episodes, args.mode)
        qfn = query_e5_small
    elif args.model == "e5-large":
        mat = corpus_torch(episodes, args.mode, "intfloat/multilingual-e5-large",
                           "e5large_%s_corpus" % args.mode)
        qfn = lambda t: query_torch(t, "intfloat/multilingual-e5-large",
                                     "e5large_q_" + hashlib_md5(t))
    elif args.model == "bge-m3":
        mat = corpus_torch(episodes, args.mode, "BAAI/bge-m3", "bgem3_%s_corpus" % args.mode)
        qfn = lambda t: query_torch(t, "BAAI/bge-m3", "bgem3_q_" + hashlib_md5(t))
    else:
        mat = nim_corpus(episodes, args.mode, nim_tag("nemotron_%s_corpus" % args.mode))
        qfn = lambda t: nim_call([t], "query", nim_tag("nemotron_q_" + hashlib_md5(t)), NEM_INSTR)[0]

    vectors = vectors_from_mat(keys, mat, quant=(args.quant == "1"))

    gold = json.load(io.open(GOLD, encoding="utf-8"))["questions"]
    rescue = list((json.load(io.open(MENUS, encoding="utf-8")).get("rescue_questions") or {}).items())

    def tr(q):
        return EN_Q.get(q, q) if args.lang == "en" else q

    # набор вопросов: по умолчанию — 14 золотых (или их английские версии),
    # с --paraphrase — плюс перефразы (scripts/vector_paraphrases.json).
    items = []           # (группа, текст, spec)
    for g in gold:
        items.append(("ru0", tr(g["q"]), g))
    if args.paraphrase:
        pf = json.load(io.open(PARAPHRASES, encoding="utf-8"))
        by_q = {p["q"]: p for p in pf["questions"]}
        for g in gold:
            p = by_q.get(g["q"])
            if not p:
                continue
            for group, texts in (p.get("variants") or {}).items():
                for t in texts:
                    items.append((group, t, g))

    groups = []
    for grp, _, _ in items:
        if grp not in groups:
            groups.append(grp)

    rows = []
    for grp, q, g in items:
        trigger = A.classify(q)     # сырой триггер: класс выводит сама lexical_scores
        qv = qfn(q)
        menu6 = forced_menu(q, trigger, episodes, vectors, qv, k=6)
        pool18 = forced_menu(q, trigger, episodes, vectors, qv, k=18)
        hit6 = any(covers(episodes[k], pl) for k in menu6 for pl in g["places"])
        hit18 = any(covers(episodes[k], pl) for k in pool18 for pl in g["places"])
        core6 = any(covers(episodes[k], pl) for k in menu6 for pl in g.get("core", []))
        rr = 0.0
        for i, k in enumerate(pool18, 1):
            if any(covers(episodes[k], pl) for pl in g["places"]):
                rr = 1.0 / i
                break
        rows.append((grp, q, hit6, hit18, core6, rr))

    def agg(sel):
        rs = [r for r in rows if r[0] in sel]
        if not rs:
            return (0, 0, 0, 0.0, 0)
        return (sum(1 for r in rs if r[2]), sum(1 for r in rs if r[3]),
                sum(1 for r in rs if r[4]), sum(r[5] for r in rs) / len(rs), len(rs))

    resc = []
    for q, page_keys in rescue:
        q2 = tr(q)
        trigger = A.classify(q2)
        menu6 = forced_menu(q2, trigger, episodes, vectors, qfn(q2), k=6)
        resc.append((q2, len(set(menu6) & set(page_keys)), menu6))

    name = "%s %s %s%s" % (args.model if args.model != "nemotron" else NIM_SLUG,
                           args.mode, args.lang, " int8" if args.quant == "1" else " fp32")
    print("\n=== %s ===" % name)
    m6, m18, c6, mrr, n = agg(set(groups))
    print("меню-6 %d/%d   пул-18 %d/%d   ядро-6 %d/%d   MRR %.3f   спасательные %d/12"
          % (m6, n, m18, n, c6, n, mrr, sum(r[1] for r in resc)))
    for grp in groups:
        a = agg({grp})
        print("   группа %-4s меню-6 %d/%d   пул-18 %d/%d   ядро-6 %d/%d   MRR %.3f"
              % (grp, a[0], a[4], a[1], a[4], a[2], a[4], a[3]))
    for grp, q, h6, h18, c, rr in rows:
        if args.verbose:
            print("   [%s] %-44s меню %s  пул %s  ядро %s  mrr %.2f"
                  % (grp, q[:44], "да" if h6 else "—", "да" if h18 else "—",
                     "да" if c else "—", rr))
    for q, hit, menu in resc:
        print("   спасат. %-38s пересечение с меню страницы %d/6" % (q[:38], hit))

    if args.json:
        report = {"model": args.model, "mode": args.mode, "lang": args.lang,
                  "quant": args.quant == "1", "menu6": m6, "pool18": m18,
                  "core6": c6, "mrr": round(mrr, 3), "n": n,
                  "groups": {g: dict(zip(("menu6", "pool18", "core6", "mrr", "n"),
                                         agg({g}))) for g in groups},
                  "rescue": sum(r[1] for r in resc),
                  "rows": [{"group": r[0], "q": r[1], "menu6": r[2], "pool18": r[3],
                            "core6": r[4], "mrr": round(r[5], 3)} for r in rows]}
        io.open(args.json, "w", encoding="utf-8").write(
            json.dumps(report, ensure_ascii=False, indent=1))
        print("отчёт:", args.json)


def hashlib_md5(text):
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    main()
