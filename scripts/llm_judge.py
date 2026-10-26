"""LLM-as-judge: DictaLM оценивает, какой retrieval-алгоритм лучше отвечает на вопрос.

Не self-judging: модель видит только вопрос и текст эпизода — НЕ знает, какой
алгоритм его отобрал. Для каждого из 22 вопросов модель оценивает три кандидата
(лексика / z-гибрид / RRF) по шкале 1–10. Победитель включается на прод.

    python scripts/llm_judge.py          # полный прогон → выводит таблицу
"""
import argparse, base64, io, json, math, os, sys, time, urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_REPO = str(_ROOT)
sys.path.insert(0, os.path.join(_REPO, "scripts"))
from bench_retrieval import (QUESTIONS, lexical_scores, query_tokens, MODEL as EMB_MODEL,
                             load_retrieval_corpus)

BRAIN = json.load(io.open(os.path.join(_REPO, "brain", "brain_snapshot.json"), encoding="utf-8"))
URL = BRAIN["url"] + "/v1/chat/completions"
KEY = BRAIN.get("key", "")

JUDGE_PROMPT = """You are a judge evaluating search results for a research project on the Tanakh.
For each question a person might ask, you see a candidate episode from the Tanakh corpus.
Rate 1-10 how well the episode's divine response addresses the question.
Be strict: a 10 means the episode is the perfect answer, a 5 means it's tangentially related.
Reply ONLY with the number (1-10). No explanation."""


def ask_brain(messages, max_tokens=10):
    body = json.dumps({"messages": messages, "max_tokens": max_tokens, "temperature": 0.1}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.loads(r.read())
    return j["choices"][0]["message"]["content"].strip()


def rate_episode(question, summary, god_speech):
    text = f"Question: {question}\n\nEpisode: {summary}\n\nGod's speech (if any): {(god_speech or '—')[:300]}"
    try:
        r = ask_brain([{"role": "system", "content": JUDGE_PROMPT},
                       {"role": "user", "content": text}])
        score = int(r.strip())
        return max(1, min(10, score))
    except Exception as e:
        print(f"  ошибка: {e}")
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="LLM-as-judge: DictaLM оценивает три retrieval-алгоритма (лексика / z-гибрид / RRF).")
    ap.parse_args(argv)

    # загрузка данных: мастер-корпус + векторы, согласованные по ключу book|span.start
    episodes, vecs = load_retrieval_corpus()

    from transformers import AutoModel, AutoTokenizer
    import torch
    tok = AutoTokenizer.from_pretrained(EMB_MODEL)
    model = AutoModel.from_pretrained(EMB_MODEL)
    model.eval()

    def embed(q):
        with torch.no_grad():
            enc = tok(["query: " + q], padding=True, truncation=True, max_length=64, return_tensors="pt")
            out = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            v = (out * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            v = v[0]
            return (v / v.norm()).tolist()

    cos = lambda a, b: sum(x * y for x, y in zip(a, b))
    top1 = lambda scores: sorted(scores.items(), key=lambda kv: -kv[1])[0]

    totals = {"lex": 0, "zhyb": 0, "rrf": 0}
    counts = {"lex": 0, "zhyb": 0, "rrf": 0}
    details = []

    print("LLM-as-judge: DictaLM оценивает retrieval...")
    for qi, (q, expected) in enumerate(QUESTIONS):
        lex = lexical_scores(q, episodes, expected)
        qv = embed(q)
        allcos = {k: cos(qv, vecs[k]) for k in episodes}
        mean = sum(allcos.values()) / len(allcos)
        std = math.sqrt(sum((c - mean) ** 2 for c in allcos.values()) / len(allcos)) or 1e-9
        zhyb = {k: lex[k] + 6.0 * (c - mean) / std for k, c in allcos.items()}
        lex_rank = {k: r for r, (k, _) in enumerate(sorted(lex.items(), key=lambda kv: -kv[1]))}
        vec_rank = {k: r for r, (k, _) in enumerate(sorted(allcos.items(), key=lambda kv: -kv[1]))}
        fused = {k: 1.0 / (60 + lex_rank.get(k, 10**6)) + 1.0 / (60 + vec_rank.get(k, 10**6)) for k in lex}

        scores_line = {}
        for name, scores in (("lex", lex), ("zhyb", zhyb), ("rrf", fused)):
            top_key = top1(scores)[0]
            ep = episodes[top_key]
            s = rate_episode(q, ep["summary_ru"], ep.get("god_speech_plain", ""))
            if s is not None:
                scores_line[name] = s
                totals[name] += s
                counts[name] += 1
            print(f"  [{qi+1}/22] {name}: {ep['book']} {ep['span']['start']} → {s}/10")
            time.sleep(0.3)  # не душим параллельный слот
        details.append((q, scores_line))

    print("\n=== ИТОГ ===")
    for name in ("lex", "zhyb", "rrf"):
        avg = totals[name] / counts[name] if counts[name] else 0
        print(f"  {name}: средняя оценка {avg:.1f}/10 ({counts[name]} вопросов)")

    # определить победителя
    winner = max(("lex", "zhyb", "rrf"), key=lambda n: totals[n] / max(1, counts[n]))
    print(f"\nПОБЕДИТЕЛЬ: {winner}")
    print("Включить на прод: VEC_W=" + ("6.0 (z-гибрид, как сейчас)" if winner == "zhyb" else
          "0 (чистая лексика)" if winner == "lex" else
          "RRF (союз рангов, нужна правка retrieve())"))

    # сохранить детали
    out = os.path.join(_REPO, "output", "llm_judge_results.json")
    json.dump({"totals": totals, "counts": counts, "details": [(q, s) for q, s in details],
               "winner": winner}, io.open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"детали: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
