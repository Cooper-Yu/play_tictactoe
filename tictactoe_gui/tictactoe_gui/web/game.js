'use strict';
const get = id => document.getElementById(id);
const board = get('board');
const winLine = get('win-line');
let winCells = [];
const start = get('start');
const stop = get('stop');
const reset = get('reset');
const image = get('image');
const cameraDetection = get('camera-detection');
let token;
let state;
let sending = false;
let notice = '';
let frame;
let activeMode;
let visionAvailable = false;
let realEnvironment = false;
const perception = get('perception');
const perceptionView = get('perception-view');
const perceptionImage = get('perception-image');
const perceptionMessage = get('perception-message');
let perceptionUrl;
let perceptionRequest;
let renderedPerception;
const perceptionCaptions = {
  rectified: 'Perspective-corrected view aligned with the camera.',
  edges: 'Edges of the grid and pen strokes.',
  detections: 'Calibrated cell boundaries and YOLO detections. Labels show symbol, row and column; O/X indicates a conflicting cell.'
};

function resetPerception() {
  perceptionRequest?.abort();
  renderedPerception = undefined;
  if (perceptionUrl) URL.revokeObjectURL(perceptionUrl);
  perceptionUrl = undefined;
  perceptionImage.removeAttribute('src');
  perceptionImage.hidden = true;
  perceptionMessage.hidden = false;
  perceptionMessage.textContent = 'Waiting for camera image';
  get('perception-caption').textContent = perceptionCaptions[perceptionView.value];
}

async function updatePerception() {
  if (!perception.open || !online || !state?.camera_sequence || perceptionRequest) return;
  const view = perceptionView.value;
  const key = [state.camera_sequence, state.game?.size, view].join(':');
  if (renderedPerception === key) return;
  const request = new AbortController();
  perceptionRequest = request;
  try {
    const response = await fetch('/api/game/perception?view=' + view, {
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(12000)])
    });
    if (!response.ok) throw Error((await response.json()).error);
    const imageBlob = await response.blob();
    if (request.signal.aborted || !perception.open) return;
    const previous = perceptionUrl;
    perceptionUrl = URL.createObjectURL(imageBlob);
    perceptionImage.src = perceptionUrl;
    perceptionImage.hidden = false;
    perceptionMessage.hidden = true;
    if (previous) URL.revokeObjectURL(previous);
    renderedPerception = key;
  } catch (error) {
    if (!request.signal.aborted) {
      perceptionMessage.textContent = error.message || 'Perception preview is temporarily unavailable';
      perceptionMessage.hidden = false;
    }
  } finally {
    perceptionRequest = undefined;
  }
}
let online = false;
const phases = {
  preparing: 'Preparing board', player: 'Your turn, Select an empty cell to draw X',
  drawing_x: 'The arm is drawing your X', thinking: 'AI is choosing a cell',
  drawing_o: 'The arm is drawing AI of O', blocked: 'Game paused, Inspect the board before starting a new game'
};
const chosenMode = () => document.querySelector('input[name="size"]:checked').value;
const selected = () => ['9', 'four', 'four-three-stone'].includes(chosenMode()) ? 9 : 3;

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


function render() {
  const game = state?.game;
  const mode = game && (game.mode === 'classic' ? String(game.size) : game.mode);
  if (mode && mode !== activeMode) {
    document.querySelector('input[name="size"][value="' + mode + '"]').checked = true;
  }
  activeMode = mode;
  const isThreeStone = chosenMode() === 'four-three-stone';
  get('first-option').hidden = isThreeStone;
  get('input-option').hidden = !visionAvailable || chosenMode() !== '3';
  const vision = game?.input_source === 'vision';
  get('three-stone-rules').hidden = !isThreeStone;
  const size = game?.size ?? selected();
  const showPoints = game ? game.mode === "score" : chosenMode() === "score";
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
  winCells = game && !showPoints ? winningRun(game.board, game.winner, game.win_length ?? (size === 3 ? 3 : 5)) : [];
  Array.from(board.children).forEach((cell, index) => {
    const row = Math.floor(index / size), col = index % size;
    const mark = game?.board[row][col] ?? '';
    const points = game?.weights?.[index] ?? [2,1,2,1,3,1,2,1,2][index];
    cell.firstElementChild.textContent = showPoints ? points + ' points' : '';
    cell.dataset.mark = mark;
    cell.dataset.winning = String(winCells.includes(index));
    cell.disabled = !playable || Boolean(mark);
    cell.setAttribute('aria-label', 'Row ' + (row+1) + ', column ' + (col+1) + ', ' + (mark || 'Empty') + (showPoints ? ', ' + points + ' points' : ''));
  });
  winLine.hidden = winCells.length === 0;
  winLine.dataset.mark = game?.winner ?? '';
  positionWinLine();
  get('heading').textContent = ({'score': 'Scored Tic-Tac-Toe', 'four': 'Four-in-a-Row', 'four-three-stone': 'Four-in-a-Row · Three-stone opening', '9': 'Gomoku', '3': 'Tic-Tac-Toe'})[mode ?? chosenMode()];
  const human = game?.human ?? get('mark').value;
  get('roles').textContent = 'You play ' + human + ' · AI plays ' + (human === 'X' ? 'O' : 'X');
  get('connection').textContent = ready ? (realEnvironment ? 'Robot connected' : 'Gazebo connected')
    : (online ? (realEnvironment ? 'Waiting for robot feedback or camera' : 'Simulation is not ready') : 'Disconnected');
  if (realEnvironment) {
    get('camera-heading').textContent = state?.frame_source === 'saved' ? 'Saved robot camera image' : 'Robot camera';
  }
  const observed = state?.vision;
  get('vision-status').textContent = observed
    ? 'Camera frame ' + observed.sequence + ' · New mark consistency ' + observed.consecutive + ' / 3'
      + (observed.confirmed ? ' · Confirmed row ' + (observed.confirmed[0]+1) + ', column ' + (observed.confirmed[1]+1) + ': ' + observed.confirmed[2] : '')
    : (realEnvironment ? (state?.frame_source === 'saved' ? 'Saved YOLO detections. Waiting for a live connection.' : 'Update the board after three consistent camera frames') : '');
  start.disabled = !ready || busy;
  start.textContent = game ? 'New game' : 'Start game';
  stop.disabled = !online || !state?.busy;
  reset.disabled = !ready || busy || !game;
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
      const reason = {points: 'Winner determined by total points', lines: 'Winner determined by total line count', coin: 'Total points and line counts are tied, Random tiebreaker'};
      outcome = (game.match_winner === 'player' ? 'You win the match' : 'AI wins the match') +
        ' · ' + reason[game.decided_by];
    } else if (game.phase === 'between_rounds') {
      outcome = 'Round 1 score · You ' + playerScore.points + ' points, AI ' + aiScore.points + ' points';
    }
  } else {
    outcome = game?.winner === 'draw' ? 'Draw' : game?.winner && (game.winner === game.human ? 'You win' : 'AI wins');
  }

  const result = get('result');
  result.hidden = !outcome;
  result.textContent = outcome || '';
  result.dataset.outcome = game?.mode === 'score' ? (game.match_winner === 'player' ? 'X' : game.match_winner === 'ai' ? 'O' : 'draw') : game?.winner ?? '';
  let message = state?.message ?? 'Connecting to local simulation…';
  if (busy && game && ['drawing_x','thinking','drawing_o'].includes(game.phase)) {
    const mark = game.phase === 'drawing_x' ? 'X' : 'O';
    const action = game.phase === 'thinking' ? 'AI is choosing a cell' :
      'The arm is drawing ' + (human === mark ? 'your ' : 'AI mark ') + mark;
    message = action + ' · ' + message;
  } else if (!busy && game) {
    if (game.phase === 'between_rounds') message = 'The first player changes next round, You still play ' + human;
    else if (game.phase === 'player') message = vision
      ? 'Select an empty cell for proxy drawing ' + human + ', Submit automatically after stable camera recognition'
      : 'Your turn, Select an empty cell to draw ' + human;
    else message = outcome ? 'Game finished. Start a new game' : phases[game.phase] || message;
  }
  get('status').textContent = notice || message;
  const cameraUrl = state?.camera_sequence
    ? (cameraDetection.checked ? '/api/game/perception?view=camera_detections&seq=' : '/api/game/camera?seq=') + state.camera_sequence
    : state?.game_frame ? '/api/game/frame?job=' + state.game_frame : null;
  if (cameraUrl !== frame) {
    frame = cameraUrl;
    if (frame) {
      const nextImage = new Image();
      nextImage.onload = () => {
        if (frame !== cameraUrl) return;
        image.src = cameraUrl;
        image.hidden = false;
        get('preview').querySelector('p').hidden = true;
      };
      nextImage.onerror = () => { if (frame === cameraUrl) frame = undefined; };
      nextImage.src = cameraUrl;
    } else {
      image.hidden = true;
      get('preview').querySelector('p').hidden = false;
    }
  }
}

async function refresh() {
  if (!token) {
    const response = await fetch('/api/config', {signal: AbortSignal.timeout(2500)});
    if (!response.ok) throw Error('Could not read configuration');
    const config = await response.json();
    token = config.token;
    visionAvailable = config.vision_available === true;
    realEnvironment = config.environment === 'real';
    document.body.dataset.environment = config.environment;
    if (realEnvironment) {
      get('camera-heading').textContent = 'Robot camera';
      image.alt = 'Real tablet and robot arm';
      get('preview').querySelector('p').textContent = 'Waiting for robot camera image';
      perception.open = true;
      perceptionView.value = 'detections';
      get('input-source').value = 'vision';
      get('input-source').querySelector('[value=click]').disabled = true;
      get('input-source').querySelector('[value=vision]').textContent = 'Robot proxy drawing · Camera confirmation';
      document.querySelectorAll('input[name=size]').forEach(input => {
        if (input.value !== '3') input.closest('label').hidden = true;
      });
      get('canvas-link').textContent = 'Calibration workbench';
      get('canvas-link').href = config.workstation_url;
      board.style.aspectRatio = config.width_mm + '/' + config.height_mm;
    }
    const supportsThreeStone = config.game_modes?.includes('four-three-stone') === true;
    get('three-stone-option').hidden = !supportsThreeStone;
    if (!supportsThreeStone && chosenMode() === 'four-three-stone') {
      document.querySelector('input[value="four"]').checked = true;
    }
  }
  const response = await fetch('/api/status', {signal: AbortSignal.timeout(2500)});
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
    const response = await fetch(path, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Canvas-Token': token},
      body: JSON.stringify(data), signal: AbortSignal.timeout(3500)});
    if (!response.ok) throw Error((await response.json()).error || 'Request failed');
    await refresh();
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
  renderedPerception = undefined;
  perceptionRequest?.abort();
  clearTimeout(pollTimer);
  void poll().then(() => updatePerception());
}
document.addEventListener('visibilitychange', resumePage);
document.addEventListener('resume', resumePage);
window.addEventListener('pageshow', resumePage);
window.addEventListener('focus', resumePage);
window.addEventListener('online', resumePage);
perception.addEventListener('toggle', resetPerception);
perceptionView.addEventListener('change', resetPerception);
setInterval(updatePerception, 850);
start.addEventListener('click', () => {
  if (!state?.game || window.confirm('Clear the current board and start a new game？')) {
    act('/api/game/start', {size: selected(), mode: ['score', 'four', 'four-three-stone'].includes(chosenMode()) ? chosenMode() : 'classic',
      first: get('first').value, mark: get('mark').value,
      input_source: visionAvailable && chosenMode() === '3' ? get('input-source').value : 'click'});
  }
});
get('next').addEventListener('click', () => act('/api/game/next', {revision: state.game.revision}));
stop.addEventListener('click', () => act('/api/stop', {}));
reset.addEventListener('click', () => act('/api/reset', {}));
document.querySelectorAll('input[name="size"]').forEach(input => input.addEventListener('change', render));
get('mark').addEventListener('change', render);
new ResizeObserver(positionWinLine).observe(board);
const preset = location.hash.slice(1);
if (['four', 'four-three-stone'].includes(preset)) {
  document.querySelector('input[value="' + preset + '"]').checked = true;
}
render();
poll();

cameraDetection.addEventListener('change', () => { frame = undefined; render(); });
