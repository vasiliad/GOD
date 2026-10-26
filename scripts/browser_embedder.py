# -*- coding: utf-8 -*-
"""Вектор запроса — тем же int8-ONNX, которым считает страница.

Страница грузит Xenova/multilingual-e5-small (quantized) через transformers.js
и считает «query: » → mean pooling → normalize. Зеркало раньше считало то же
в torch fp32: косинус векторов равнялся 0.996, чего хватало, чтобы перетасовать
меню (замер: страница 5/14 против зеркала 13/14 на одном мозге). Разница
умножалась на z-нормировку (std ≈ 0.012) и превращалась в сдвиг очков до 1.2.

Теперь зеркало считает тем же графом через onnxruntime — вектор страницы и вектор
зеркала совпадают, и замер на золотом эталоне описывает страницу, а не близкий
к ней суррогат. Модель: .agent/models/multilingual-e5-small/onnx/model_quantized.onnx
(та же, что грузит браузер; каталог вне git).
"""
import os
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONNX_PATH = os.path.join(_ROOT, ".agent", "models", "multilingual-e5-small",
                          "onnx", "model_quantized.onnx")
TOKENIZER_ID = "intfloat/multilingual-e5-small"

_SESSION = None
_TOKENIZER = None


def available():
    return os.path.exists(ONNX_PATH)


def _session():
    global _SESSION
    if _SESSION is None:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _SESSION = ort.InferenceSession(ONNX_PATH, sess_options=opts,
                                        providers=["CPUExecutionProvider"])
    return _SESSION


def _tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        from transformers import AutoTokenizer
        _TOKENIZER = AutoTokenizer.from_pretrained(TOKENIZER_ID)
    return _TOKENIZER


def query_vector(text):
    """Нормализованный mean-pooling вектор «query: <text>» — как на странице."""
    tok = _tokenizer()
    enc = tok(["query: " + text], padding=True, truncation=True, max_length=64,
              return_tensors="np")
    feed = {"input_ids": enc["input_ids"].astype(np.int64),
            "attention_mask": enc["attention_mask"].astype(np.int64)}
    if "token_type_ids" in enc:
        feed["token_type_ids"] = enc["token_type_ids"].astype(np.int64)
    else:
        # XLM-R не выдаёт token_type_ids, а граф их требует — нули, как в transformers.js
        feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
    out = _session().run(["last_hidden_state"], feed)[0]
    mask = feed["attention_mask"][..., None].astype(np.float32)
    v = (out * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
    v = v[0]
    n = np.linalg.norm(v)
    return (v / (n if n > 0 else 1.0)).tolist()


def cosine(a, b):
    return float(sum(x * y for x, y in zip(a, b)))
