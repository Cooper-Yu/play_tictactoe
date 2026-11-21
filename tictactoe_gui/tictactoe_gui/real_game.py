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
from tictactoe_gui.server import CanvasSession, make_handler
from tictactoe_gui.workstation_client import Workstation, RemoteDrawing
from tictactoe_perception.stable_player_move import StablePlayerMove


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

    def observe():
        nonlocal gate, gate_revision
        state = session.status()
        current = state['game']
        if current is None or current['phase'] != 'player':
            return None
        if gate_revision != current['revision']:
            gate = StablePlayerMove(current['board'], current['human'])
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
                if kind == 'reset':
                    client.command(kind='reset', speed=.1)
                    client.park('zero')
                    game.game = None
                    session.update(game=None, vision=None)
                elif kind == 'game_start':
                    client.command(kind='reset', speed=.1)
                    client.park('clear')
                    game.start(request.get('size', 3), job['job'], mode=request.get('mode', 'classic'),
                               first=request.get('first', 'player'),
                               mark=request.get('mark', 'X'), input_source='vision')
                    gate_revision = None
                elif kind == 'game_vision_move':
                    mark = game.player_mark
                    center = game.game.cell_center(request['row'], request['col'])
                    session.update(message='Drawing the player mark, then waiting for camera confirmation.')
                    timing.emit('player_draw_begin', job=job['job'])
                    if mark == 'X':
                        actions.draw_x(center, game.game.cell_size*.55)
                    else:
                        actions.draw_o(center, game.game.cell_size*.25)
                    timing.emit('player_draw_complete', job=job['job'])
                    deadline = time.monotonic()+45
                    found = None
                    while time.monotonic() < deadline and not session.stop.is_set():
                        found = observe()
                        if found:
                            break
                        session.shutdown.wait(.05)
                    if found is None:
                        raise RuntimeError('Camera has not confirmed one unique new mark, Inspect the board before continuing')
                    register(found, job['job'])
                else:
                    raise ValueError('Unsupported real game operation')
                session.update(state='ready', busy=False, message='Operation completed')
            except Exception as error:
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
    preview = RealBoardPerception(args.weights, points, device=args.device)
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
