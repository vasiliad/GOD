---
description: Агент подготовки датасета и fine-tuning локальной LLM через LM Studio + QLora
---

# /agent-llm — Fine-tuning LLM

Зависит от: **registry-001, linguistics-001 (должны быть DONE)**

## Важно: LM Studio вместо Ollama

У пользователя установлен **LM Studio**. Используем его для:
1. Скачивания базовой модели (без HuggingFace токена)
2. Запуска финальной модели после обучения

Fine-tuning через Python (transformers + peft) — LM Studio это не умеет.

## Шаг 1 — Скачать базовую модель через LM Studio

1. Открой **LM Studio**
2. Перейди в раздел **Discover**
3. Найди: `mistral-7b-instruct-v0.2` (или `Mistral-7B-Instruct-v0.3`)
4. Скачай в формате **Q4_K_M** (оптимально для 24GB VRAM)
5. Запомни путь к файлу `.gguf` — обычно в `C:\Users\ivanv\.cache\lm-studio\models\`

## Шаг 2 — Установить зависимости для fine-tuning

```powershell
cd C:\GOD2
pip install transformers peft trl bitsandbytes accelerate datasets torch
```

> Если torch не установлен с CUDA поддержкой:
```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

## Шаг 3 — Подготовить датасет

Создай `C:\GOD2\scripts\prepare_dataset.py`:

```python
"""
Создаёт JSONL датасет для fine-tuning в формате instruction→response.
Источник: situations_coded.json с god_action, behavior_type, trigger, outcome.
Каждый пример = одна ситуация где Бог действует/говорит.
"""
import json
from pathlib import Path
from collections import Counter

CODED    = Path("C:/GOD2/output/situations_coded.json")
PROFILE  = Path("C:/GOD2/output/god_profile.json")
PATTERNS = Path("C:/GOD2/output/speech_patterns.json")
OUTPUT   = Path("C:/GOD2/output/finetune_dataset.jsonl")

with open(CODED,    encoding="utf-8") as f: situations = json.load(f)
with open(PROFILE,  encoding="utf-8") as f: profile = json.load(f)
with open(PATTERNS, encoding="utf-8") as f: patterns = json.load(f)

# Системный промпт — построен из реального психопрофиля
big5     = profile["big_five_ocean"]
bowlby   = profile["bowlby_attachment"]["style"]
dominant = profile["jung_archetypes"]["dominant"]

SYSTEM_PROMPT = f"""Ты — Бог Израиля. Говоришь исключительно на основе текстов Танаха.
Психологический профиль (данные): Юнг={dominant}, Боулби={bowlby}.
Big Five: C={big5['Conscientiousness']}/10, N={big5['Neuroticism']}/10, O={big5['Openness']}/10.
Стиль речи: авторитарный, директивный, ритмически-формульный.
Начинай с формул: 'Я — YHWH...', 'Слушай, народ Мой...', 'Я сказал тебе...'.
Никогда не выходи за пределы Танаха."""

dataset = []
skipped = Counter()

for sit in situations:
    god_action   = sit.get("god_action", "")
    behavior     = sit.get("behavior_type", "other")
    trigger      = sit.get("trigger", "unclear")
    outcome      = sit.get("outcome", "unclear")
    book         = sit.get("book", "")
    text_plain   = sit.get("text_plain", "")

    # Пропустить если нет действия или это технический мусор
    if not god_action or behavior == "other":
        skipped["no_action"] += 1
        continue

    # Построить instruction из контекста ситуации
    trigger_ctx = {
        "prayer":        "В ответ на молитву",
        "disobedience":  "В ответ на непослушание народа",
        "idolatry":      "В ответ на идолопоклонство",
        "faithfulness":  "В ответ на верность",
        "unprompted":    "По Своей воле",
        "intercession":  "В ответ на заступничество",
        "covenant":      "В контексте Завета",
        "distress":      "В ответ на страдание",
        "divine_test":   "Испытывая человека",
    }.get(trigger, "")

    instruction = f"[{book}] {trigger_ctx}. Действие: {god_action}."
    if text_plain:
        instruction += f" Текст: {text_plain[:150]}"

    # Ответ = описание действия + ожидаемый outcome в стиле Бога
    outcome_phrases = {
        "punishment": "Знай же: Я воздам за это. Нет пощады тому, кто нарушает Завет Мой.",
        "blessing":   "Благословен будешь ты, ибо послушался голоса Моего.",
        "covenant":   "Вот Завет Мой с тобой — вечный, нерушимый, во все роды.",
        "rescue":     "Я — YHWH, избавляющий тебя. Рука Моя сильна и простёрта.",
        "revelation": "Говорит YHWH: слушай и запомни то, что открываю тебе.",
        "compliance": "Так сказал YHWH — исполни и не отступи.",
        "dialogue":   "Отвечай Мне: где ты? Что ты сделал?",
        "silence":    "Я сокрою лицо Моё от вас в тот день.",
    }
    response = outcome_phrases.get(outcome, f"Я — YHWH. {god_action.capitalize()}.")

    dataset.append({
        "system":      SYSTEM_PROMPT,
        "instruction": instruction,
        "response":    response,
        "metadata": {
            "book":          book,
            "behavior_type": behavior,
            "trigger":       trigger,
            "outcome":       outcome,
            "severity":      sit.get("severity", 1),
            "id":            sit.get("id", ""),
        }
    })

# Сохранить JSONL
with open(OUTPUT, "w", encoding="utf-8") as f:
    for item in dataset:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"Датасет: {len(dataset)} примеров")
print(f"Пропущено: {dict(skipped)}")
print(f"Распределение behavior_type:")
bt = Counter(d["metadata"]["behavior_type"] for d in dataset)
for t, c in bt.most_common(): print(f"  {t:<15} {c}")
print(f"Файл: {OUTPUT}")
```


Запустить:
```powershell
python scripts\prepare_dataset.py
```

## Шаг 4 — Fine-tuning QLora

Создай `C:\GOD2\scripts\finetune.py`:

```python
"""
Fine-tuning Mistral-7B с QLora на датасете Танаха.
Требует: GPU с 16+ GB VRAM (у нас RTX 5090 24GB — отлично!)
"""
import json, torch
from pathlib import Path
from datasets import Dataset
from transformers import (
    AutoTokenizer, AutoModelForCausalLM,
    BitsAndBytesConfig, TrainingArguments
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

# Найти базовую модель (скачанную через LM Studio или Hugging Face ID)
# Вариант 1: Hugging Face model ID (требует интернет, но малый токен не нужен для некоторых)
BASE_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
# Вариант 2: Локальный путь если конвертирован из GGUF
# BASE_MODEL = r"C:\путь\к\модели"

OUTPUT_DIR = Path("C:/GOD2/models/god2-lora")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DATASET_FILE = Path("C:/GOD2/output/finetune_dataset.jsonl")

# Загрузить датасет
data = []
with open(DATASET_FILE, encoding="utf-8") as f:
    for line in f:
        item = json.loads(line)
        # Форматировать в Mistral Instruct формат
        text = f"<s>[INST] {item['system']}\n\n{item['instruction']} [/INST] {item['response']} </s>"
        data.append({"text": text})

dataset = Dataset.from_list(data)
print(f"Датасет загружен: {len(data)} примеров")

# 4-bit квантизация
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
)

# Загрузить модель
print("Загружаем базовую модель...")
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True
)
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
tokenizer.pad_token = tokenizer.eos_token

# Подготовить для QLora
model = prepare_model_for_kbit_training(model)

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# Обучение
training_args = TrainingArguments(
    output_dir=str(OUTPUT_DIR),
    num_train_epochs=3,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    save_steps=100,
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    report_to="none",
)

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    args=training_args,
    dataset_text_field="text",
    max_seq_length=1024,
)

print("Начинаем обучение...")
trainer.train()
trainer.save_model(str(OUTPUT_DIR))
tokenizer.save_pretrained(str(OUTPUT_DIR))
print(f"Модель сохранена: {OUTPUT_DIR}")
```

Запустить:
```powershell
python scripts\finetune.py
```

> ⏱️ На RTX 5090 24GB ожидаемое время: ~2-4 часа для 3 эпох

## Шаг 5 — Экспорт и загрузка в LM Studio

Создай `C:\GOD2\scripts\export_gguf.py`:

```python
"""
Конвертирует LoRA модель в GGUF для загрузки в LM Studio.
Требует: llama.cpp (python bindings)
"""
import subprocess, os
from pathlib import Path

LORA_DIR = Path("C:/GOD2/models/god2-lora")
OUTPUT_GGUF = Path("C:/GOD2/models/god2.gguf")

# Слить LoRA адаптеры с базовой моделью
print("Сливаем LoRA с базовой моделью...")
merge_script = """
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

base_model = AutoModelForCausalLM.from_pretrained(
    "mistralai/Mistral-7B-Instruct-v0.3",
    torch_dtype=torch.float16,
    device_map="cpu"
)
model = PeftModel.from_pretrained(base_model, "C:/GOD2/models/god2-lora")
model = model.merge_and_unload()
model.save_pretrained("C:/GOD2/models/god2-merged")
AutoTokenizer.from_pretrained("C:/GOD2/models/god2-lora").save_pretrained("C:/GOD2/models/god2-merged")
print("Слияние завершено: models/god2-merged")
"""

exec(merge_script)

# Конвертация в GGUF через llama.cpp
print("\nКонвертируем в GGUF...")
print("Скачай llama.cpp: https://github.com/ggerganov/llama.cpp/releases")
print("Затем выполни:")
print(f"  python llama.cpp/convert_hf_to_gguf.py C:/GOD2/models/god2-merged --outfile {OUTPUT_GGUF}")
print("\nПосле конвертации:")
print("  1. Открой LM Studio")
print("  2. Укажи путь к god2.gguf")
print("  3. Загрузи модель и начинай диалог")
```

## Шаг 6 — Верификация в LM Studio

После загрузки god2.gguf в LM Studio — тест:
- Вопрос: "What should I do if my people worship other gods?"
- Ожидаемый стиль: ответ из контекста Танаха, авторитарный тон

## Шаг 7 — Сигнал завершения
```powershell
cd C:\GOD2\.agent
.\task_manager.ps1 verify
```
