# The Image of God in the Tanakh: A Behavioral Profile from a Corpus of 2,050 Episodes

**GOD — research report v1.0** · 2026-10-18 · translated from the Russian original
Corpus: all 39 books of the Tanakh, 2,050 human↔God interaction episodes (master file
`output/episodes_TANAKH_v2.json`, deduplicated; every episode is traceable to verses).
Interactive: [vasiliad.github.io/GOD](https://vasiliad.github.io/GOD/)

---

## Abstract

From the full text of the Tanakh we extracted and annotated a corpus of 2,050 human↔God
interaction episodes (contract v2: verse span, initiative direction, channel, trigger,
verbatim consonantal Hebrew speech, action, outcome, severity 1–5, emotions with
justifications). From the corpus we measured an empirical reaction model: P(outcome | trigger).
Main findings: (1) punishment is nearly deterministic after an offense, yet in 79% of cases
it is **announced**, not executed; (2) explicit mercy is event-driven and tied to intercession;
(3) God's silence is a genre phenomenon of poetry (27% of poetic-book episodes vs 3% in
narrative); (4) interceding for others is the most "hearable" form of address (48% answered);
(5) the channel of revelation shifts across eras from direct speech (Torah, 61% direct) to
mediated prophetic word (late Prophets, 79% via prophet).

## 1. Problem statement

The project SPEC: a psychological and linguistic study of the image of God in the Tanakh.
Question: how does the God of the text react to human actions — and can that reaction be
measured? An early stage (v1, March 2026) coded individual verses by "verb+name" formulas;
its systematic bias (a speech-act filter) is documented in
[`retrospective_v1.md`](retrospective_v1.md). This report is built on the v2 episode corpus,
where the unit of analysis is a whole interaction with an outcome.

## 2. Methodology

- **Extraction:** agents segmented the text under a uniform 17-field contract; poetic
  books — psalm/chapter = one address-episode; prophetic books — each "כה אמר" oracle
  separately; categories A (God's speech) / B (plea without answer) / C (action without speech).
- **Audit:** every book passed a merge audit (speech/address/silence/action formulas,
  control verses) — 100% after spot span fixes; names of God — 26 forms
  (`god_names_audit.json`; the maqqef U+05BE bug inside the vowel range was fixed).
- **Deduplication:** batch overlaps merged globally (`dedup_overlaps.py`, selftest PASS);
  2,056 → 2,050 episodes.
- **Outcome coding** is the researcher's rubric (deterministic rules + LLM agents with an
  audit), not theological truth; this is the main limitation of the method (see §6).

## 3. Corpus morphology

| Parameter | Value |
|---|---|
| Initiative: God / human / action without speech | 55% / 34% / 10% |
| Mean severity | 2.89 / 5 |
| Top outcomes | punishment 24% · revelation 18% · blessing 9% · covenant 7% · silence 7% |
| Episode-rich books | Jeremiah 229 · Isaiah 211 · Psalms 180 · Ezekiel 137 |

Channel triad: direct 37%, prophet 41%, others (vision, angel, dream, inner) — 22% combined.
Against the v1 conclusion that "God always initiates" (0% human initiative in that
measurement): in the episode measurement a human initiates every third interaction.

## 4. Punishment: threatens more often than it strikes

Punishment — 494 episodes (24%). Split by mode:

- **announced verdict-oracles** — 79% (392);
- **executed actions without speech** — 17% (84; 4% of the whole corpus);
- others (punishment within an answer) — ~4%.

Causes (multi-label over descriptions): covenant/law violation 28% · violence/bloodshed 22% ·
idolatry 12% · pride 6% · spiritual adultery 6% · injustice to the weak 5% ·
direct disobedience 4% · unbelief/grumbling 2%. By trigger: 57% of punishments follow
disobedience; a plea for help is punished in 0.4% of episodes; prayer — 0.2%.

**P(punishment | disobedience) = 80%.** This is the most deterministic law of the image:
disobedience almost inevitably brings punishment (mean severity 4.2). Comparable only to
**P(covenant | covenant_follow_up) = 44%**: God answers covenant initiative with covenant
faithfulness. Model for the imitation: wrath is the rule, mercy the exception.

## 5. Mercy: event-driven, not the norm

Explicit mercy (forgiveness, revoking an already-announced punishment, sparing) — 53
episodes, 2.6% of the corpus. The mechanism is almost always one of two: **intercession**
by a third party (Moses, Samuel, the prophets) or **repentance** (Ahab, Manasseh, Nineveh).
The contrast with punishment: punishment is deterministic (57% follow an offense), mercy is
exceptional and intersubjective — the God of the text shows mercy more often at another's
request than on His own initiative.

## 6. Silence is a genre phenomenon of poetry

| Corpus | Share of episodes with silence |
|---|---|
| Poetic books (Psalms, Job, Lamentations, Song, Proverbs, Ecclesiastes) | **91/337 = 27%** |
| Narrative and Prophets | **47/1713 = 3%** |

A nine-fold gap. In narrative and prophecy God's silence is a rare dramatic event
(1 Sam 8:9 "he will not answer you that day"; Deut 1:45); in poetry it is the structural
norm of lament — a psalm ends with a question to heaven left unanswered. Conclusion: "God's
silence" is to a significant degree a literary device of the genre, not an empirical
measure of attitude — a limitation any psychological reading must account for.

## 7. Hearability of pleas: a hierarchy of address

P(answer_granted | trigger) for "pleading" triggers:

| Address | Heard |
|---|---|
| Intercession for others | **22/46 = 48%** |
| Prayer | 17/55 = 31% |
| Inquiry | 31/101 = 31% |
| Vow | 4/17 = 24% |
| Distress (a cry for help) | 30/188 = **16%** |
| Complaint | 13/115 = **11%** |

An unexpected result: **cries for help and complaints are heard worse than questions or
prayers**. Interpretation within the corpus: distress episodes fall massively in the poetic
books (genre silence, §6), and complaint in narrative is often a courtroom scene where the
answer is deferred or given as punishing action. Intercession is the most "hearable" genre:
asking for another in the world of the text is safer than asking for oneself (imitation
profile: P(answer)=48%).

## 8. Channels of revelation by era

| Era | Dominant channel |
|---|---|
| Torah | **direct 61%** (direct speech, including face to face) |
| Early Prophets | direct 35% + unclear 34% (rescue actions; via prophet 24%) |
| Late Prophets | **prophet 79%** (the word almost exclusively mediated) |
| Ketuvim | direct 58% (a human's prayer; unclear 27%) |

Trajectory: from the unveiled theophany of the Torah to the fully mediated word of the late
Prophets; in Ketuvim "direct" is no longer a voice from heaven but the directedness of
prayer. Era portrait (from `analytics.json`): Torah — covenant (covenant 23%, punishment
11%); early Prophets — rescue-war (rescue 14%, punishment 27%); late Prophets — verdict
(punishment 43%); Ketuvim — silence and piety (punishment 5%, silence 19%).

## 9. Reaction profile (the model for the imitation)

The final P(outcome | trigger) matrix — in `output/god_behavior_profile.json` (used by the
`god_behavior.py` engine and the chat). Key rows:

- disobedience → punishment 80% (sev 4.2)
- covenant_follow_up → covenant 44% + compliance 18%
- intercession → answer_granted 48% (+ rescue 11%)
- inquiry → answer_granted 31%
- prayer → answer_granted 31%
- complaint → silence 36% (genre)
- distress → silence 24% + rescue 19% + answer 16%
- gratitude → mostly without a recorded answer

The engine adds modifiers: repentance lowers severity (precedents Ex 32:14, 2 Sam 24:16),
repeat offenses raise it (the Judges cycle).

## 10. Limitations

1. Outcomes are the researcher's coding (deterministic rubrics + LLM agents with formula
   coverage audits); the rubrics are not theology but a measuring scale.
2. Silence in poetry is a literary device (§6): psychological interpretation of silence must
   exclude the genre effect.
3. "Announced punishment" is not always executed in the text — mixing threat and strike in
   one category is a deliberate simplification; the 79/17 split is given for transparency.
4. Psychological typologies (Jung/Bern/Big5 over "the image of God") are a category error;
   v1 profiles are kept only as illustrations (`retrospective_v1.md`).
5. The DSS (Qumran) layer is not included: no openly licensed transcriptions exist.

## 11. Reproducibility

All scripts carry `--test`/`--selftest` (PASS): `god_profile.py`, `god_behavior.py`,
`analytics_v2.py`, `dedup_overlaps.py`, `audit_god_names.py`, `god_chat.py`. Standing gates:
`scripts/selftest_all.py` (6/6) and `scripts/verify_corpus.py` (data integrity, zero failures).
Data: the master corpus, analytics and per-book episodes are published in the
[vasiliad/GOD](https://github.com/vasiliad/GOD) repository; the corpus browser —
[vasiliad.github.io/GOD](https://vasiliad.github.io/GOD/).

---
*The report is built entirely on the annotated corpus; every number reproduces in one
command. Russian annotations — CC BY 4.0; the Tanakh text is public domain.*
