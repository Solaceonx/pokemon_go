import {pathToFileURL} from 'node:url';
const [port, html] = process.argv.slice(2);
let targets;
for(let i=0;i<60;i++){
  try{targets=await(await fetch(`http://127.0.0.1:${port}/json`)).json();break}
  catch{await new Promise(r=>setTimeout(r,200))}
}
if(!targets)throw Error('Browser did not start');
const ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
let id=0;const pending=new Map(),errors=[];
ws.onmessage=({data})=>{const m=JSON.parse(data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}};
function send(method,params={}){return new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}))})}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value}
try{
  await send('Runtime.enable');await send('Page.enable');
  await send('Page.navigate',{url:html.startsWith('http')?html:pathToFileURL(html).href});
  for(let i=0;i<100;i++){if(await evaluate('Boolean(window.battleViewer)'))break;await new Promise(r=>setTimeout(r,100))}
  const checks=await evaluate('({ready:Boolean(window.battleViewer),phase:document.getElementById("phase").textContent,buttonsDisabled:document.getElementById("back").disabled&&document.getElementById("next").disabled,decoded:window.battleViewer?.getMemoryStats().decoded_sources,status:document.getElementById("media-status").textContent})');
  if(!checks.ready||checks.phase!=='No battles loaded'||!checks.buttonsDisabled||checks.decoded!==0||!checks.status.includes('Open a battles folder'))throw Error(JSON.stringify(checks));
  if(errors.length)throw Error(errors.join('\n'));
  process.stdout.write('PASS: fresh empty viewer opens with folder-import guidance and no script errors.\n');
}finally{ws.close()}
