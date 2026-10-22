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
let brainJson = null;
let llmResponse = null;         // ответ /v1/chat/completions
let llmShouldFail = false;
global.localStorage = {
  getItem: k => (k in LS ? LS[k] : null),
  setItem: (k, v) => { LS[k] = String(v); },
  removeItem: k => { delete LS[k]; }
};
global.fetch = async (url) => {
  calls.push(url);
  if (url.includes("god-brain-status")) {
    if (brainJson === null) throw new Error("network down");
    return { ok: true, json: async () => brainJson };
  }
  if (url.includes("/v1/chat/completions")) {
    if (llmShouldFail) return { ok: false, status: 503 };
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
global.document = {
  documentElement: { lang: "", dir: "" },
  title: "",
  getElementById: () => ({ textContent: "", title: "", value: "" }),
  createElement: () => ({ className: "", innerHTML: "", prepend() {} }),
  querySelectorAll: () => ({ forEach() {} })
};
global.window = { scrollTo(){}, _brainTimer: null, setInterval: () => 1, clearInterval(){} };

const api = new Function(
  "var nav={innerHTML:'',querySelectorAll:()=>({forEach(){}})};var main={innerHTML:''};" +
  code + "\nreturn { brainRefresh, liveReply, parseSections, retrieve, classify, BRAIN, store, I18N, dequant, cosv, embIndex, bookName, BOOK_NAMES, LANG };")();

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
  check("офлайн: liveReply бросает без POST (=> честное сообщение + корпусный прецедент)",
        threw && !calls.some(u => u.includes("/v1/chat/completions")));

  // 2) мозг онлайн: свежий ok:true -> state on, POST на туннель Kaggle, 6 секций
  brainJson = { ok: true, url: "https://tun.trycloudflare.com", key: "godbrain-v1-vasiliad",
                model: "dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF", ts: Math.floor(Date.now() / 1000) - 60 };
  await api.brainRefresh();
  check("онлайн: state=on", api.BRAIN.info.state === "on");
  llmResponse = { choices: [{ message: { content:
    "[HEBREW] איכה\n[NIKKUD] אַיֵּה\n[Russian] Где ты?\n[English] Where art thou?\n[Hebrew Modern] איפה אתה\n[SOURCES] Genesis 3:9" } }] };
  calls.length = 0;
  const r = await api.liveReply("я боюсь");
  const called = calls.find(u => u.includes("/v1/chat/completions"));
  check("онлайн: POST ушёл на туннель мозга", !!called && called.startsWith("https://tun.trycloudflare.com"));
  check("онлайн: 6 секций распознаны", Object.keys(r.sections).length === 6);
  check("онлайн: HEBREW совпадает", r.sections["[HEBREW]"] === "איכה");
  check("онлайн: SOURCES совпадает", r.sections["[SOURCES]"] === "Genesis 3:9");

  // 3) мозг онлайн, но LLM упал (503) -> liveReply бросает => send() ответит корпусом
  llmShouldFail = true;
  threw = false;
  try { await api.liveReply("спаси меня"); } catch (e) { threw = true; }
  check("LLM-ошибка: liveReply бросает (=> корпусный фолбэк)", threw);

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
  console.log(`\n${pass} PASS, ${fail} FAIL`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error("CRASH:", e); process.exit(2); });