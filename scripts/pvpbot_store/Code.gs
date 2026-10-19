// The website's game store: a Google Apps Script web app that keeps each game played on
// solaceonx.github.io/pokemon_go_pvpbot as one JSON file in the owner's Google Drive (folder "pvpbot games").
// Set up once by the owner (scripts/pvpbot_store/README.md). The page POSTs a game; sending it again (notes added
// later) replaces the file. `python3 scripts/import_played.py --store` reads them back by POSTing the read key (in
// the body, never in the address), which lives only in this project's Script Properties (READ_KEY) and in the
// owner's untracked .pvpbot_store.json.

const FOLDER = "pvpbot games";
const MAX_BYTES = 500000;

function folder_() {
  const found = DriveApp.getFoldersByName(FOLDER);
  return found.hasNext() ? found.next() : DriveApp.createFolder(FOLDER);
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  const body = (e && e.postData && e.postData.contents) || "";
  if (body.length > MAX_BYTES) return reply_({ ok: false, error: "too big" });
  let game;
  try { game = JSON.parse(body); } catch (err) { return reply_({ ok: false, error: "not JSON" }); }
  if (game && game.read_key !== undefined) return read_(game);
  const started = String(game.started || "");
  if (!/^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d$/.test(started) || !["win", "loss", "draw"].includes(game.result) ||
      !Array.isArray(game.mine) || !Array.isArray(game.theirs)) return reply_({ ok: false, error: "not a game" });
  const who = String(game.player || "web").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 30) || "web";
  const name = `${started}-${who}.json`;
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const dir = folder_();
    const old = dir.getFilesByName(name);
    if (old.hasNext()) old.next().setContent(body);
    else dir.createFile(name, body, "application/json");
  } finally {
    lock.releaseLock();
  }
  return reply_({ ok: true, name: name });
}

function doGet(e) {
  return reply_({ ok: false, error: "read key needed" });  // reading is by POST, so the key never sits in an address
}

function read_(request) {
  const key = PropertiesService.getScriptProperties().getProperty("READ_KEY");
  if (!key || request.read_key !== key) return reply_({ ok: false, error: "read key needed" });
  const after = Number(request.after || 0);
  const games = [];
  const files = folder_().getFiles();
  while (files.hasNext()) {
    const f = files.next();
    if (f.getLastUpdated().getTime() > after) {
      try { games.push(JSON.parse(f.getBlob().getDataAsString())); } catch (err) { /* skip a damaged file */ }
    }
  }
  return reply_({ ok: true, now: Date.now(), games: games });
}
