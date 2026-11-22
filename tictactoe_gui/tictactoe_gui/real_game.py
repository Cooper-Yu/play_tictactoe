"""Connect the game page to the real workstation and visual player confirmation."""
import argparse
import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import queue
import signal
import threading
import time

import requests

from tictactoe_coordinator.game_coordinator import GameCoordinator
from tictactoe_gui.real_board_perception import RealBoardPerception
from tictactoe_gui.game_timing import Timeline
from tictactoe_gui.grid_recovery import unstarted_grid_tail
from tictactoe_gui.server import CanvasSession, make_handler
from tictactoe_gui.workstation_client import Workstation, RemoteDrawing
from tictactoe_perception.stable_player_move import StablePlayerMove
from tictactoe_gui.geometry import validate_strokes, verify_handwriting_cell, verify_handwriting_shape


def real_handwriting_strokes(strokes, width, height):
    """Map game-grid coordinates to the real canvas without rotating or double-insetting.

    The game grid has a 2-mm outer inset; CanvasAction independently reserves
    1 mm for the pen. Invert that extra inset before handing it the strokes.
    This transforms geometry only, never supplies a committed row or column.
    """
    checked = validate_strokes(strokes)
    if width <= .004 or height <= .004:
        raise ValueError('Invalid calibrated board dimensions')
    return [[[.001/(width-.002)+u*(width-.004)/(width-.002),
              .001/(height-.002)+v*(height-.004)/(height-.002)]
             for u,v in stroke] for stroke in checked]


def real_game_worker(session, *, url, perception, restore=None):
    """Keep motion serialized while an independent thread supplies live camera frames."""
    timing = Timeline(session.output)
    def progress(state):
        session.update(message=state['message'], motion_job=state['job'])

    if restore:
        saved_path = Path(restore)
        saved = json.loads(saved_path.read_text())['game']
        if saved['phase'] != 'finished' or saved.get('input_source') != 'vision':
            raise ValueError('Only completed vision games can be restored for display')
        session.update(game=saved, frame_source='saved', camera_fresh=False, robot_fresh=False)
        photo = saved_path.parent/'finished.jpg'
        if photo.is_file():
            session.publish_camera(photo.read_bytes())
    while not session.shutdown.is_set():
        try:
            client = Workstation(url, session.output/'motion', cancelled=session.stop.is_set,
                                 progress=progress, timing=timing.emit)
            break
        except requests.RequestException:
            session.update(state='offline', busy=False, message='Workbench disconnected. Showing the saved game and retrying.')
            session.shutdown.wait(5)
    else:
        return
    actions = RemoteDrawing(client)
    def publish(**changes):
        session.update(**changes)
        if 'game' in changes:
            game_state = changes['game']
            timing.emit('game_state', phase=game_state['phase'], revision=game_state['revision'],
                        board=game_state['board'])
    game = GameCoordinator(actions, publish, session.stop.is_set, flip=False)

    def camera_loop():
        with requests.Session() as http:
            while not session.shutdown.is_set():
                try:
                    state = http.get(client.url+'api/status', timeout=8)
                    state.raise_for_status()
                    state = state.json()
                    camera = state['camera']
                    image = http.get(client.url+'api/frame', timeout=8)
                    image.raise_for_status()
                    session.publish_camera(image.content, camera['sequence'])
                    session.update(frame_source='live', camera_fresh=camera.get('fresh', False),
                                   camera_age_s=camera.get('age_s'), camera_error=None,
                                   robot_fresh=state.get('fresh', False))
                except Exception as error:
                    session.update(camera_fresh=False, camera_error=str(error))
                session.shutdown.wait(.1)

    camera_thread = threading.Thread(target=camera_loop, daemon=True)
    camera_thread.start()
    gate = None
    gate_revision = None
    pending_turn = None
    resumed_strokes = None

    def checkpoint(stage, job=None):
        nonlocal pending_turn
        if job is not None:
            pending_turn = dict(original_job=job['job'], stage=stage,
                                strokes=job.get('strokes'),
                                board=[row[:] for row in session.status()['game']['board']],
                                available=False)
        elif pending_turn is not None:
            pending_turn['stage'] = stage
        session.update(continuation=pending_turn)
        temporary = session.output/'turn-recovery.tmp'
        temporary.write_text(json.dumps(pending_turn, indent=2))
        temporary.replace(session.output/'turn-recovery.json')

    def observe():
        nonlocal gate, gate_revision
        state = session.status()
        current = state['game']
        if current is None or current['phase'] != 'player':
            return None
        if gate_revision != current['revision']:
            expected_mark = current['turn'] if current.get('opponent') == 'human' else current['human']
            gate = StablePlayerMove(current['board'], expected_mark)
            gate_revision = current['revision']
        image, sequence, _ = session.preview_frame()
        if not image or not state.get('camera_fresh') or sequence == gate.last_sequence:
            return None
        detect_started = time.monotonic()
        cells = perception.detect_cells(image, size=current["size"])
        found = gate.observe(sequence, cells)
        timing.emit('vision_frame', sequence=sequence, seconds=time.monotonic()-detect_started,
                    consecutive=gate.count, confirmed=found)
        evidence = dict(sequence=sequence,
                        cells={f'{r+1},{c+1}':sorted(m) for (r,c),m in cells.items()},
                        consecutive=gate.count, confirmed=found)
        with (session.output/'observations.jsonl').open('a') as stream:
            stream.write(json.dumps(evidence)+'\n')
        session.update(vision=evidence)
        if found:
            (session.output/f'confirmed-{current["revision"]}-{sequence}.jpg').write_bytes(image)
        return found

    def register(found, revision):
        nonlocal resumed_strokes
        if resumed_strokes:
            verify_handwriting_cell(resumed_strokes, found, game.game.rows)
            verify_handwriting_shape(resumed_strokes, game.game.width, game.game.height)
        resumed_strokes = None
        if pending_turn is not None:
            checkpoint('committing')
        timing.emit('player_confirmed', revision=revision, found=found)
        session.update(message='Three camera frames confirmed. Submitting player move.')
        game.register_observed_move(*found, revision)
        if game.game.outcome:
            client.park('zero')

    try:
        deadline = time.monotonic()+25
        while session.camera_image() is None:
            if time.monotonic() > deadline:
                raise RuntimeError('Timed out waiting for the robot camera')
            session.shutdown.wait(.1)
        session.update(state='connecting', message='Warming up YOLO inference; robot controls remain idle')
        warmup_started = time.monotonic()
        perception.detect_cells(session.camera_image())
        if getattr(perception, 'nine_preview', None) is not None:
            perception.detect_cells(session.camera_image(), size=9)
        session.update(inference_warmup_s=time.monotonic()-warmup_started)
        if restore:
            saved = json.loads(Path(restore).read_text())['game']
            cells = perception.detect_cells(session.camera_image())
            expected = {(r,c):frozenset((m,)) for r,row in enumerate(saved['board'])
                        for c,m in enumerate(row) if m}
            if cells != expected:
                raise RuntimeError('The live board differs from the saved game, Check calibration or board contents')
            session.update(game=saved)
        session.update(state='ready', busy=False, message='Real vision game connected. Start a new game to clear and prepare the physical board.')
        while not session.shutdown.is_set():
            try:
                job = session.jobs.get(timeout=.2)
            except queue.Empty:
                if game.game is None or session.status().get('state') != 'ready':
                    continue
                try:
                    found = observe()
                    if found:
                        with session.lock:
                            if session.state['busy'] or not session.jobs.empty():
                                continue
                            session.state.update(busy=True, state='running')
                            session.state['job'] += 1
                            revision = session.state['job']
                        register(found, revision)
                        session.update(state='ready', busy=False, message='Visual move processed')
                except Exception as error:
                    session.update(state='blocked', busy=False, message=str(error))
                continue
            try:
                session.update(state='running')
                kind, request = job['kind'], job['game_request'] or {}
                timing.emit('job_begin', job=job['job'], kind=kind)
                if kind == 'game_resume':
                    if pending_turn is None or not pending_turn['available']:
                        raise RuntimeError('Paused turn is no longer available')
                    actual = client.get('status', timeout=3)
                    if actual.get('feedback_recovery'):
                        client.recover_feedback()
                        actual = client.get('status', timeout=3)
                    if (actual['busy'] or not actual['fresh'] or actual['state'] != 'ready'
                            or not actual.get('pose') or actual['pose']['z'] < .2109):
                        raise RuntimeError('Raise the pen to at least 211 mm with the workbench before resuming')
                    if session.status()['game']['board'] != pending_turn['board']:
                        raise RuntimeError('The board changed; paused turn cannot be resumed')
                    if pending_turn.get('strokes'):
                        verify_handwriting_shape(pending_turn['strokes'], game.game.width, game.game.height)
                    if pending_turn.get('kind') == 'grid':
                        client.park('clear')
                        checkpoint('grid_remaining')
                        client.command(kind='canvas', strokes=pending_turn['remaining_strokes'], speed=.45)
                        checkpoint('grid_returning')
                    client.park('zero')
                    resumed_strokes = pending_turn.get('strokes')
                    game.game.phase = 'playing'
                    game._update('player', job['job'])
                    gate_revision = None
                    pending_turn = None
                    checkpoint('resumed')
                    session.update(vision=None)
                elif kind == 'reset':
                    pending_turn = resumed_strokes = None
                    checkpoint('cleared')
                    client.command(kind='reset', speed=.1)
                    client.park('zero')
                    game.game = None
                    session.update(game=None, vision=None)
                elif kind == 'game_start':
                    pending_turn = resumed_strokes = None
                    checkpoint('new_game')
                    session.update(vision=None)
                    client.command(kind='reset', speed=.1)
                    client.park('clear')
                    game.start(request.get('size', 3), job['job'], mode=request.get('mode', 'classic'),
                               first=request.get('first', 'player'),
                               mark=request.get('mark', 'X'), input_source=request.get('input_source', 'vision'),
                               opponent=request.get('opponent', 'ai'))
                    gate_revision = None
                    session.update(vision=None)
                elif kind in ('game_vision_move', 'game_handwriting'):
                    checkpoint('preparing', job)
                    mark = game.active_mark
                    session.update(message='Drawing the player mark, then waiting for camera confirmation.')
                    timing.emit('player_draw_begin', job=job['job'])
                    if kind == 'game_handwriting':
                        strokes = real_handwriting_strokes(job['strokes'], actions.width, actions.height)
                        client.park('clear')
                        checkpoint('drawing')
                        client.command(kind='canvas', strokes=strokes, speed=.45)
                    else:
                        checkpoint('drawing')
                        center = game.game.cell_center(request['row'], request['col'])
                        if mark == 'X':
                            actions.draw_x(center, game.game.cell_size*.55)
                        else:
                            actions.draw_o(center, game.game.cell_size*.25)
                    checkpoint('returning_to_zero')
                    if kind == 'game_handwriting' or game.opponent == 'human':
                        client.park('zero')
                    checkpoint('camera_confirmation')
                    timing.emit('player_draw_complete', job=job['job'])
                    session.update(message='Drawing completed; waiting for three consistent camera frames')
                    deadline = time.monotonic()+45
                    found = None
                    while time.monotonic() < deadline and not session.stop.is_set():
                        found = observe()
                        if found:
                            break
                        session.shutdown.wait(.05)
                    if found is None:
                        raise RuntimeError('Camera has not confirmed one unique new mark, Inspect the board before continuing')
                    if kind == 'game_handwriting':
                        verify_handwriting_cell(job['strokes'], found, game.game.rows)
                        verify_handwriting_shape(job['strokes'], game.game.width, game.game.height)
                    register(found, job['job'])
                else:
                    raise ValueError('Unsupported real game operation')
                pending_turn = None
                checkpoint('completed')
                session.update(state='ready', busy=False, message='Operation completed')
            except Exception as error:
                if ((kind == 'game_start' or (kind == 'game_resume' and pending_turn
                        and pending_turn.get('kind') == 'grid')) and game.game is not None
                        and getattr(client, 'last_command_kind', None) == 'canvas'):
                    try:
                        actual = client.get('status', timeout=3)
                        paths = (pending_turn['remaining_strokes'] if pending_turn else
                            actions.grid_strokes(game.game.center, game.game.width, game.game.height,
                                                 game.game.rows, game.game.columns))
                        tail, completed = unstarted_grid_tail(paths, actual, client.last_command_job)
                        pending_turn = dict(kind='grid', original_job=job['job'], stage='grid_remaining',
                            strokes=None, remaining_strokes=tail, completed_grid_strokes=completed,
                            board=[row[:] for row in session.status()['game']['board']], available=True)
                    except Exception as grid_error:
                        session.update(grid_recovery_error=str(grid_error))
                        if pending_turn is not None:
                            pending_turn['stage'] = 'committing'
                if pending_turn is not None:
                    pending_turn['available'] = (pending_turn['stage'] != 'committing'
                        and session.status()['game']['board'] == pending_turn['board'])
                    pending_turn['error'] = str(error)
                    try:
                        actual = client.get('status', timeout=3)
                        pending_turn['motion_checkpoint'] = {key:actual.get(key) for key in
                            ('job', 'state', 'busy', 'fresh', 'pose', 'last_stop',
                             'drawing_progress', 'feedback_recovery')}
                    except Exception as observation_error:
                        pending_turn['observation_error'] = str(observation_error)
                    checkpoint(pending_turn['stage'])
                if game.game is not None:
                    game.block(job['job'])
                session.update(state='blocked', busy=False, message=str(error))
            finally:
                state = session.status()
                (session.output/f'job-{job["job"]}.json').write_text(
                    json.dumps(state, ensure_ascii=False, indent=2))
                timing.emit('job_complete', job=job['job'], state=state['state'])
                session.jobs.task_done()
    finally:
        camera_thread.join(timeout=18)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workstation-url', required=True)
    parser.add_argument('--weights', required=True)
    parser.add_argument('--nine-weights', help='Optional detector fine-tuned for native 9x9 crops')
    parser.add_argument('--grid-points', required=True)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--output', required=True)
    parser.add_argument('--restore-game')
    parser.add_argument('--port', type=int, default=8775)
    parser.add_argument('--cpu-threads', type=int, default=2)
    args = parser.parse_args()
    if args.device == 'cpu':
        if args.cpu_threads < 1:
            raise ValueError('CPU threads must be positive')
        import torch
        torch.set_num_threads(args.cpu_threads)
    points = json.loads(Path(args.grid_points).read_text())
    preview = RealBoardPerception(args.weights, points, device=args.device, nine_weights=args.nine_weights)
    if not preview.weights.is_file():
        raise ValueError('YOLO weights are missing')
    Path(args.output).expanduser().mkdir(parents=True, exist_ok=True)
    (Path(args.output).expanduser()/'grid_points.json').write_text(json.dumps(points))
    session = CanvasSession(args.output, partial(real_game_worker,
        url=args.workstation_url, perception=preview, restore=args.restore_game),
        vision_available=True, environment='real')
    session.workstation_url = args.workstation_url
    import yaml
    from ament_index_python.packages import get_package_share_directory
    profile = yaml.safe_load((Path(get_package_share_directory('tictactoe_motion'))/'config/board_real.yaml').read_text())
    corners = profile['safe_corners']
    session.width_mm = (max(p[0] for p in corners)-min(p[0] for p in corners))*1000
    session.height_mm = (max(p[1] for p in corners)-min(p[1] for p in corners))*1000
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(session, preview))
    thread = threading.Thread(target=session.run, daemon=True)
    thread.start()
    def stop(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f'REAL_GAME_GUI http://localhost:{args.port}/game', flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:
        session.stop.set()
    finally:
        session.shutdown.set()
        thread.join(timeout=25)
        server.server_close()


if __name__ == '__main__':
    main()
