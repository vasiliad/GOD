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
let brainJson = null;          // ответ brain_status
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
  getElementById: () => ({ textContent:"", title:"", value:"" }),
  createElement: () => ({ className:"", innerHTML:"", prepend(){} }),
  querySelectorAll: () => ({ forEach(){} })
};
global.window = { scrollTo(){}, _brainTimer: null, setInterval: () => 1, clearInterval(){} };

const api = new Function(
  "var nav={innerHTML:'',querySelectorAll:()=>({forEach(){}})};var main={innerHTML:''};" +
  code + "\nreturn { brainRefresh, liveReply, parseSections, retrieve, classify, BRAIN, store };")();

(async () => {
  let pass = 0, fail = 0;
  const check = (name, cond) => { cond ? (pass++, console.log("PASS", name)) : (fail++, console.log("FAIL", name)); };

  // 1) мозг офлайн: brain.json недоступен -> state off, liveReply кидает ошибку
  brainJson = null;
  await api.brainRefresh();
  check("офлайн: state=off", api.BRAIN.info.state === "off");
  let threw = false;
  try { await api.liveReply("я боюсь"); } catch (e) { threw = true; }
  check("офлайн: liveReply бросает (корпусный фолбэк)", threw);

  // 2) мозг онлайн: свежий ok:true -> state on, POST на туннель, 6 секций
  brainJson = { ok: true, url: "https://tun.trycloudflare.com", key: "godbrain-v1-vasiliad",
                model: "dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF", ts: Math.floor(Date.now() / 1000) - 60 };
  await api.brainRefresh();
  check("онлайн: state=on", api.BRAIN.info.state === "on");
  llmResponse = { choices: [{ message: { content:
    "[HEBREW] איכה\n[NIKKUD] אַיֵּה\n[Russian] Где ты?\n[English] Where art thou?\n[Hebrew Modern] איפה אתה\n[SOURCES] Genesis 3:9" } }] };
  calls.length = 0;
  const r = await api.liveReply("я боюсь");
  const called = calls.find(u => u.includes("/v1/chat/completions"));
  check("онлайн: POST ушёл на туннель", !!called && called.startsWith("https://tun.trycloudflare.com"));
  check("онлайн: 6 секций распознаны", Object.keys(r.sections).length === 6);
  check("онлайн: HEBREW совпадает", r.sections["[HEBREW]"] === "איכה");
  check("онлайн: SOURCES совпадает", r.sections["[SOURCES]"] === "Genesis 3:9");

  // 3) мозг онлайн, но LLM упал (503) -> liveReply бросает => send() ответит корпусом
  llmShouldFail = true;
  threw = false;
  try { await api.liveReply("спаси меня"); } catch (e) { threw = true; }
  check("LLM-ошибка: liveReply бросает (=> корпусный фолбэк)", threw);

  // 4) мозг поднимается: ok:false + phase=starting, свежий пульс -> state starting, liveReply отказывает
  brainJson = { ok: false, phase: "starting", url: null, key: "godbrain-v1-vasiliad",
                model: "dicta-il/DictaLM-3.0-Nemotron-12B-Instruct-GGUF", ts: Math.floor(Date.now() / 1000) - 120 };
  await api.brainRefresh();
  check("старт: state=starting (🟡)", api.BRAIN.info.state === "starting");
  threw = false;
  try { await api.liveReply("я боюсь"); } catch (e) { threw = true; }
  check("старт: liveReply отказывает (ввод заблокирован)", threw);

  // 5) протухший пульс (2 часа) -> state off
  brainJson.ok = true; brainJson.ts = Math.floor(Date.now() / 1000) - 7200;
  await api.brainRefresh();
  check("протухший пульс: state=off", api.BRAIN.info.state === "off");

  console.log(`\n${pass} PASS, ${fail} FAIL`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error("CRASH:", e); process.exit(2); });
