"""
finetune.py
Этап 3: Ученик (DictaLM 2.0 Instruct 7B) учится по учебнику Учителя.

Инструмент: Unsloth (быстрее peft/trl в 2-5x на Ampere GPU).

Установка:
  pip install unsloth datasets trl

Запуск:
  python scripts/finetune.py
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DATASET_FILE  = Path("C:/GOD2/output/reasoning_dataset.jsonl")
LORA_OUT_DIR  = Path("C:/GOD2/models/god2-lora")
GGUF_OUT_PATH = Path("C:/GOD2/models/god2.gguf")
LORA_OUT_DIR.mkdir(parents=True, exist_ok=True)

STUDENT_MODEL = "dicta-il/dictaLM-2.0-Instruct"
MAX_SEQ_LEN   = 2048
LORA_RANK     = 16
NUM_EPOCHS    = 3
BATCH_SIZE    = 2
GRAD_ACCUM    = 4
LEARNING_RATE = 2e-4

# ============================================================
# ИМПОРТЫ
# ============================================================
try:
    from unsloth import FastLanguageModel  # type: ignore[import]
    import torch  # type: ignore[import]
    from trl import SFTTrainer, SFTConfig  # type: ignore[import]
    from datasets import Dataset  # type: ignore[import]
except ImportError as e:
    print(f"Ошибка импорта: {e}")
    print("pip install unsloth datasets trl")
    sys.exit(1)

# ============================================================
# ШАБЛОН ФОРМАТИРОВАНИЯ
# ============================================================
def format_example(ex: dict) -> str:
    """Переводит пример в chat-формат для обучения."""
    situation  = ex.get("situation", "")
    think      = ex.get("think", "")
    voice_he   = ex.get("voice_hebrew", "")
    voice_ru   = ex.get("voice_russian", "")
    # Собираем полный ответ: иврит + русский перевод
    response   = f"{voice_he}\n\n{voice_ru}".strip()

    return (
        f"<|im_start|>system\n"
        f"Ты — Бог Израиля. "
        f"Думай через атрибуты Middat HaDin / Middat HaRachamim "
        f"и отвечай голосом Танаха.\n<|im_end|>\n"
        f"<|im_start|>user\n{situation}<|im_end|>\n"
        f"<|im_start|>assistant\n"
        f"<think>\n{think}\n</think>\n\n{response}<|im_end|>"
    )

# ============================================================
# ЗАГРУЗКА ДАТАСЕТА
# ============================================================
print(f"Загружаем датасет: {DATASET_FILE}")
if not DATASET_FILE.exists():
    print("Сначала запусти generate_reasoning_dataset.py")
    sys.exit(1)

raw = []
with open(DATASET_FILE, encoding="utf-8") as f:
    for line in f:
        try:
            ex = json.loads(line)
            if ex.get("think") and (ex.get("voice_hebrew") or ex.get("voice_russian")):
                raw.append({"text": format_example(ex)})
        except Exception:
            pass

print(f"Примеров в датасете: {len(raw)}")
if len(raw) < 100:
    print("Слишком мало примеров. Сначала сгенерируй датасет.")
    sys.exit(1)

dataset = Dataset.from_list(raw)
print(f"Примеры готовы к обучению: {len(dataset)}")

# ============================================================
# ЗАГРУЗКА МОДЕЛИ-УЧЕНИКА
# ============================================================
print(f"\nЗагружаем ученика: {STUDENT_MODEL}")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name     = STUDENT_MODEL,
    max_seq_length = MAX_SEQ_LEN,
    load_in_4bit   = True,
    dtype          = None,
)

# LoRA адаптеры
model = FastLanguageModel.get_peft_model(
    model,
    r              = LORA_RANK,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    lora_alpha     = LORA_RANK * 2,
    lora_dropout   = 0.05,
    bias           = "none",
    use_gradient_checkpointing = "unsloth",
    random_state   = 42,
)
print(f"LoRA r={LORA_RANK} | "
      f"Trainable params: {model.get_nb_trainable_parameters():,}")

# ============================================================
# ОБУЧЕНИЕ
# ============================================================
trainer = SFTTrainer(
    model     = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    args = SFTConfig(
        dataset_text_field      = "text",
        max_seq_length          = MAX_SEQ_LEN,
        output_dir              = str(LORA_OUT_DIR),
        num_train_epochs        = NUM_EPOCHS,
        per_device_train_batch_size = BATCH_SIZE,
        gradient_accumulation_steps = GRAD_ACCUM,
        warmup_ratio            = 0.05,
        learning_rate           = LEARNING_RATE,
        fp16                    = not torch.cuda.is_bf16_supported(),
        bf16                    = torch.cuda.is_bf16_supported(),
        logging_steps           = 10,
        save_strategy           = "epoch",
        lr_scheduler_type       = "cosine",
        report_to               = "none",
    ),
)

print("\nОбучение started...")
print(f"Эпохи: {NUM_EPOCHS} | Batch: {BATCH_SIZE} | Grad accum: {GRAD_ACCUM}")
trainer.train()

# Сохранить LoRA
model.save_pretrained(str(LORA_OUT_DIR))
tokenizer.save_pretrained(str(LORA_OUT_DIR))
print(f"\nLoRA сохранен: {LORA_OUT_DIR}")

# ============================================================
# ЭКСПОРТ В GGUF (для LM Studio)
# ============================================================
print("\nЭкспорт в GGUF (Q5_K_M)...")
try:
    model.save_pretrained_gguf(
        str(GGUF_OUT_PATH.parent / "god2"),
        tokenizer,
        quantization_method = "q5_k_m",
    )
    print(f"GGUF сохранен: {GGUF_OUT_PATH}")
    print("\nЗагрузи god2.gguf в LM Studio: File → Load Model")
except Exception as e:
    print(f"GGUF экспорт: {e}")
    print("Можно конвертировать вручную через llama.cpp convert_hf_to_gguf.py")

print("\nГотово! Tanakh Reasoning Model создана.")
