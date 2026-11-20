'use strict';
const get = id => document.getElementById(id);
const board = get('board');
const winLine = get('win-line');
let winCells = [];
const start = get('start');
const stop = get('stop');
const reset = get('reset');
const image = get('image');
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
  rectified: '沿用相机方向做透视校正。',
  edges: '白线显示图像中的边缘，包括棋盘线和笔迹。',
  detections: '细线为标定格线。检测框标注 X/O 和对弈棋盘的行列；同格冲突显示 O/X。'
};

function resetPerception() {
  perceptionRequest?.abort();
  renderedPerception = undefined;
  if (perceptionUrl) URL.revokeObjectURL(perceptionUrl);
  perceptionUrl = undefined;
  perceptionImage.removeAttribute('src');
  perceptionImage.hidden = true;
  perceptionMessage.hidden = false;
  perceptionMessage.textContent = '正在等待相机画面';
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
      perceptionMessage.textContent = error.message || '感知预览暂不可用';
      perceptionMessage.hidden = false;
    }
  } finally {
    perceptionRequest = undefined;
  }
}
let online = false;
const phases = {
  preparing: '正在建立棋盘', player: '轮到你了，选一个空格画 X',
  drawing_x: '机械臂正在画你的 X', thinking: 'AI 正在选格',
  drawing_o: '机械臂正在画 AI 的 O', blocked: '对局暂停，请检查板面后重新开局'
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
    cell.firstElementChild.textContent = showPoints ? points + ' 分' : '';
    cell.dataset.mark = mark;
    cell.dataset.winning = String(winCells.includes(index));
    cell.disabled = !playable || Boolean(mark);
    cell.setAttribute('aria-label', '第 ' + (row+1) + ' 行，第 ' + (col+1) + ' 列，' + (mark || '空格') + (showPoints ? '，' + points + ' 分' : ''));
  });
  winLine.hidden = winCells.length === 0;
  winLine.dataset.mark = game?.winner ?? '';
  positionWinLine();
  get('heading').textContent = ({'score': '分值井字棋', 'four': '四子棋', 'four-three-stone': '四子棋 · 三子开局', '9': '五子棋', '3': '井字棋'})[mode ?? chosenMode()];
  const human = game?.human ?? get('mark').value;
  get('roles').textContent = '你执 ' + human + ' · AI 执 ' + (human === 'X' ? 'O' : 'X');
  get('connection').textContent = ready ? (realEnvironment ? '真机已连接' : 'Gazebo 已连接')
    : (online ? (realEnvironment ? '等待真机反馈或相机' : '仿真尚未就绪') : '连接已断开');
  if (realEnvironment) {
    get('camera-heading').textContent = state?.frame_source === 'saved' ? '已保存的真机画面' : '真机相机';
  }
  const observed = state?.vision;
  get('vision-status').textContent = observed
    ? '相机帧 ' + observed.sequence + ' · 新落子一致 ' + observed.consecutive + ' / 3'
      + (observed.confirmed ? ' · 已确认第 ' + (observed.confirmed[0]+1) + ' 行第 ' + (observed.confirmed[1]+1) + ' 列 ' + observed.confirmed[2] : '')
    : (realEnvironment ? (state?.frame_source === 'saved' ? '已保存棋局的 YOLO 识别结果，等待实时连接' : '连续三帧确认后更新左侧棋盘') : '');
  start.disabled = !ready || busy;
  start.textContent = game ? '重新开局' : '开局';
  stop.disabled = !online || !state?.busy;
  reset.disabled = !ready || busy || !game;
  const points = get('points');
  points.hidden = !showPoints;
  const playerScore = game?.current_score?.player ?? {points: 0, lines: 0};
  const aiScore = game?.current_score?.ai ?? {points: 0, lines: 0};
  get('score-round').textContent = '第 ' + (game?.round ?? 1) + ' / 2 局';
  get('score-player').textContent = String(playerScore.points);
  get('score-ai').textContent = String(aiScore.points);
  get('score-total').textContent = '已结算 玩家 ' + (game?.totals?.player?.points ?? 0) +
    ' 分 · AI ' + (game?.totals?.ai?.points ?? 0) + ' 分';
  get('score-lines').textContent = '本局连线 玩家 ' + playerScore.lines + ' · AI ' + aiScore.lines;
  const next = get('next');
  next.hidden = game?.phase !== 'between_rounds';
  next.disabled = !ready || busy;
  next.textContent = game?.first === 'player' ? '开始第二局 · AI 先手' : '开始第二局 · 玩家先手';
  let outcome;
  if (game?.mode === 'score') {
    if (game.match_winner) {
      const reason = {points: '总分决胜', lines: '累计连线数决胜', coin: '总分和连线数相同，由随机决胜'};
      outcome = (game.match_winner === 'player' ? '你赢得比赛' : 'AI 赢得比赛') +
        ' · ' + reason[game.decided_by];
    } else if (game.phase === 'between_rounds') {
      outcome = '第一局结算 · 你 ' + playerScore.points + ' 分，AI ' + aiScore.points + ' 分';
    }
  } else {
    outcome = game?.winner === 'draw' ? '平局' : game?.winner && (game.winner === game.human ? '你赢了' : 'AI 获胜');
  }

  const result = get('result');
  result.hidden = !outcome;
  result.textContent = outcome || '';
  result.dataset.outcome = game?.mode === 'score' ? (game.match_winner === 'player' ? 'X' : game.match_winner === 'ai' ? 'O' : 'draw') : game?.winner ?? '';
  let message = state?.message ?? '正在连接本地仿真…';
  if (busy && game && ['drawing_x','thinking','drawing_o'].includes(game.phase)) {
    const mark = game.phase === 'drawing_x' ? 'X' : 'O';
    const action = game.phase === 'thinking' ? 'AI 正在选格' :
      '机械臂正在画' + (human === mark ? '你的 ' : ' AI 的 ') + mark;
    message = action + ' · ' + message;
  } else if (!busy && game) {
    if (game.phase === 'between_rounds') message = '下一局交换先手，你仍执 ' + human;
    else if (game.phase === 'player') message = vision
      ? '选一个空格模拟书写 ' + human + '，相机识别稳定后自动提交'
      : '轮到你了，选一个空格画 ' + human;
    else message = outcome ? '本局结束，可以重新开局' : phases[game.phase] || message;
  }
  get('status').textContent = notice || message;
  const cameraUrl = state?.camera_sequence
    ? '/api/game/camera?seq=' + state.camera_sequence
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
    if (!response.ok) throw Error('配置读取失败');
    const config = await response.json();
    token = config.token;
    visionAvailable = config.vision_available === true;
    realEnvironment = config.environment === 'real';
    document.body.dataset.environment = config.environment;
    if (realEnvironment) {
      get('camera-heading').textContent = '真机相机';
      image.alt = '真实平板与机械臂画面';
      get('preview').querySelector('p').textContent = '正在等待真机相机画面';
      perception.open = true;
      perceptionView.value = 'detections';
      get('input-source').value = 'vision';
      get('input-source').querySelector('[value=click]').disabled = true;
      get('input-source').querySelector('[value=vision]').textContent = '机械臂代写 · 相机确认';
      document.querySelectorAll('input[name=size]').forEach(input => {
        if (input.value !== '3') input.closest('label').hidden = true;
      });
      get('canvas-link').textContent = '定位工作台';
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
  if (!response.ok) throw Error('状态读取失败');
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
    if (!response.ok) throw Error((await response.json()).error || '请求失败');
    await refresh();
  } catch (error) {
    notice = error.message;
    try { await refresh(); } catch { online = false; token = undefined; }
  } finally {
    sending = false;
    render();
  }
}

async function poll() {
  if (!sending) {
    try { await refresh(); } catch { online = false; token = undefined; }
    render();
  }
  setTimeout(poll, 350);
}
perception.addEventListener('toggle', resetPerception);
perceptionView.addEventListener('change', resetPerception);
setInterval(updatePerception, 850);
start.addEventListener('click', () => {
  if (!state?.game || window.confirm('清空当前对局并重新开局？')) {
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
