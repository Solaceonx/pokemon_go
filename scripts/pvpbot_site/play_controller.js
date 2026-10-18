// The page's side of a battle against the bot: the setup screen, the clock, prompts, notes and saved games.
// The battle itself runs in play_worker.js (Python, play_api.py); the battle screen is scripts/play/index.html's.
const ACTIONS = { c0: 1, c1: 2, s0: 3, s1: 4, s2: 5 };
const STORE = "pvpbot-games";
const worker = new Worker("play_worker.js");
const calls = {};
let callId = 0, INFO = null, BY_NAME = {}, BY_ID = {}, G = null;

worker.onmessage = (e) => {
  const m = e.data;
  if (m.type === "status") startButton(m.text, true);
  else if (m.type === "ready") startButton("Start the battle", false);
  else if (m.type === "result") { calls[m.id].resolve(m.out); delete calls[m.id]; }
  else if (m.type === "error") {
    if (m.id !== undefined && calls[m.id]) { calls[m.id].reject(m.text); delete calls[m.id]; }
    else startButton("Could not load the bot: " + m.text, true);
  }
};
function call(fn, arg) {
  return new Promise((resolve, reject) => { const id = callId++; calls[id] = { resolve, reject }; worker.postMessage({ id, fn, arg }); });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function startButton(text, disabled) { $("start").textContent = text; $("start").disabled = disabled; }

// --- saved games
function games() { try { return JSON.parse(localStorage.getItem(STORE) || "[]"); } catch (e) { return []; } }
function keep(list) { try { localStorage.setItem(STORE, JSON.stringify(list)); } catch (e) { /* private window: nothing kept */ } }
function tally() { const g = games(); return { win: g.filter((r) => r.result === "win").length, loss: g.filter((r) => r.result === "loss").length }; }
function stamp(d) { const p = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`; }
function listGames() {
  const g = games().slice().reverse();
  $("games").innerHTML = g.length ? g.slice(0, 30).map((r) => `<div class="game"><b class="${r.result}">${{ win: "Win", loss: "Loss", draw: "Draw" }[r.result]}</b>
    · ${r.started.replace("_", " ").slice(0, 16)} · ${r.mine.map(name).join(" / ")} vs ${r.theirs.map(name).join(" / ")}
    ${r.lineup_win_chance ? `· line-up ${Math.round(100 * r.lineup_win_chance[0])}%` : ""}
    ${r.notes ? `<div class="note">${r.notes.replace(/</g, "&lt;")}</div>` : ""}</div>`).join("") : `<div class="small">No games yet.</div>`;
}
$("download").onclick = () => {
  const who = ($("player").value.trim() || "player").replace(/[^A-Za-z0-9_-]/g, "");
  const blob = new Blob([JSON.stringify(games(), null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `pvpbot-games-${who}-${stamp(new Date()).slice(0, 10)}.json`; a.click();
};

// --- the setup screen
const name = (id) => (BY_ID[id] ? BY_ID[id].name : id);
function find(text) { const t = text.trim().toLowerCase(); return BY_NAME[t] || BY_ID[t] || null; }
function slots(box, values) {
  $(box).innerHTML = values.map((v, i) => `<div class="slotrow"><span>${i ? "back" : "lead"}</span><img alt="">
    <input value="${v}" list="species" autocomplete="off" spellcheck="false"></div>`).join("");
  $(box).querySelectorAll("input").forEach((inp) => { inp.addEventListener("input", () => look(inp)); look(inp); });
}
function look(inp) {
  const sp = find(inp.value), img = inp.parentElement.querySelector("img");
  inp.classList.toggle("bad", !sp && inp.value.trim() !== "");
  img.src = sp ? `https://play.pokemonshowdown.com/sprites/gen5/${sp.showdown}.png` : "";
  img.style.visibility = sp ? "visible" : "hidden";
}
function picked(box) { return [...$(box).querySelectorAll("input")].map((i) => find(i.value)); }
const radio = (n) => document.querySelector(`input[name=${n}]:checked`).value;
document.querySelectorAll("input[name=foe]").forEach((r) => r.addEventListener("change", () => {
  for (const k of ["random", "top", "custom"]) $("foe-" + k).hidden = radio("foe") !== k;
}));
function legal(team) { return !team.includes(null) && new Set(team.map((s) => s.dex)).size === 3; }
function randomTeam() {
  const pool = INFO.species.slice(0, 50);
  for (;;) {
    const t = [...pool].sort(() => Math.random() - 0.5).slice(0, 3);
    if (new Set(t.map((s) => s.dex)).size === 3) return t.map((s) => s.id);
  }
}
function foeTeam() {
  const kind = radio("foe");
  if (kind === "random") return randomTeam();
  if (kind === "top") {
    const v = $("top-team").value;
    const team = v === "any" ? INFO.top[Math.floor(Math.random() * INFO.top.length)].team : INFO.top[Number(v)].team;
    return team;
  }
  const t = picked("foe-custom");
  return legal(t) ? t.map((s) => s.id) : null;
}

$("start").onclick = () => {
  const mine = picked("my-team");
  if (!legal(mine)) { startButton("Pick three different known Pokémon for your team", false); return; }
  const theirs = foeTeam();
  if (!theirs) { startButton("Pick three different known Pokémon for the bot", false); return; }
  play({ mine: mine.map((s) => s.id), theirs, owned: $("owned").checked, bot: radio("bot"), speed: Number(radio("speed")) });
};

// --- the battle
function act(a) { if (G && !G.over && ACTIONS[a] !== undefined) G.queued = ACTIONS[a]; }
function answer(value) { if (G && G.prompt) { const p = G.prompt; G.prompt = null; p.resolve(value); } }
function ask(kind, options, seconds, fallback) {
  return new Promise((resolve) => {
    G.prompt = { kind, options, until: Date.now() + 1000 * seconds, resolve };
    setTimeout(() => { if (G.prompt && G.prompt.resolve === resolve) { G.prompt = null; resolve(fallback); } }, 1000 * seconds);
  });
}
function newBattle() { if (G && G.over && G.record) { saveNotes(); play(G.config); } }
function changeTeams() { saveNotes(); G = null; $("game").style.display = "none"; $("setup").style.display = ""; listGames(); }
function saveNotes() {
  if (!G || !G.record) return;
  const list = games(), i = list.findIndex((r) => r.started === G.record.started);
  G.record.notes = $("notes").value;
  if (i >= 0) { list[i].notes = G.record.notes; keep(list); }
}
function screen() {
  const s = G.state, now = Date.now();
  return { ...s, bot: G.config.bot === "engine" ? "engine" : "trained bot", tally: tally(), eval: null, review: G.review || null,
    charging: now < G.pauseUntil, countdown: Math.max(0, (G.startAt - now) / 1000),
    prompt: G.prompt ? { kind: G.prompt.kind, options: G.prompt.options, seconds: Math.max(0, (G.prompt.until - now) / 1000) } : null };
}
setInterval(() => {
  if (!G || !G.state) return;
  render(screen());
  if (G.over) $("end-text").textContent = G.endText;
}, 100);

async function play(config) {
  $("end-box").classList.remove("open");
  $("review").dataset.done = ""; $("review").replaceChildren();
  $("notes").value = "";
  $("setup").style.display = "none"; $("game").style.display = "flex";
  const tick = Number(new URLSearchParams(location.search).get("tick")) || 500 * config.speed;  // ?tick= for testing
  G = { config, state: null, queued: null, prompt: null, pauseUntil: 0, startAt: Date.now() + 3000, over: false, record: null,
        endText: "", started: new Date() };
  const game = G;
  const out = await call("new", { mine: config.mine, theirs: config.theirs, owned: config.owned, bot: config.bot, tick_ms: tick });
  if (G !== game) return;
  G.state = out.state;
  await sleep(Math.max(0, G.startAt - Date.now()));
  while (G === game && !G.state.winner) {
    const t0 = Date.now(), answers = [];
    let res;
    for (;;) {
      res = await call("step", { action: G.queued, answers });
      G.state = res.state;
      if (!res.need) break;
      answers.push(await ask(res.need, res.options, res.need === "shield" ? 6 : 12, res.need === "shield" ? false : res.options[0]));
    }
    if (res.took) G.queued = null;
    if (G.state.winner) break;
    // A charged move holds the screen from when it lands: longer after ours, so there is time to choose what next.
    const hold = Math.max(res.throwers.includes(0) ? 4000 : 0, res.throwers.includes(1) ? 2000 : 0);
    if (hold) { G.pauseUntil = Date.now() + hold; await sleep(hold); }
    else await sleep(Math.max(0, tick - (Date.now() - t0)));
  }
  if (G !== game) return;
  G.over = true;
  G.endText = "Working out how your line-up does against this one…";
  const rec = await call("finish", "");
  rec.started = stamp(G.started);
  rec.player = $("player").value.trim();
  try { localStorage.setItem("pvpbot-player", rec.player); } catch (e) { /* nothing kept */ }
  const list = games(); list.push(rec); keep(list);
  G.record = rec;
  G.review = rec.review;  // the advantage over the battle, drawn by the battle screen's own review
  const [chance, margin] = rec.lineup_win_chance;
  G.endText = `Before anyone decided anything, your line-up wins ${Math.round(100 * chance)}% (± ${Math.round(100 * margin)}) against this one when two equally good bots play it. Saved in this browser; add notes below.`;
}

(async () => {
  INFO = await (await fetch("species.json")).json();
  for (const s of INFO.species) { BY_NAME[s.name.toLowerCase()] = s; BY_ID[s.id] = s; }
  $("species").innerHTML = INFO.species.map((s) => `<option value="${s.name}">`).join("");
  slots("my-team", INFO.mine.map(name));
  slots("foe-custom", ["Corviknight", "Tinkaton", "Mandibuzz"]);
  $("top-team").innerHTML = `<option value="any">Any of them at random</option>` +
    INFO.top.map((t, i) => `<option value="${i}">${t.team.map(name).join(" / ")}</option>`).join("");
  try { $("player").value = localStorage.getItem("pvpbot-player") || ""; } catch (e) { /* nothing kept */ }
  listGames();
})();
