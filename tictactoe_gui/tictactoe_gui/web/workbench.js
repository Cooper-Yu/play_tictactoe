'use strict';
const $ = id => document.getElementById(id);
const raw = $('raw'), enhanced = $('enhanced');
let token, state = {}, roi = null, drag = null, rawImage = null, selected = 'Reset';
let lastSequence = -1, lastTopic = '', lastRecordKey = '', requestBusy = false;
let betaRevision = 0, renderedRevision = -1, imageBusy = false, toastTimer;
let appliedEnvironment = null, polling = false;
const fixedNames = ['Reset', '左上', '右上', '右下', '左下'];
function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => {$('toast').hidden = true;}, 4500);
}
async function post(path, data) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', 'X-Workbench-Token':token}, body:JSON.stringify(data), signal:AbortSignal.timeout(5000)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
async function command(data) {
  if (requestBusy) return;
  requestBusy = true; renderControls();
  try { await post('api/command', data); state={...state,busy:true,state:'queued'}; void poll(); }
  catch (error) {toast(error.message);}
  finally {requestBusy = false; renderControls();}
}
function renderControls() {
  const blocked = requestBusy || state.busy || ['connecting','offline','blocked','stopping'].includes(state.state) || !state.fresh;
  for (const button of document.querySelectorAll('[data-axis], #plan-preset, #record')) button.disabled = blocked || (button.dataset.axis==='z' && Number($('step').value)>.02);
  $('reset-cycle').disabled = blocked || !state.records?.['reset悬空预备'] || !state.records?.Reset;
  $('execute').disabled = blocked || !state.plan;
  $('return').disabled = blocked || !state.records?.[selected];
  $('delete').disabled = blocked || !state.records?.[selected];
  $('switch-camera').disabled = requestBusy || state.busy || !state.topics?.length;
}
$('step').onchange=renderControls;
function renderRecords() {
  const records = state.records || {};
  const names = [...new Set([...fixedNames, ...Object.keys(records)])];
  const key = JSON.stringify([records, selected]);
  if (key === lastRecordKey) return;
  lastRecordKey = key; $('records').replaceChildren();
  $('record-count').textContent = `${fixedNames.filter(name => records[name]).length} / 5 已记录`;
  for (const name of names) {
    const button = document.createElement('button');
    button.className = 'record-card'+(selected === name ? ' selected' : '');
    const title = document.createElement('b'); title.textContent = name; button.append(title);
    const detail = document.createElement('small');
    detail.textContent = records[name] ? (records[name].screenshot ? '已记录 · 已关联截图' : '已记录 · 无匹配截图') : '等待记录'; button.append(detail);
    if (records[name]?.screenshot) {
      const img = document.createElement('img'); img.alt = name+' 记录截图';
      img.src = 'api/snapshot?name='+encodeURIComponent(name)+'&v='+encodeURIComponent(JSON.stringify(records[name].pose_stamped.header.stamp)); button.append(img);
    }
    button.onclick = () => {selected=name; $('record-name').value=name; renderRecords(); renderControls();};
    $('records').append(button);
  }
  const record = records[selected];
  $('record-detail').textContent = record ? `${selected} · X ${(record.pose_stamped.pose.position.x*1000).toFixed(2)} / Y ${(record.pose_stamped.pose.position.y*1000).toFixed(2)} / Z ${(record.pose_stamped.pose.position.z*1000).toFixed(2)} mm · base_link / link6 · joint1–joint6 已保存` : '选择一条记录查看位姿';
}
function render() {
  const real = state.environment === 'real';
  if(appliedEnvironment !== state.environment && state.environment) {
    appliedEnvironment=state.environment;
    if(real) {
      if(![...$('step').options].some(o=>o.value==='0.05')) $('step').add(new Option('50 mm (XY)','0.05'));
      for(const option of [...$('speed').options]) if(Number(option.value)>.1) option.remove();
      $('speed').value='.05';
      if(!$('speed').value)$('speed').value='0.05';
    }
  }
  $('environment-label').textContent='ROS 2 / MoveIt 2 · '+(real?'真机模式':'仿真模式');
  $('status').textContent = state.message || '等待连接';
  $('storage').textContent = state.storage ? '记录保存位置（WSL）：'+state.storage : '';
  $('connection').textContent = state.state === 'offline' ? '工作台未连接' : state.fresh ? '● '+(real?'真机':'仿真')+'已连接' : '等待机械臂反馈';
  $('feedback').textContent = state.fresh ? '实际反馈 · base_link → link6' : '反馈已过期 / 等待数据';
  $('feedback').classList.toggle('stale', !state.fresh);
  for (const axis of ['x','y','z']) $('p'+axis).textContent = state.pose && state.fresh ? (state.pose[axis]*1000).toFixed(2) : '—';
  $('rpy').textContent = state.pose && state.fresh ? state.pose.rpy.map(v => (v*180/Math.PI).toFixed(2)+'°').join(' / ') : '—';
  $('quaternion').textContent = state.pose ? '四元数 xyzw：'+state.pose.quaternion.map(v=>v.toFixed(5)).join(', ') : '';
  $('joints').replaceChildren();
  for (let i=1;i<=6;i++) {const span=document.createElement('span'); const value=state.joints?.['joint'+i]; span.textContent=`J${i}　${state.fresh && Number.isFinite(value) ? (value*180/Math.PI).toFixed(2)+'°' : '—'}`; $('joints').append(span);}
  $('plan-label').textContent = state.plan ? `${state.plan.label} · ${state.plan.points} 点 · ${state.plan.duration_s.toFixed(2)} s · 待执行` : '无待执行规划';
  const topics = state.topics || [];
  if (JSON.stringify(topics) !== $('topic').dataset.topics) {
    $('topic').replaceChildren(...topics.map(topic=>{const option=document.createElement('option');option.value=topic;option.textContent=topic;return option;}));
    $('topic').dataset.topics=JSON.stringify(topics); $('topic').value=state.camera?.topic || topics[0] || '';
  }
  const camera=state.camera || {};
  $('resolution').textContent = camera.width ? `${camera.width} × ${camera.height} · ${camera.encoding}` : '等待图像';
  $('camera-badge').textContent = camera.fresh ? 'LIVE · '+(real?'真机':'仿真')+'相机' : camera.sequence ? '相机延迟 · 保留上一帧' : '等待实时相机';
  $('camera-badge').classList.toggle('stale', !camera.fresh);
  $('camera-info').textContent = camera.error || (camera.frame_id ? `${camera.frame_id} · 图像年龄 ${camera.age_s?.toFixed(1)} s${camera.fps ? ' · '+camera.fps.toFixed(1)+' fps' : ''}` : '选择一个 sensor_msgs/msg/Image topic');
  if (!camera.sequence) {rawImage=null;raw.getContext('2d').clearRect(0,0,raw.width,raw.height);enhanced.getContext('2d').clearRect(0,0,enhanced.width,enhanced.height);}
  renderRecords(); renderControls();
}
async function poll() {
  if(polling)return;
  polling=true;
  try {const response=await fetch('api/status',{signal:AbortSignal.timeout(3000)}); if(!response.ok) throw new Error('连接失败'); state=await response.json();render();}
  catch(error) {state={...state,state:'offline',fresh:false,camera:{...state.camera,fresh:false},plan:null,message:'工作台连接中断'};render();}
  finally {polling=false;}
}
function drawRaw() {
  if(!rawImage || !state.camera?.fresh) return;
  raw.width=rawImage.naturalWidth;raw.height=rawImage.naturalHeight;
  const ctx=raw.getContext('2d');ctx.drawImage(rawImage,0,0);
  const box=drag ? normalize(drag.start,drag.end) : roi;
  if(box) {ctx.strokeStyle='#49e3d3';ctx.lineWidth=Math.max(1,raw.width/300);ctx.fillStyle='#49e3d326';ctx.fillRect(box[0]*raw.width,box[1]*raw.height,box[2]*raw.width,box[3]*raw.height);ctx.strokeRect(box[0]*raw.width,box[1]*raw.height,box[2]*raw.width,box[3]*raw.height);}
}
function normalize(a,b) {return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1])];}
function point(event) {
  const rect=raw.getBoundingClientRect(), scale=Math.min(rect.width/raw.width,rect.height/raw.height);
  const width=raw.width*scale,height=raw.height*scale;
  return [Math.max(0,Math.min(1,(event.clientX-rect.left-(rect.width-width)/2)/width)),Math.max(0,Math.min(1,(event.clientY-rect.top-(rect.height-height)/2)/height))];
}
raw.onpointerdown=event=>{if(!state.camera?.fresh) return; raw.setPointerCapture(event.pointerId);drag={start:point(event),end:point(event)};};
raw.onpointermove=event=>{if(drag){drag.end=point(event);drawRaw();}};
raw.onpointerup=event=>{if(!drag)return;drag.end=point(event);const candidate=normalize(drag.start,drag.end);if(candidate[2]*raw.width>=2 && candidate[3]*raw.height>=2)roi=candidate;drag=null;betaRevision++;updateRoi();drawRaw();};
raw.onpointercancel=()=>{drag=null;drawRaw();};
function updateRoi() {updateEnhancementControls();$('roi-label').textContent=roi ? `选区：${Math.round(roi[2]*raw.width)} × ${Math.round(roi[3]*raw.height)} px` : '选区：整张图';}
async function loadImage(url) {
  const response=await fetch(url,{signal:AbortSignal.timeout(4000)});if(!response.ok)throw new Error('图像不可用');
  const objectUrl=URL.createObjectURL(await response.blob());
  try {const image=new Image();image.src=objectUrl;await image.decode();return image;}finally{URL.revokeObjectURL(objectUrl);}
}
async function refreshImages() {
  if(imageBusy || !state.camera?.fresh)return;
  if(lastTopic!==state.camera.topic){lastTopic=state.camera.topic;roi=null;lastSequence=-1;betaRevision++;updateRoi();}
  if(lastSequence===state.camera.sequence && renderedRevision===betaRevision)return;
  imageBusy=true;
  const revision=betaRevision, topic=state.camera.topic, sequence=state.camera.sequence;
  try {
    const ink=$('enhancement-mode').value==='ink';
    const query=new URLSearchParams({beta:ink?'0':$('brightness').value,t:String(sequence),mode:ink&&roi?'ink':'brightness',strength:$('ink-strength').value,tolerance:$('ink-tolerance').value});
    if(roi)query.set('roi',roi.join(','));
    const [original,processed]=await Promise.all([loadImage('api/frame?t='+sequence),loadImage('api/frame?'+query)]);
    if(state.camera?.fresh && topic===state.camera.topic && revision===betaRevision) {
      rawImage=original;drawRaw();
      enhanced.width=raw.width;enhanced.height=raw.height;
      const ctx=enhanced.getContext('2d');ctx.fillStyle='#eef3f5';ctx.fillRect(0,0,enhanced.width,enhanced.height);
      const scale=Math.min(enhanced.width/processed.naturalWidth,enhanced.height/processed.naturalHeight);
      const w=processed.naturalWidth*scale,h=processed.naturalHeight*scale;ctx.drawImage(processed,(enhanced.width-w)/2,(enhanced.height-h)/2,w,h);
      lastSequence=sequence;renderedRevision=revision;
    }
  }catch(error){/* The status panel reports stale cameras; retry the next frame. */}
  finally{imageBusy=false;}
}
$('brightness').oninput=()=>{$('beta').textContent=$('brightness').value;betaRevision++;};
$('neutral').onclick=()=>{$('brightness').value=0;$('beta').textContent='0';for(const [id,value] of [['ink-strength',50],['ink-tolerance',20]]){$(id).value=value;$(id+'-value').textContent=value;}betaRevision++;};
$('full-image').onclick=()=>{roi=null;betaRevision++;updateRoi();drawRaw();};
for(const button of document.querySelectorAll('[data-axis]'))button.onclick=()=>command({kind:'jog',axis:button.dataset.axis,distance:Number($('step').value)*Number(button.dataset.sign),speed:Number($('speed').value)});
$('switch-camera').onclick=()=>command({kind:'camera',topic:$('topic').value});
$('plan-preset').onclick=()=>command({kind:'preset',name:$('preset').value,speed:Number($('speed').value)});
$('execute').onclick=()=>command({kind:'execute'});
$('reset-cycle').onclick=()=>command({kind:'reset',speed:Number($('speed').value)});
$('stop').onclick=async()=>{try{await post('api/stop',{});await poll();}catch(error){toast(error.message);}};
$('record').onclick=()=>command({kind:'record',name:$('record-name').value,overwrite:$('overwrite').checked});
$('return').onclick=()=>command({kind:'return',name:selected,speed:Number($('speed').value)});
$('delete').onclick=()=>{if(confirm(`删除记录「${selected}」？`))command({kind:'delete',name:selected});};
function updateEnhancementControls() {
  const ink=$('enhancement-mode').value==='ink';
  $('neutral').textContent=ink?'还原增强参数':'还原亮度';
  $('ink-controls').hidden=!ink;
  $('brightness-controls').hidden=ink;
  $('enhancement-hint').textContent=ink ? (roi?'仅增强框选区域内已有的青蓝色细线；请确保选区避开蓝框。不会加粗或补线，也不表示压力大小。':'请在左侧框选黑色书写面，避开蓝色边框；选区前仅显示原图。') : '亮度调节有助于观察，不会补回原图缺失的细节。';
}
$('enhancement-mode').onchange=()=>{betaRevision++;updateEnhancementControls();};
for(const id of ['ink-strength','ink-tolerance']) $(id).oninput=()=>{$(id+'-value').textContent=$(id).value;betaRevision++;};
updateEnhancementControls();
async function start(){try{const response=await fetch('api/config');token=(await response.json()).token;await poll();setInterval(poll,350);setInterval(refreshImages,500);}catch(error){toast('工作台连接失败，请刷新页面');}}
start();
