'use strict';
const get = id => document.getElementById(id);
const gameMount = location.pathname.endsWith('/game/') ? location.pathname.slice(0, -1) : '';
const gameURL = path => gameMount + path;
const gameFetch = (path, options) => fetch(gameURL(path), options);
const board = get('board');
const winLine = get('win-line');
let winCells = [];
const start = get('start-game');
const saveSettings = get('save-settings');
const stop = get('stop');
const reset = get('reset');
const image = get('image');
const cameraDetection = get('camera-detection');
const settings = get('game-settings');
const settingsToggle = get('settings-toggle');
const stageLabels = ['perception', 'decision', 'planning', 'execution'].map(name => {
  const node = get('stage-' + name);
  return {node, label: node.querySelector('small')};
});
let settingsOpener;
let lastCameraSequence;
let cameraAdvancedAt = -Infinity;
let fadeCamera = false;
let token;
let state;
let sending = false;
let notice = '';
let frame;
const settingsFields = ['size', 'opponent', 'first', 'mark', 'input-source'];
let settingsKey;
let saved = {size: location.hash === '#four' ? 'four' : '3', opponent: 'ai',
  first: 'player', mark: 'X', 'input-source': 'click'};
let visionAvailable = false;
let inkSize;
let realEnvironment = false;
let online = false;
const modes = {
  '3': {size: 3, win: 3, engine: 'Minimax', example: {0: 'X', 5: 'O'}},
  four: {size: 9, win: 4, engine: 'Alpha–beta search', example: {38: 'O', 40: 'X', 41: 'X', 42: 'X', 49: 'O'}},
};
const choice = name => settings.querySelector('input[name="' + name + '"]:checked').value;
const option = (name, value) => settings.querySelector('input[name="' + name + '"][value="' + CSS.escape(value) + '"]');

function selectOption(name, value) {
  const input = option(name, value);
  if (input && !input.disabled) input.checked = true;
}

function restoreSettingsForm() {
  settingsFields.forEach(name => selectOption(name, saved[name]));
  renderSettings();
}

function loadSettings(environment) {
  const key = 'robot-arena/settings/v1:' + location.pathname.replace(/\/+$/, '') + ':' + environment;
  if (settingsKey === key) return;
  settingsKey = key;
  saved['input-source'] = 'click';
  renderSettings();
  let stored;
  try { stored = JSON.parse(localStorage.getItem(key)); } catch { /* Keep session defaults. */ }
  for (const name of settingsFields) {
    const storedValue = stored?.[name];
    const value = name === 'input-source' && storedValue === 'vision' ? 'click' : storedValue;
    if (typeof value !== 'string' || !option(name, value) || option(name, value).disabled) continue;
    if (name === 'input-source' && !visionAvailable) continue;
    saved[name] = value;
  }
  restoreSettingsForm();
}

function renderSettings() {
  const mode = choice('size');
  const {size, win, engine, example} = modes[mode];
  const twoPlayers = choice('opponent') === 'human';
  get('first-option').hidden = twoPlayers;
  get('mark-label').textContent = twoPlayers ? 'First symbol' : 'Your symbol';
  get('input-option').hidden = !visionAvailable;
  get('physical-input').hidden = !realEnvironment || !visionAvailable;
  option('input-source', 'physical').disabled = !realEnvironment || !visionAvailable;

  const preview = get('preview-board');
  if (preview.dataset.mode !== mode) {
    preview.dataset.mode = mode;
    preview.style.setProperty('--preview-size', size);
    preview.replaceChildren(...Array.from({length: size * size}, (_, index) => {
      const cell = document.createElement('span');
      cell.textContent = example[index] === 'X' ? '×' : example[index] === 'O' ? '○' : '';
      return cell;
    }));
    get('preview-size').textContent = size + ' × ' + size;
    get('preview-win').textContent = win + ' in a row';
  }
  const engineLabel = twoPlayers ? 'None · two players' : engine;
  if (get('preview-engine').textContent !== engineLabel) get('preview-engine').textContent = engineLabel;
}


function winningRun(cells, winner, length) {
  if (winner !== 'X' && winner !== 'O') return [];
  const size = cells.length;
  const markAt = (row, col) => cells[row]?.[col];
  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      if (markAt(row, col) !== winner) continue;
      for (const [dr, dc] of [[0,1], [1,0], [1,1], [1,-1]]) {
        if (markAt(row-dr, col-dc) === winner) continue;
        const indices = [];
        for (let r = row, c = col; markAt(r, c) === winner; r += dr, c += dc) {
          indices.push(r*size+c);
        }
        if (indices.length >= length) return indices;
      }
    }
  }
  return [];
}

function positionWinLine() {
  if (winLine.hidden) return;
  const startCell = board.children[winCells[0]].getBoundingClientRect();
  const endCell = board.children[winCells.at(-1)].getBoundingClientRect();
  const area = board.getBoundingClientRect();
  const x = startCell.left + startCell.width/2 - area.left;
  const y = startCell.top + startCell.height/2 - area.top;
  const dx = endCell.left + endCell.width/2 - area.left - x;
  const dy = endCell.top + endCell.height/2 - area.top - y;
  winLine.style.left = x + 'px';
  winLine.style.top = y + 'px';
  winLine.style.width = Math.hypot(dx, dy) + 'px';
  winLine.style.transform = 'translateY(-50%) rotate(' + Math.atan2(dy, dx) + 'rad)';
}


function showSettings(show, opener = settingsToggle) {
  settings.hidden = !show;
  settingsToggle.setAttribute('aria-expanded', String(show));
  if (show) {
    settingsOpener = opener;
    restoreSettingsForm();
    settings.querySelector('input:checked')?.focus({preventScroll: true});
  } else {
    settingsOpener?.focus({preventScroll: true});
  }
}

function renderPipeline(game, vision, busy) {
  const cameraLive = online && performance.now() - cameraAdvancedAt < 5000 &&
    (!realEnvironment || state.camera_fresh === true);
  const sync = get('live-sync');
  sync.hidden = !vision;
  sync.dataset.live = String(cameraLive && vision);
  get('live-sync-label').textContent = cameraLive ? 'Live sync' : 'Waiting for camera';

  const phase = game?.phase;
  const stage = state?.continuation?.stage;
  const observing = vision && cameraLive && phase === 'player';
  const confirming = busy && stage === 'camera_confirmation' && cameraLive;
  const drawing = busy && (['drawing_x', 'drawing_o'].includes(phase) || stage === 'drawing');
  const motion = state?.motion_progress;
  const planning = busy && motion?.phase === 'planning';
  const executing = busy && motion?.phase === 'executing';
  const returning = busy && stage === 'returning_to_zero';
  const stages = [
    state?.vision?.confirmed ? ['done', 'Confirmed']
      : observing || confirming ? ['active', 'Tracking']
      : cameraLive ? ['idle', 'Camera ready'] : ['idle', 'Waiting'],
    phase === 'thinking' && busy ? ['active', 'Choosing move']
      : state?.decision === 'chosen' ? ['done', 'Move chosen'] : ['idle', 'Idle'],
    planning ? ['active', 'Planning'] : motion?.planned ? ['done', 'Plan found']
      : (drawing || returning) && !motion ? ['idle', 'Not reported'] : ['idle', 'Idle'],
    executing ? ['active', returning ? 'Returning' : 'Executing']
      : !motion && drawing ? ['active', 'Drawing turn']
      : busy && phase === 'preparing' && !planning ? ['idle', 'Preparing board']
      : ['idle', phase === 'blocked' ? 'Paused' : 'Idle'],
  ];
  stages.forEach(([kind, text], index) => {
    const {node, label} = stageLabels[index];
    node.dataset.state = kind;
    if (label.textContent !== text) label.textContent = text;
  });
}

function gameStatus(game, busy, ready, mark, outcome) {
  if (notice) return notice.length <= 72 ? notice : 'Action failed.';
  if (!state || state.state === 'connecting') return 'Connecting…';
  if (!online || state.state === 'offline') return 'Disconnected.';
  if (state.state === 'stopping') return 'Stopping robot…';
  if (state.state === 'stopped') return 'Motion stopped.';
  if (state.state === 'blocked' || game?.phase === 'blocked') {
    return state.continuation?.available ? 'Check the board, then resume.' : 'Check the board, then clear it.';
  }
  if (state.state === 'failed' && !busy) return 'Action failed.';
  if (busy) {
    if (state.reply_countdown > 0) return 'Robot reply in ' + state.reply_countdown + ' s';
    if (game?.phase === 'drawing_win_line') return 'Drawing the winning line…';
    if (state.continuation?.stage === 'camera_confirmation'
        || /^Waiting for camera confirmation|waiting for three consistent camera frames/i.test(state.message ?? '')) {
      return 'Checking your move…';
    }
    if (game?.phase === 'thinking') return 'AI is choosing…';
    if (state.motion_progress?.phase === 'planning') return 'Planning motion…';
    if (state.continuation?.stage === 'returning_to_zero') return 'Robot is returning…';
    if (game?.phase === 'drawing_x') return 'Drawing X…';
    if (game?.phase === 'drawing_o') return 'Drawing O…';
    if (game?.phase === 'preparing') return 'Preparing board…';
    if (game?.input_source === 'handwriting' && game.phase === 'player') return 'Drawing your mark…';
    return 'Robot is working…';
  }
  if (!ready) return 'Waiting for robot…';
  if (game?.phase === 'player') {
    if (game.input_source === 'physical') return 'Write ' + mark + ' on the physical board, then move your hand clear.';
    if (game.input_source === 'handwriting') return 'Draw ' + mark + ', then confirm.';
    return game.opponent === 'human' ? mark + ': Pick an empty cell.' : 'Pick an empty cell.';
  }
  if (game?.phase === 'between_rounds') return 'Start round two.';
  if (game?.phase === 'finished') return outcome ? '' : 'Game over.';
  return 'Ready to play.';
}

function render() {
  const game = state?.game;
  const mode = game && (game.mode === 'classic' ? String(game.size) : game.mode);
  const twoPlayers = (game?.opponent ?? saved.opponent) === 'human';
  const vision = ['vision', 'handwriting', 'physical'].includes(game?.input_source);
  const handwriting = game?.input_source === 'handwriting' && game.phase !== 'finished';
  const size = game?.size ?? modes[saved.size].size;
  const showPoints = game?.mode === "score";
  const ready = online && token && state && !['connecting','offline','blocked'].includes(state.state)
    && (!realEnvironment || (state.camera_fresh && state.robot_fresh));
  const busy = sending || state?.busy;
  const playable = ready && !busy && game?.phase === 'player';
  if (Number(board.dataset.size) !== size) {
    board.dataset.size = String(size);
    board.replaceChildren(...Array.from({length: size * size}, (_, index) => {
      const cell = document.createElement('button');
      const row = Math.floor(index / size);
      const col = index % size;
      cell.type = 'button';
      const points = document.createElement('span');
      points.className = 'cell-points';
      points.setAttribute('aria-hidden', 'true');
      cell.append(points);
      cell.addEventListener('click', () => {
        const path = state.game.input_source === 'vision' ? '/api/game/simulate-player' : '/api/game/move';
        act(path, {row, col, revision: state.game.revision});
      });
      return cell;
    }));
  }
  winCells = game && !showPoints ? (Array.isArray(game.winning_cells)
    ? game.winning_cells.map(([row, col]) => row * size + col)
    : winningRun(game.board, game.winner, game.win_length ?? (size === 3 ? 3 : 5))) : [];
  Array.from(board.children).forEach((cell, index) => {
    const row = Math.floor(index / size), col = index % size;
    const mark = game?.board[row][col] ?? '';
    const points = game?.weights?.[index] ?? [2,1,2,1,3,1,2,1,2][index];
    cell.firstElementChild.textContent = showPoints ? points + ' points' : '';
    cell.dataset.mark = mark;
    cell.dataset.winning = String(winCells.includes(index));
    cell.disabled = !playable || game?.input_source === 'physical' || Boolean(mark);
    cell.setAttribute('aria-label', 'Row ' + (row+1) + ', column ' + (col+1) + ', ' + (mark || 'Empty') + (showPoints ? ', ' + points + ' points' : ''));
  });
  updateHandwriting(handwriting, playable, game?.revision);
  winLine.hidden = winCells.length === 0;
  winLine.dataset.mark = game?.winner ?? '';
  positionWinLine();
  get('heading').textContent = ({'score': 'Scored Tic-Tac-Toe', 'four': 'Four-in-a-Row', 'four-three-stone': 'Four-in-a-Row · Three-stone opening', '9': 'Gomoku', '3': 'Tic-Tac-Toe'})[mode ?? saved.size];
  const human = game?.human ?? saved.mark;
  const primary = twoPlayers ? 'X' : human;
  const secondary = primary === 'X' ? 'O' : 'X';
  get('role-primary-icon').dataset.mark = primary;
  get('role-secondary-icon').dataset.mark = secondary;
  get('role-primary').textContent = (twoPlayers ? 'Player · ' : 'You · ') + primary;
  get('role-secondary').textContent = (twoPlayers ? 'Player · ' : 'AI · ') + secondary;
  const robotConnected = online && token && state?.camera_fresh && state?.robot_fresh;
  get('connection').textContent = realEnvironment
    ? (robotConnected ? (state.state === 'blocked' ? 'Robot connected · Game paused' : 'Robot connected')
      : (online ? 'Waiting for robot feedback or camera' : 'Disconnected'))
    : (ready ? 'Simulation online' : (online ? 'Waiting for simulation' : 'Disconnected'));
  get('connection').dataset.online = String(Boolean(realEnvironment ? robotConnected : ready));
  if (realEnvironment) {
    get('camera-heading').textContent = state?.frame_source === 'saved' ? 'Saved robot camera image' : 'Robot camera';
  }
  start.disabled = !ready || busy;
  start.textContent = game ? 'New game' : 'Start game';
  saveSettings.disabled = !settingsKey;
  renderPipeline(game, vision, busy);
  stop.disabled = !online || !state?.busy;
  const resetReady = online && token && state && !['connecting','offline'].includes(state.state)
    && (!realEnvironment || (state.camera_fresh && state.robot_fresh));
  const resumeTurn = get('resume-turn');
  resumeTurn.hidden = !realEnvironment || !state?.continuation?.available || state?.state !== 'blocked';
  resumeTurn.textContent = state?.continuation?.kind === 'grid' ? 'Resume grid' : 'Resume turn';
  resumeTurn.disabled = !online || !token || busy || !state?.camera_fresh || !state?.robot_fresh;
  reset.hidden = !game && state?.state !== 'blocked';
  reset.disabled = !resetReady || busy || reset.hidden;
  const points = get('points');
  points.hidden = !showPoints;
  const playerScore = game?.current_score?.player ?? {points: 0, lines: 0};
  const aiScore = game?.current_score?.ai ?? {points: 0, lines: 0};
  get('score-round').textContent = 'Round ' + (game?.round ?? 1) + ' / 2';
  get('score-player').textContent = String(playerScore.points);
  get('score-ai').textContent = String(aiScore.points);
  get('score-total').textContent = 'Settled score Player ' + (game?.totals?.player?.points ?? 0) +
    ' points · AI ' + (game?.totals?.ai?.points ?? 0) + ' points';
  get('score-lines').textContent = 'Lines this round Player ' + playerScore.lines + ' · AI ' + aiScore.lines;
  const next = get('next');
  next.hidden = game?.phase !== 'between_rounds';
  next.disabled = !ready || busy;
  next.textContent = game?.first === 'player' ? 'Start round two · AI moves first' : 'Start round two · Player moves first';
  let outcome;
  if (game?.mode === 'score') {
    if (game.match_winner) {
      const reason = {points: 'Points', lines: 'Line count', coin: 'Random tiebreak'};
      outcome = (game.match_winner === 'player' ? 'You win the match' : 'AI wins the match') +
        ' · ' + reason[game.decided_by];
    } else if (game.phase === 'between_rounds') {
      outcome = 'Round 1 score · You ' + playerScore.points + ' points, AI ' + aiScore.points + ' points';
    }
  } else {
    outcome = game?.winner === 'draw' ? 'Game ended in a draw' : game?.winner && (twoPlayers
      ? 'Player ' + game.winner + ' wins' : (game.winner === game.human ? 'You win' : 'AI wins'));
  }

  const result = get('result');
  result.hidden = !outcome;
  result.textContent = outcome || '';
  result.dataset.outcome = game?.mode === 'score' ? (game.match_winner === 'player' ? 'X' : game.match_winner === 'ai' ? 'O' : 'draw') : game?.winner ?? '';
  const message = gameStatus(game, busy, ready, twoPlayers ? game?.turn : human, outcome);
  const status = get('status');
  if (status.textContent !== message) status.textContent = message;
  const error = notice || (
    ['blocked', 'failed'].includes(state?.state) || game?.phase === 'blocked' ? state?.message : ''
  );
  const details = get('game-error');
  details.hidden = !error || error === message;
  if (details.hidden) details.open = false;
  const detailText = get('game-error-message');
  if (detailText.textContent !== (error || '')) detailText.textContent = error || '';
  const cameraSequence = state?.camera_sequence;
  const cameraUrl = cameraSequence
    ? (cameraDetection.checked ? '/api/game/perception?view=camera_detections&seq=' : '/api/game/camera?seq=') + cameraSequence
    : state?.game_frame ? '/api/game/frame?job=' + state.game_frame : null;
  if (cameraUrl !== frame) {
    frame = cameraUrl;
    if (frame) {
      const nextImage = new Image();
      nextImage.onload = () => {
        if (frame !== cameraUrl) return;
        image.src = gameURL(cameraUrl);
        image.hidden = false;
        if (cameraSequence && cameraSequence !== lastCameraSequence) {
          lastCameraSequence = cameraSequence;
          cameraAdvancedAt = performance.now();
        }
        if (fadeCamera && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
          image.animate([{opacity: .5}, {opacity: 1}], {duration: 170});
        }
        fadeCamera = false;
        get('preview').querySelector('p').hidden = true;
      };
      nextImage.onerror = () => { if (frame === cameraUrl) frame = undefined; };
      nextImage.src = gameURL(cameraUrl);
    } else {
      image.hidden = true;
      get('preview').querySelector('p').hidden = false;
    }
  }
}

async function refresh() {
  if (!token) {
    const response = await gameFetch('/api/config', {signal: AbortSignal.timeout(2500)});
    if (!response.ok) throw Error('Could not read configuration');
    const config = await response.json();
    token = config.token;
    visionAvailable = config.vision_available === true;
    realEnvironment = config.environment === 'real';
    document.body.dataset.environment = config.environment;
    // The playable grid is inset 2 mm along each edge of the calibrated board.
    inkSize = [config.width_mm - 4, config.height_mm - 4];
    get('camera-heading').textContent = realEnvironment ? 'Robot camera' : 'Simulation camera';
    if (realEnvironment) {
      image.alt = 'Real tablet and robot arm';
      get('preview').querySelector('p').textContent = 'Waiting for robot camera image';
      const workbenchUrl = gameMount ? '../' : config.workstation_url;
      get('canvas-link').textContent = 'Calibration workbench';
      get('canvas-link').href = workbenchUrl;
      get('studio-calibration-link').href = workbenchUrl;
      get('studio-canvas-link').href = new URL('canvas', new URL(workbenchUrl, location.href)).href;
    } else {
      get('studio-calibration-link').href = 'http://localhost:8766/';
      get('studio-canvas-link').href = '/';
    }
    loadSettings(config.environment);
  }
  const response = await gameFetch('/api/status', {signal: AbortSignal.timeout(2500)});
  if (!response.ok) throw Error('Could not read status');
  state = await response.json();
  online = true;
}

async function act(path, data) {
  if (!token || (sending && path !== '/api/stop')) return;
  sending = true;
  notice = '';
  render();
  try {
    const response = await gameFetch(path, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Canvas-Token': token},
      body: JSON.stringify(data), signal: AbortSignal.timeout(3500)});
    if (!response.ok) throw Error((await response.json()).error || 'Request failed');
    await refresh();
    return true;
  } catch (error) {
    notice = error.message;
    try { await refresh(); } catch { online = false; token = undefined; }
  } finally {
    sending = false;
    render();
  }
}

let pollTimer;
let polling = false;
async function poll() {
  if (polling) return;
  clearTimeout(pollTimer);
  polling = true;
  try {
    if (!sending) {
      try { await refresh(); } catch { online = false; token = undefined; }
      render();
    }
  } finally {
    polling = false;
    pollTimer = setTimeout(poll, document.hidden ? 1500 : 350);
  }
}
function resumePage() {
  if (document.hidden) return;
  // Reconcile server state after a frozen tab; never replay a motion request.
  token = undefined;
  frame = undefined;
  clearTimeout(pollTimer);
  void poll();
}
document.addEventListener('visibilitychange', resumePage);
document.addEventListener('resume', resumePage);
window.addEventListener('pageshow', resumePage);
window.addEventListener('focus', resumePage);
window.addEventListener('online', resumePage);
settingsToggle.addEventListener('click', () => showSettings(settings.hidden, settingsToggle));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !settings.hidden) {
    event.preventDefault();
    showSettings(false);
  }
});
saveSettings.addEventListener('click', () => {
  if (!settingsKey) return;
  saved = Object.fromEntries(settingsFields.map(name => [name, choice(name)]));
  try { localStorage.setItem(settingsKey, JSON.stringify(saved)); } catch { /* The current tab still retains the settings. */ }
  const feedback = get('settings-saved');
  feedback.textContent = 'Saved for next game.';
  feedback.hidden = false;
  showSettings(false);
  render();
});
start.addEventListener('click', async () => {
  if (state?.game && !window.confirm('Clear the current board and start a new game?')) return;
  const {size: mode, opponent, first, mark} = saved;
  const started = await act('/api/game/start', {
    size: modes[mode].size,
    mode: mode === 'four' ? 'four' : 'classic',
    first: opponent === 'human' ? 'player' : first,
    mark,
    opponent,
    input_source: visionAvailable && saved['input-source'] !== 'click'
      ? saved['input-source'] : realEnvironment ? 'vision' : 'click',
  });
  if (started) get('settings-saved').hidden = true;
});
settings.addEventListener('change', renderSettings);
get('settings-close').addEventListener('click', () => showSettings(false));
get('settings-back').addEventListener('click', () => showSettings(false));
get('next').addEventListener('click', () => act('/api/game/next', {revision: state.game.revision}));
stop.addEventListener('click', () => act('/api/stop', {}));
reset.addEventListener('click', () => act('/api/reset', {}));
get('resume-turn').addEventListener('click', () => {
  const explanation = state?.continuation?.kind === 'grid'
    ? 'Inspect the pen and board first. Only the unstarted grid strokes will be drawn, then the arm returns to zero. Continue?'
    : 'Inspect the pen and board first. The arm will return to zero and resume camera observation. No original stroke will be replayed. Continue?';
  if (confirm(explanation)) {
    act('/api/game/resume', {revision: state.game.revision,
      original_job: state.continuation.original_job, inspected: true});
  }
});
new ResizeObserver(positionWinLine).observe(board);
const ink = get('handwriting');
const inkContext = ink.getContext('2d');
let draft = [], activeStroke = null, inkEnabled = false, draftRevision;
function paintDraft() {
  const box = ink.getBoundingClientRect();
  if (!box.width || !box.height) return;
  ink.width = Math.round(box.width * devicePixelRatio);
  ink.height = Math.round(box.height * devicePixelRatio);
  inkContext.scale(devicePixelRatio, devicePixelRatio);
  inkContext.strokeStyle = '#ffffff';
  inkContext.lineWidth = 2.5;
  inkContext.lineCap = inkContext.lineJoin = 'round';
  for (const stroke of draft) {
    inkContext.beginPath();
    stroke.forEach(([x,y], index) => inkContext[index ? 'lineTo' : 'moveTo'](x*box.width, y*box.height));
    inkContext.stroke();
  }
  get('stroke-count').textContent = draft.length + (draft.length === 1 ? ' stroke' : ' strokes');
}
function updateHandwriting(show, playable, revision) {
  ink.hidden = get('handwriting-controls').hidden = !show;
  inkEnabled = show && playable && (draftRevision === undefined || draftRevision === revision);
  ink.style.pointerEvents = show ? 'auto' : 'none';
  get('submit-handwriting').disabled = !inkEnabled || !draft.length || activeStroke !== null;
  get('undo-stroke').disabled = get('clear-draft').disabled = sending || state?.busy || !draft.length;
  paintDraft();
}
function inkPoint(event) {
  const box = ink.getBoundingClientRect();
  return [Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),
          Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))];
}
ink.addEventListener('pointerdown', event => {
  if (!inkEnabled || activeStroke || event.button !== 0 || draft.length >= 32) return;
  event.preventDefault(); ink.setPointerCapture(event.pointerId);
  draftRevision ??= state.game.revision;
  activeStroke = [inkPoint(event)]; draft.push(activeStroke); paintDraft();
  get('submit-handwriting').disabled = true;
});
ink.addEventListener('pointermove', event => {
  if (!activeStroke || activeStroke.length >= 2000) return;
  activeStroke.push(inkPoint(event)); paintDraft();
});
function finishInk() {
  if (!activeStroke) return;
  if (activeStroke.length < 2) draft.pop();
  activeStroke = null; render();
}
ink.addEventListener('pointerup', finishInk);
ink.addEventListener('pointercancel', () => { if (activeStroke) draft.pop(); activeStroke = null; render(); });
get('undo-stroke').addEventListener('click', () => { draft.pop(); if (!draft.length) draftRevision = undefined; render(); });
get('clear-draft').addEventListener('click', () => { draft = []; draftRevision = undefined; render(); });
function boardStrokes(strokes, size, [width, height]) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw Error('Handwriting needs valid board dimensions.');
  }
  let left = 1, top = 1, right = 0, bottom = 0;
  for (const stroke of strokes) {
    for (const [x, y] of stroke) {
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x);
      bottom = Math.max(bottom, y);
    }
  }
  const col = Math.min(size - 1, Math.floor(left * size));
  const row = Math.min(size - 1, Math.floor(top * size));
  if (right > (col + 1) / size || bottom > (row + 1) / size) {
    throw Error('Keep the entire mark within one cell.');
  }
  // Scale around the mark's center so the square preview preserves both shape
  // and the chosen cell when mapped onto the longer physical axis.
  const centerX = (left + right) / 2;
  const centerY = (top + bottom) / 2;
  const scale = Math.min(width, height);
  return strokes.map(stroke => stroke.map(([x, y]) => [
    centerX + (x - centerX) * (scale / width),
    centerY + (y - centerY) * (scale / height),
  ]));
}

get('submit-handwriting').addEventListener('click', async () => {
  if (!inkEnabled || activeStroke || !draft.length) return;
  let submitted;
  try {
    submitted = boardStrokes(draft, state.game.size, inkSize ?? []);
  } catch (error) {
    notice = error.message;
    render();
    return;
  }
  await act('/api/game/handwriting', {strokes: submitted, revision: draftRevision});
  if (!notice) { draft = []; draftRevision = undefined; render(); }
});
new ResizeObserver(paintDraft).observe(ink);
renderSettings();
render();
poll();

cameraDetection.closest('.camera-switch').addEventListener('change', () => { fadeCamera = true; frame = undefined; render(); });
