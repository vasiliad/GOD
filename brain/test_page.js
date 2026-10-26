/* Node-тест JS страницы GOD: мозг офлайн / онлайн+ответ LLM / ошибка LLM.
   Метод из памяти проекта: new Function(код + return{...}) + fetch/DOM стабы. */
const fs = require("fs");
const html = fs.readFileSync(__dirname + "/../docs/index.html", "utf8");
const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) { console.error("FAIL: <script> не найден"); process.exit(1); }
let code = m[1];
code = code.split("/* ---------- роутер ---------- */")[0]; // DOM-роутер проверяем вживую браузером

// --- стабы браузера ---
const LS = {};
const calls = [];
const bodies = [];              // тела POST-запросов к мозгу
let brainJson = null;
let llmResponse = null;         // ответ шага формулировки /v1/chat/completions
let llmSelectResponse = null;   // ответ шага выбора эпизода (одно число)
let llmShouldFail = false;
global.localStorage = {
  getItem: k => (k in LS ? LS[k] : null),
  setItem: (k, v) => { LS[k] = String(v); },
  removeItem: k => { delete LS[k]; }
};
global.fetch = async (url, opts) => {
  calls.push(url);
  if (opts && opts.body) bodies.push(String(opts.body));
  if (url.includes("god-brain-status")) {
    if (brainJson === null) throw new Error("network down");
    return { ok: true, json: async () => brainJson };
  }
  if (url.includes("/v1/chat/completions")) {
    if (llmShouldFail) return { ok: false, status: 503 };
    // схема из двух шагов: выбор эпизода (короткий вопрос) и формулировка
    const body = (opts && opts.body) ? String(opts.body) : "";
    if (body.includes("выбрать ОДИН эпизод"))
      return { ok: true, json: async () => llmSelectResponse };
    return { ok: true, json: async () => llmResponse };
  }
  // data/books/*.json, analytics.json, nikud.json — минимальный корпус
  if (url.includes("analytics.json")) {
    return { ok: true, json: async () => ({
      corpus: { episodes: 2050, books: 39 },
      book_order: { Torah: ["Genesis"] },
      per_era: {}, per_book: {}, trigger_table: { inquiry: { n: 5, answer_granted: 0.5 } },
      punishment_split: { total: 494, announced_oracle: 0.79, executed_action: 84 }
    }) };
  }
  if (url.includes("data/books/")) {
    return { ok: true, json: async () => [{
      span: { start: "3:9", end: "3:15" }, trigger: "disobedience", outcome: "punishment",
      god_speech_plain: "איכה", god_speech_refs: ["3:9"], summary_ru: "Бог призывает к ответу",
      god_action: "Бог вопрошает", direction: "god_to_human", severity: 3, via: "direct",
      emotions: [], confidence: "high", human_speech_plain: ""
    }] };
  }
  if (url.includes("nikud.json")) return { ok: true, json: async () => ({ "Genesis|3|9": "אַיֵּה" }) };
  if (url.includes("research_report.md")) return { ok: true, text: async () => "# отчёт" };
  return { ok: true, json: async () => ({}) };
};
// Реестр элементов по id — иначе нельзя проверить, что заметка чата меняется по состоянию
const EL = {};
const elFor = id => (EL[id] = EL[id] || { id, textContent: "", title: "", value: "", style: {} });
global.document = {
  documentElement: { lang: "", dir: "" },
  title: "",
  getElementById: id => elFor(id),
  createElement: () => ({ className: "", innerHTML: "", prepend() {} }),
  querySelectorAll: () => ({ forEach() {} })
};
global.window = { scrollTo(){}, _brainTimer: null, setInterval: () => 1, clearInterval(){} };

const api = new Function(
  "var nav={innerHTML:'',querySelectorAll:()=>({forEach(){}})};var main={innerHTML:''};" +
  code + "\nreturn { brainRefresh, liveReply, liveHTML, parseSections, retrieve, classify, BRAIN, store, I18N, dequant, cosv, embIndex, bookName, BOOK_NAMES, LANG, esc, linkSources, paintBrainNote, hebWords, hebNorm, guardCoverage, guardCtxCoverage, guardVerify, guardRuCoverage };")();

(async () => {
  let pass = 0, fail = 0;
  const check = (name, cond) => { cond ? (pass++, console.log("PASS", name)) : (fail++, console.log("FAIL", name)); };

  // 0) i18n: словари RU/EN/HE покрывают одинаковый набор ключей
  const keysOf = o => Object.keys(o).sort().join(",");
  check("i18n: EN покрывает все ключи RU", keysOf(api.I18N.ru) === keysOf(api.I18N.en));
  check("i18n: HE покрывает все ключи RU", keysOf(api.I18N.ru) === keysOf(api.I18N.he));
  const hebrewUi = api.I18N.he.chat_note;
  check("i18n: HE-интерфейс действительно на иврите", /[\u05D0-\u05EA]/.test(hebrewUi));
  check("i18n: тон «говори, а не спрашивай» — нет «спрашивай» в RU-статусе готовности", !/спрашивай/.test(api.I18N.ru.b_on));

  // 1) мозг недоступен: brain.json нет -> state off, liveReply отказывает сразу, без сетевого вызова
  brainJson = null;
  await api.brainRefresh();
  check("офлайн: state=off", api.BRAIN.info.state === "off");
  calls.length = 0;
  let threw = false;
  try { await api.liveReply("я боюсь"); } catch (e) { threw = true; }
  check("офлайн: liveReply бросает без POST (=> честное сообщение «до субботы»)",
        threw && !calls.some(u => u.includes("/v1/chat/completions")));

  // 2) мозг онлайн: свежий ok:true -> state on, POST на туннель Kaggle, 6 секций
  brainJson = { ok: true, url: "https://tun.trycloudflare.com", key: "godbrain-v1-vasiliad",
                model: "dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF", ts: Math.floor(Date.now() / 1000) - 60 };
  await api.brainRefresh();
  check("онлайн: state=on", api.BRAIN.info.state === "on");
  llmResponse = { choices: [{ message: { content:
    "[HEBREW] איכה\n[NIKKUD] אַיֵּה\n[Russian] Где ты?\n[English] Where art thou?\n[Hebrew Modern] איפה אתה\n[SOURCES] Genesis 3:9" } }] };
  llmSelectResponse = { choices: [{ message: { content: "S1" } }] };
  calls.length = 0; bodies.length = 0;
  const r = await api.liveReply("я боюсь");
  const called = calls.find(u => u.includes("/v1/chat/completions"));
  check("онлайн: POST ушёл на туннель мозга", !!called && called.startsWith("https://tun.trycloudflare.com"));
  check("онлайн: схема из двух вызовов (выбор эпизода + формулировка)",
        calls.filter(u => u.includes("/v1/chat/completions")).length === 2);
  check("онлайн: шаг выбора использует свой промпт",
        bodies.some(b => b.includes("выбрать ОДИН эпизод")));
  check("онлайн: шаг формулировки получает один эпизод и просит шесть секций",
        bodies.some(b => b.includes("СТИХ: [Genesis 3:9]") && b.includes("Ответь шестью секциями")));
  check("онлайн: выбранный эпизод возвращается для сверки",
        !!r.sel && r.sel.ctx.book === "Genesis" && r.sel.ctx.span.start === "3:9" && r.sel.index === 1);
  check("онлайн: 6 секций распознаны", Object.keys(r.sections).length === 6);
  check("онлайн: HEBREW совпадает", r.sections["[HEBREW]"] === "איכה");
  check("онлайн: SOURCES совпадает", r.sections["[SOURCES]"] === "Genesis 3:9");

  // 3) мозг онлайн, но LLM упал (503) -> liveReply бросает => send() ответит корпусом
  llmShouldFail = true;
  threw = false;
  try { await api.liveReply("спаси меня"); } catch (e) { threw = true; }
  check("LLM-ошибка: liveReply бросает (=> честная ошибка)", threw);

  // 4) мозг поднимается: ok:false + phase=starting, свежий пульс -> state starting
  brainJson = { ok: false, phase: "starting", url: null, key: "godbrain-v1-vasiliad",
                model: "dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF", ts: Math.floor(Date.now() / 1000) - 120 };
  await api.brainRefresh();
  check("старт: state=starting", api.BRAIN.info.state === "starting");

  // 5) протухший пульс (2 часа) -> state off
  brainJson.ok = true; brainJson.ts = Math.floor(Date.now() / 1000) - 7200;
  await api.brainRefresh();
  check("протухший brain.json: state=off", api.BRAIN.info.state === "off");

  // 6) векторные хелперы
  const row = { s: 2.0, q: Buffer.from(new Int8Array([-127, 0, 127]).buffer).toString("base64") };
  const dv = api.dequant(row);
  check("dequant: раундтрип [-2, 0, 2]", Math.abs(dv[0]+2)<1e-6 && dv[1]===0 && Math.abs(dv[2]-2)<1e-6);
  check("cosv: ортогональные 0, коллинеарные 1", api.cosv([1,0],[0,1])===0 && api.cosv([1,0],[1,0])===1);
  // 6b) esc реально экранирует (регрессия: сущности были потеряны, esc был no-op)
  const A = String.fromCharCode(38);   // &, без литеральных сущностей — их съедает туловый конвейер
  check("esc: <b> и & экранируются",
        api.esc("<b>") === A+"lt;b"+A+"gt;" && api.esc("и &") === "и "+A+"amp;");
  // 6c) источники становятся кликабельными ссылками на эпизоды
  const linked = api.linkSources("Genesis 3:9; Бытие 1:1");
  check("linkSources: ссылки обёрнуты в srcDive",
        linked.includes('srcDive("genesis","3:9")') && linked.includes('srcDive("genesis","1:1")'));
  // 7) bookName: имена книг на языке интерфейса
  const bn = api.bookName, BN = api.BOOK_NAMES;
  check("bookName ru/genesis = Бытие", bn("genesis") === "Бытие");
  check("bookName ru/Micah = Михей", bn("Micah") === "Михей");
  const keys = Object.keys(BN.ru);
  check("BOOK_NAMES: 39 книг в RU", keys.length === 39);
  check("BOOK_NAMES: 39 книг в EN", Object.keys(BN.en).length === 39);
  check("BOOK_NAMES: 39 книг в HE", Object.keys(BN.he).length === 39);
  check("BOOK_NAMES: ключи RU==EN==HE", JSON.stringify(Object.keys(BN.ru).sort()) === JSON.stringify(Object.keys(BN.en).sort()) && JSON.stringify(Object.keys(BN.ru).sort()) === JSON.stringify(Object.keys(BN.he).sort()));
  const heBooks = ["genesis","Judges","Psalms","Micah","Haggai"];
  const heExpected = ["בראשית","שופטים","תהלים","מיכה","חגי"];
  check("BOOK_NAMES: выборочные HE-имена", heBooks.every((b,i) => BN.he[b] === heExpected[i]));

  // 8) ключи вариантов скорости в КОДЕ совпадают с ключами в ДАННЫХ (регрессия: f/s vs fluent/slower)
  const audioGen = JSON.parse(fs.readFileSync(__dirname + "/../docs/data/audio/genesis.json", "utf8"));
  check("аудио: данные содержат ключи fluent/slower", !!audioGen.fluent && !!audioGen.slower);
  check("аудио: код читает fluent/slower (не f/s)", code.includes("am.fluent") && !/am\.f\b/.test(code) && !/am\.s\b/.test(code));

  // 9) заметка чата зависит от состояния мозга (проверяем / спит / поднимается / на связи)
  api.BRAIN.info = { state: "off" };            // до первого ответа brain.json статус неизвестен
  api.paintBrainNote();
  check("заметка чата: статус ещё не проверен -> chat_note_check", elFor("chatNote").textContent === api.I18N.ru.chat_note_check);
  brainJson = null;                              // сеть посетителя недоступна -> это не «мозг спит»
  await api.brainRefresh(); api.paintBrainNote();
  check("заметка чата: сеть недоступна -> chat_note_checkfail (не «спит»)",
        elFor("chatNote").textContent === api.I18N.ru.chat_note_checkfail
        && elFor("chatNote").textContent !== api.I18N.ru.chat_note_off);
  brainJson = { ok: false, phase: "idle", url: null, key: "k", model: "m",
                ts: Math.floor(Date.now() / 1000) - 60 };   // сервер ответил: мозг действительно спит
  await api.brainRefresh(); api.paintBrainNote();
  check("заметка чата: мозг спит -> chat_note_off", elFor("chatNote").textContent === api.I18N.ru.chat_note_off);
  brainJson = { ok: false, phase: "starting", url: null, key: "k",
                model: "m", ts: Math.floor(Date.now() / 1000) - 120 };
  await api.brainRefresh(); api.paintBrainNote();
  check("заметка чата: мозг поднимается -> chat_note_starting", elFor("chatNote").textContent === api.I18N.ru.chat_note_starting);
  brainJson = { ok: true, url: "https://tun.trycloudflare.com", key: "k",
                model: "m", ts: Math.floor(Date.now() / 1000) - 60 };
  await api.brainRefresh(); api.paintBrainNote();
  check("заметка чата: мозг на связи -> chat_note_on", elFor("chatNote").textContent === api.I18N.ru.chat_note_on);

  // 10) дисклеймер «симуляция, не Бог» есть во всех трёх языках и рендерится в чате и «О проекте»
  check("дисклеймер: есть в RU/EN/HE",
        !!api.I18N.ru.sim_note && !!api.I18N.en.sim_note && !!api.I18N.he.sim_note);
  check("дисклеймер: RU говорит «не сам Бог»", /не сам Бог/.test(api.I18N.ru.sim_note));
  check("дисклеймер: EN говорит «not God himself»", /not God himself/.test(api.I18N.en.sim_note));
  check("дисклеймер: вставлен в чат и в «О проекте»",
        code.includes('class="disclaim">${t("sim_note")}') &&
        (code.match(/class="disclaim">\$\{t\("sim_note"\)\}/g) || []).length === 2);
  // 11) паритет сверки: JS-правила страницы == Python-эталон (общие фикстуры)
  const cases = JSON.parse(fs.readFileSync(__dirname + "/../scripts/guard_cases.json", "utf8")).cases;
  for (const c of cases) {
    const reply = api.hebWords(c.hebrew);
    const cc = api.guardCtxCoverage(reply, c.fragments);
    check(`guard «${c.name}»: ctx_cov=${cc.toFixed(3)}`, Math.abs(cc - c.ctx_cov) < 0.005);
    const corpus = c.corpus.map(e => [e.book, e]);
    const hits = (c.hits || []).map(e => [e.book, e]);
    const v = api.guardVerify(c.hebrew, c.fragments, corpus, hits);
    check(`guard «${c.name}»: mode=${v.mode}`, v.mode === c.mode);
    const got = v.sources.length ? `${v.sources[0][0]}|${v.sources[0][1].span.start}` : null;
    check(`guard «${c.name}»: источник ${got}`, got === c.source);
  }
  // 11b) границы правил — те же, что в scripts/answer_guard.py
  check("guard: слова короче 2 символов не считаются", api.hebWords("א ו ל").length === 0);
  check("guard: огласовка не мешает сверке",
        JSON.stringify(api.hebWords("שְׁמַעְתֶּֽם")) === JSON.stringify(api.hebWords("שמעתם")));
  check("guard: маккеф разделяет слова",
        JSON.stringify(api.hebWords("אל־משה")) === JSON.stringify(["אל", "משה"]));
  check("guard: ведущий «ו» не мешает сверке", api.hebNorm("וענני") === "ענני");
  check("guard: пустая реплика не проходит", api.guardVerify("", ["שמע"], []).mode === "reject");
  check("guard: точная цитата проходит", api.guardVerify("שמע יהוה", ["שמע יהוה קולי"], []).mode === "verified");
  check("guard: пересказ не проходит", api.guardVerify("אני אלהים רב רע", ["ויאמר יהוה אל משה"], []).mode === "reject");

  // 12) сквозная сверка на странице: подтверждённая реплика — с источником из реестра;
  //     неподтверждённая — заменяется проверенным прецедентом корпуса
  llmShouldFail = false;
  brainJson = { ok: true, url: "https://tun.trycloudflare.com", key: "k", model: "m",
                ts: Math.floor(Date.now() / 1000) - 60 };
  await api.brainRefresh();
  llmResponse = { choices: [{ message: { content:
    "[HEBREW] איכה\n[NIKKUD] אַיֵּה\n[Russian] Где ты?\n[English] Where art thou?\n[Hebrew Modern] איפה אתה\n[SOURCES] Genesis 3:9" } }] };
  const okHtml = await api.liveHTML(await api.liveReply("я боюсь"));
  check("страница: подтверждённая реплика показана с пометкой сверки",
        okHtml.includes("איכה") && okHtml.includes(api.I18N.ru.guard_ok));
  check("страница: источник взят из реестра", okHtml.includes("3:9") && okHtml.includes('srcDive('));
  llmResponse = { choices: [{ message: { content:
    "[HEBREW] ענני יהוה ביום צרה קראני ואענה\n[NIKKUD] עֲנֵנִי\n[Russian] Услышь меня\n[English] Hear me\n[Hebrew Modern] הקשיב לי\n[SOURCES] Psalms 27:7" } }] };
  const badHtml = await api.liveHTML(await api.liveReply("я боюсь"));
  check("страница: неподтверждённая реплика не показана (заменена прецедентом корпуса)",
        !badHtml.includes("ביום צרה") && badHtml.includes("איכה") && badHtml.includes(api.I18N.ru.he_layer_note));

  console.log(`\n${pass} PASS, ${fail} FAIL`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error("CRASH:", e); process.exit(2); });