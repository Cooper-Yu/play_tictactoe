const canvas=document.querySelector('#canvas'),ctx=canvas.getContext('2d');
const $=id=>document.querySelector('#'+id);
let strokes=[],active=null,pointer=null,token=null,remote={state:'connecting',busy:false,completed:0,total:0},pending=false,localMessage='',draftChanged=true;
const locked=()=>pending||remote.busy;
function paint(){
 const completed=draftChanged?0:(remote.completed||0),total=draftChanged?strokes.length:(remote.total||0);
 ctx.clearRect(0,0,canvas.width,canvas.height);ctx.lineCap='round';ctx.lineJoin='round';ctx.lineWidth=3.2;
 [...strokes,...(active?[active]:[])].forEach((stroke,index)=>{
  if(stroke.length<2)return;ctx.strokeStyle=!draftChanged&&remote.busy&&index+1===remote.stroke?'#effff9':'#94e5d7';
  ctx.beginPath();stroke.forEach(([u,v],i)=>i?ctx.lineTo(u*canvas.width,v*canvas.height):ctx.moveTo(u*canvas.width,v*canvas.height));ctx.stroke();
  const [u,v]=stroke[0];ctx.fillStyle='#defff3';ctx.beginPath();ctx.arc(u*canvas.width,v*canvas.height,4,0,Math.PI*2);ctx.fill();
 });
 $('hint').classList.toggle('hidden',strokes.length>0||!!active);
 $('count').textContent=strokes.length;$('completed').textContent=`${completed} / ${total}`;
 $('execute').disabled=locked()||!!active||strokes.length===0||!token||['connecting','offline','blocked'].includes(remote.state);
 ['undo','clear'].forEach(id=>$(id).disabled=locked()||!!active||strokes.length===0);
 document.querySelectorAll('[data-asset]').forEach(button=>button.disabled=locked()||!!active||!token);
 $('reset').disabled=locked()||!token||['connecting','offline','blocked'].includes(remote.state);
 $('stop').disabled=!remote.busy||remote.state==='stopping';
 $('status').textContent=localMessage||remote.message||'正在连接';
 $('connection').textContent=remote.state==='offline'?'连接已断开':remote.state==='connecting'?'正在连接':'仿真已连接';
 $('connection').classList.toggle('ready',!['offline','connecting'].includes(remote.state));
 $('bar').style.width=total?`${completed/total*100}%`:'0%';
 $('strokes').replaceChildren(...strokes.map((s,i)=>{const li=document.createElement('li');li.textContent=`第 ${i+1} 笔`;
  const label=document.createElement('span');label.textContent=!draftChanged&&remote.busy&&i+1===remote.stroke?'执行中':i<completed?'已完成':`${s.length} 个点`;
  li.className=!draftChanged&&remote.busy&&i+1===remote.stroke?'active':i<completed?'done':'';li.append(label);return li;}));
}
function point(event){const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))];}
canvas.addEventListener('pointerdown',event=>{if(locked()||event.button!==0||strokes.length>=32)return;
 localMessage='';draftChanged=true;pointer=event.pointerId;active=[point(event)];canvas.setPointerCapture(pointer);event.preventDefault();paint();});
canvas.addEventListener('pointermove',event=>{if(event.pointerId!==pointer||!active)return;const p=point(event),last=active.at(-1);
 if(Math.hypot((p[0]-last[0])*144,(p[1]-last[1])*193)>=.20){if(active.length>=2000){localMessage='一笔最多 2000 个点，请松开后继续';return;}active.push(p);paint();}});
canvas.addEventListener('pointerup',event=>{if(event.pointerId!==pointer||!active)return;const p=point(event),last=active.at(-1);
 if(Math.hypot((p[0]-last[0])*144,(p[1]-last[1])*193)>.01)active.push(p);
 if(active.length>=2)strokes.push(active);active=null;pointer=null;paint();});
canvas.addEventListener('pointercancel',()=>{active=null;pointer=null;paint();});
$('undo').onclick=()=>{strokes.pop();draftChanged=true;localMessage='';paint();};
$('clear').onclick=()=>{strokes=[];draftChanged=true;localMessage='草稿已清空，平板内容保持';paint();};
async function post(path,data={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Canvas-Token':token},body:JSON.stringify(data)});
 const result=await response.json();if(!response.ok)throw Error(result.error||'提交失败');return result;}
async function command(path,data){pending=true;localMessage='正在提交…';paint();try{await post(path,data);if(path==='/api/draw')draftChanged=false;if(path==='/api/reset')draftChanged=true;localMessage='';await poll();}catch(error){localMessage=error.message;}finally{pending=false;paint();}}
$('execute').onclick=()=>command('/api/draw',{strokes});
$('stop').onclick=()=>command('/api/stop',{});
$('reset').onclick=()=>command('/api/reset',{});
document.querySelectorAll('[data-asset]').forEach(button=>button.onclick=async()=>{
 pending=true;localMessage='正在载入素材…';paint();
 try{const response=await fetch('/api/asset/'+button.dataset.asset);const asset=await response.json();
  if(!response.ok)throw Error(asset.error);strokes=asset.strokes;draftChanged=true;
  localMessage=`已载入${button.textContent} · 宽 ${asset.width_mm} mm，点击执行绘图`;
 }catch(error){localMessage=error.message;}finally{pending=false;paint();}
});
async function poll(){try{const response=await fetch('/api/status');if(!response.ok)throw Error('连接中断');remote=await response.json();}
 catch(error){remote={...remote,state:'offline',message:'连接已断开，请检查仿真服务'};}paint();}
async function start(){try{const response=await fetch('/api/config');const config=await response.json();token=config.token;}catch(error){localMessage='服务连接失败';}await poll();setInterval(poll,450);}
start();
