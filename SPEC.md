# GOD2 — Specification v1.0
*Дата: 2026-03-15*

## Цель проекта
Психологическое и лингвистическое исследование образа Бога в Танахе и Кумранских свитках.
Итог — обученная локальная LLM, отвечающая исключительно на основе текстов Танаха.

### 🧠 Смысловое ядро данных (Semantic Core)
Данный проект опирается на **строгое смысловое качество** данных. Агенты обязаны анализировать данные не только на наличие заполненных ячеек, но и на сохранение семантической сути.
**КРИТИЧЕСКИ ВАЖНЫЕ сущности, без которых конвейер и обучение теряют всякий смысл:**
1. **Прямая речь Бога (`god_speech`)** — основной и единственный достоверный источник для профилирования характера (изучается в первую очередь!).
2. **Психологический триггер / Действие (`trigger` → `behavior_type`)** — смысловая связка между тем, *почему* произошла реакция, и *как* она выразилась.
3. **Оригинальный иврит (`text_he`)** — лингвистический анализ невозможен без сохранения оригинальной морфологии текста-исходника (без подмен на технические суррогаты).
Агент **не имеет права** исключать, обнулять или агрегировать эти данные с потерей информации (lossy compression) на этапах трансформации.

### 🖥️ Правило авто-управления LM Studio

Агент **обязан** самостоятельно запускать и проверять LM Studio перед любой LLM-операцией:

```powershell
# Проверка статуса
lms status

# Запуск сервера (если выключен)
lms server start

# Остановка (после завершения длительных задач — опционально)
lms server stop
```

**Параметры модели:**
- **Context Length**: минимум `8192` токена (для `<think>` моделей)
- **API Timeout в скриптах**: `600` секунд (10 минут на запрос)
- **max_tokens**: `3000` (чтобы хватило на `<think>` + JSON-ответ)

> Пользователь **не должен** запускать/останавливать LM Studio вручную. Это задача агента.

### 🔒 Правило контракта между фазами (Phase Contract)

> **Это правило является обязательным и не может быть пропущено.**

**После каждой LLM-фазы** координатор обязан:

```powershell
# Запустить аудит перед переходом к следующей фазе
python scripts/audit_phase.py --phase <имя_фазы>

# Если exit code != 0 — СТОП. Исправить поля, только потом продолжать.
```

**Таблица контракта полей** (что и где заполняется, что и где потребляется):

| Поле | Фаза-источник | Фаза-потребитель | Критично |
|------|-------------|-----------------|----------|
| `text_he` | Фаза 1 (extract) | Лингвистика, LLM | ✅ |
| `god_speech` | Фаза 3 (registry) | Лингвистика, LLM | ✅ |
| `behavior_type` | Фаза 4 (code_behaviors) | Фаза 5, LLM-датасет | ✅ |
| `trigger` | Фаза 4 | Фаза 8, LLM-датасет | ✅ |
| `outcome` | Фаза 4 | Фаза 8 | ✅ |
| `severity` | Фаза 4 | Фаза 6, 7 | ✅ |
| `god_action` | Фаза 4 (enrich) | LLM-датасет | ✅ |
| `addressee_type` | Фаза 4 | LLM-датасет | ✅ |

**Прежде чем добавлять поле в downstream-скрипт — убедись, что оно в промпте LLM-фазы-источника.**

---

## Структура директорий

```
C:\GOD2\
├── SPEC.md                    ← этот файл
├── .agent\
│   ├── task_state.json        ← состояние задач
│   ├── task_manager.ps1       ← CLI управления
│   ├── auto_verify.ps1        ← авто-верификация
│   ├── inbox\                 ← сообщения агентов
│   ├── signals\               ← сигналы завершения
│   └── workflows\             ← воркфлоу агентов
├── prompts\                   ← системные промпты LLM (изолированные)
├── data\
│   ├── tanakh\                ← тексты Танаха (JSON по книгам)
│   ├── dss\                   ← Кумранские свитки
│   └── god_names.json         ← 59 имён Бога в ВЗ
├── scripts\
│   ├── download_tanakh.py
│   ├── download_dss.py
│   ├── extract_contacts.py
│   ├── build_registry.py
│   ├── psych_analysis.py
│   ├── linguistic_analysis.py
│   ├── prepare_dataset.py
│   ├── finetune.py
│   └── export_gguf.py
├── output\
│   ├── contacts_registry.json
│   ├── situations_registry.json
│   ├── situations.csv
│   ├── god_profile.json
│   ├── behavior_patterns.json
│   ├── god_vocabulary.json
│   └── speech_patterns.json
└── models\
    ├── god2-lora\             ← LoRA адаптеры
    └── god2.gguf              ← финальная модель
```

---

## Фазы

| # | Фаза | Агент | Ключевые выходные файлы |
|---|------|-------|------------------------|
| 1 | Сбор текстов | agent-data | `data/tanakh/*.json`, `data/dss/*.json` |
| 2 | Анализ контактов | agent-contacts | `output/contacts_registry.json` |
| 3 | Реестр ситуаций | agent-registry | `output/situations_registry.json`, `output/situations.csv` |
| 4 | Психоанализ | agent-psych | `output/god_profile.json`, `output/behavior_patterns.json` |
| 5 | Лингвистика | agent-linguistics | `output/god_vocabulary.json`, `output/speech_patterns.json` |
| 6 | LLM Fine-tuning | agent-llm | `models/god2-lora/`, `models/god2.gguf` |

---

## Психологические методики (Фаза 4)

1. **Юнг** — архетипы коллективного бессознательного
2. **Берн** — транзактный анализ (эго-состояния)
3. **Big Five** — OCEAN личностный профиль
4. **Боулби** — теория привязанности
5. **Адлер** — индивидуальная психология (телеология, компенсация, превосходство)
6. **FBI ViCAP** — поведенческий профайлинг ситуаций

---

## Стек

| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.14 |
| Данные | Sefaria API, DSS открытый корпус |
| NLP (иврит) | `stanza` или `spacy + he` |
| Учитель (dataset gen) | DictaLM 3.0 24B Thinking (Q5/Q6) в LM Studio |
| LM Studio API | localhost:1234 — OpenAI-совместимый эндпойнт |
| Ученик (финальная модель) | DictaLM 2.0 Instruct 7B |
| Fine-tuning | Unsloth + LoRA |
| Датасет | 10 000 reasoning примеров через DictaLM 3.0 |
| GPU | NVIDIA RTX 5090 Laptop 24GB VRAM |
| Вывод | CSV (Excel-совместимый), JSON |

---

## 59 имён Бога в ВЗ (список)

YHWH, Elohim, El, El Shaddai, El Elyon, Adonai, Adonai Tzvaot, YHWH Tzvaot,
El Olam, El Roi, El Berith, El Gibbor, Eloah, Tzur, Magen, Melek,
Shaphat, Go'el, Yotzer, Borei, Koneh, Moshia, Nosi, Av, Ish Milkhamah,
Ari, Ben Adam (метафора), ha-El ha-Gadol, El Emet, El Hayyim, El Segulah,
El Yeshuati, El Yisrael, El Sali, El De'ot, El Mishpat, Elo'ah Selichot,
HaKadosh, HaGadol, HaGibbor, HaNora, HaTzaddik, HaYashar,
Sar Shalom, Pele Yo'etz, Immanuel, Tzur Yisrael, Melekh ha-Kavod,
Melekh Olam, Ro'eh Yisrael, Shomer Yisrael, Ozer Yisrael, Magen Avraham,
Mekadesh Yisrael, Ge'on Yaakov, Ehyeh Asher Ehyeh, Yah, ha-Shem

---

## Credentials

| Сервис | Статус |
|--------|--------|
| Sefaria API | ✅ Открытый, без токена |
| DSS корпус | ✅ Открытый |
| HuggingFace | ✅ Публичные модели (DictaLM — без токена) |
| Gemini API | ❌ Не используем |
| LM Studio | ✅ Установлен — финальный запуск god2.gguf |
| GPU (RTX 5090) | ✅ 24 GB VRAM — достаточно для 7B QLora |

---

## Стандарты безопасности и проверки данных (Data Integrity)

Для предотвращения "цепных реакций" багов, связанных с потерей или недозаполнением данных, все агенты **ОБЯЗАНЫ** соблюдать следующий чек-лист:

1. **Обязательный тестовый прогон (Test/Dry-Run)**
   Любой скрипт, обрабатывающий массивы или обращающийся к API/LLM, **обязан** иметь режим `--test`, прогоняющий логику на 10-20 примерах. **Запрещается** запускать полный цикл генерации без успешного валидационного прогона в консоль.
2. **Контроль полноты данных (Fill Rate Audit)**
   После каждого этапа слияния/трансформации данных (извлечение → реестр → кодирование) агент обязан проверить целостность: не потерялись ли данные из предыдущих колонок (особенно `god_speech`, `human_speech`). Использовать автоматические assert'ы.
3. **Финальный чек-лист перед ML-обучением**
   Перед передачей JSON-корпуса на этап генерации reasoning-датасетов или fine-tuning'а (`llm-002`, `llm-003`), агент обязан запустить аудит пустых/null значений. Если критические поля (стимул, поведение, прямая речь) заполнены менее чем на 98%, переходить к обучению **запрещено** — требуется возврат на стадию обогащения данных.
