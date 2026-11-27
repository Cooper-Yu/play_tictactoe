'use strict';

const get = id => document.getElementById(id);
const canvas = get('canvas');
const context = canvas.getContext('2d');
const real = document.body.dataset.environment === 'real';
const assetButtons = [...document.querySelectorAll('[data-asset]')];
const assetPath = real ? 'api/canvas/asset/' : '/api/asset/';
let strokes = [], redo = [], active = null, pointer = null, selectedAsset;
let token, dimensions = real ? null : {width_mm: 144, height_mm: 193};
let remote = {state: 'connecting'}, submittedJob, pending = false, epoch = 0, polling = false;
let message = '', lastFrame, cameraSequence, loadingFrame = false, cameraEpoch = 0;
const assets = new Map();
const locked = () => pending || remote.busy;

function configure(size) {
  if (!(size?.width_mm > 0 && size.height_mm > 0)) return;
  if (dimensions?.width_mm === size.width_mm && dimensions?.height_mm === size.height_mm) return;
  dimensions = size;
  canvas.height = Math.round(canvas.width * size.height_mm / size.width_mm);
  document.body.style.setProperty('--drawing-ratio', size.width_mm / size.height_mm);
  get('dimensions').textContent = Number(size.width_mm.toFixed(1)) + ' × ' +
    Number(size.height_mm.toFixed(1)) + ' mm';
  assets.clear();
  for (const button of assetButtons) button.querySelector('svg').replaceChildren();
  loadPreviews();
}

async function json(path, options) {
  const response = await fetch(path, {...options, signal: AbortSignal.timeout(6000)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Request failed');
  return result;
}

async function loadAsset(name) {
  if (!assets.has(name)) {
    const promise = json(assetPath + name).catch(error => {
      if (assets.get(name) === promise) assets.delete(name);
      throw error;
    });
    assets.set(name, promise);
  }
  return assets.get(name);
}

function previewAsset(button, asset, size) {
  const projected = asset.strokes.map(stroke => stroke.map(([x, y]) => [x*size.width_mm, y*size.height_mm]));
  const points = projected.flat();
  const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
  const left = Math.min(...xs), top = Math.min(...ys);
  const svg = button.querySelector('svg');
  svg.setAttribute('viewBox', [left-3, top-3, Math.max(...xs)-left+6, Math.max(...ys)-top+6].join(' '));
  svg.replaceChildren(...projected.map(stroke => {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', stroke.map(([x,y], index) => (index ? 'L' : 'M') + x + ' ' + y).join(' '));
    path.setAttribute('vector-effect', 'non-scaling-stroke');
    return path;
  }));
}

function loadPreviews() {
  const size = dimensions;
  if (!size) return;
  for (const button of assetButtons) {
    void loadAsset(button.dataset.asset).then(asset => {
      if (dimensions === size) previewAsset(button, asset, size);
    }).catch(() => { /* Selecting an unavailable asset will show the request error. */ });
  }
}

function updateProgress(working, motion, isDrawing, completed) {
  const step = working ? motion?.phase === 'planning' ? 'planning'
    : isDrawing ? 'drawing' : motion?.planned ? null : 'preparing' : null;
  for (const item of document.querySelectorAll('.execution-chain li')) {
    const phase = item.dataset.phase;
    const done = phase === 'preparing' ? motion?.planned || step === 'planning' || isDrawing
      : phase === 'planning' ? motion?.planned : completed > 0 && completed === strokes.length;
    item.dataset.state = phase === step ? 'active' : done ? 'done' : 'idle';
  }
  get('bar').max = Math.max(strokes.length, 1);
  get('bar').value = completed;
  get('completed').textContent = completed + ' / ' + strokes.length;
}

function paint() {
  const ours = submittedJob !== undefined && submittedJob === remote.job;
  const progress = ours && real && remote.drawing_progress?.shape === 'canvas' ? remote.drawing_progress : null;
  const complete = ours && real && remote.drawing_result?.shape === 'canvas' && remote.drawing_result.motion_completed;
  const motion = ours ? remote.motion_progress : null;
  const stroke = real ? progress?.source_stroke : remote.stroke;
  const stage = real ? progress?.stage : remote.stage;
  const completed = complete ? strokes.length : ours ? (real ? progress?.completed_input_strokes : remote.completed) || 0 : 0;
  const drawing = ours && remote.busy && motion?.phase === 'executing' && stage?.split('_').at(-1) === 'draw';
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.lineCap = context.lineJoin = 'round';
  context.lineWidth = 3.2;
  [...strokes, ...(active ? [active] : [])].forEach((points, index) => {
    if (points.length < 2) return;
    context.strokeStyle = drawing && index + 1 === stroke ? '#45d6c5' : index < completed ? '#a8d8cd' : '#dce6ed';
    context.beginPath();
    points.forEach(([x,y], i) => context[i ? 'lineTo' : 'moveTo'](x * canvas.width, y * canvas.height));
    context.stroke();
  });
  get('hint').hidden = strokes.length > 0 || Boolean(active);
  get('count').textContent = strokes.length + (strokes.length === 1 ? ' stroke' : ' strokes');
  const offline = ['connecting', 'offline'].includes(remote.state);
  const motionReady = token && dimensions && !locked() && (real
    ? remote.environment === 'real' && remote.fresh && remote.state === 'ready'
    : !offline && remote.state !== 'blocked');
  get('execute').disabled = !motionReady || Boolean(active) || !strokes.length;
  get('reset').disabled = !motionReady || (real && (!remote.records?.Reset || !remote.records?.['Reset hover']));
  get('undo').disabled = get('clear').disabled = locked() || Boolean(active) || !strokes.length;
  get('redo').disabled = locked() || Boolean(active) || !redo.length;
  get('stop').disabled = !remote.busy || remote.state === 'stopping' || pending;
  for (const button of assetButtons) {
    button.disabled = locked() || Boolean(active) || !token || !dimensions;
    button.setAttribute('aria-pressed', String(button.dataset.asset === selectedAsset));
  }
  if (real) {
    get('speed').disabled = locked();
    const confirm = remote.state === 'recovering' && remote.feedback_recovery?.phase === 'confirmation';
    get('ack-recovery').hidden = !confirm;
    get('ack-recovery').disabled = pending || !confirm;
  }
  const online = !offline && (!real || remote.fresh);
  get('connection').textContent = online ? (real ? 'Robot online' : 'Simulation online')
    : remote.state === 'offline' ? 'Disconnected' : 'Connecting…';
  get('connection').classList.toggle('ready', Boolean(online));
  const status = message || (drawing ? 'Drawing stroke ' + stroke + '…'
    : ours && remote.busy && motion?.phase === 'planning' ? 'Planning motion…'
    : real || ours || locked() || offline ? remote.message : 'Ready to draw.') || 'Connecting…';
  if (get('status').textContent !== status) get('status').textContent = status;
  updateProgress(ours && remote.busy, motion, drawing, completed);
  const outline = get('strokes');
  if (outline.closest('details').open) {
    outline.replaceChildren(...strokes.map((points, i) => {
      const item = document.createElement('li');
      const detail = document.createElement('span');
      item.textContent = 'Stroke ' + (i + 1);
      detail.textContent = drawing && i + 1 === stroke ? 'Drawing' : i < completed ? 'Complete' : points.length + ' points';
      item.className = drawing && i + 1 === stroke ? 'active' : i < completed ? 'done' : '';
      item.append(detail);
      return item;
    }));
  }
}

function clearExecution() {
  submittedJob = undefined;
  selectedAsset = undefined;
  message = '';
}
function point(event) {
  const rect = canvas.getBoundingClientRect();
  return [Math.max(0, Math.min(1, (event.clientX-rect.left)/rect.width)),
    Math.max(0, Math.min(1, (event.clientY-rect.top)/rect.height))];
}
function distance(a, b) {
  return Math.hypot((a[0] - b[0]) * dimensions.width_mm, (a[1] - b[1]) * dimensions.height_mm);
}
canvas.addEventListener('pointerdown', event => {
  if (locked() || !dimensions || active || event.button !== 0 || strokes.length >= 32) return;
  clearExecution();
  pointer = event.pointerId;
  active = [point(event)];
  canvas.setPointerCapture(pointer);
  event.preventDefault();
  paint();
});
canvas.addEventListener('pointermove', event => {
  if (event.pointerId !== pointer || !active) return;
  if (active.length >= 2000) { message = 'Stroke limit reached. Lift the pointer.'; paint(); return; }
  const next = point(event);
  if (distance(next, active.at(-1)) < .20) return;
  active.push(next);
  paint();
});
canvas.addEventListener('pointerup', event => {
  if (event.pointerId !== pointer || !active) return;
  const last = point(event);
  if (distance(last, active.at(-1)) > .01) {
    if (active.length < 2000) active.push(last);
    else active[active.length - 1] = last;
  }
  if (active.length >= 2) { strokes.push(active); redo = []; }
  active = null;
  pointer = null;
  paint();
});
canvas.addEventListener('pointercancel', () => { active = null; pointer = null; paint(); });
get('undo').onclick = () => { redo.push(strokes.pop()); clearExecution(); paint(); };
get('redo').onclick = () => { strokes.push(redo.pop()); clearExecution(); paint(); };
get('clear').onclick = () => { strokes = []; redo = []; clearExecution(); message = 'Draft cleared.'; paint(); };
get('strokes').closest('details').addEventListener('toggle', paint);

async function command(path, data, drawing = false) {
  if (!token || pending) return;
  ++epoch;
  pending = true;
  message = 'Submitting…';
  paint();
  try {
    const ack = await json(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', [real ? 'X-Workbench-Token' : 'X-Canvas-Token']: token},
      body: JSON.stringify(data),
    });
    if (drawing) submittedJob = ack.job;
    if (data.kind === 'reset' || path === '/api/reset') submittedJob = undefined;
    if (data.kind !== 'acknowledge_recovery') remote = {...remote, busy: true, state: 'queued'};
    message = '';
  } catch (error) {
    message = error.message;
  } finally {
    pending = false;
    paint();
    void poll();
  }
}
get('execute').onclick = () => {
  if (strokes.reduce((total, stroke) => total + stroke.length, 0) > 8000) {
    message = 'Too many points. Shorten the draft.';
    paint();
    return;
  }
  void command(real ? 'api/canvas' : '/api/draw',
    real ? {strokes, speed: Number(get('speed').value)} : {strokes}, true);
};
get('reset').onclick = () => {
  if (window.confirm('Clear the robot’s drawing board?')) {
    void command(real ? 'api/command' : '/api/reset', real ? {kind: 'reset', speed: .05} : {});
  }
};
get('stop').onclick = () => void command(real ? 'api/stop' : '/api/stop', {});
if (real) get('ack-recovery').onclick = () => void command('api/command', {kind: 'acknowledge_recovery', job: remote.feedback_recovery.job});
for (const button of assetButtons) {
  button.onclick = async () => {
    if (locked()) return;
    pending = true;
    message = 'Loading asset…';
    paint();
    try {
      const asset = await loadAsset(button.dataset.asset);
      strokes = asset.strokes;
      redo = [];
      clearExecution();
      selectedAsset = button.dataset.asset;
      message = button.textContent.trim() + ' loaded · ' + asset.width_mm + ' mm';
    } catch (error) {
      message = error.message;
    } finally {
      pending = false;
      paint();
    }
  };
}

async function refreshCamera() {
  const camera = real ? remote.camera : {sequence: remote.camera_sequence, fresh: remote.state !== 'offline'};
  const live = camera?.fresh && lastFrame !== undefined && performance.now() - lastFrame < 5000;
  const label = get('image-status');
  label.textContent = live ? 'Live' : lastFrame !== undefined ? 'Last frame' : 'Waiting for camera';
  label.classList.toggle('ready', live);
  if (!camera?.fresh || !camera.sequence || camera.sequence === cameraSequence || loadingFrame) return;
  const version = cameraEpoch;
  loadingFrame = true;
  try {
    const source = (real ? 'api/frame?v=' : '/api/game/camera?seq=') + camera.sequence;
    const response = await fetch(source, {signal: AbortSignal.timeout(3000)});
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    try {
      const frame = new Image();
      frame.src = url;
      await frame.decode();
      if (version !== cameraEpoch) return;
      const image = get('live-view');
      if (image.src.startsWith('blob:')) URL.revokeObjectURL(image.src);
      image.src = url;
      image.hidden = false;
      lastFrame = performance.now();
      cameraSequence = camera.sequence;
      label.textContent = 'Live';
      label.classList.add('ready');
    } finally {
      if (get('live-view').src !== url) URL.revokeObjectURL(url);
    }
  } catch { /* Keep the last valid camera frame. */ }
  finally { loadingFrame = false; }
}

async function poll() {
  if (polling) return;
  polling = true;
  const generation = epoch;
  try {
    if (!token) {
      const config = await json(real ? 'api/config' : '/api/config');
      if (generation !== epoch) return;
      token = config.token;
      if (real) configure(config.canvas);
      else loadPreviews();
    }
    const next = await json(real ? 'api/status' : '/api/status');
    if (generation !== epoch || pending) return;
    remote = next;
    if (real) configure(next.canvas);
  } catch {
    if (generation === epoch) remote = {...remote, state: 'offline', message: 'Disconnected.'};
  } finally {
    polling = false;
    paint();
    void refreshCamera();
  }
}

function resume() {
  if (document.hidden) return;
  ++epoch;
  ++cameraEpoch;
  token = undefined;
  cameraSequence = undefined;
  paint();
  void poll();
}
document.addEventListener('visibilitychange', resume);
document.addEventListener('resume', resume);
window.addEventListener('pageshow', event => { if (event.persisted) resume(); });
window.addEventListener('online', resume);
window.addEventListener('focus', resume);
paint();
void poll();
setInterval(() => void poll(), 450);
