/* E2E рекомбинации: реальный retrieval по корпусу -> реальный мозг -> 6 секций.
   Вопрос передаётся аргументом. Локальные данные сайта (docs/data) + настоящий HTTP к мозгу. */
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(__dirname + "/../docs/index.html", "utf8");
let code = html.match(/<script>([\s\S]*)<\/script>/)[1];
code = code.split("/* ---------- роутер ---------- */")[0];

const QUESTION = process.argv[2] || "почему ты медлишь спасти меня от врагов?";
const DOCS = path.join(__dirname, "..", "docs");
const realFetch = globalThis.fetch.bind(globalThis);

global.localStorage = { getItem: () => null, setItem(){}, removeItem(){} };
global.document = { getElementById: () => ({ textContent:"", title:"" }) };
global.window = { setInterval: () => 1, clearInterval(){} };
global.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes("god-brain-status")) {
    const status = JSON.parse(fs.readFileSync(__dirname + "/brain_snapshot.json", "utf8"));
    return { ok: true, json: async () => status };
  }
  if (u.startsWith("http")) return realFetch(u, opts);      // настоящий запрос к мозгу
  const p = path.join(DOCS, u.replace(/^\.\//, ""));        // data/ сайта — локально
  return { ok: true, json: async () => JSON.parse(fs.readFileSync(p)) };
};

const api = new Function(code + "\nreturn { brainRefresh, liveReply, BRAIN };")();

(async () => {
  await api.brainRefresh();
  console.log("мозг:", api.BRAIN.info.url, "| fresh:", api.BRAIN.info.fresh);
  console.log("ВОПРОС:", QUESTION);
  const t0 = Date.now();
  const r = await api.liveReply(QUESTION);
  console.log("латентность, c:", ((Date.now() - t0) / 1000).toFixed(1));
  console.log("секций распознано:", Object.keys(r.sections).length);
  for (const [tag, val] of Object.entries(r.sections))
    console.log("\n" + tag + "\n" + val);
  const ok = Object.keys(r.sections).length === 6 &&
             /[א-ת]/.test(r.sections["[HEBREW]"] || "") &&
             /[א-ת]/.test(r.sections["[NIKKUD]"] || "");
  console.log("\nVERDICT:", ok ? "PASS — шесть секций, иврит и огласовка на месте" : "CHECK MANUALLY");
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error("FAIL:", e); process.exit(2); });
