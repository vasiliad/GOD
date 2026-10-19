/* E2E рекомбинации: реальный retrieval по корпусу -> реальный мозг -> 6 секций.
   Вопрос передаётся аргументом. Использует локальные данные сайта (docs/data). */
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(__dirname + "/../docs/index.html", "utf8");
let code = html.match(/<script>([\s\S]*)<\/script>/)[1];
code = code.split("/* ---------- роутер ---------- */")[0];

const QUESTION = process.argv[2] || "почему ты медлишь спасти меня от врагов?";
const DOCS = path.join(__dirname, "..", "docs");

global.localStorage = { getItem: () => null, setItem(){}, removeItem(){} };
global.fetch = async (url) => {
  if (url.includes("god-brain-status") || url.startsWith("https://"))
    return (await import("node:https")).request ? null : null; // не используется: brainRefresh мокнем ниже
  const p = path.join(DOCS, url.replace(/^\.\//, ""));
  const data = fs.readFileSync(p);
  const json = JSON.parse(data);
  return { ok: true, json: async () => json };
};
global.document = { getElementById: () => ({ textContent:"", title:"" }) };
global.window = { setInterval: () => 1, clearInterval(){} };

const api = new Function(code + "\nreturn { brainRefresh, liveReply, BRAIN };")();

(async () => {
  // brain.json берём по-настоящему (fetch выше перехватит только локальные пути)
  const status = JSON.parse(fs.readFileSync(__dirname + "/brain_snapshot.json", "utf8"));
  const ageSec = Date.now() / 1000 - status.ts;
  console.log("мозг:", status.url, "| модель:", status.model, "| возраст пульса, c:", Math.round(ageSec));
  global.fetch = async (url) => {
    if (url.includes("god-brain-status"))
      return { ok: true, json: async () => status };
    const p = path.join(DOCS, url.replace(/^\.\//, ""));
    return { ok: true, json: async () => JSON.parse(fs.readFileSync(p)) };
  };
  await api.brainRefresh();
  console.log("BRAIN.info:", JSON.stringify(api.BRAIN.info));
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
