# NOTICE — атрибуции и источники

Проект GOD (репозиторий `https://github.com/vasiliad/GOD`, сайт
`https://vasiliad.github.io/GOD/`) использует материалы третьих лиц. Каждый
материал сохраняет лицензию и условия своего источника; ниже — полный список
с обязательными формами атрибуции. Сводная таблица лицензий продублирована в
[`LICENSE`](../LICENSE), краткая — в [`README.md`](../README.md).

---

## 1. Текст Танаха с огласовками и кантиляцией

- **Источник:** Sefaria — <https://www.sefaria.org/>
- **Версия:** «Miqra according to the Masorah» (масоретский текст с огласовкой и кантиляцией)
- **Лицензия:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- **Использовано в:** `data/tanakh/`, `docs/data/tanakh/` — полный текст 39 книг, 23 206 стихов; из него собираются огласовка речи Бога (`data/nikud.json`, `docs/data/nikud.json`) и спан стихов эпизодов.
- **Требуемая атрибуция:** `Tanakh text with vowel points: Miqra according to the Masorah, Sefaria (https://www.sefaria.org/), licensed under CC BY-SA 4.0.`
- **Важно:** этот текст **не** в общественном достоянии. Условие Share-Alike распространяется на адаптации самого текста; производные от него файлы проекта (например, производные эмбеддинги) распространяются на условиях, указанных для соответствующего актива.

## 2. Аудио чтений Танаха

### 2.1. «fluent» — archive.org

- **Источник:** [archive.org, item `HebBible_AShmuelof`](https://archive.org/details/HebBible_AShmuelof)
- **Автор / правообладатель записей:** **Abraham Shmuelof** (creator, см. метаданные item'а)
- **Лицензия:** [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)
- **Использовано в:** `docs/data/audio/*.json` → блок `fluent` (URL главы + таймкоды стихов); проигрывается в читалке на сайте.
- **Требуемая атрибуция:** `Audio: Bible recordings by Abraham Shmuelof (archive.org, item HebBible_AShmuelof), licensed under CC BY-NC-ND 4.0.`

### 2.2. «slower» — датасет arabyan/tanakh-audio

- **Источник:** [Hugging Face dataset `arabyan/tanakh-audio`](https://huggingface.co/datasets/arabyan/tanakh-audio), каталог `slower/` (929 глав)
- **Происхождение:** mp3 извлечены из slower-варианта аудио-EPUB ebible.org **дословно** (переименование файлов, байтовая копия, без переработки контейнера) — сборка: `scripts/build_audio.py`, загрузка: `scripts/upload_slow_audio.py`
- **Лицензия:** [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/) (следует лицензии исходных записей)
- **Требуемая атрибуция:** та же, что в п. 2.1: `Abraham Shmuelof`, CC BY-NC-ND 4.0.

### 2.3. Таймкоды глав — ebible.org

- **Источник:** [ebible.org, Hebrew Bible Online multimedia (`hbo`)](https://ebible.org/multimedia/hbo/)
- **Что взято:** файлы **SMIL (Media Overlays)** из аудио-EPUB — таймкоды стихов внутри глав (используются в `docs/data/audio/*.json` и в логике подсветки/плеера)
- **Лицензия:** см. условия ebible.org для использованных файлов; таймкоды — служебные метаданные SMIL, включённые в исходные EPUB-пакеты
- **Требуемая атрибуция:** `Verse timecodes: ebible.org Hebrew Bible Online (https://ebible.org/multimedia/hbo/), SMIL media overlays.`

### 2.4. Соблюдение NC и ND

- **NC (некоммерческое использование):** проект GOD — некоммерческое исследование; аудио используется только в этом контексте и не предлагается для коммерческого использования.
- **ND (нет производных):** записи воспроизводятся **дословно** — целыми главами, без нарезки, склейки, монтажа, ремикса и любой иной переработки. Проект хранит только ссылки на исходные файлы и таймкоды стихов (метаданные SMIL), но не модифицированные аудиопотоки.

## 3. Русский перевод (Синодальный, 1876)

- **Источник:** [api.getbible.net, `synodal`](https://api.getbible.net/v2/synodal/) — сборка: `scripts/build_ru.py`
- **Лицензия:** **общественное достояние** (перевод 1876 года)
- **Использовано в:** `docs/data/tanakh-ru/` — постихный перевод в читалке (877 из 929 глав; в остальных — честные `null` для стихов, отсутствующих в синодальной нумерации)
- **Атрибуция:** не требуется; приветствуется указание «Синодальный перевод, 1876».

## 4. Модель мозга чата

- **Модель:** **DictaLM-3.0-Nemotron-12B-Instruct** (GGUF-сборка `Q5_K_M`)
- **Карточка модели:** <https://huggingface.co/dicta-il/DictaLM-3.0-Nemotron-12B-Instruct>
- **GGUF-сборка:** <https://huggingface.co/dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF>
- **Лицензия модели:** **NVIDIA Open Model License** (`license_name: nvidia-open-model-license`) — <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/>; точные условия — в карточке модели на Hugging Face.
- **Как используется:** веса не переобучаются и не распространяются в составе репозитория; на Kaggle-ноутбуке поднимается сервер `llama.cpp` (`brain/kernel.py`), который обслуживает запросы чата; ответ — рекомбинация фрагментов `god_speech_plain` реальных эпизодов корпуса, скомпонованная моделью (RAG, без дообучения).

## 5. Модель эмбеддингов

- **Модель:** `intfloat/multilingual-e5-small` — <https://huggingface.co/intfloat/multilingual-e5-small>
- **Лицензия:** **MIT**
- **Как используется:** оффлайн-сборка `docs/data/embeddings.json` (2 050 векторов, dim 384, int8-квантизация, `scripts/build_embeddings.py`); в браузере — через transformers.js. Векторы — производные от аннотаций корпуса, распространяются на условиях CC BY 4.0 (см. `LICENSE`).

## 6. transformers.js (библиотека)

- **Пакет:** `@xenova/transformers` (npm), репозиторий <https://github.com/xenova/transformers.js>
- **Лицензия:** **Apache-2.0**
- **Как используется:** клиентский inference для эмбеддинга запроса посетителя (страница грузит модель в браузере, `quantized: true`). Скрипты страницы подключаются с CDN; код библиотеки в репозиторий не входит.

## 7. Статус живого мозга

- **Источник:** [Hugging Face dataset `arabyan/god-brain-status`](https://huggingface.co/datasets/arabyan/god-brain-status), файл `brain.json` — публикуется ноутбуком на Kaggle (URL туннеля, ключ, метка времени).
- **Как используется:** страница и `scripts/test_accuracy.py` читают этот файл, чтобы узнать, жив ли мозг. Файл содержит технические параметры подключения, не данные и не записи.

---

## Сводка

| Актив | Лицензия | Атрибуция |
|---|---|---|
| Текст Танаха с огласовкой (Sefaria, «Miqra according to the Masorah») | CC BY-SA 4.0 | Обязательна: Sefaria |
| Аудио «fluent» (archive.org `HebBible_AShmuelof`) | CC BY-NC-ND 4.0 | Обязательна: Abraham Shmuelof |
| Аудио «slower» (arabyan/tanakh-audio) | CC BY-NC-ND 4.0 | Обязательна: Abraham Shmuelof |
| Таймкоды стихов (ebible.org SMIL) | условия ebible.org | Указать источник |
| Синодальный перевод 1876 | общественное достояние | — |
| DictaLM-3.0-Nemotron-12B-Instruct | NVIDIA Open Model License | Карточка модели на Hugging Face |
| intfloat/multilingual-e5-small | MIT | — |
| @xenova/transformers | Apache-2.0 | — |
| Аннотации, разметка, аналитика, эмбеддинги корпуса | CC BY 4.0 | Указать проект GOD (vasiliad) |
| Код проекта | MIT | Сохранять уведомление об авторских правах |
