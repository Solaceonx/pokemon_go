// Exercise the actual HTML/video synchronization through a local headless browser.
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const [port, html, screenshot, libraryRoot] = process.argv.slice(2);
let targets;
for (let i=0;i<60;i++) {
  try {targets=await (await fetch(`http://127.0.0.1:${port}/json`)).json();break}
  catch {await new Promise(r=>setTimeout(r,200))}
}
if(!targets)throw Error('Browser did not start');
const ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
let id=0;const pending=new Map(),errors=[];
ws.onmessage=({data})=>{const msg=JSON.parse(data);if(msg.method==='Runtime.exceptionThrown')errors.push(msg.params.exceptionDetails.text);if(msg.id){const p=pending.get(msg.id);pending.delete(msg.id);msg.error?p.reject(Error(msg.error.message)):p.resolve(msg.result)}};
function send(method,params={}){return new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}))})}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value}
async function wait(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,100))}throw Error('Timed out: '+expression)}
function assert(value,message){if(!value)throw Error(message)}
try {
 await send('Runtime.enable');await send('Page.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:1450,height:1050,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:html.startsWith('http')?html:pathToFileURL(html).href});
 await wait('Boolean(window.battleViewer) && document.getElementById("video").readyState >= 2 && Math.abs(document.getElementById("video").currentTime - 5) < .1');
 assert(await evaluate('document.getElementById("phase").textContent === "Normal fighting"'),'Initial video and reading do not align');
 assert(await evaluate('!document.getElementById("video-title").textContent.includes("Â")'),'Battle title encoding failed');
 assert(await evaluate('document.getElementById("estimate-status").textContent.includes("00:05.000")'),'Initial tracker state not aligned');
 await evaluate('document.getElementById("video").play()');
 await wait('document.getElementById("video").currentTime > 5.2');
 await evaluate('document.getElementById("video").pause()');
 assert(await evaluate('JSON.parse(document.getElementById("raw").textContent).t <= document.getElementById("video").currentTime + .001'),'Playback shows future frame data');
 assert(await evaluate('document.getElementById("storage").textContent.includes("MB")'),'Storage estimates missing');
 assert(await evaluate('document.getElementById("source").options[0].textContent.includes("training")'),'Dataset assignments missing from viewer');
 await evaluate('battleViewer.seek(16)');await wait('!document.getElementById("video").seeking');
 assert(await evaluate('document.getElementById("state-raw").textContent.includes("Body Slam")'),'Post-attack observation not synchronized');
 assert(await evaluate('document.getElementById("cards").textContent.includes("Shields left1")'),'Shield update missing');
 await evaluate('battleViewer.seek(64.2)');await wait('!document.getElementById("video").seeking');
 assert(await evaluate('document.getElementById("cards").textContent.includes("76.8%–79.7%")'),'Settled visible health range missing');
 assert(await evaluate('document.getElementById("values-current").textContent.includes("76.8%–79.7%")'),'Live table does not follow health readings');
 assert(await evaluate('Array.from(document.querySelectorAll("#values-history tr")).every(r=>r.cells[0].textContent <= "01:04.200")'),'Live history includes future readings');
 assert(await evaluate('document.getElementById("review-phase").value === "" && document.getElementById("review-mine-low").value === ""'),'Review labels auto-filled from predictions');
 await evaluate('battleViewer.seek(41.1)');await wait('!document.getElementById("video").seeking');
 await evaluate('document.getElementById("review-blind").checked=true;document.getElementById("review-blind").dispatchEvent(new Event("change"))');
 assert(await evaluate('getComputedStyle(document.getElementById("values-panel")).visibility === "hidden"'),'Blind review shows predictions');
 await evaluate('document.getElementById("review-phase").value="normal_fighting";document.getElementById("review-form").requestSubmit()');
 assert(await evaluate('battleViewer.valueSheet.getReviews().some(r=>r.battle_id==="reis-01"&&Math.abs(r.clip_seconds-41.1)<.001&&r.phase==="normal_fighting"&&r.reviewed_without_predictions&&!r.mine)'),'Human label saving or source alignment failed');
 await evaluate('localStorage.removeItem("battle-lens-human-labels-v1");document.getElementById("review-blind").checked=false;document.getElementById("review-blind").dispatchEvent(new Event("change"))');
 assert(await evaluate('document.getElementById("cards").textContent.includes("Max HP needed")'),'Unknown maximum HP presented as known');
 assert(await evaluate('battleViewer.valueSheet.flatten({t:0,mine:{health_bar:{value:null,status:"unknown"},health_estimate:{status:"unknown"},shields_left:{value:0,status:"observed"}}},"mine",{id:"check",source_start:52.4}).visible_health_fraction === null'),'Live table converts unknown health to zero');
 assert(await evaluate('battleViewer.valueSheet.flatten({t:2,mine:{shields_left:{value:0,status:"observed"}}},"mine",{id:"check",source_start:52.4}).shields_left === 0'),'Live table loses observed zero');
 await evaluate('document.getElementById("values-panel").scrollIntoView()');
 const sheetCapture=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(screenshot.replace(/\.png$/,'-table.png'),Buffer.from(sheetCapture.data,'base64'));
 await evaluate('window.scrollTo(0,0)');
 await evaluate('battleViewer.seek(35)');await wait('!document.getElementById("video").seeking');
 assert(await evaluate('document.getElementById("phase").textContent === "Shield choice"'),'Shield prompt not synchronized');
 assert(await evaluate('document.getElementById("state-raw").textContent === "No tracker state for this timestamp."'),'Tracker falsely held beyond coverage');
 await evaluate('battleViewer.seek(16)');await wait('!document.getElementById("video").seeking');
 await evaluate('document.getElementById("next").click()');await wait('!document.getElementById("video").seeking');
 assert(await evaluate('Math.abs(document.getElementById("video").currentTime - (16+1/30)) < .002'),'Frame step failed');
 await evaluate('battleViewer.render(500)');
 assert(await evaluate('document.getElementById("phase").textContent === "No readings at this time"'),'Missing data falsely shown as current');
 await evaluate('battleViewer.seek(16)');await wait('!document.getElementById("video").seeking');
 const capture=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(screenshot,Buffer.from(capture.data,'base64'));
 const henryIndex=await evaluate('Array.from(document.getElementById("source").options).findIndex(o=>o.textContent.includes("Henry"))');
 assert(henryIndex>=0,'Henry battle absent from library');
 await evaluate(`battleViewer.loadSource(${henryIndex})`);await wait('document.getElementById("video").readyState >= 2 && Math.abs(document.getElementById("video").currentTime) < .1');
 assert(await evaluate('document.getElementById("estimate-status").textContent.includes("No tracker run")'),'Henry inherits wrong tracker state');
 assert(await evaluate('battleViewer.getMemoryStats().decoded_sources === 1'),'Inactive battle readings retained in memory');
 await evaluate(`Promise.all([battleViewer.loadSource(0),battleViewer.loadSource(${henryIndex})])`);
 await wait('document.getElementById("video").readyState >= 2 && battleViewer.getSource().id.startsWith("henry-")');
 assert(await evaluate('battleViewer.getMemoryStats().decoded_sources === 1'),'An obsolete asynchronous load retained inactive readings');
 await evaluate('document.getElementById("speed").value="0.5"; document.getElementById("speed").dispatchEvent(new Event("change"))');
 assert(await evaluate('document.getElementById("video").playbackRate === .5'),'Speed control failed');
 const pendingIndex=await evaluate('Array.from(document.getElementById("source").options).findIndex(o=>o.textContent.includes("Battle 02")&&o.textContent.includes("Reis"))');
 await evaluate(`battleViewer.loadSource(${pendingIndex})`);await wait('document.getElementById("video").readyState >= 2 && battleViewer.getSource().id === "reis-02"');
 assert(await evaluate('battleViewer.getSource().readings.length > 0'),'Full library run missing readings');
 await evaluate('document.getElementById("dataset-filter").value="test";document.getElementById("dataset-filter").dispatchEvent(new Event("change"))');
 await wait('battleViewer.getSource().id.startsWith("henry-") && document.getElementById("video").readyState >= 2');
 assert(await evaluate('document.getElementById("source").options.length === 9 && Array.from(document.getElementById("source").options).every(o=>o.textContent.includes("regression test"))'),'Test-set filter mixes source partitions');
 await evaluate('document.getElementById("dataset-filter").value="train";document.getElementById("dataset-filter").dispatchEvent(new Event("change"))');
 await wait('battleViewer.getSource().id.startsWith("reis-") && document.getElementById("video").readyState >= 2');
 assert(await evaluate('document.getElementById("source").options.length === 9'),'Training-set filter missing videos');
 await evaluate('document.getElementById("dataset-filter").value="all";document.getElementById("dataset-filter").dispatchEvent(new Event("change"))');
 await wait('document.getElementById("source").options.length === 18 && document.getElementById("video").readyState >= 2');
 if(libraryRoot){
  const doc=await send('DOM.getDocument');const node=await send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#battle-folder'});
  await send('DOM.setFileInputFiles',{nodeId:node.nodeId,files:[libraryRoot]});
  await wait('Boolean(battleViewer.getSource().videoFile) && document.getElementById("video").readyState >= 2');
  assert(await evaluate('document.getElementById("source").options.length === 18'),'Folder import includes superseded combined battle');
  assert(await evaluate('document.getElementById("video").src.startsWith("blob:")'),'Folder video did not load through user file selection');
  await evaluate('battleViewer.importFolder([new File([battleViewer.getSource().videoFile],"my-battle.mp4",{type:"video/mp4"})])');
  await wait('battleViewer.getSource().name === "my-battle" && document.getElementById("video").readyState >= 2');
  assert(await evaluate('document.getElementById("next").disabled'),'Raw video has an invented frame rate');
  assert(await evaluate('document.getElementById("freshness").textContent.includes("not been analyzed")'),'Raw clip import invents readings');
 }
 assert(!errors.length,'Browser script errors: '+errors.join('; '));
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert(await evaluate('document.documentElement.scrollWidth <= 390'),'Mobile page has horizontal overflow');
 console.log('PASS: clip playback, timestamps, shield update, seeking, coverage limits, frame stepping, library selection, pending analysis, speed, folder import, and no script errors.');
} finally {ws.close()}
