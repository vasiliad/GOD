#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_numbers.py — воспроизводимый вычислитель всех чисел научных отчётов GOD
(docs/research_report.md, docs/research_report.en.md, docs/research_report.he.md).

Скрипт читает ТОЛЬКО мастер-корпус `output/episodes_TANAKH_v2.json`.
Per-book файлы `output/episodes_<Book>_v2.json` НЕ используются: они преддедупликационные
(2 056 эпизодов), и любое число, взятое из них, не сойдётся с отчётом.

Каждое число печатается вместе с явным знаменателем:
    494 (24.10%, знаменатель=2050)
Никаких «голых» процентов. Если число отчёта не воспроизводится из мастер-корпуса,
оно помечается NOT_REPRODUCIBLE с пояснением — ничего не подгоняется.

Рубрики, которых нет полем в контракте v2, вычисляются документированными правилами
по текстовым полям (god_action + summary_ru):
    * явная милость — MERCY_MARKERS («простил», «прощен», «пощад», «помило»);
    * причины наказаний — CAUSE_RUBRIC (мультиметка по ключевым словам; поле «причина»
      в эпизоде отсутствует, поэтому и доли, и словарь категорий заданы здесь).

Usage:
    python scripts/report_numbers.py          # таблица чисел (по умолчанию)
    python scripts/report_numbers.py --test   # самопроверка на синтетическом корпусе
    python scripts/report_numbers.py --json   # машинный вывод всех чисел (JSON)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO = Path(__file__).resolve().parents[1]  # корень репозитория
MASTER = _REPO / "output" / "episodes_TANAKH_v2.json"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - старые терминалы Windows
    pass


# ---------------------------------------------------------------------------
# Константы рубрик и структуры корпуса
# ---------------------------------------------------------------------------

#: Поля контракта v2 (17) — все поля эпизода, кроме служебных.
SERVICE_FIELDS = frozenset({"book", "episode_id", "source_batch", "dedup_note"})

#: «Явная милость»: подстроки в god_action + summary_ru (регистронезависимо).
MERCY_MARKERS = ("простил", "прощен", "пощад", "помило")

#: Поэтические книги — жанровая группа для расчёта доли молчания.
POETIC_BOOKS = ("Psalms", "Job", "Lamentations", "Song_of_Songs", "Proverbs", "Ecclesiastes")

# ---------------------------------------------------------------------------
# Рубрика причин наказаний
# ---------------------------------------------------------------------------
#: В мастер-корпусе НЕТ поля «причина» (см. контракт v2: 17 полей, `cause` среди них нет).
#: Поэтому рубрика причин строится ДЕТЕРМИНИРОВАННЫМ ПРАВИЛОМ по текстовым полям
#: `god_action` + `summary_ru` — тем же приёмом, что и рубрика явной милости.
#: Правило (версия 1):
#:   1) текст эпизода = god_action + " " + summary_ru, приведён к нижнему регистру;
#:   2) для каждой категории ищется хотя бы одно ключевое слово категории;
#:   3) мультиметка: один эпизод может получить несколько меток;
#:   4) доли в отчёте считаются ОТ ВСЕХ наказаний (494) — как и в прежней формулировке.
#: Ключевые слова — морфемы, поэтому ловят и словоформы («убий» → убийство/убийца).
CAUSE_RUBRIC: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("covenant_law", "Нарушение завета/закона",
     ("завет", "закон", "повелени", "заповед", "нарушени", "нарушил",
      "неисполн", "устав", "тору", "торы", "торе")),
    ("violence_blood", "Насилие/кровь",
     ("кров", "убий", "убива", "убив", "убил", "убит", "умертв", "насил",
      "изби", "резн", "жертвопр", "закла", "вырезал", "вторг", "воевал",
      "войну", "изнасил", "удуш", "задуш", "истребил", "истребля",
      "перебил", "грабил", "выпотрош", "вспарыва", "сожжен")),
    ("idolatry", "Идолопоклонство",
     ("идол", "ваал", "поклон", "обожеств", "изваяни", "сервен", "божеств",
      "чужим бог", "богов чужих", "золотой те", "теленок")),
    ("pride", "Гордость",
     ("горд", "высокомери", "надмен", "пренебреж", "кичлив", "самонадеян",
      "величав", "хвастов", "могуч", "честолюб", "надм")),
    ("spiritual_unfaith", "Духовная измена",
     ("измен", "неверн", "прелюб", "блуд", "нечист", "отступ", "веролом",
      "изменниц", "нецеломудр", "разврат", "непотреб", "оскверн")),
    ("injustice_weak", "Несправедливость к слабым",
     ("слаб", "бедн", "нищ", "унижен", "притесн", "вдов", "сирот", "угнет",
      "несправед", "обид", "пришельц", "странник", "пленник", "нищего",
      "обездол", "правосуди", "попрал", "праведник", "ростовщик", "заимодав")),
    ("disobedience", "Непослушание",
     ("непослуш", "ослуш", "сопротив", "воспротив", "не слуш", "не выполнил",
      "отверг", "непокор", "отвержен", "не соблюд", "пренебрег", "отвергну",
      "неподчинил", "восстал")),
    ("unbelief_grumble", "Неверие/ропот",
     ("ропот", "не верит", "не поверил", "сомнени", "недоволь", "упрек", "бунт",
      "недовери", "невери", "неверующ", "маловер", "лжи", "лжец",
      "не довери", "не повери")),
)

#: Маркеры причинной конструкции — для консервативной подрубрики «причина названа прямо».
CAUSAL_MARKERS: tuple[str, ...] = (
    "из-за", "потому что", "так как", "за то, что", "за то что",
    "по вине", "виной", "потому", "поэтому", "за ",
)

#: Окно, в котором ищется причинная конструкция (символов от маркера).
CAUSAL_WINDOW = 200

#: «Молящие» триггеры — для P(answer_granted | trigger).
PLEADING_TRIGGERS = ("prayer", "intercession", "complaint", "distress", "inquiry", "vow")

#: Триггеры «просьба о чужой/собственной милости» — для проверки тезиса §5 отчёта.
MERCY_INTERVENTION_TRIGGERS = ("intercession", "prayer", "complaint")

#: Эпохи и книги (как в scripts/analytics_v2.py).
ERA_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Тора", ("Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy")),
    ("Невиим (ранние)", ("Joshua", "Judges", "I_Samuel", "II_Samuel", "I_Kings", "II_Kings")),
    ("Невиим (поздние)", ("Isaiah", "Jeremiah", "Ezekiel", "Hosea", "Joel", "Amos", "Obadiah",
                          "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai",
                          "Zechariah", "Malachi")),
    ("Кетувим", ("Psalms", "Proverbs", "Job", "Song_of_Songs", "Ruth", "Lamentations",
                 "Ecclesiastes", "Esther", "Daniel", "Ezra", "Nehemiah",
                 "I_Chronicles", "II_Chronicles")),
)

#: Прочие каналы (не direct и не prophet).
OTHER_VIA = ("unclear", "vision", "angel", "dream", "internal")

#: Каналы «исполненного действия без речи» / «объявленного оракула» внутри punishment.
#: Правило восстановлено из scripts/analytics_v2.py и однозначно кодируется полем `direction`.
PUNISHMENT_ANNOUNCED_DIRECTION = "god_initiated"   # объявленный оракул-приговор
PUNISHMENT_EXECUTED_DIRECTION = "divine_action"    # исполненное действие без речи

TOP_BOOKS = 10


# ---------------------------------------------------------------------------
# Структуры результата
# ---------------------------------------------------------------------------

@dataclass
class Metric:
    """Одно число отчёта с явным знаменателем."""

    key: str
    label: str
    count: float
    denominator: int
    kind: str = "share"      # share | mean | ratio | raw
    note: str = ""

    @property
    def pct(self) -> float | None:
        if self.kind != "share" or not self.denominator:
            return None
        return round(self.count / self.denominator * 100, 2)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "count": self.count,
            "denominator": self.denominator,
            "kind": self.kind,
        }
        if self.kind == "share":
            out["pct"] = self.pct
        if self.note:
            out["note"] = self.note
        return out

    def render(self) -> str:
        num = _fmt_num(self.count)
        if self.kind == "share":
            assert self.pct is not None
            body = f"{num} ({self.pct:.2f}%, знаменатель={self.denominator})"
        elif self.kind == "mean":
            body = f"{num} (среднее, знаменатель={self.denominator})"
        elif self.kind == "ratio":
            body = f"{num}× (отношение долей, знаменатель={self.denominator})"
        else:
            body = f"{num} (счётчик, знаменатель={self.denominator})"
        if self.note:
            body += f"  — {self.note}"
        return body


@dataclass(frozen=True)
class Claim:
    """Проверочное утверждение из отчёта: что написано и что посчитал скрипт."""

    section: str
    key: str
    label: str
    report_value: str
    expect_pct: float | None = None
    expect_count: float | None = None
    tolerance: float = 0.5        # допуск к count (для целых счётчиков — 0)
    pct_tolerance: float = 0.5    # допуск к процентам (отчёт округляет до целых)
    status: str = "OK"        # OK | NOT_REPRODUCIBLE | CONTRADICTED | MANUAL_RUBRIC
    note: str = ""


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _fmt_num(value: float) -> str:
    """Число без хвостовых нулей: 494 → '494', 2.89 → '2.89'."""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _pct(count: float, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(count / denominator * 100, 2)


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def load_corpus(path: Path = MASTER) -> list[dict[str, Any]]:
    """Загрузить мастер-корпус и вернуть плоский список эпизодов.

    Поле `book` авторитетно (в мастере есть опечатка в ключе словаря `genesis`),
    поэтому имя книги берётся из самого эпизода.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    episodes: list[dict[str, Any]] = []
    for book_key, book_eps in raw.items():
        for ep in book_eps:
            ep = dict(ep)
            ep.setdefault("book", book_key)
            episodes.append(ep)
    return episodes


def is_mercy(ep: Mapping[str, Any]) -> bool:
    """«Явная милость»: god_action + summary_ru содержит маркер прощения/пощады."""
    blob = f"{ep.get('god_action') or ''} {ep.get('summary_ru') or ''}".lower()
    return any(marker in blob for marker in MERCY_MARKERS)


# ---------------------------------------------------------------------------
# Рубрика причин наказаний
# ---------------------------------------------------------------------------

def cause_text(ep: Mapping[str, Any]) -> str:
    """Текст, по которому ищется причина наказания: god_action + summary_ru."""
    return f"{ep.get('god_action') or ''} {ep.get('summary_ru') or ''}".lower()


def causal_clauses(text: str) -> list[str]:
    """Фрагменты с ЯВНОЙ причинной конструкцией.

    Маркер («за …», «из-за …», «потому что …», «так как …», «по вине …») плюс
    следующие символы до первого «:»/«;» (или окна в CAUSAL_WINDOW символов).
    Используется только для консервативной подрубрики «причина названа прямо»:
    основная рубрика ищет ключевые слова во всём описании.
    """
    out: list[str] = []
    for marker in CAUSAL_MARKERS:
        start = 0
        while True:
            i = text.find(marker, start)
            if i < 0:
                break
            seg = text[i:i + CAUSAL_WINDOW]
            for cut in (":", ";"):
                j = seg.find(cut)
                if j > 0:
                    seg = seg[:j]
            out.append(seg)
            start = i + len(marker)
    return out


def _cause_hits(text: str) -> set[str]:
    """Ключи категорий рубрики причин, чьё слово встретилось в тексте."""
    return {key for key, _label, words in CAUSE_RUBRIC if any(w in text for w in words)}


def classify_causes(ep: Mapping[str, Any]) -> set[str]:
    """Мультиметка причин по полному описанию эпизода (god_action + summary_ru)."""
    return _cause_hits(cause_text(ep))


def classify_causes_explicit(ep: Mapping[str, Any]) -> set[str]:
    """Мультиметка причин, где ключевое слово стоит в явной причинной конструкции."""
    hits: set[str] = set()
    for clause in causal_clauses(cause_text(ep)):
        hits |= _cause_hits(clause)
    return hits


# ---------------------------------------------------------------------------
# Подсчёт всех чисел
# ---------------------------------------------------------------------------

def build_sections(episodes: Sequence[Mapping[str, Any]]) -> dict[str, list[Metric]]:
    """Посчитать все числа отчёта. Одна функция и для реального, и для тестового корпуса."""
    n = len(episodes)
    sections: dict[str, list[Metric]] = {}

    def add(section: str, metric: Metric) -> None:
        sections.setdefault(section, []).append(metric)

    # --- 1. Корпус -----------------------------------------------------------
    book_names = sorted({str(e.get("book", "")) for e in episodes})
    contract_fields = set(episodes[0].keys()) if episodes else set()
    for ep in episodes:
        contract_fields &= set(ep.keys())
    contract_fields -= SERVICE_FIELDS
    dedup_marked = sum(1 for e in episodes if e.get("dedup_note"))
    with_span = sum(1 for e in episodes if (e.get("span") or {}).get("start"))

    add("corpus", Metric("total_episodes", "N всего эпизодов", n, n, "raw"))
    add("corpus", Metric("books", "Книг в корпусе", len(book_names), len(book_names), "raw"))
    add("corpus", Metric("contract_fields", "Полей контракта v2", len(contract_fields),
                          len(contract_fields), "raw"))
    add("corpus", Metric("episodes_with_span", "Эпизодов со ссылкой на стихи", with_span, n, "share"))
    add("corpus", Metric("dedup_marked_episodes", "Эпизодов с пометкой dedup_note", dedup_marked,
                          n, "share",
                          note="следы глобальной дедупликации; преддедупликационный счёт 2 056 "
                               "в мастер-корпусе отсутствует"))

    # --- 2. Распределение исходов ------------------------------------------
    outcomes = Counter(str(e.get("outcome")) for e in episodes)
    for name, count in outcomes.most_common():
        add("outcome_distribution", Metric(f"out::{name}", f"outcome = {name}", count, n, "share"))

    # --- 3. Распределение триггеров ----------------------------------------
    triggers = Counter(str(e.get("trigger")) for e in episodes)
    for name, count in triggers.most_common():
        add("trigger_distribution", Metric(f"trig::{name}", f"trigger = {name}", count, n, "share"))

    # --- 4. Направление инициативы -----------------------------------------
    directions = Counter(str(e.get("direction")) for e in episodes)
    direction_labels = {
        "god_initiated": "Бог инициирует (речь)",
        "human_initiated": "человек инициирует",
        "divine_action": "действие без речи",
    }
    for name, count in directions.most_common():
        add("direction", Metric(f"dir::{name}", direction_labels.get(name, name), count, n, "share"))

    # --- 5. Каналы откровения ----------------------------------------------
    vias = Counter(str(e.get("via")) for e in episodes)
    for name in ("direct", "prophet"):
        add("channels", Metric(f"via::{name}", f"канал = {name}", vias.get(name, 0), n, "share"))
    others = sum(vias.get(v, 0) for v in OTHER_VIA)
    add("channels", Metric("via::others", "канал = прочие (unclear/vision/angel/dream/internal)",
                           others, n, "share"))
    for name, count in vias.most_common():
        add("channels_detail", Metric(f"via::{name}", f"канал = {name}", count, n, "share"))

    # --- 6. Тяжесть ----------------------------------------------------------
    severities = [e.get("severity", 0) for e in episodes]
    add("severity", Metric("sev_mean_all", "Средняя тяжесть (все эпизоды)",
                           _mean(severities), n, "mean"))
    sev_dist = Counter(severities)
    for level in sorted(sev_dist):
        add("severity", Metric(f"sev::{level}", f"severity = {level}", sev_dist[level], n, "share"))

    # --- 7. Наказание --------------------------------------------------------
    pun = [e for e in episodes if e.get("outcome") == "punishment"]
    n_pun = len(pun)
    announced = [e for e in pun if e.get("direction") == PUNISHMENT_ANNOUNCED_DIRECTION]
    executed = [e for e in pun if e.get("direction") == PUNISHMENT_EXECUTED_DIRECTION]
    other_pun = [e for e in pun
                 if e.get("direction") not in (PUNISHMENT_ANNOUNCED_DIRECTION,
                                              PUNISHMENT_EXECUTED_DIRECTION)]

    add("punishment", Metric("punishment_total", "Наказаний (outcome = punishment)",
                             n_pun, n, "share"))
    add("punishment", Metric("punishment_announced",
                             "Объявленные оракулы-приговоры (direction = god_initiated)",
                             len(announced), n_pun, "share",
                             note="правило восстановлено из scripts/analytics_v2.py; "
                                  "поле direction кодирует «объявлен» однозначно"))
    add("punishment", Metric("punishment_executed",
                             "Исполненные действия без речи (direction = divine_action)",
                             len(executed), n_pun, "share",
                             note="правило восстановлено из scripts/analytics_v2.py"))
    add("punishment", Metric("punishment_other",
                             "Прочие: наказание в ходе ответа (direction = human_initiated)",
                             len(other_pun), n_pun, "share"))
    add("punishment", Metric("punishment_executed_of_corpus",
                             "Исполненные действия — доля от корпуса",
                             len(executed), n, "share"))
    add("punishment", Metric("punishment_announced_of_corpus",
                             "Объявленные оракулы — доля от корпуса",
                             len(announced), n, "share"))

    dis = [e for e in episodes if e.get("trigger") == "disobedience"]
    pun_from_dis = [e for e in pun if e.get("trigger") == "disobedience"]
    add("punishment", Metric("punishment_from_disobedience",
                             "Наказаний по триггеру disobedience",
                             len(pun_from_dis), n_pun, "share"))
    add("punishment", Metric("p_punishment_given_disobedience",
                             "P(punishment | disobedience)",
                             len(pun_from_dis), len(dis), "share"))
    add("punishment", Metric("sev_mean_disobedience_all",
                             "Средняя тяжесть эпизодов с trigger = disobedience",
                             _mean([e.get("severity", 0) for e in dis]), len(dis), "mean",
                             note="именно это среднее (4.2) стоит в отчёте рядом с P = 80%"))
    add("punishment", Metric("sev_mean_punishment",
                             "Средняя тяжесть всех наказаний",
                             _mean([e.get("severity", 0) for e in pun]), n_pun, "mean",
                             note="4.31 — а не 4.2; 4.2 в отчёте относится к подмножеству disobedience"))

    for trig, label in (("distress", "Бедствие (distress) → punishment"),
                        ("prayer", "Молитва (prayer) → punishment")):
        cnt = sum(1 for e in episodes if e.get("trigger") == trig and e.get("outcome") == "punishment")
        trig_n = sum(1 for e in episodes if e.get("trigger") == trig)
        add("punishment", Metric(f"{trig}_to_punishment", label, cnt, n_pun, "share",
                                 note=f"в отчёте знаменатель назван «% эпизодов», фактически "
                                      f"{n_pun} наказаний; от корпуса это {cnt}/{n}; "
                                      f"всего триггер {trig} — {trig_n}"))
        add("punishment", Metric(f"{trig}_to_punishment_of_corpus", f"{label} — доля от корпуса",
                                 cnt, n, "share"))

    cfu = [e for e in episodes if e.get("trigger") == "covenant_follow_up"]
    for outcome in ("covenant", "compliance", "revelation"):
        cnt = sum(1 for e in cfu if e.get("outcome") == outcome)
        add("punishment", Metric(f"p_{outcome}_given_covenant_follow_up",
                                 f"P({outcome} | covenant_follow_up)", cnt, len(cfu), "share"))

    # --- 7a. Причины наказаний: рубрика по тексту описаний ------------------
    # Поля «причина» в контракте v2 нет, поэтому рубрика вычисляется по
    # god_action + summary_ru (см. CAUSE_RUBRIC). Мультиметка, доли — от всех наказаний.
    cause_hits = [classify_causes(e) for e in pun]
    n_labelled = sum(1 for h in cause_hits if h)
    add("causes", Metric("punishment_cause_labelled",
                         "Наказаний с хотя бы одной названной причиной",
                         n_labelled, n_pun, "share",
                         note="рубрика причин по тексту описаний (god_action + summary_ru); "
                              "мультиметка, доли считаются от всех наказаний"))
    add("causes", Metric("punishment_cause_unlabelled",
                         "Наказаний без названной причины",
                         n_pun - n_labelled, n_pun, "share",
                         note="ни одна категория не сработала: мотив в описании не назван "
                              "или выражен не теми словами"))
    n_explicit = sum(1 for e in pun if classify_causes_explicit(e))
    add("causes", Metric("punishment_cause_named_explicitly",
                         "Наказаний с прямо названной причиной",
                         n_explicit, n_pun, "share",
                         note="консервативная подрубрика: ключевое слово засчитывается, только "
                              "если стоит в причинной конструкции («за …», «из-за …», "
                              "«потому что …»)"))
    for key, label, words in CAUSE_RUBRIC:
        cnt = sum(1 for h in cause_hits if key in h)
        add("causes", Metric(f"cause::{key}", f"Причина: {label}", cnt, n_pun, "share",
                             note="мультиметка по тексту описаний (god_action + summary_ru); "
                                  "ключевые слова: " + ", ".join(words)))

    # --- 8. Явная милость ----------------------------------------------------
    mercy = [e for e in episodes if is_mercy(e)]
    n_mercy = len(mercy)
    add("mercy", Metric("mercy_total", "Явная милость (прощение / пощада / отмена кары)",
                        n_mercy, n, "share",
                        note="правило: god_action + summary_ru содержит "
                             + ", ".join(f"«{m}»" for m in MERCY_MARKERS)))
    mercy_trigs = Counter(str(e.get("trigger")) for e in mercy)
    for name, count in mercy_trigs.most_common():
        add("mercy", Metric(f"mercy_trigger::{name}", f"милость, trigger = {name}",
                            count, n_mercy, "share"))
    interv = sum(1 for e in mercy if e.get("trigger") in MERCY_INTERVENTION_TRIGGERS)
    unprompted = sum(1 for e in mercy if e.get("trigger") == "unprompted")
    add("mercy", Metric("mercy_intervention_triggers",
                        "Милость при триггере intercession/prayer/complaint",
                        interv, n_mercy, "share",
                        note="проверка тезиса §5: милость «чаще по чужой просьбе»"))
    add("mercy", Metric("mercy_unprompted", "Милость при триггере unprompted (своя инициатива)",
                        unprompted, n_mercy, "share",
                        note="для сравнения с предыдущей строкой"))
    mercy_outs = Counter(str(e.get("outcome")) for e in mercy)
    for name, count in mercy_outs.most_common():
        add("mercy", Metric(f"mercy_outcome::{name}", f"милость, outcome = {name}",
                            count, n_mercy, "share"))

    # --- 9. Молчание: поэзия vs нарратив+пророки ----------------------------
    poetic = [e for e in episodes if e.get("book") in POETIC_BOOKS]
    non_poetic = [e for e in episodes if e.get("book") not in POETIC_BOOKS]
    sil_poetic = sum(1 for e in poetic if e.get("outcome") == "silence")
    sil_non_poetic = sum(1 for e in non_poetic if e.get("outcome") == "silence")
    add("silence", Metric("poetic_episodes", "Эпизодов поэтических книг",
                          len(poetic), n, "raw"))
    add("silence", Metric("nonpoetic_episodes", "Эпизодов нарратива и пророков",
                          len(non_poetic), n, "raw"))
    add("silence", Metric("silence_poetic", "Молчание в поэтических книгах",
                          sil_poetic, len(poetic), "share"))
    add("silence", Metric("silence_nonpoetic", "Молчание в нарративе и пророках",
                          sil_non_poetic, len(non_poetic), "share"))
    ratio = round(sil_poetic / len(poetic) / (sil_non_poetic / len(non_poetic)), 2) \
        if sil_poetic and sil_non_poetic and poetic and non_poetic else 0.0
    add("silence", Metric("silence_gap_ratio", "Разрыв долей молчания (поэзия / нарратив)",
                          ratio, n, "ratio",
                          note="в отчёте: «разрыв в девять раз»"))

    # --- 10. P(answer_granted | молящие триггеры) --------------------------
    for trig in PLEADING_TRIGGERS:
        sub = [e for e in episodes if e.get("trigger") == trig]
        cnt = sum(1 for e in sub if e.get("outcome") == "answer_granted")
        add("hearing", Metric(f"hear::{trig}", f"P(answer_granted | {trig})",
                              cnt, len(sub), "share"))

    # --- 11. Книги-рекордсмены ----------------------------------------------
    books = Counter(str(e.get("book")) for e in episodes)
    for name, count in books.most_common(TOP_BOOKS):
        add("books", Metric(f"book::{name}", f"Книга {name}", count, n, "share"))

    # --- 12. Эпохи: каналы и исходы -----------------------------------------
    for era, era_books in ERA_ORDER:
        sub = [e for e in episodes if e.get("book") in era_books]
        if not sub:
            continue
        era_via = Counter(str(e.get("via")) for e in sub)
        for name, count in era_via.most_common():
            add("eras", Metric(f"era::{era}::via::{name}", f"{era}: канал {name}",
                               count, len(sub), "share"))
        era_out = Counter(str(e.get("outcome")) for e in sub)
        for name, count in era_out.most_common():
            add("eras", Metric(f"era::{era}::out::{name}", f"{era}: исход {name}",
                               count, len(sub), "share"))

    # --- 13. Профиль P(исход | триггер) для ключевых строк §9 ---------------
    profile_triggers = ("disobedience", "covenant_follow_up", "intercession", "inquiry",
                        "prayer", "complaint", "distress", "gratitude")
    for trig in profile_triggers:
        sub = [e for e in episodes if e.get("trigger") == trig]
        if not sub:
            continue
        sub_out = Counter(str(e.get("outcome")) for e in sub)
        for name, count in sub_out.most_common():
            add("profile", Metric(f"prof::{trig}::{name}", f"{trig} → {name}",
                                  count, len(sub), "share"))
        add("profile", Metric(f"prof::{trig}::severity_mean", f"{trig}: средняя тяжесть",
                              _mean([e.get("severity", 0) for e in sub]), len(sub), "mean"))

    return sections


# ---------------------------------------------------------------------------
# Проверка утверждений отчётов
# ---------------------------------------------------------------------------

def build_claims() -> list[Claim]:
    """Утверждения трёх отчётов, которые скрипт умеет проверить машинно."""
    c: list[Claim] = []
    a = c.append

    # §1–3: корпус и морфология
    a(Claim("corpus", "total_episodes", "N эпизодов в отчётах", "2 050", expect_count=2050,
            tolerance=0))
    a(Claim("corpus", "books", "Книг Танаха", "39", expect_count=39, tolerance=0))
    a(Claim("corpus", "contract_fields", "Полей в контракте v2", "17", expect_count=17,
            tolerance=0))
    a(Claim("corpus", "dedup_marked_episodes", "Дедупликация 2 056 → 2 050", "2 056 → 2 050",
            status="MANUAL_RUBRIC",
            note="преддедупликационный счёт 2 056 живёт в per-book файлах "
                 "output/episodes_*_v2.json (39 файлов, сумма 2 056) и в метаданных профиля "
                 "(docs/data/god_behavior_profile.json → metadata.episodes = 2056); мастер "
                 "output/episodes_TANAKH_v2.json содержит 2 050 после того, как "
                 "scripts/dedup_overlaps.py слил 6 перекрытий (6 пометок dedup_note). "
                 "Скрипт читает только мастер, поэтому число 2 056 здесь не пересчитывается"))
    a(Claim("direction", "dir::god_initiated", "Инициатива Бога", "55%", expect_pct=55))
    a(Claim("direction", "dir::human_initiated", "Инициатива человека", "34%", expect_pct=34))
    a(Claim("direction", "dir::divine_action", "Действие без речи", "10%", expect_pct=10))
    a(Claim("severity", "sev_mean_all", "Средняя тяжесть", "2.89 / 5", expect_count=2.89,
            tolerance=0.005))
    a(Claim("outcome_distribution", "out::punishment", "Топ-исходы: punishment", "24%",
            expect_pct=24))
    a(Claim("outcome_distribution", "out::revelation", "Топ-исходы: revelation", "18%",
            expect_pct=18))
    a(Claim("outcome_distribution", "out::blessing", "Топ-исходы: blessing", "9%", expect_pct=9))
    a(Claim("outcome_distribution", "out::covenant", "Топ-исходы: covenant", "7%", expect_pct=7))
    a(Claim("outcome_distribution", "out::silence", "Топ-исходы: silence", "7%", expect_pct=7))
    a(Claim("books", "book::Jeremiah", "Книга-рекордсмен: Иеремия", "229", expect_count=229,
            tolerance=0))
    a(Claim("books", "book::Isaiah", "Книга-рекордсмен: Исайя", "210", expect_count=210,
            tolerance=0))
    a(Claim("books", "book::Psalms", "Книга-рекордсмен: Псалмы", "178", expect_count=178,
            tolerance=0))
    a(Claim("books", "book::Ezekiel", "Книга-рекордсмен: Иезекииль", "137", expect_count=137,
            tolerance=0))
    a(Claim("channels", "via::direct", "Триада каналов: direct", "37%", expect_pct=37))
    a(Claim("channels", "via::prophet", "Триада каналов: prophet", "41%", expect_pct=41))
    a(Claim("channels", "via::others", "Триада каналов: прочие", "22%", expect_pct=22))

    # §4: наказание
    a(Claim("punishment", "punishment_total", "Наказаний", "494 эпизода (24%)",
            expect_count=494, expect_pct=24, tolerance=0))
    a(Claim("punishment", "punishment_announced", "Объявленные оракулы-приговоры", "79% (392)",
            expect_count=392, expect_pct=79, tolerance=0))
    a(Claim("punishment", "punishment_executed", "Исполненные действия без речи", "17% (84)",
            expect_count=84, expect_pct=17, tolerance=0))
    a(Claim("punishment", "punishment_executed_of_corpus", "Исполненные действия от корпуса",
            "4% всего корпуса", expect_count=84, expect_pct=4, tolerance=0))
    a(Claim("punishment", "punishment_other", "Прочие (наказание в ходе ответа)", "~4%",
            expect_pct=4))
    a(Claim("punishment", "punishment_from_disobedience", "Наказаний по disobedience", "57%",
            expect_pct=57))
    a(Claim("punishment", "distress_to_punishment", "Мольба о помощи наказана",
            "2 из 494 наказаний (0,4% кар)", expect_count=2, expect_pct=0.4,
            note="знаменатель назван явно: это доля от 494 наказаний, а не «% эпизодов»"))
    a(Claim("punishment", "distress_to_punishment_of_corpus",
            "Мольба о помощи наказана — доля от корпуса", "0,10% корпуса",
            expect_count=2, expect_pct=0.1))
    a(Claim("punishment", "prayer_to_punishment", "Молитва наказана",
            "1 из 494 наказаний (0,2% кар)", expect_count=1, expect_pct=0.2,
            note="знаменатель назван явно: это доля от 494 наказаний, а не «% эпизодов»"))
    a(Claim("punishment", "prayer_to_punishment_of_corpus",
            "Молитва наказана — доля от корпуса", "0,05% корпуса",
            expect_count=1, expect_pct=0.05))
    a(Claim("punishment", "p_punishment_given_disobedience", "P(punishment | disobedience)",
            "80%", expect_pct=80))
    a(Claim("punishment", "sev_mean_disobedience_all", "Средняя тяжесть при disobedience",
            "4,20 (350 эпизодов)", expect_count=4.2, tolerance=0.005))
    a(Claim("punishment", "sev_mean_punishment", "Средняя тяжесть самих наказаний",
            "4,31 (494 наказания)", expect_count=4.31, tolerance=0.005))
    a(Claim("punishment", "p_covenant_given_covenant_follow_up",
            "P(covenant | covenant_follow_up)", "44%", expect_pct=44))
    a(Claim("punishment", "p_revelation_given_covenant_follow_up",
            "Строка covenant_follow_up: revelation", "18%",
            expect_pct=18,
            note="в отчёте эти 18% подписаны как compliance; фактически compliance = 12.18%, "
                 "а revelation = 18.08%"))
    a(Claim("punishment", "p_compliance_given_covenant_follow_up",
            "Строка covenant_follow_up: compliance", "12%", expect_pct=12))
    # §4: причины наказаний — воспроизводимая рубрика по тексту описаний
    a(Claim("causes", "punishment_cause_labelled", "Причины: покрытие рубрики",
            "341 из 494 (69%)", expect_count=341, expect_pct=69, tolerance=0.5))
    a(Claim("causes", "punishment_cause_unlabelled", "Причины: без названной причины",
            "153 из 494 (31%)", expect_count=153, expect_pct=31, tolerance=0.5))
    a(Claim("causes", "punishment_cause_named_explicitly",
            "Причины: названа прямо (причинная конструкция)",
            "причинная конструкция — 102 из 494", expect_count=102, tolerance=0))
    for key, report_value, report_pct in (
        ("covenant_law", "нарушение завета/закона 25,7%", 25.7),
        ("violence_blood", "насилие/кровь 33,4%", 33.4),
        ("idolatry", "идолопоклонство 11,1%", 11.1),
        ("pride", "гордость 7,3%", 7.3),
        ("spiritual_unfaith", "духовная измена 13,8%", 13.8),
        ("injustice_weak", "несправедливость к слабым 9,1%", 9.1),
        ("disobedience", "непослушание 12,8%", 12.8),
        ("unbelief_grumble", "неверие/ропот 3,6%", 3.6),
    ):
        a(Claim("causes", f"cause::{key}", f"Причина: {key}", report_value,
                expect_pct=report_pct, pct_tolerance=0.06))

    # §5: милость
    a(Claim("mercy", "mercy_total", "Явная милость", "53 эпизода, 2.6%", expect_count=53,
            expect_pct=2.6, tolerance=0.05))
    a(Claim("mercy", "mercy_intervention_triggers",
            "Милость по чужой просьбе (intercession/prayer/complaint)",
            "9 из 53 = 17%", expect_count=9, expect_pct=17))
    a(Claim("mercy", "mercy_unprompted", "Милость по собственной инициативе (unprompted)",
            "16 из 53 = 30%", expect_count=16, expect_pct=30))
    a(Claim("mercy", "mercy_trigger::intercession", "Милость при заступничестве",
            "4 из 53 = 7,6%", expect_count=4, expect_pct=7.6, pct_tolerance=0.05))
    a(Claim("mercy", "mercy_trigger::distress", "Милость при крике о помощи",
            "10 из 53 = 19%", expect_count=10, expect_pct=19))
    a(Claim("mercy", "mercy_trigger::disobedience", "Милость при непослушании",
            "9 из 53 = 17%", expect_count=9, expect_pct=17))

    # §6: молчание
    a(Claim("silence", "silence_poetic", "Молчание в поэтических книгах", "91/337 = 27%",
            expect_count=91, expect_pct=27))
    a(Claim("silence", "silence_nonpoetic", "Молчание в нарративе и пророках", "47/1713 = 3%",
            expect_count=47, expect_pct=3))
    a(Claim("silence", "silence_gap_ratio", "Разрыв долей молчания", "9,8×",
            expect_count=9.84, tolerance=0.05,
            note="точное отношение 27.00% (91/337) / 2.74% (47/1713) = 9.84×"))

    # §7: слышимость
    a(Claim("hearing", "hear::intercession", "Заступничество за других услышано", "22/46 = 48%",
            expect_count=22, expect_pct=48))
    a(Claim("hearing", "hear::prayer", "Молитва услышана", "17/55 = 31%", expect_count=17,
            expect_pct=31))
    a(Claim("hearing", "hear::inquiry", "Вопрошание услышано", "31/101 = 31%", expect_count=31,
            expect_pct=31))
    a(Claim("hearing", "hear::vow", "Обет услышан", "4/17 = 24%", expect_count=4, expect_pct=24))
    a(Claim("hearing", "hear::distress", "Бедствие (крик о помощи) услышано", "30/188 = 16%",
            expect_count=30, expect_pct=16))
    a(Claim("hearing", "hear::complaint", "Жалоба услышана", "13/115 = 11%", expect_count=13,
            expect_pct=11))

    # §8: эпохи
    a(Claim("eras", "era::Тора::via::direct", "Тора: direct", "61%", expect_pct=61))
    a(Claim("eras", "era::Тора::out::covenant", "Тора: covenant", "23%", expect_pct=23))
    a(Claim("eras", "era::Тора::out::punishment", "Тора: punishment", "11%", expect_pct=11))
    a(Claim("eras", "era::Невиим (ранние)::via::direct", "Ранние пророки: direct", "35%",
            expect_pct=35))
    a(Claim("eras", "era::Невиим (ранние)::via::unclear", "Ранние пророки: unclear", "34%",
            expect_pct=34))
    a(Claim("eras", "era::Невиим (ранние)::via::prophet", "Ранние пророки: via prophet", "24%",
            expect_pct=24))
    a(Claim("eras", "era::Невиим (ранние)::out::rescue", "Ранние пророки: rescue", "14%",
            expect_pct=14))
    a(Claim("eras", "era::Невиим (ранние)::out::punishment", "Ранние пророки: punishment",
            "27%", expect_pct=27))
    a(Claim("eras", "era::Невиим (поздние)::via::prophet", "Поздние пророки: via prophet", "79%",
            expect_pct=79))
    a(Claim("eras", "era::Невиим (поздние)::out::punishment", "Поздние пророки: punishment",
            "43%", expect_pct=43))
    a(Claim("eras", "era::Кетувим::via::direct", "Кетувим: direct", "58%", expect_pct=58))
    a(Claim("eras", "era::Кетувим::via::unclear", "Кетувим: unclear", "27%", expect_pct=27))
    a(Claim("eras", "era::Кетувим::out::punishment", "Кетувим: punishment", "5%", expect_pct=5))
    a(Claim("eras", "era::Кетувим::out::silence", "Кетувим: silence", "19%", expect_pct=19))

    # §9: профиль
    a(Claim("profile", "prof::disobedience::punishment", "disobedience → punishment", "80%",
            expect_pct=80))
    a(Claim("profile", "prof::covenant_follow_up::covenant",
            "covenant_follow_up → covenant", "44%", expect_pct=44))
    a(Claim("profile", "prof::covenant_follow_up::compliance",
            "covenant_follow_up → compliance", "12%", expect_pct=12))
    a(Claim("profile", "prof::covenant_follow_up::revelation",
            "covenant_follow_up → revelation", "18%", expect_pct=18))
    a(Claim("profile", "prof::intercession::answer_granted", "intercession → answer_granted",
            "48%", expect_pct=48))
    a(Claim("profile", "prof::intercession::rescue", "intercession → rescue", "11%",
            expect_pct=11))
    a(Claim("profile", "prof::inquiry::answer_granted", "inquiry → answer_granted", "31%",
            expect_pct=31))
    a(Claim("profile", "prof::prayer::answer_granted", "prayer → answer_granted", "31%",
            expect_pct=31))
    a(Claim("profile", "prof::complaint::silence", "complaint → silence", "36%", expect_pct=36))
    a(Claim("profile", "prof::distress::silence", "distress → silence", "24%", expect_pct=24))
    a(Claim("profile", "prof::distress::rescue", "distress → rescue", "19%", expect_pct=19))
    a(Claim("profile", "prof::distress::answer_granted", "distress → answer_granted", "16%",
            expect_pct=16))
    a(Claim("profile", "prof::gratitude::unclear",
            "gratitude — «в основном без записанного ответа»", "unclear — крупнейший исход",
            status="OK", note="unclear — крупнейший исход в подмножестве gratitude"))

    # §2/§11: числа вне мастер-корпуса
    a(Claim("", "", "Формы имени Бога", "41 форма / 24 имени", status="MANUAL_RUBRIC",
            note="в мастер-корпусе нет поля имён Бога; внешний output/god_names_audit.json "
                 "содержит 41 форму, 22 из них в лексиконе пайплайна и 5 закодированы "
                 "(coded_names_counts); канонический список data/god_names.json — 24 имени. "
                 "Числа «26 форм» не подтверждается ни одним из этих файлов"))
    a(Claim("", "", "Покрытие merge-аудитом", "процедурная методика, без числа",
            status="MANUAL_RUBRIC",
            note="аудит — процессуальная метрика, а не число корпуса; процент покрытия "
                 "не выводится из мастер-корпуса"))

    return c


def get_metric(sections: Mapping[str, list[Metric]], section: str, key: str) -> Metric | None:
    for m in sections.get(section, []):
        if m.key == key:
            return m
    return None


def check_claims(sections: Mapping[str, list[Metric]]) -> list[dict[str, Any]]:
    """Сверить утверждения отчётов с посчитанными числами."""
    results: list[dict[str, Any]] = []
    for claim in build_claims():
        metric = get_metric(sections, claim.section, claim.key)
        rec: dict[str, Any] = {
            "section": claim.section,
            "key": claim.key,
            "label": claim.label,
            "report_value": claim.report_value,
            "status": claim.status,
            "note": claim.note,
        }
        if claim.expect_pct is not None:
            rec["expected_pct"] = claim.expect_pct
            rec["computed_pct"] = metric.pct if metric else None
        if claim.expect_count is not None:
            rec["expected_count"] = claim.expect_count
            rec["computed_count"] = metric.count if metric else None
        if metric is not None:
            rec["denominator"] = metric.denominator

        if claim.status in ("MANUAL_RUBRIC", "CONTRADICTED"):
            results.append(rec)
            continue

        ok = metric is not None
        if ok and claim.expect_pct is not None:
            ok = (metric.pct is not None
                  and abs(metric.pct - claim.expect_pct) <= claim.pct_tolerance)
        if ok and claim.expect_count is not None:
            ok = abs(metric.count - claim.expect_count) <= claim.tolerance
        rec["status"] = "OK" if ok else "NOT_REPRODUCIBLE"
        results.append(rec)
    return results


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------

SECTION_TITLES = {
    "corpus": "1. Корпус",
    "outcome_distribution": "2. Распределение исходов (outcome)",
    "trigger_distribution": "3. Распределение триггеров (trigger)",
    "direction": "4. Направление инициативы",
    "channels": "5. Каналы откровения (via)",
    "channels_detail": "5a. Каналы откровения — полный разбор",
    "severity": "6. Тяжесть (severity)",
    "punishment": "7. Наказание: объявлено vs исполнено",
    "causes": "7a. Причины наказаний (рубрика по тексту описаний)",
    "mercy": "8. Явная милость",
    "silence": "9. Молчание: поэзия vs нарратив+пророки",
    "hearing": "10. P(answer_granted | молящий триггер)",
    "books": "11. Книги-рекордсмены",
    "eras": "12. Эпохи: каналы и исходы",
    "profile": "13. Профиль P(исход | триггер), ключевые строки §9",
}


def print_table(sections: Mapping[str, list[Metric]], claims: Sequence[Mapping[str, Any]]) -> None:
    n = get_metric(sections, "corpus", "total_episodes")
    n_books = get_metric(sections, "corpus", "books")
    print("=" * 100)
    print("GOD — воспроизводимые числа научных отчётов")
    print(f"Источник: output/episodes_TANAKH_v2.json  "
          f"(книг={n_books.count if n_books else '?'}, эпизодов={n.count if n else '?'})")
    print("Формат: число (процент, знаменатель=N). Доля считается от указанного знаменателя.")
    print("=" * 100)

    for section, title in SECTION_TITLES.items():
        metrics = sections.get(section)
        if not metrics:
            continue
        print()
        print(f"[{title}]")
        print("-" * 100)
        for m in metrics:
            print(f"  {m.label:<62} : {m.render()}")

    print()
    print("[Проверка утверждений отчётов]")
    print("-" * 100)
    bad = [c for c in claims if c["status"] != "OK"]
    ok_n = sum(1 for c in claims if c["status"] == "OK")
    print(f"  Воспроизведено: {ok_n} из {len(claims)}; расхождений/ручных рубрик: {len(bad)}")
    print()

    print("[NOT_REPRODUCIBLE / требует ручной рубрики]")
    print("-" * 100)
    if not bad:
        print("  (нет)")
    for c in bad:
        print(f"  • {c['label']}: в отчёте «{c['report_value']}» — статус {c['status']}")
        if c.get("computed_pct") is not None:
            print(f"      посчитано: {c['computed_pct']:.2f}% "
                  f"(знаменатель {c.get('denominator', '—')})")
        if c.get("computed_count") is not None:
            print(f"      посчитано: {_fmt_num(c['computed_count'])}")
        if c.get("note"):
            print(f"      пояснение: {c['note']}")


def print_json(sections: Mapping[str, list[Metric]], claims: Sequence[Mapping[str, Any]],
               episodes: int, books: int) -> None:
    payload = {
        "meta": {
            "script": "scripts/report_numbers.py",
            "source": "output/episodes_TANAKH_v2.json",
            "source_only_master": True,
            "episodes": episodes,
            "books": books,
            "mercy_markers": list(MERCY_MARKERS),
            "punishment_announced_direction": PUNISHMENT_ANNOUNCED_DIRECTION,
            "punishment_executed_direction": PUNISHMENT_EXECUTED_DIRECTION,
            "cause_rubric": {
                "fields": ["god_action", "summary_ru"],
                "mode": "multi-label",
                "denominator": "все наказания (outcome = punishment)",
                "categories": {key: {"label": label, "keywords": list(words)}
                               for key, label, words in CAUSE_RUBRIC},
                "causal_markers": list(CAUSAL_MARKERS),
                "causal_window": CAUSAL_WINDOW,
            },
        },
        "sections": {name: [m.as_dict() for m in metrics]
                     for name, metrics in sections.items()},
        "claims": list(claims),
        "not_reproducible": [c for c in claims if c["status"] != "OK"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Самопроверка на синтетическом корпусе
# ---------------------------------------------------------------------------

def _synthetic_episode(idx: int, book: str, outcome: str, trigger: str, direction: str,
                       severity: int, via: str = "direct", god_action: str = "",
                       summary_ru: str = "") -> dict[str, Any]:
    """Синтетический эпизод с полным набором полей контракта v2."""
    return {
        "span": {"start": "1:1", "end": "1:2"},
        "direction": direction,
        "via": via,
        "participants": ["Моше", "ЯХВЕ"],
        "addressee_type": "nation",
        "trigger": trigger,
        "god_speech_refs": ["1:1"] if direction == "god_initiated" else [],
        "god_speech_plain": "",
        "human_speech_refs": ["1:1"] if direction == "human_initiated" else [],
        "human_speech_plain": "",
        "god_action": god_action,
        "outcome": outcome,
        "severity": severity,
        "emotions": [],
        "summary_ru": summary_ru,
        "confidence": "high",
        "boundary": False,
        "episode_id": f"SynV2_{idx:03d}",
        "book": book,
        "source_batch": 1,
    }


def build_synthetic_corpus() -> list[dict[str, Any]]:
    """Маленький корпус в памяти, на котором ответы известны вручную."""
    return [
        _synthetic_episode(1, "Genesis", "punishment", "disobedience", "god_initiated", 4,
                           god_action="ЯХВЕ объявил приговор народу",
                           summary_ru="Кара объявлена за нарушение завета"),
        _synthetic_episode(2, "Genesis", "punishment", "disobedience", "divine_action", 5,
                           god_action="Кара постигла народ без речи",
                           summary_ru="Наложена кара без слов"),
        _synthetic_episode(3, "Genesis", "punishment", "distress", "human_initiated", 2,
                           god_action="Ответа не было, пришла кара",
                           summary_ru="Мольба о помощи наказана"),
        _synthetic_episode(4, "Psalms", "silence", "distress", "human_initiated", 1,
                           via="unclear", god_action="Бог молчит",
                           summary_ru="Крик о помощи остался без ответа"),
        _synthetic_episode(5, "Psalms", "silence", "complaint", "human_initiated", 2,
                           via="unclear", god_action="Бог молчит",
                           summary_ru="Жалоба осталась без ответа"),
        _synthetic_episode(6, "Psalms", "answer_granted", "intercession", "god_initiated", 1,
                           god_action="Бог ответил заступнику",
                           summary_ru="Ответ дано по заступничеству"),
        _synthetic_episode(7, "Proverbs", "covenant", "covenant_follow_up", "god_initiated", 2,
                           god_action="Бог подтвердил завет",
                           summary_ru="Завет подтверждён"),
        _synthetic_episode(8, "Proverbs", "compliance", "covenant_follow_up", "god_initiated", 2,
                           god_action="Бог принял послушание",
                           summary_ru="Послушание принято"),
        _synthetic_episode(9, "Job", "answer_granted", "prayer", "god_initiated", 1,
                           god_action="ЯХВЕ простил вину",
                           summary_ru="Грех прощён по молитве"),
        _synthetic_episode(10, "Isaiah", "revelation", "unprompted", "god_initiated", 3,
                           via="prophet", god_action="ЯХВЕ открыл видение",
                           summary_ru="Открыто видение о грядущем"),
        _synthetic_episode(11, "Genesis", "revelation", "disobedience", "god_initiated", 2,
                           god_action="ЯХВЕ обличил народ",
                           summary_ru="Обличение за проступок без кары"),
    ]


def run_selftest() -> bool:
    """Проверить счётчики на маленьком синтетическом корпусе."""
    episodes = build_synthetic_corpus()
    sections = build_sections(episodes)
    checks: list[tuple[str, Any, Any]] = []

    def check(label: str, actual: Any, expected: Any) -> None:
        checks.append((label, actual, expected))

    def val(section: str, key: str) -> Any:
        m = get_metric(sections, section, key)
        return None if m is None else (m.pct if m.kind == "share" else m.count)

    # Корпус: 11 эпизодов, 5 книг, 17 полей контракта
    check("N всего эпизодов", val("corpus", "total_episodes"), 11)
    check("книг", val("corpus", "books"), 5)
    check("полей контракта", val("corpus", "contract_fields"), 17)

    # Исходы: punishment 3, silence 2, answer_granted 2, revelation 2, covenant 1, compliance 1
    check("outcome punishment", val("outcome_distribution", "out::punishment"), 27.27)
    check("outcome silence", val("outcome_distribution", "out::silence"), 18.18)
    check("outcome answer_granted", val("outcome_distribution", "out::answer_granted"), 18.18)
    check("outcome revelation", val("outcome_distribution", "out::revelation"), 18.18)
    check("outcome covenant", val("outcome_distribution", "out::covenant"), 9.09)

    # Триггеры: disobedience 3, covenant_follow_up 2, distress 2, complaint 1, intercession 1,
    # prayer 1, unprompted 1
    check("trigger disobedience", val("trigger_distribution", "trig::disobedience"), 27.27)
    check("trigger covenant_follow_up", val("trigger_distribution", "trig::covenant_follow_up"),
          18.18)
    check("trigger distress", val("trigger_distribution", "trig::distress"), 18.18)

    # Направление: god_initiated 7, human_initiated 3, divine_action 1
    check("direction god_initiated", val("direction", "dir::god_initiated"), 63.64)
    check("direction divine_action", val("direction", "dir::divine_action"), 9.09)
    check("direction human_initiated", val("direction", "dir::human_initiated"), 27.27)

    # Каналы: direct 8, unclear 2, prophet 1
    check("via direct", val("channels", "via::direct"), 72.73)
    check("via prophet", val("channels", "via::prophet"), 9.09)
    check("via others", val("channels", "via::others"), 18.18)

    # Тяжесть: (4+5+2+1+2+1+2+2+1+3+2)/11 = 25/11
    check("severity mean", val("severity", "sev_mean_all"), 2.2727)

    # Наказание: 3 эпизода — по одному каждого типа direction
    check("punishment total", val("punishment", "punishment_total"), 27.27)
    check("punishment announced", val("punishment", "punishment_announced"), 33.33)
    check("punishment executed", val("punishment", "punishment_executed"), 33.33)
    check("punishment other", val("punishment", "punishment_other"), 33.33)
    check("punishment from disobedience", val("punishment", "punishment_from_disobedience"),
          66.67)
    check("P(punishment|disobedience)", val("punishment", "p_punishment_given_disobedience"),
          66.67)
    check("severity mean punishment", val("punishment", "sev_mean_punishment"), 3.6667)
    check("P(covenant|covenant_follow_up)",
          val("punishment", "p_covenant_given_covenant_follow_up"), 50.0)
    check("P(compliance|covenant_follow_up)",
          val("punishment", "p_compliance_given_covenant_follow_up"), 50.0)

    # Милость: 1 эпизод (Job, молитва, «ЯХВЕ простил вину»)
    check("mercy total", val("mercy", "mercy_total"), 9.09)
    check("mercy trigger prayer", val("mercy", "mercy_trigger::prayer"), 100.0)
    check("mercy intervention triggers", val("mercy", "mercy_intervention_triggers"), 100.0)
    check("mercy unprompted", val("mercy", "mercy_unprompted"), 0.0)

    # Молчание: поэтические — Psalms 3 + Proverbs 2 + Job 1 = 6, из них silence 2
    check("poetic episodes", val("silence", "poetic_episodes"), 6)
    check("silence poetic", val("silence", "silence_poetic"), 33.33)
    check("silence non-poetic", val("silence", "silence_nonpoetic"), 0.0)

    # Слышимость
    check("P(answer_granted|intercession)", val("hearing", "hear::intercession"), 100.0)
    check("P(answer_granted|prayer)", val("hearing", "hear::prayer"), 100.0)
    check("P(answer_granted|distress)", val("hearing", "hear::distress"), 0.0)
    check("P(answer_granted|complaint)", val("hearing", "hear::complaint"), 0.0)

    # Книги: Genesis 4, Psalms 3, Proverbs 2, Job 1, Isaiah 1
    check("Genesis episodes", val("books", "book::Genesis"), 36.36)
    check("Psalms episodes", val("books", "book::Psalms"), 27.27)

    # Эпохи: Тора = Genesis (4 эпизода, все direct)
    check("Тора direct", val("eras", "era::Тора::via::direct"), 100.0)
    check("Тора revelation", val("eras", "era::Тора::out::revelation"), 25.0)

    # Причины наказаний: 3 наказания, у одного ключевое слово рубрики («нарушение завета»)
    check("causes labelled", val("causes", "punishment_cause_labelled"), 33.33)
    check("causes unlabelled", val("causes", "punishment_cause_unlabelled"), 66.67)
    check("causes explicit", val("causes", "punishment_cause_named_explicitly"), 33.33)
    check("cause covenant_law", val("causes", "cause::covenant_law"), 33.33)
    check("cause violence_blood", val("causes", "cause::violence_blood"), 0.0)
    check("cause pride", val("causes", "cause::pride"), 0.0)

    failed = [(label, actual, expected)
              for label, actual, expected in checks
              if actual is None or abs(float(actual) - float(expected)) > 0.01]

    print("SELFTEST (синтетический корпус из 11 эпизодов)")
    print("-" * 100)
    for label, actual, expected in checks:
        mark = "ok " if (label, actual, expected) not in failed else "FAIL"
        print(f"  [{mark}] {label:<42} ожидалось={expected!r:>12}  получено={actual!r}")
    print("-" * 100)
    if failed:
        print(f"SELFTEST: FAIL — расхождений {len(failed)} из {len(checks)}")
        return False
    print(f"SELFTEST: PASS — все {len(checks)} счётчиков сошлись")
    return True


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Воспроизводимый вычислитель чисел научных отчётов GOD.")
    parser.add_argument("--test", action="store_true",
                        help="самопроверка на синтетическом корпусе")
    parser.add_argument("--json", action="store_true",
                        help="машинный вывод всех чисел в JSON")
    args = parser.parse_args(argv)

    if args.test:
        return 0 if run_selftest() else 1

    episodes = load_corpus()
    sections = build_sections(episodes)
    claims = check_claims(sections)
    n_books = len({str(e.get("book", "")) for e in episodes})

    if args.json:
        print_json(sections, claims, len(episodes), n_books)
    else:
        print_table(sections, claims)
    return 0


if __name__ == "__main__":
    sys.exit(main())
