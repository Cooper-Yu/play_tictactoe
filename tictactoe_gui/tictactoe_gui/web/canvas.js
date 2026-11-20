"use strict";
const $=id=>document.getElementById(id),canvas=$('canvas'),ctx=canvas.getContext('2d');
let strokes=[],active=null,pointer=null,token=null,remote={state:'connecting',busy:false};
let pending=false,localMessage='',draftChanged=true,sentJob=null,dimensions=null;
let polling=false,epoch=0,imageBusy=false,imageSequence=-1,imageUrl=null;
const locked=()=>pending||remote.busy;
const ready=()=>!!token&&!!dimensions&&remote.environment==='real'&&remote.fresh&&remote.state==='ready'&&!locked();
function configure(value){
 if(!value||!(value.width_mm>0)||!(value.height_mm>0))return;
 if(!dimensions||dimensions.width_mm!==value.width_mm||dimensions.height_mm!==value.height_mm){
  dimensions=value;canvas.height=Math.round(canvas.width*value.height_mm/value.width_mm);
  document.querySelector('.screen').style.aspectRatio=`${value.width_mm}/${value.height_mm}`;
  $('dimensions').textContent=`${value.width_mm.toFixed(1)} × ${value.height_mm.toFixed(1)} mm Usable area · Inset on all sides 1 mm`;
 }
}
function paint(){
 const ours=!draftChanged&&sentJob!==null&&remote.job===sentJob;
 const progress=ours&&remote.drawing_progress?.shape==='canvas'?remote.drawing_progress:{};
 const done=ours&&remote.drawing_result?.shape==='canvas'&&remote.drawing_result.motion_completed;
 const completed=done?strokes.length:(progress.completed_input_strokes||0);
 const totalParts=done?remote.drawing_result.strokes:(progress.total_parts||0);
 const parts=done?totalParts:(progress.completed_parts||0);
 ctx.clearRect(0,0,canvas.width,canvas.height);ctx.lineCap='round';ctx.lineJoin='round';ctx.lineWidth=3.2;
 [...strokes,...(active?[active]:[])].forEach((s,i)=>{if(s.length<2)return;
  ctx.strokeStyle=ours&&remote.busy&&i+1===progress.source_stroke?'#effff9':'#94e5d7';ctx.beginPath();
  s.forEach(([u,v],j)=>j?ctx.lineTo(u*canvas.width,v*canvas.height):ctx.moveTo(u*canvas.width,v*canvas.height));ctx.stroke();});
 $('hint').classList.toggle('hidden',strokes.length>0||!!active);
 $('count').textContent=strokes.length;$('completed').textContent=`${parts} / ${totalParts}`;
 $('execute').disabled=!ready()||!!active||strokes.length===0;
 ['undo','clear'].forEach(id=>$(id).disabled=locked()||!!active||strokes.length===0);
 document.querySelectorAll('[data-asset]').forEach(b=>b.disabled=locked()||!!active||!dimensions);
 $('speed').disabled=locked();$('reset').disabled=!ready()||!remote.records?.Reset||!remote.records?.['Reset hover'];
 $('stop').disabled=pending||!remote.busy||remote.state==='stopping';
 const canConfirm=remote.state==='recovering'&&remote.feedback_recovery?.phase==='confirmation';
 $('ack-recovery').hidden=!canConfirm;
 $('ack-recovery').disabled=pending||!canConfirm;
 $('status').textContent=localMessage||remote.message||'Connecting';
 $('connection').textContent=remote.state==='offline'?'Workbench disconnected':remote.fresh?'Robot connected':'Waiting for arm feedback';
 $('connection').classList.toggle('ready',!!remote.fresh&&remote.state!=='offline');
 $('bar').style.width=totalParts?`${parts/totalParts*100}%`:'0%';
 $('strokes').replaceChildren(...strokes.map((s,i)=>{const li=document.createElement('li'),span=document.createElement('span');
  li.textContent=`Stroke ${i+1}`;span.textContent=ours&&remote.busy&&i+1===progress.source_stroke?'Running':i<completed?'completed':`${s.length} points`;
  li.className=ours&&remote.busy&&i+1===progress.source_stroke?'active':i<completed?'done':'';li.append(span);return li;}));
}
function point(e){const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];}
function distance(a,b){return Math.hypot((a[0]-b[0])*(dimensions?.width_mm||138),(a[1]-b[1])*(dimensions?.height_mm||177));}
canvas.addEventListener('pointerdown',e=>{if(locked()||e.button!==0||strokes.length>=32)return;
 draftChanged=true;sentJob=null;localMessage='';pointer=e.pointerId;active=[point(e)];canvas.setPointerCapture(pointer);e.preventDefault();paint();});
canvas.addEventListener('pointermove',e=>{if(e.pointerId!==pointer||!active)return;const p=point(e);
 if(distance(p,active.at(-1))>=.20){if(active.length>=2000){localMessage='Each stroke supports up to 2000 points, Release and continue with another stroke';paint();return;}active.push(p);paint();}});
canvas.addEventListener('pointerup',e=>{if(e.pointerId!==pointer||!active)return;const p=point(e);
 if(distance(p,active.at(-1))>.01){if(active.length<2000)active.push(p);else active[active.length-1]=p;}
 if(active.length>=2)strokes.push(active);active=null;pointer=null;paint();});
canvas.addEventListener('pointercancel',()=>{active=null;pointer=null;paint();});
$('undo').onclick=()=>{strokes.pop();draftChanged=true;sentJob=null;localMessage='';paint();};
$('clear').onclick=()=>{strokes=[];draftChanged=true;sentJob=null;localMessage='Draft cleared, Real tablet contents preserved';paint();};
async function jsonRequest(path,options={}){const r=await fetch(path,{...options,signal:AbortSignal.timeout(5000)});const data=await r.json();if(!r.ok)throw Error(r.status===403?'Session changed, Refresh the page and retry':data.error||`Request failed ${r.status}`);return data;}
async function command(path,data={}){
 if(pending)return;epoch++;pending=true;localMessage='Submitting…';paint();
 try{const ack=await jsonRequest(path,{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':token},body:JSON.stringify(data)});
  if(path==='api/canvas'){sentJob=ack.job;draftChanged=false;}
  if(data.kind!=='acknowledge_recovery'){
   if(path==='api/command'){draftChanged=true;sentJob=null;}
   remote={...remote,busy:true,state:path==='api/stop'?'stopping':'queued'};
  }
  localMessage='';
 }catch(e){localMessage=e.message;}finally{pending=false;paint();void poll();}
}
$('execute').onclick=()=>{if(strokes.reduce((n,s)=>n+s.length,0)>8000){localMessage='Sample count exceeds 8000, Reduce the number of strokes';paint();return;}command('api/canvas',{strokes,speed:Number($('speed').value)});};
$('reset').onclick=()=>command('api/command',{kind:'reset',speed:.05});
$('stop').onclick=()=>command('api/stop',{});
$('ack-recovery').onclick=()=>command('api/command',{kind:'acknowledge_recovery',job:remote.feedback_recovery.job});
document.querySelectorAll('[data-asset]').forEach(button=>button.onclick=async()=>{
 if(locked())return;pending=true;localMessage='Loading asset…';paint();
 try{const asset=await jsonRequest('api/canvas/asset/'+button.dataset.asset);strokes=asset.strokes;draftChanged=true;sentJob=null;
  localMessage=`Loaded${button.textContent} · width ${asset.width_mm} mm; The arm moves only after clicking Execute`;
 }catch(e){localMessage=e.message;}finally{pending=false;paint();}});
async function refreshImage(){
 const camera=remote.camera||{};
 if(!camera.fresh){$('image-status').textContent=imageUrl?`Camera delayed · Showing the last frame(${(camera.age_s||0).toFixed(1)} s)`:'Waiting for a new camera image';return;}
 $('image-status').textContent='Live camera · '+(camera.width||'—')+' × '+(camera.height||'—');
 if(imageBusy||camera.sequence===imageSequence)return;imageBusy=true;
 try{const r=await fetch('api/frame?v='+camera.sequence,{signal:AbortSignal.timeout(3000)});if(!r.ok)throw Error('No image available yet');
  const next=URL.createObjectURL(await r.blob()),old=imageUrl;const image=$('live-view');image.src=next;
  try{await image.decode();image.hidden=false;imageUrl=next;imageSequence=camera.sequence;if(old)URL.revokeObjectURL(old);}
  catch(e){URL.revokeObjectURL(next);if(old)image.src=old;throw e;}
 }catch(e){$('image-status').textContent=e.message;}finally{imageBusy=false;}
}
async function poll(){
 if(polling)return;polling=true;const generation=epoch;
 try{const data=await jsonRequest('api/status');if(generation!==epoch||pending)return;remote=data;configure(data.canvas);
  if(!token){const config=await jsonRequest('api/config');token=config.token;configure(config.canvas);}void refreshImage();
 }catch(e){remote={...remote,state:'offline',fresh:false,message:'Disconnected, Check the workbench service'};}
 finally{polling=false;paint();}
}
async function start(){try{const config=await jsonRequest('api/config');token=config.token;configure(config.canvas);}catch(e){localMessage=e.message;}await poll();setInterval(()=>void poll(),450);}
start();
