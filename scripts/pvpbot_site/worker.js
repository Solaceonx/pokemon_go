// Runs the Python simulator in the background with Pyodide, so the page stays responsive.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let py = null;

async function boot() {
  py = await loadPyodide();
  postMessage({ type: "status", text: "Loading numpy…" });
  await py.loadPackage("numpy");
  postMessage({ type: "status", text: "Loading the simulator…" });
  const buf = await (await fetch("bundle.zip")).arrayBuffer();
  py.unpackArchive(buf, "zip", { extractDir: "/home/pyodide/pvpbot" });
  py.runPython(`import sys; sys.path.insert(0, "/home/pyodide/pvpbot"); import site_api; site_api.setup()`);
  postMessage({ type: "ready" });
}

const booting = boot().catch((e) => postMessage({ type: "error", text: String(e) }));

onmessage = async (event) => {
  await booting;
  const { id, job } = event.data;
  try {
    py.globals.set("job_text", JSON.stringify(job));
    const out = JSON.parse(py.runPython("site_api.run(job_text)"));
    postMessage({ type: "result", id, ...out });
  } catch (e) {
    postMessage({ type: "error", id, text: String(e) });
  }
};
