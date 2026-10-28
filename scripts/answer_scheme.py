#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СХЕМА ОТВЕТА мозга — зеркало страницы (docs/index.html) для скриптов-гейтов.

Схема, измеренная на локальном мозге (DictaLM-3.0-Nemotron-12B-Instruct, Q5_K_M,
llama.cpp + CUDA, RTX 5090) на восьми вопросах:

    ШАГ 1  выбор эпизода   — короткий закрытый вызов (temperature 0, max_tokens 16),
                               модель отвечает одним номером кандидата;
    ШАГ 2  формулировка     — модель получает ОДИН эпизод и обязана взять его слова
                               (5–12 слов, шесть секций);
    ШАГ 3  сверка («S»)     — ответ проверяется по реестру, источник всегда из реестра.

Старая схема (один вызов + JSON-контекст из шести эпизодов) давала 1–2/8 сверенных
ответов при покрытии 38–45 %: модель цитировала Танах ПО ПАМЯТИ. Новая — 7/8 при
покрытии 88 %. Причина: выбор и формулировка разведены, а «ТОЛЬКО из этого эпизода»
стало короткой копирующей задачей, а не запретом внутри JSON-простыни.

Промпты берутся СО СТРАНИЦЫ (answer_guard.page_sys_prompt / page_sys_select) —
страница остаётся единственным источником истины, скрипты не могут с ней разойтись.

Запуск самопроверки:  python scripts/answer_scheme.py --test
"""
import base64
import io
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
from answer_guard import page_sys_prompt, page_sys_select   # noqa: E402

try:
    import browser_embedder                          # noqa: E402
except Exception:                                   # нет onnxruntime — работаем на torch
    browser_embedder = None

MASTER_CORPUS = _ROOT / "output" / "episodes_TANAKH_v2.json"
ANALYTICS = _ROOT / "docs" / "data" / "analytics.json"
NIKUD_INDEX = _ROOT / "docs" / "data" / "nikud.json"
EMBEDDINGS = _ROOT / "docs" / "data" / "embeddings.json"
EMB_NEM_BIN = _ROOT / "docs" / "data" / "embeddings_nemotron.bin"
EMB_NEM_META = _ROOT / "docs" / "data" / "embeddings_nemotron.json"
# Адрес серверного эмбеддера (Nemotron-3-Embed-1B на сервере проекта). Пусто —
# зеркало работает на браузерном e5-small, как и страница, когда сервер лежит.
EMBED_URL = os.environ.get("GOD_EMBED_URL", "").strip()
PROFILE = _ROOT / "docs" / "data" / "god_behavior_profile.json"

# Классы обращения страницы → классы реестра (12 триггеров корпуса).
# «confession» и «covenant» в реестре нет: без маппинга буст +4 и блок [ACTION]
# уезжали в пустоту. Основание — scripts/god_profile.py --publish и замер по корпусу.
TRIG_CLASS = {"confession": "intercession", "covenant": "covenant_follow_up"}
OUT_RU = {"answer_granted": "ответ дан", "blessing": "благословение", "compliance": "послушание",
          "covenant": "завет", "delayed": "отложено", "punishment": "кара", "refusal": "отказ",
          "rescue": "спасение", "revelation": "откровение", "silence": "молчание", "unclear": "неясно"}
MODE_RU = {"speaks_and_acts": "говорит и действует", "acts_silently": "действует молча",
           "silence": "молчит полностью", "speaks_only": "только говорит"}
TRIG_RU = {"unprompted": "по инициативе Бога", "disobedience": "непослушание",
           "covenant_follow_up": "следование завету", "distress": "бедствие", "faithfulness": "верность",
           "complaint": "жалоба", "inquiry": "вопрошание", "gratitude": "благодарность",
           "prayer": "молитва", "intercession": "заступничество", "vow": "обет",
           "divine_test": "божественное испытание"}

# ── промпты (страница — источник) и параметры вызовов ────────────────────────
SYS_PROMPT = page_sys_prompt()
SYS_SELECT = page_sys_select()
SELECT_TEMP = 0.0          # выбор — детерминированный вопрос с одним ответом
SELECT_MAX_TOKENS = 16
FORM_TEMP = 0.15           # формулировка — почти детерминированная (измерено)
FORM_MAX_TOKENS = 900      # хватает на шесть коротких секций
FORM_ATTEMPTS = 3          # попыток на неполный ответ (страница: три попытки в liveReply)
FORM_REPEAT_PENALTY = 1.15 # штраф за повтор: без него модель на коротких репликах уходит
                            # в петлю (русский слой повторяет фразу до лимита токенов).
                            # Замер под шестипачечной нагрузкой, как в потоке вопросов:
                            # без штрафа 14/18 ответов полные, со штрафом 18/18
FORM_RETRY_TEMPS = (0.15, 0.30, 0.45)  # повтор — другой образец, а не тот же запрос:
                            # три одинаковых запроса — по сути одна партия, и в провале
                            # все три выродились одинаково
SECTION_TAGS = ("[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]")
# Содержательные слои — те пять, которые видит пользователь. [SOURCES] — служебная
# секция: источник показывается ИЗ РЕЕСТРА (book|span выбранного эпизода), а не из
# строки модели. Замер в потоке (2026-10-27): модель иногда не пишет [SOURCES] вовсе
# (finish_reason=stop, все пять слоёв на месте) — и весь хороший ответ заменялся
# прецедентом корпуса из-за секции, которую никто не показывает. Полный ответ = пять
# непустых содержательных слоёв; страница считает так же (CONTENT_SECTIONS).
CONTENT_TAGS = ("[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]")
CONTENT_FULL = len(CONTENT_TAGS)
VEC_W = 1.0                # вес вектора e5-small в СПАСАТЕЛЬНОМ режиме (страница: const VEC_W)
MEM_IN_FORM = False        # память диалога в шаг формулировки — флаг общий со страницей
DEFAULT_TIMEOUT = 180

# ── лексика запроса (порт queryTokens() страницы + мост для иврита) ───────────
RU_STOP = set("и в на с по о не что как это то же ли бы а но или у к из за до для при".split(" "))
# Вопросительные маркеры: называют ТИП вопроса, а не тему. «почему» уже закодировано
# формой ответа («объяснение»), а как тематический сигнал оно ловилось у случайных
# эпизодов (в их пересказе встречается «почему») и выдавало их за тематические
# совпадения — при этом настоящего тематического слова («зло», «праведники») в
# описаниях эпизодов нет, и отбор опирался на класс и форму, а не на содержание.
RU_MARKERS = set("почему зачем какой какая какие сколько".split())
RU_SYN = [
    ["умер", "смерть", "смерт", "умирает", "погиб", "погибель", "умрет", "мертв"],
    ["гнев", "разгневал", "гнева", "гневен", "ярост"],
    ["милосерд", "милост", "простил", "прощение", "простить", "пощадил", "милость"],
    ["люб", "любов", "любовь", "любим", "возлюб"],
    ["страх", "боюсь", "боится", "страшно", "устраш", "трепет", "бойся", "бойтесь", "испуг", "пугает"],
    ["наказа", "кара", "карает", "наказание", "покарал"],
    ["спас", "спасение", "спасает", "избав", "избавит"],
    ["молитв", "молитва", "молится", "молит"],
    ["завет", "завета", "завету", "договор"],
    ["грех", "греха", "грехов", "согрешил", "преступ"],
    # мосты по замеру на золотом эталоне: в аннотациях корпуса другие словоформы
    # («путям» против «пути», «имени» против «имя», «научить» против «узнать»)
    ["сотвор", "созда", "создал", "сотворил", "твор", "начал"],
    ["имя", "имени", "име", "имями", "зовут", "называ", "назван", "называет"],
    ["сил", "силы", "силу", "силён", "мочь", "можешь", "держ", "устал", "выдерж"],
    ["утеш", "утешь", "утешить", "утеша", "скорб", "скорби", "страдан", "страда", "страдают"],
    ["путь", "пути", "путям", "путями", "путей", "идти", "ходить", "воле", "воля", "волю", "волей"],
    ["враг", "враги", "врагов", "противник", "напад"],
    ["узна", "узнать", "узнаю", "научи", "научить", "вразуми", "позна", "учить", "учу"],
    ["справедл", "несправедлив", "винов", "прав"],
]
EN_BRIDGE = {"fear": "страх", "afraid": "страх", "scared": "страх", "anger": "гнев", "wrath": "гнев",
             "destroy": "разруш", "destroyed": "разруш", "punish": "наказа", "punishment": "наказание",
             "mercy": "милость", "forgive": "прости", "forgiven": "прощ", "forgiveness": "прощ",
             "sorry": "прости", "forgave": "прости", "silence": "молчание", "pray": "молитва",
             "prayer": "молитва", "save": "спас", "rescue": "спас", "saved": "спас", "help": "спас",
             "deliver": "избав", "protect": "защищ", "protection": "защищ", "sin": "грех", "sins": "грех",
             "sinned": "согрешил", "love": "люб", "covenant": "завет", "temple": "храм", "idol": "идол",
             "dream": "сон", "die": "умер", "died": "умер", "death": "смерть", "why": "почему",
             "listen": "слыш", "hear": "слыш", "answer": "отвеча", "command": "повел", "law": "закон",
             "torah": "тор", "enemies": "враг", "enemy": "враг", "comfort": "утеш", "comforted": "утеш",
             "comforts": "утеш", "sorrow": "скорб", "grief": "скорб", "strength": "сил", "strong": "сил",
             "strengthen": "сил", "tired": "устал", "exhausted": "устал", "weary": "устал",
             "give": "дай", "guide": "вед", "lead": "вед", "show": "покаж", "way": "путь", "path": "путь",
             "thanks": "благодар", "thank": "благодар", "grateful": "благодар", "name": "имя",
             "called": "имя", "who": "кто", "trust": "надежд", "hope": "надежд", "heal": "исцел",
             "healing": "исцел", "sick": "бол", "illness": "бол", "war": "войн", "battle": "войн",
             "righteous": "правед", "evil": "зл", "wicked": "зл", "peace": "покой", "teach": "уч",
             "wisdom": "мудр", "born": "рожд", "created": "сотвор", "creation": "сотвор",
             "beginning": "нач", "promise": "обещан", "promises": "обещан",
             "promised": "обещан", "power": "сил"}
HE_BRIDGE = {"מה": "что", "מי": "кто", "ספר": "скажи", "תן": "дай", "דרך": "путь", "דרכך": "путь",
             "לאדם": "человек", "אדם": "человек", "איך": "как", "כיצד": "как", "לדעת": "знать",
             "לעשות": "делать", "לחיות": "жизн", "חיים": "жизн", "תפילה": "молитва", "תפילתי": "молитва",
             "בכי": "плач", "עצב": "скорб", "אשמה": "вина", "אשמתי": "вина", "שמחה": "радость",
             "לב": "сердц", "לבב": "сердц", "ירושלים": "Иерусалим", "מצרים": "Египет",
             "אברהם": "Авраам", "בני": "сын", "בנים": "сын", "בת": "дочь", "ילדי": "дит", "עם": "народ",
             "נחמי": "утеш", "נחם": "утеш", "נחמתי": "утеш", "נחמו": "утеш", "נחמים": "утеш",
             "סלח": "прости", "סליחה": "прощ", "מחיל": "прости", "מחילה": "прощ",
             "עזר": "помощ", "עזרה": "помощ", "כוח": "сил", "עוצם": "сил", "כוחות": "сил",
             "הראה": "покаж", "הראי": "покаж", "ללכת": "идти", "ללך": "идти", "לך": "идти",
             "תודה": "благодар", "אודה": "благодар", "הודה": "благодар",
             "שמך": "имя", "שמו": "имя", "קוראים": "имя",
             "חטא": "грех", "חטאתי": "грех", "חטאים": "грех",
             "מות": "смерт", "למות": "смерт", "פחד": "страх", "מפחד": "страх", "ירא": "страх",
             "אוהב": "люб", "אהבה": "люб", "ברית": "завет", "הברית": "завет",
             "רע": "зл", "רעה": "зл", "הרע": "зл", "צדיק": "правед", "הצדיקים": "правед",
             "בראשית": "сотвор", "בריאה": "сотвор", "נוצר": "сотвор", "נעשה": "сотвор",
             "צרות": "бед", "צרה": "бед", "מצוקה": "бед", "צרותי": "бед",
             "אויב": "враг", "אויבי": "враг", "שר": "войн", "מלחמה": "войн",
             "חכמה": "мудр", "חכם": "мудр", "מוסר": "мудр", "למד": "уч", "ללמד": "уч",
             "תורה": "закон", "מצוה": "повел", "מצות": "повел", "חוק": "закон",
             "יחלו": "надежд", "תקווה": "надежд", "שלום": "покой", "בריאות": "исцел", "רפא": "исцел",
             "אחר": "буд", "אחרית": "буд", "ימים": "дн", "כבר": "уже", "עוד": "ещ",
             "הבטחת": "обещан", "הבטח": "обещан", "בטחתי": "обещан", "מודה": "благодар",
             "חזק": "сил"}
# ивритские словоформы меняются окончаниями («נחמי» от «נחם», «סליחה» от «סלח»),
# поэтому целого слова в мосте нет — ищем по началу. Ключи сортируются по длине
# (длинный префикс проверяется первым), чтобы результат не зависел от порядка.
HE_PREFIX = {"נחמי": "утеш", "נחם": "утеш", "נחמ": "утеш", "סליח": "прощ", "סלח": "прости",
             "מחיל": "прости", "עזר": "помощ", "כוח": "сил", "שמך": "имя", "שמו": "имя",
             "חטא": "грех", "מפחד": "страх", "פחד": "страх", "ברית": "завет", "רעה": "зл",
             "צדיק": "правед", "אויב": "враг", "תודה": "благодар", "אודה": "благодар",
             "בראשית": "сотвор", "צרות": "бед", "צרה": "бед", "מצוק": "бед", "לב": "сердц",
             "חכמ": "мудр", "הרא": "покаж", "ללך": "идти", "ללכ": "идти", "אוהב": "люб",
             "בריא": "сотвор", "נוצר": "сотвор", "יחל": "надежд", "תקווה": "надежд",
             "שלום": "покой", "רפא": "исцел", "ילד": "дит", "אחר": "буд", "מות": "смерт",
             "חיים": "жизн", "בנים": "сын", "בני": "сын"}
HE_PREFIX_KEYS = sorted(HE_PREFIX, key=len, reverse=True)

# ── ВОРОТА ЛЕКСИКИ ──────────────────────────────────────────────────────────
# Сигналом лексики считается не любое совпадение слова, а значимое: слово от
# 4 букв, встречающееся не чаще, чем в 5% эпизодов. Без этого ворота шумовой
# матч (ивритская цитата внутри русской выжимки: «למה יהוה» в Judges 21:1, или
# мост «איך» → «как», а слово «как» есть в 599 эпизодах из 2050) объявлял
# лексику «нашедшей» и выключал вектор — единственный тематический сигнал для
# вопроса, написанного на другом языке.
LEX_MIN_LEN = 4
LEX_MAX_DF_PCT = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# Корпус
# ─────────────────────────────────────────────────────────────────────────────
def load_corpus():
    """Мастер-корпус {книга: [эпизоды]} → {book|span.start: эпизод}, порядок книг — как на странице."""
    master = json.load(io.open(MASTER_CORPUS, encoding="utf-8"))
    analytics = json.load(io.open(ANALYTICS, encoding="utf-8"))
    books = [b for era in analytics["book_order"].values() for b in era if b in master]
    books += [b for b in master if b not in books]
    episodes = {}
    for book in books:
        for e in master[book]:
            episodes["%s|%s" % (book, e["span"]["start"])] = dict(e, book=book)
    return episodes


def load_nikud():
    return json.load(io.open(NIKUD_INDEX, encoding="utf-8"))


def load_analytics():
    return json.load(io.open(ANALYTICS, encoding="utf-8"))


def nikud_for(book, refs, index):
    """Порт nikudFor() из docs/index.html — символ в символ (регистр, 3 стиха, склейка)."""
    bk = book[:1].upper() + book[1:]
    out = []
    for r in (refs or [])[:3]:
        m = re.match(r"^(\d+):(\d+)$", r or "")
        if not m:
            continue
        t = index.get(bk + "|" + m[1] + "|" + m[2])
        if t:
            out.append(t)
    return "  ".join(out)


def build_context(episodes, nikud_index, hits):
    """Контекст для мозга — те же поля и те же ограничения длины, что на странице."""
    ctx = []
    for key in hits:
        e = episodes[key]
        ctx.append({
            "book": e["book"],
            "span": e["span"],
            "trigger": e.get("trigger", ""),
            "outcome": e.get("outcome", ""),
            "god_speech_plain": (e.get("god_speech_plain") or "")[:300],
            "nikud": nikud_for(e["book"], e.get("god_speech_refs"), nikud_index)[:300],
            "summary_ru": (e.get("summary_ru") or ""),
            "god_action": (e.get("god_action") or "")[:160],
        })
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Отбор кандидатов — та же формула, что на странице (retrieve())
# ─────────────────────────────────────────────────────────────────────────────
TRIGGERS = [
    ["disobedience", ["не буду", "наруш", "не послуш", "отвергаю", "идол", "другого бога", "не выполню",
                      "проигнор", "откажусь слушаться", "мне всё равно", "плевать", "i will not", "i won't",
                      "i disobey", "לא אשמע", "אלהים אחרים", "אעבור על"]],
    ["intercession", ["прости им", "не губи", "пощади", "защити их", "за них", "сбереги", "не карай их",
                      "сжалься над ними", "spare them", "do not destroy them", "חנם עליהם", "אל תהרג",
                      "הציל אותם", "בעדם"]],
    ["confession", ["согрешил", "согрешила", "прости меня", "прости мне", "мой грех", "раскаиваюсь",
                    "провинился", "виновен", "оставил грех", "i have sinned", "forgive me", "i repent",
                    "חטאתי", "חטאתי ב", "סלח לי"]],
    ["complaint", ["почему ты", "зачем ты", "несправедливо", "жалуюсь", "ропщу", "ты покинул", "ты оставил",
                   "не заботишься", "страдают", "почему в мире", "почему зло", "почему добрые", "почему страдают", "почему мучаются", "почему же", "обидно", "why is there", "why do the righteous", "why do good people", "למה יש", "למה רע", "למה הטובים", "why did you", "why have you",
                   "למה עזבת", "למה אתה", "לא צדק"]],
    ["distress", ["спаси меня", "спаси нас", "спасите", "спаси ", "спаси,", "спаси!", "спаси.", "помоги", "помогите", "выручи", "погибаю", "беда", "окружили", "напали", "враг одолел", "умираю", "утопаю", "горит",
                  "страх", "боюсь", "боится", "страшно", "утешь", "скорб", "враг", "тревож", "help me",
                  "save me", "i am afraid", "i'm afraid", "scared", "ירא", "מפחד", "בצרה", "עזר לי",
                  "הציל אותי", "אויבים"]],
    ["prayer", ["молю", "молюсь", "прошу тебя", "воззвал", "обращаюсь к тебе", "i pray", "i beg you",
                "מתפלל", "תפילתי", "בקשתי", "נא תענה"]],
    ["covenant", ["завет", "обещание отцам", "обещание", "обещал", "ради авраама", "ради израиля", "земля обещанная", "потомству", "הבטחת", "בטח",
                  "ברית"]],
    ["inquiry", ["скажи мне", "что мне делать", "спрашиваю", "истолкуй", "довольно ли", "кто виноват",
                 "объясни", "зовут", "научи", "покажи", "хочу знать", "расскажи", "что значит", "каков", "что бы ты хотел", "что ты хочешь", "как мне жить", "как жить", "куда мне", "what do you want", "מה אתה רוצה", "מה אתה הבטחת",
                 "твою волю", "твоей воли", "tell me", "what shall i do", "מה עליי", "ספר לי",
                 "מה דרכך", "לדעת", "מה אמרת"]],
    ["vow", ["даю обет", "клянусь", "обещаю тебе", "обязуюсь", "i vow", "i swear", "נדר", "נשבעתי"]],
    ["gratitude", ["благодар", "славлю", "хвала тебе", "воспою тебе", "спасибо", "thank you", "thanks", "thank", "i praise you", "grateful",
                   "תודה", "אודה", "מודה", "הודה"]],
    ["faithfulness", ["делаю как велел", "следую за тобой", "верен тебе", "исполнил всё", "хожу путями",
                      "люблю тебя всем сердцем", "i follow you", "i am faithful", "אני נאמן",
                      "מקיים את דברי"]],
]


def classify(q):
    """Порт classify() из docs/index.html (порядок TRIGGERS важен).

    Возвращает "" (а не «inquiry»), если тип обращения не распознан: буст класса
    и блок [ACTION] тогда не применяются. Замер на золотом эталоне: «меню=верный»
    7/14 с бустом-заглушкой, 9/14 без него.
    """
    m = q.lower()
    for t, kws in TRIGGERS:
        for k in kws:
            if k in m:
                return t
    return ""


def trig_class(t):
    """Класс реестра для класса обращения страницы (TRIG_CLASS)."""
    return TRIG_CLASS.get(t, t)


# ─────────────────────────────────────────────────────────────────────────────
# ФОРМА ОТВЕТА, КОТОРУЮ ПРОСИТ ЧЕЛОВЕК (порт страницы)
# Класс обращения отвечает на вопрос «какая ситуация», но человек просит
# конкретную форму: утешить, простить, направить, защитить. Без этой размерности
# тема совпадала, а форма — нет: на «утешь меня в скорби» модель выбрала смертный
# приговор царю Езекии («ты умрёшь»). Форма просьбы — отдельный сигнал ранжирования,
# и она же печатается в блоке кандидатов.
REQ_FORMS = [
    ("утешение", ["утеш", "утешь", "утешить", "успокой", "обнадёж", "сил", "держ", "comfort", "נחמ", "נחמו", "כוח"]),
    ("прощение", ["прости", "прощ", "вину", "грех", "forgive", "forgiveness", "סלח", "חטא"]),
    ("направление", ["путь", "веди", "направ", "научи", "воле", "учить", "вразуми", "guide", "teach", "דרך", "דרכי", "как жить", "как мне жить", "идти дальше", "куда", "двигаться", "потерялся", "how should i live", "where should i go", "what should i do", "איך לחיות", "לאן ללכת"]),
    ("защита", ["защити", "сохрани", "спаси меня", "спаси нас", "избав", "охрани", "save me", "protect", "הציל", "от опасности", "убери меня", "избавь меня", "הצילני", "מאויבי", "save me from", "protect me from"]),
    ("наказание", ["накаж", "наказать", "воздай", "отомст", "punish", "ענש"]),
    ("хвала", ["благодар", "слава", "хвала", "thank", "praise", "תודה", "спасибо", "grateful", "מודה"]),
    ("завет", ["завет", "обещание", "הבטחת", "ברית"]),
    ("объяснение", ["почему", "зачем", "что значит", "что такое", "объясни", "ответь", "why", "מדוע", "למה"]),
]
# исходы реестра по форме ответа — структурное поле эпизода, а не выдумка
FORM_OUTCOMES = {
    # Форма ответа — это НЕ «любой ответ», а ответ нужного рода. Утешение — это
    # благословение, спасение или завет (Бог обещает и защищает), а не «откровение»
    # и не «исполнение просьбы»: откровение отвечает на вопрос «что?», исполнение —
    # на вопрос «дай». Объяснение — это откровение (Бог НАЗЫВАЕТ причину), а не
    # исполнение просьбы: на «почему ты допустил зло» нужен ответ с причиной.
    # (Замер: при размытой таблице в меню «почему ты допустил зло» попадали ответы
    # Моисею о его медлительности, а форма «утешение» тянула в меню откровения вместо
    # обещания — «дай мне силы» отвечало откровением об идолах.)
    "утешение": {"good": ["blessing", "rescue", "covenant"], "bad": []},
    "прощение": {"good": ["answer_granted", "covenant", "blessing", "revelation"], "bad": []},
    "направление": {"good": ["covenant", "revelation", "compliance", "answer_granted"], "bad": ["punishment"]},
    "защита": {"good": ["rescue", "blessing", "answer_granted", "revelation", "delayed"], "bad": ["punishment"]},
    "наказание": {"good": ["punishment"], "bad": []},
    "хвала": {"good": ["unclear", "blessing", "compliance", "covenant", "revelation"], "bad": ["punishment"]},
    "завет": {"good": ["covenant", "blessing", "compliance", "revelation"], "bad": []},
    "объяснение": {"good": ["revelation"], "bad": ["silence"]},
}
# смертный приговор в речи Бога (три эпизода из 2050) утешением не считается
DEATH_VERDICT = ["מת אתה", "לא תחיה", "מתה אתה"]
FORM_GOOD = 2.0        # вес совпавшей формы ответа
FORM_BAD = -1.5       # вес неуместного исхода
DEATH_PENALTY = -8.0  # приговор вместо утешения

# ТЕМА «ИМЯ» — отдельный сигнал отбора (порт страницы). Вопрос «как тебя зовут?»
# обязан привести к эпизоду, где Бог НАЗЫВАЕТ своё имя (Исход 3:13 «אהיה אשר אהיה»).
# Без этого лексика цеплялась за общие слова («звучит», «название»), в пул попадали
# случайные эпизоды, а перефраз «ты же имеешь имя — как оно звучит?» не вёл никуда:
# модель дописала стих по памяти, и сверка справедливо отклонила цитату. Маркер
# самоименования ищем по САМОЙ речи Бога — таких эпизодов в корпусе ровно три.
NAME_TOPIC = ["имя", "имени", "как тебя зовут", "зовут", "называ",
               "your name", "what is your name", "call you", "מה שמך", "שמך", "שמו",
               "קוראים לך", "קוראים"]
SELF_NAME = ["אהיה אשר אהיה", "שמי יהוה", "שמי אלהים"]
NAME_BOOST = 6.0


def name_topic(q):
    """Вопрос об имени — порт nameTopic() страницы."""
    m = str(q or "").lower()
    return any(k in m for k in NAME_TOPIC)


def self_name(speech):
    """Бог называет своё имя — порт selfName() страницы."""
    s = str(speech or "")
    return any(k in s for k in SELF_NAME)


def request_form(q):
    """Форма ответа, которую просит человек (порт requestForm страницы)."""
    m = q.lower()
    for form, kws in REQ_FORMS:
        for k in kws:
            if k in m:
                return form
    return ""


def _verse_key(span):
    """Стих «20:1» → (20, 1): тот же порядок, что cmpVerse на странице."""
    parts = str(span).split(":")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (TypeError, ValueError):
        return (0, 0)


def _f32(x):
    """Округление до float32 — страница хранит вектор в Float32Array."""
    import struct
    return struct.unpack("f", struct.pack("f", x))[0]


def _round6(x):
    """Math.round(x*1e6)/1e6 — как на странице (половинки вверх, не банковское округление)."""
    return math.floor(x * 1e6 + 0.5) / 1e6


def load_profile():
    """Поведенческий профиль реестра — «образ Бога» (P(исход|класс) + форма реакции)."""
    return json.load(io.open(PROFILE, encoding="utf-8"))


def query_tokens(q):
    """Порт queryTokens() из docs/index.html + мост для иврита (HE_BRIDGE)."""
    m = q.lower()
    toks = set()
    for t in re.findall(r"[а-яё-]{4,}", m):
        if t not in RU_STOP:
            toks.add(t)
    for w in re.findall(r"[a-z]{2,}", m):
        if w in EN_BRIDGE:
            toks.add(EN_BRIDGE[w])
    for w in re.findall(r"[א-ת]{3,}", m):
        toks.add(w)
        if w in HE_BRIDGE:
            toks.add(HE_BRIDGE[w])
        else:
            # словоформа не найдена целиком — ищем по началу («נחמי» от «נחם»)
            for p in HE_PREFIX_KEYS:
                if w.startswith(p):
                    toks.add(HE_PREFIX[p])
                    break
    # маркеры убираем из итогового набора (мост EN/HE тоже мог их дать)
    for w in RU_MARKERS:
        toks.discard(w)
    syn = set(toks)
    for t in list(toks):
        for g in RU_SYN:
            if any(x == t or (len(x) >= 4 and (x in t or t in x)) for x in g):
                syn.update(g)
    return syn


def is_proper(w):
    return bool(re.match(r"^[A-ZА-Я]", w)) and len(w) >= 4


def search_texts(e):
    """Тексты эпизода, по которым ищется вопрос: пересказ на русском и речь Бога на иврите.

    Иврит искался только в русском пересказе, где он встречается цитатами
    («למה יהוה» в Judges 21:1) — и вопрос на иврите не находил в корпусе НИЧЕГО
    своего. Теперь ивритское слово ищется в речи Бога: это и есть его дом.
    """
    return (((e.get("summary_ru") or "") + " " + (e.get("god_action") or "")).lower(),
            (e.get("god_speech_plain") or "").lower())


HE_RE = re.compile(r"[א-ת]")


def is_hebrew(t):
    """Слово на иврите? Иврит ищется в речи Бога, а не в русском пересказе."""
    return bool(HE_RE.search(t))


def lexical_scores(q, trigger, episodes):
    """Лексическая часть retrieve() страницы: summary_ru + god_action + речь Бога, буст класса.

    Возвращает тройки (очки, ключ, лексический_сигнал). Сигнал True ставится не на
    любое совпадение, а на ЗНАЧИМОЕ: слово от 4 букв, встречающееся не чаще, чем
    в 5% эпизодов (либо имя из вопроса). По нему страница решает, подключать ли
    вектор: если значимого совпадения нет — лексика молчит, и вектор становится
    единственным тематическим сигналом.

    Язык слова решает, где оно ищется: иврит — в речи Бога, русский — в пересказе.
    Ивритские цитаты внутри русского пересказа («למה יהוה») были шумом: они
    совпадали с ивритским словом вопроса и объявляли тему найденной.
    """
    toks = query_tokens(q)
    props = [w for w in re.split(r"[^A-Za-zА-Яа-яёЁא-ת]+", q) if is_proper(w)]
    cls = trig_class(trigger)
    form = request_form(q)
    fo = FORM_OUTCOMES.get(form) if form else None
    name_q = name_topic(q)
    scored = []
    df = {}
    for key, e in episodes.items():
        txt, htxt = search_texts(e)
        s = 0.0
        hit = False
        matched = []
        for t in toks:
            found = (htxt and t in htxt) if is_hebrew(t) else (t in txt)
            if found:
                # 6+ букв — 10/log, 4–5 — 6/log (короткое, но различимое слово),
                # 3 и меньше — 1/log. Замер: короткое слово с весом 1/log тонуло
                # в бусте класса и векторе, нужные эпизоды уходили в хвост.
                s += (10 / math.log(4 + len(txt)) if len(t) >= 6
                      else 6 / math.log(3 + len(txt)) if len(t) >= 4
                      else 1 / math.log(3 + len(txt)))
                matched.append(t)
        for p in props:
            if len(p) >= 5 and p.lower() in txt:
                s += 6 / math.log(4 + len(txt))
                hit = True
        if e.get("god_speech_plain"):
            s += 2.5
        if name_q and self_name(e.get("god_speech_plain")):
            s += NAME_BOOST
        if cls and e.get("trigger") == cls:
            s += 4
        if fo:
            # форма ответа совпала с просьбой — отдельный сигнал, независимый от темы
            if e.get("outcome") in fo["good"]:
                s += FORM_GOOD
            if e.get("outcome") in fo["bad"]:
                s += FORM_BAD
            # приговор не утешает: на просьбе об утешении или защите таких эпизодов быть не должно
            if form in ("утешение", "защита"):
                speech = e.get("god_speech_plain") or ""
                if any(w in speech for w in DEATH_VERDICT):
                    s += DEATH_PENALTY
        for t in matched:
            df[t] = df.get(t, 0) + 1
        scored.append((s, key, hit, matched))
    # ворота лексики: частотное слово («как» — в 599 эпизодах из 2050) не считается
    # темой, даже если совпало; значимое слово обязано быть и длинным, и не частым
    limit = max(1, int(len(episodes) * LEX_MAX_DF_PCT / 100.0))
    out = []
    for s, key, hit, matched in scored:
        if not hit:
            for t in matched:
                if len(t) >= LEX_MIN_LEN and df.get(t, 0) <= limit:
                    hit = True
                    break
        out.append((s, key, hit))
    return out


_VECTORS = None
_VECTORS_E5 = None
_EMBEDDER = None


def load_nemotron_vectors():
    """Индекс Nemotron: .bin (int8 построчно) + .json (ключи, масштабы).

    Деквантование — ровно как на странице (Float32Array): значение = int8 * scale / 127.
    """
    meta = json.load(io.open(EMB_NEM_META, encoding="utf-8"))
    raw = open(str(EMB_NEM_BIN), "rb").read()
    n, dim = meta["n"], meta["dim"]
    if len(raw) != n * dim:
        raise ValueError("размер индекса Nemotron не совпал: %d против %d" % (len(raw), n * dim))
    vecs = {}
    for i, key in enumerate(meta["keys"]):
        s = meta["scales"][i]
        off = i * dim
        v = [_f32((raw[off + j] - 256 if raw[off + j] > 127 else raw[off + j]) * s / 127)
             for j in range(dim)]
        vecs[key] = v
    return vecs


def load_vectors(dim=None):
    """Индекс эмбеддингов → {book|span.start: вектор}.

    dim — размерность вектора запроса. Сервер настроен — индекс Nemotron (страница
    берёт тот же). Сервер не настроен или индекс недоступен — браузерный e5-small.

    Размерность ОБЯЗАНА совпадать с индексом: zip() в зеркале молча обрезал вектор
    (384 измерения против 2048), и косинусы считались по чужому пространству — меню
    получалось «мусорным», но без всякой ошибки. Страница от такого защищена
    проверкой qv.length === idx.meta.dim, зеркало теперь защищено здесь.
    """
    global _VECTORS, _VECTORS_E5
    if dim is None:
        if EMBED_URL:
            try:
                if _VECTORS is None:
                    _VECTORS = load_nemotron_vectors()
                return _VECTORS
            except Exception as e:
                sys.stderr.write("индекс Nemotron недоступен (%s: %s) — беру e5-small\n"
                                 % (type(e).__name__, e))
        return _load_e5_vectors()
    if dim == 2048:
        try:
            if _VECTORS is None:
                _VECTORS = load_nemotron_vectors()
            return _VECTORS
        except Exception as e:
            sys.stderr.write("индекс Nemotron недоступен (%s: %s) — вектор отключён\n"
                             % (type(e).__name__, e))
            return {}
    if dim == 384:
        try:
            return _load_e5_vectors()
        except Exception as e:
            sys.stderr.write("индекс e5-small недоступен (%s: %s) — вектор отключён\n"
                             % (type(e).__name__, e))
            return {}
    return {}


def _load_e5_vectors():
    """Браузерный индекс e5-small (384 измерения) — запасной путь страницы."""
    global _VECTORS_E5
    if _VECTORS_E5 is None:
        idx = json.load(io.open(EMBEDDINGS, encoding="utf-8"))
        vecs = {}
        for row, meta in zip(idx["rows"], idx["meta"]):
            b = base64.b64decode(row["q"])
            # int8 → float. В JS «c << 24 >> 24» — арифметический сдвиг (знак сохраняется),
            # а в Python «c << 24 >> 24» — логический: байты ≥ 128 становились положительными,
            # норма вектора выходила 3.2 вместо 1.0, и косинусы в зеркале не совпадали
            # с косинусами страницы (меню разъезжалось).
            # Значения округляем до float32 — страница кладёт их в Float32Array.
            vecs["%s|%s" % (meta["b"], meta["s1"])] = [
                _f32((c - 256 if c > 127 else c) * row["s"] / 127) for c in b]
        _VECTORS_E5 = vecs
    return _VECTORS_E5


def _embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        from transformers import AutoTokenizer, AutoModel
        import torch
        tok = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-small")
        mdl = AutoModel.from_pretrained("intfloat/multilingual-e5-small")
        mdl.eval()
        _EMBEDDER = (tok, mdl, torch)
    return _EMBEDDER


def embed_query_server(text):
    """Вектор запроса с сервера эмбеддеров (Nemotron-3-Embed-1B).

    Сервер держит ключ NVIDIA; в зеркало ключ не попадает — только адрес.
    Любая ошибка — None: дальше идёт браузерный запасной путь, как на странице.
    """
    if not EMBED_URL:
        return None
    try:
        import urllib.request
        body = json.dumps({"input": text}).encode("utf-8")
        req = urllib.request.Request(EMBED_URL.rstrip("/") + "/v1/embeddings", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode("utf-8"))
        v = j["data"][0]["embedding"]
        return v if isinstance(v, list) else None
    except Exception as e:
        sys.stderr.write("сервер эмбеддеров не ответил (%s: %s) — беру e5-small\n"
                         % (type(e).__name__, e))
        return None


def embed_query(text):
    """Вектор запроса — как в браузере: «query: » + mean pooling + normalize.

    Считаем тем же int8-ONNX (Xenova/multilingual-e5-small), что грузит страница:
    вектор зеркала совпадает с браузерным до cos = 1.000000. Раньше зеркало считало
    в torch fp32 (cos 0.996), чего хватало, чтобы перетасовать меню — страница давала
    5/14, зеркало 13/14 на одном и том же мозге.
    """
    qv = embed_query_server(text)
    if qv:
        return qv
    if browser_embedder is not None and browser_embedder.available():
        return browser_embedder.query_vector(text)
    tok, mdl, torch = _embedder()
    with torch.no_grad():
        enc = tok(["query: " + text], padding=True, truncation=True, max_length=64, return_tensors="pt")
        out = mdl(**enc).last_hidden_state
        mask = enc["attention_mask"].unsqueeze(-1).float()
        v = (out * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        v = v[0]
        return (v / v.norm()).tolist()


def rank_episodes(q, trigger, episodes, k=6, hybrid=True, note=None):
    """Отбор кандидатов — как на странице: лексика, а вектор только как спасатель.

    ВЕКТОР ПОДКЛЮЧАЕТСЯ ТОЛЬКО КОГДА ЛЕКСИКА НЕ НАШЛА ЗНАЧИМОГО СОВПАДЕНИЯ (слово
    от 4 букв, не чаще, чем в 5% эпизодов). Замер на золотом эталоне (14 вопросов):
    при весах 0; 0,05; 0,1; 0,25; 0,5; 1,0 меню содержало эталон 13/14 — прироста не
    даёт ни один вес, но меню переставляется (одинаковых меню у весов 0 и 0,25 — 1 из
    14). Хуже: браузер считает вектор int8-WASM, зеркало — int8-CPU, и для длинных
    запросов косинус векторов падает до 0,9987: страница и зеркало давали разное меню,
    то есть замер описывал не страницу. Теперь обычный вопрос — чистая лексика
    (детерминированно, быстро, без загрузки модели), а вектор работает там, где
    лексика молчит, и тогда он — единственный тематический сигнал.

    hybrid=False — вектор не подключать вовсе (быстрый офлайн-режим).
    """
    scored = lexical_scores(q, trigger, episodes)
    lex_hit = any(hit for _, _, hit in scored)
    if hybrid and not lex_hit:
        try:
            qv = embed_query(q)
            # индекс берём под размерность вектора запроса: сервер отвечает 2048,
            # браузерный e5 — 384; смешивать нельзя (см. load_vectors)
            vecs = load_vectors(len(qv)) if qv else {}
            cos_rows = []
            for s, key, _ in scored:
                v = vecs.get(key)
                if v is not None and len(v) == len(qv):
                    cos_rows.append((s, key, sum(x * y for x, y in zip(qv, v))))
            if len(cos_rows) > 20:
                mean = sum(c[2] for c in cos_rows) / len(cos_rows)
                std = math.sqrt(sum((c[2] - mean) ** 2 for c in cos_rows) / len(cos_rows)) or 1e-9
                cos_map = {key: (c - mean) / std for _, key, c in cos_rows}
                # тройку (s, key, hit) сохраняем: ниже строка ждёт именно её,
                # а раньше здесь терялся hit и отбор падал с ValueError —
                # на любом вопросе, по которому лексика молчит.
                scored = [(s + VEC_W * cos_map[key] if key in cos_map else s, key, hit)
                          for s, key, hit in scored]
        except Exception as e:
            if note:
                note("векторный поиск недоступен (%s: %s) — только лексика" % (type(e).__name__, e))
    scored = [(s, key) for s, key, _ in scored]
    # при равных очках — книга и стих: иначе порядок зависит от обхода корпуса,
    # и страница с зеркалом дают разное меню (а с ним — разный ответ).
    # Очки округляем до 1e-6: страница копит в double, зеркало — в double же, но
    # порядок сложения и float32-векторы дают разницу в последних битах, а на
    # равных очках это переставляло двух кандидатов. Книги сравниваем без локали
    # (сначала нижний регистр, потом как есть) — localeCompare на странице зависел
    # от локали браузера и ставил «genesis» иначе, чем зеркало.
    # При равных очках — книга по алфавиту (без локали), затем стих числами.
    # Замер на золотом эталоне (14 вопросов): алфавитный порядок дал меню 14/14,
    # канонический (устойчивая сортировка по обходу корпуса: Тора → Невиим →
    # Кетувим) — 13/14. Канонический порядок ставил «II_Chronicles» и «I_Samuel»
    # выше «Exodus» и «genesis», и при равных очках (класс обращения + форма +
    # речь) решал, кто попадёт в меню.
    scored.sort(key=lambda kv: (-_round6(kv[0]), kv[1].split("|")[0].lower(),
                                kv[1].split("|")[0],
                                _verse_key(kv[1].split("|")[1])))
    return [key for _, key in scored[:k]]


# ─────────────────────────────────────────────────────────────────────────────
# Блоки и разбор шага выбора — формат символ в символ как на странице
# ─────────────────────────────────────────────────────────────────────────────
def candidate_block(q, ctx):
    form = request_form(q)
    lines = ["ВОПРОС ЧЕЛОВЕКА: " + q]
    if form:
        lines.append("ФОРМА ОТВЕТА, КОТОРУЮ ПРОСИТ ЧЕЛОВЕК: " + form.upper())
    lines += ["", "КАНДИДАТЫ:"]
    for i, c in enumerate(ctx, 1):
        lines.append("S%d [%s %s]" % (i, c["book"], c["span"]["start"]))
        lines.append("   О ЧЁМ: " + c["summary_ru"])
        if c.get("trigger"):
            lines.append("   класс обращения: " + TRIG_RU.get(c["trigger"], c["trigger"]))
        # исход не печатаем — форма отклика и исходы приходят из блока [ACTION]
        lines.append("   речь: " + c["god_speech_plain"])
        if c.get("nikud"):
            lines.append("   огласовка: " + c["nikud"])
    return "\n".join(lines)


def action_block(cls, prof):
    """Блок [ACTION] — «образ Бога» для класса обращения (форма реакции + исходы).

    Уходит в шаг выбора: задаёт, какую форму отклика искать в эпизодах,
    и не даёт подмешать в цитату слова вне эпизода.

    Вероятности исходов — сглаженные (outcome_p_smooth, Дирихле alpha=5 к
    базовой частоте): сырые доли на малых классах дают 0 % и 100 % и читаются
    моделью как правило, хотя это шум. Ключ outcome_p остаётся в профиле для
    совместимости, но в блок выбора идёт сглаженная оценка.
    """
    bt = (prof or {}).get("by_trigger", {}).get(cls)
    rm = (prof or {}).get("response_modes", {}).get(cls)
    if not bt or not rm:
        return ""
    probs = bt.get("outcome_p_smooth") or bt["outcome_p"]
    outs = sorted(probs.items(), key=lambda kv: -kv[1])[:4]
    dist = sorted(rm["distribution"].items(), key=lambda kv: -kv[1])
    outs_txt = ", ".join("%s %d%%" % (OUT_RU.get(k, k), round(v * 100)) for k, v in outs)
    dist_txt = ", ".join("%s %d%%" % (MODE_RU.get(k, k), round(v * 100)) for k, v in dist)
    return ("[ACTION] класс обращения: %s (%d эпизодов в реестре)\n"
            "форма реакции по реестру: %s\nисходы по реестру: %s"
            % (TRIG_RU.get(cls, cls), bt["n"], dist_txt, outs_txt))


def episode_block(c):
    lines = ["СТИХ: [%s %s]" % (c["book"], c["span"]["start"]),
             "речь Бога: " + c["god_speech_plain"]]
    if c.get("nikud"):
        lines.append("огласовка: " + c["nikud"])
    lines.append("о чём: " + c["summary_ru"])
    return "\n".join(lines)


def pick_index(raw, n):
    """Номер выбранного кандидата из ответа шага выбора (как pickIndex() страницы)."""
    m = re.search(r"[Ss]\s*(\d+)|(\d+)", raw or "")
    if not m:
        return 1
    v = int(m.group(1) or m.group(2))
    return v if 1 <= v <= n else 1


def parse_sections(raw):
    """Разбор секций ответа — как parseSections() страницы (та же логика разрезки)."""
    out = {}
    text = raw or ""
    for tag in SECTION_TAGS:
        i = text.find(tag)
        if i < 0:
            continue
        rest = text[i + len(tag):]
        end = len(rest)
        for t2 in SECTION_TAGS:
            j = rest.find(t2)
            if 0 <= j < end:
                end = j
        out[tag] = rest[:end].strip()
    return out


def count_sections(raw):
    """Сколько содержательных слоёв пришло в ответе (как parseSections() страницы).

    Считаем ПЯТЬ слоёв, которые видит пользователь ([HEBREW], [NIKKUD], [Russian],
    [English], [Hebrew Modern]), и только НЕПУСТЫЕ: пустой слой — это отсутствующий
    слой (страница его не рисует). Секция [SOURCES] не в счёт: источник показывается
    из реестра, а её отсутствие у модели не лишает читателя ничего (замер потока
    2026-10-27: ответ 5/6 секций с полным текстом заменялся прецедентом корпуса).
    """
    secs = parse_sections(raw)
    return sum(1 for t in CONTENT_TAGS if secs.get(t))


def is_degenerate(raw):
    """Петля в ответе: одна короткая последовательность повторяется много раз.

    Так модель вырождается на коротких репликах: русский слой уходит в повтор
    и ответ упирается в лимит токенов (finish_reason=length) — секций 3/6.
    Нормальный ответ — около сотни слов, и десять одинаковых 4-грамм в нём
    не бывает.
    """
    words = (raw or "").split()
    if len(words) < 60:
        return False
    for n in (4, 5, 6):
        counts = {}
        for i in range(len(words) - n + 1):
            key = " ".join(words[i:i + n])
            counts[key] = counts.get(key, 0) + 1
            if counts[key] >= 10:
                return True
    return False


def spoken_candidates(ctx, limit=6):
    """Кандидаты для выбора: только эпизоды, где Бог говорил, не больше limit.

    В 807 эпизодах из 2050 поля god_speech_plain нет — цитировать там нечего,
    и модель выбирала именно их (и получала отказ сверки). Поэтому пул берётся
    ШИРОКО (18) и фильтруется уже после: на шести найденных фильтр оставлял
    модели 1–3 кандидата вместо шести.
    """
    spoken = [c for c in ctx if (c.get("god_speech_plain") or "").strip()]
    pool = spoken or list(ctx)
    return pool[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Сеть: два вызова по схеме
# ─────────────────────────────────────────────────────────────────────────────
def ask_brain(system, user, url, key, timeout=DEFAULT_TIMEOUT, model="god-brain",
              temperature=0.15, max_tokens=900, retries=1, extra=None, meta=None):
    """Запрос к OpenAI-совместимому эндпойнту мозга. Возвращает текст ответа.

    extra — дополнительные поля тела запроса (например repeat_penalty). Если сервер
            такой параметр не знает (400/422), запрос повторяется без него — страница
            и зеркало должны работать и с тем мозгом, который параметр не понимает.
    meta  — словарь, куда кладётся finish_reason ответа: по нему видно, что ответ
            упёрся в лимит токенов (finish=length), а не просто не дописан.
    """
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra:
        payload.update(extra)
    hdr = {"Content-Type": "application/json"}
    if key:
        hdr["Authorization"] = "Bearer " + key
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = None
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(url, data=body, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            choice = data["choices"][0]
            if meta is not None:
                meta["finish_reason"] = choice.get("finish_reason")
            return choice["message"]["content"]
        except urllib.error.HTTPError as e:
            if extra and e.code in (400, 422):
                # сервер не знает параметр — тот же запрос без него
                payload = dict((k, v) for k, v in payload.items() if k not in extra)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                extra = None
                if meta is not None:
                    meta["extra_dropped"] = True
                continue
            last = e
        except Exception as e:
            last = e
        if attempt >= retries:
            raise last
        attempt += 1
        import time as _t
        _t.sleep(2)


def two_stage(q, ctx, url, key, timeout=DEFAULT_TIMEOUT, model="god-brain", memory=None,
              profile=None, action=True):
    """Полный проход схемы: выбор эпизода → формулировка из него.

    В шаг выбора уходит блок [ACTION] — поведенческий профиль класса обращения
    («образ Бога»): форма реакции и вероятности исходов по реестру.

    Возвращает {"raw_sel", "index", "chosen", "raw", "user_form", "action"}.
    """
    cls = trig_class(classify(q))
    cand = spoken_candidates(ctx)
    act = action_block(cls, profile if profile is not None else load_profile()) if action else ""
    sel_user = candidate_block(q, cand) + ("\n\n" + act if act else "")
    raw_sel = ask_brain(SYS_SELECT, sel_user, url, key,
                        timeout=timeout, model=model,
                        temperature=SELECT_TEMP, max_tokens=SELECT_MAX_TOKENS)
    idx = pick_index(raw_sel, len(cand))
    chosen = cand[idx - 1]
    user_form = "ВОПРОС ЧЕЛОВЕКА: %s\n\n%s" % (q, episode_block(chosen))
    if MEM_IN_FORM and memory:
        user_form += "\n\n" + memory
    user_form += "\n\nОтветь шестью секциями."
    # Формулировка. Неполный ответ — не галлюцинация, а зацикливание модели: русский
    # слой повторяет одну фразу до лимита токенов и ответ приходит с 3–4 секциями из
    # шести. Ответ против: штраф за повтор (FORM_REPEAT_PENALTY) и разная температура
    # на повторах (FORM_RETRY_TEMPS) — три одинаковых запроса были по сути одной
    # партией, и в провале потока все три выродились одинаково. Берём ответ с большим
    # числом содержательных слоёв (пять; [SOURCES] — служебная, источник из реестра).
    # Страница делает ровно то же — см. docs/index.html, liveReply.
    best_raw, best_n, best_finish = "", -1, None
    form_attempts = 0
    for temp in FORM_RETRY_TEMPS:
        form_attempts += 1
        meta = {}
        raw_try = ask_brain(SYS_PROMPT, user_form, url, key,
                            timeout=timeout, model=model,
                            temperature=temp, max_tokens=FORM_MAX_TOKENS,
                            extra={"repeat_penalty": FORM_REPEAT_PENALTY}, meta=meta)
        n = count_sections(raw_try)
        if n > best_n:
            best_raw, best_n, best_finish = raw_try, n, meta.get("finish_reason")
        if best_n >= CONTENT_FULL:
            break
    raw = best_raw
    complete = best_n >= CONTENT_FULL
    return {"raw_sel": raw_sel, "index": idx, "chosen": chosen, "raw": raw,
            "user_form": user_form, "action": act, "cls": cls,
            "form_attempts": form_attempts, "form_finish": best_finish,
            "complete": complete, "degenerate": (not complete) and is_degenerate(raw)}


# ─────────────────────────────────────────────────────────────────────────────
# Самопроверка (сеть не нужна)
# ─────────────────────────────────────────────────────────────────────────────
def run_selftest():
    checks = []

    def chk(name, cond, strict=True):
        checks.append((name, bool(cond), strict))
        print(("PASS" if cond else ("FAIL" if strict else "WARN")) + "  " + name)

    print("=== selftest: схема ответа (офлайн, без сети) ===")

    chk("SYS_SELECT достаётся со страницы", "выбрать ОДИН эпизод" in SYS_SELECT)
    chk("SYS_PROMPT достаётся со страницы", "ТОЛЬКО из указанного эпизода" in SYS_PROMPT)
    chk("SYS_SELECT и SYS_PROMPT — разные промпты", SYS_SELECT != SYS_PROMPT)
    chk("в SYS_PROMPT шесть секций", all(t in SYS_PROMPT for t in
        ["[HEBREW]", "[NIKKUD]", "[Russian]", "[English]", "[Hebrew Modern]", "[SOURCES]"]))

    c = {"book": "Psalms", "span": {"start": "95:1"}, "summary_ru": "Пойте Господу, ибо Он милосерд",
         "god_speech_plain": "הזמרו ליהוה כי טוב זמרו לאלהינו", "nikud": "הַזְמִרוּ לַיהוָה כִּי־טוֹב"}
    blk = candidate_block("вопрос?", [c])
    chk("блок кандидатов начинается с вопроса", blk.startswith("ВОПРОС ЧЕЛОВЕКА: вопрос?"))
    chk("в блоке кандидатов есть речь", "речь: הזמרו" in blk)
    chk("в блоке кандидатов есть огласовка", "огласовка: הַזְמִרוּ" in blk)
    c2 = dict(c, trigger="gratitude", outcome="blessing")
    chk("в блоке кандидатов есть класс обращения",
        "класс обращения: благодарность" in candidate_block("вопрос?", [c2]))
    chk("исход в блоке кандидатов НЕ печатается",
        "исход:" not in candidate_block("вопрос?", [c2]),
        "подпись исхода уводила выбор модели от темы вопроса (замер на золотом эталоне)")
    ep = episode_block(c)
    chk("блок эпизода начинается со стиха", ep.startswith("СТИХ: [Psalms 95:1]"))
    chk("в блоке эпизода есть речь Бога", "речь Бога: הזמרו" in ep)
    chk("в блоке эпизода есть «о чём»", "о чём: Пойте Господу" in ep)

    chk("выбор «S3» → 3", pick_index("S3", 6) == 3)
    chk("выбор «s 2» → 2", pick_index("s 2", 6) == 2)
    chk("выбор «4» → 4", pick_index("4", 6) == 4)
    chk("выбор с болтовнёй → первый номер", pick_index("S2 (проступков 1)", 6) == 2)
    chk("выбор без числа → 1", pick_index("не знаю", 6) == 1)
    chk("выбор вне диапазона → 1", pick_index("S99", 6) == 1)

    # форма ответа: что человек ПРОСИТ (утешить/простить/направить/защитить)
    chk("форма «утешь меня в скорби» → утешение", request_form("утешь меня в скорби") == "утешение")
    chk("форма «прости мне мой грех» → прощение", request_form("прости мне мой грех") == "прощение")
    chk("форма «научи меня твоему пути» → направление", request_form("научи меня твоему пути") == "направление")
    chk("форма «сохрани меня от врагов» → защита", request_form("сохрани меня от врагов") == "защита")
    chk("форма «благодарю тебя» → хвала", request_form("благодарю тебя за всё") == "хвала")
    chk("форма «что такое завет» → завет", request_form("что такое завет с тобой?") == "завет")
    chk("страх о смерти — не просьба об утешении", request_form("я боюсь умереть") == "")
    chk("форма печатается в блоке кандидатов",
        "ФОРМА ОТВЕТА, КОТОРУЮ ПРОСИТ ЧЕЛОВЕК: УТЕШЕНИЕ" in candidate_block("утешь меня", [c]))
    chk("без формы строка формы не печатается",
        "ФОРМА ОТВЕТА" not in candidate_block("как тебя зовут?", [c]))

    eps = {"|".join([b, e["span"]["start"]]): dict(e, book=b)
           for b, arr in json.load(io.open(MASTER_CORPUS, encoding="utf-8")).items() for e in arr}
    hits = rank_episodes("благодарю тебя за всё", "gratitude", eps, 6, hybrid=False)
    chk("лексический отбор детерминирован", hits == rank_episodes("благодарю тебя за всё", "gratitude", eps, 6, hybrid=False))
    chk("лексический отбор дал кандидатов", len(hits) == 6)

    # «спасатель»: вопрос, по которому лексика молчит, идёт по векторному пути.
    # Раньше здесь терялся третий элемент тройки — отбор падал с ValueError.
    saved_load, saved_embed = load_vectors, embed_query
    try:
        fake = {k: [0.0, 0.0, 0.0, 0.0] for k in list(eps.keys())[:60]}
        globals()["load_vectors"] = lambda: fake
        globals()["embed_query"] = lambda q: [1.0, 0.0, 0.0, 0.0]
        quiet = "кхммщщ ззз"
        chk("вопрос без лексического совпадения найден",
            not any(hit for _, _, hit in lexical_scores(quiet, "", eps)), "")
        rescue_hits = rank_episodes(quiet, "", eps, 6, hybrid=True)
        chk("спасательный путь (вектор) не роняет отбор", len(rescue_hits) == 6,
            str(rescue_hits[:2]))
    finally:
        globals()["load_vectors"] = saved_load
        globals()["embed_query"] = saved_embed

    ctx = build_context(eps, load_nikud(), hits)
    chk("контекст собран", len(ctx) == 6 and "god_speech_plain" in ctx[0])
    chk("контекст обрезан по 300", all(len(c["god_speech_plain"]) <= 300 for c in ctx))
    spoken = spoken_candidates(ctx)
    chk("кандидаты для выбора — только с речью Бога",
        all((c.get("god_speech_plain") or "").strip() for c in spoken))
    chk("кандидатов для выбора — не больше шести", len(spoken_candidates(ctx * 4)) <= 6)

    # приговор не утешает: на просьбе об утешении смертный приговор в меню не попадает
    comfort = rank_episodes("утeшь меня в скорби".replace("е", "е"), "distress", eps, 18, hybrid=False)
    death_keys = [k for k, e in eps.items()
                  if any(w in (e.get("god_speech_plain") or "") for w in DEATH_VERDICT)]
    chk("в речи Бога ровно три смертных приговора", len(death_keys) == 3, str(death_keys))
    comfort_menu = comfort[:12]
    chk("смертный приговор вытеснен из меню утешения",
        not any(k in comfort_menu for k in death_keys),
        "в меню: %s" % comfort_menu)
    chk("приговор остаётся в ответе на страх о смерти",
        "II_Kings|20:1" in rank_episodes("я боюсь умереть", "distress", eps, 6, hybrid=False))

    # «образ Бога»: класс обращения → класс реестра, блок [ACTION] из профиля
    chk("«confession» отображается в класс intercession", trig_class("confession") == "intercession")
    chk("«covenant» отображается в класс covenant_follow_up",
        trig_class("covenant") == "covenant_follow_up")
    chk("остальные классы не переименовываются", trig_class("complaint") == "complaint")
    prof = load_profile()
    chk("профиль реестра загружен", prof.get("metadata", {}).get("episodes") == 2050)
    chk("в профиле 12 классов реакции", len(prof.get("response_modes", {})) == 12)
    act = action_block("complaint", prof)
    chk("блок [ACTION] начинается с класса", act.startswith("[ACTION] класс обращения: жалоба"))
    chk("в блоке [ACTION] есть форма реакции", "форма реакции по реестру:" in act)
    chk("в блоке [ACTION] есть исходы", "исходы по реестру:" in act)
    chk("для неизвестного класса блока нет", action_block("нет_такого", prof) == "")
    chk("в SYS_SELECT есть правило про [ACTION]", "[ACTION]" in SYS_SELECT)

    # тема «имя»: вопрос об имени обязан привести к эпизоду, где Бог называет имя
    name_hits = rank_episodes("ты же имеешь имя — как оно звучит?", "", eps, 18, hybrid=False)
    chk("вопрос об имени → в пуле эпизод самоименования",
        "Exodus|3:13" in name_hits, str(name_hits[:6]))
    chk("вопрос об имени → эпизод самоименования первый в пуле",
        name_hits and name_hits[0] == "Exodus|3:13", str(name_hits[:3]))
    chk("вопрос НЕ об имени → буст самоименования не применяется",
        "Exodus|3:13" not in rank_episodes("утешь меня в скорби", "distress", eps, 18,
                                           hybrid=False), "")
    selfn = [k for k, e in eps.items() if self_name(e.get("god_speech_plain"))]
    chk("эпизодов самоименования в корпусе ровно три", len(selfn) == 3, str(selfn))
    chk("в SYS_PROMPT есть запрет дополнять короткую речь из памяти",
        "короткая" in SYS_PROMPT and "из памяти" in SYS_PROMPT, "")

    ok = sum(1 for _, c, s in checks if c)
    print("\nИТОГ: %d/%d проверок — %s" % (ok, len(checks), "PASS" if ok == len(checks) else "FAIL"))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(run_selftest())
    print(__doc__)
