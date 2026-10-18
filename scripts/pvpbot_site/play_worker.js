// Runs a battle against the bot in the background with Pyodide (play_api.py), one step per message.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let py = null;

async function boot() {
  py = await loadPyodide();
  postMessage({ type: "status", text: "Loading numpy…" });
  await py.loadPackage("numpy");
  postMessage({ type: "status", text: "Loading the bot…" });
  const buf = await (await fetch("bundle.zip")).arrayBuffer();
  py.unpackArchive(buf, "zip", { extractDir: "/home/pyodide/pvpbot" });
  py.runPython(`import sys; sys.path.insert(0, "/home/pyodide/pvpbot"); import play_api; play_api.setup()`);
  postMessage({ type: "ready" });
}

const booting = boot().catch((e) => postMessage({ type: "error", text: String(e) }));

onmessage = async (event) => {
  await booting;
  const { id, fn, arg } = event.data;
  try {
    py.globals.set("call_arg", JSON.stringify(arg));
    const out = JSON.parse(py.runPython(`play_api.${fn}(call_arg)`));
    postMessage({ type: "result", id, out });
  } catch (e) {
    postMessage({ type: "error", id, text: String(e) });
  }
};
