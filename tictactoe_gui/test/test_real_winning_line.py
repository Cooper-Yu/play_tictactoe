"""Run real-worker input paths against camera/motion doubles, never a robot."""
import json
import math
import threading
import time
from types import SimpleNamespace

import pytest

from tictactoe_gui import real_game
from tictactoe_gui.server import CanvasSession


@pytest.mark.parametrize('source', ['vision', 'handwriting', 'physical', 'physical_stop'])
def test_real_worker_draws_winner_once_after_confirmed_final_move(monkeypatch, tmp_path, source):
    world = SimpleNamespace(cells={}, sequence=0, target=None, lines=[])

    class Response:
        content = b'camera'
        def raise_for_status(self):
            pass
        def json(self):
            world.sequence += 1
            return dict(camera=dict(sequence=world.sequence, fresh=True, age_s=0), fresh=True)

    class HTTP:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, *args, **kwargs):
            return Response()

    class Client:
        def __init__(self, *args, **kwargs):
            self.url = 'http://fixture/'
        def command(self, **kwargs):
            assert kwargs['kind'] == 'reset'
        def park(self, *args):
            pass

    class Actions:
        width, height = .144, .193
        def __init__(self, client, **kwargs):
            pass
        def grid_strokes(self, *args):
            pass
        x_strokes = o_strokes = grid_strokes
        def draw_grid(self, *args, **kwargs):
            return {'passed': True}
        def prepare_draw(self):
            pass
        def run_canvas(self, strokes):
            world.cells[world.target] = frozenset(('X' if len(strokes) == 2 else 'O',))
        def draw_x(self, *args, **kwargs):
            world.cells[world.target] = frozenset(('X',))
        def draw_o(self, *args, **kwargs):
            world.cells[world.target] = frozenset(('O',))
        def draw(self, strokes, **kwargs):
            state = session.status()
            assert state['game']['winner'] == 'X'
            assert state['game']['board'][0] == ['X', 'X', 'X']
            assert state['vision']['consecutive'] == 3
            world.lines.append(strokes)
            return {'passed': True}

    class Perception:
        def detect_cells(self, image, size=3):
            return dict(world.cells)

    monkeypatch.setattr(real_game.requests, 'Session', HTTP)
    monkeypatch.setattr(real_game, 'Workstation', Client)
    monkeypatch.setattr(real_game, 'RemoteDrawing', Actions)
    session = CanvasSession(tmp_path, None, environment='real', vision_available=True)
    worker = threading.Thread(target=real_game.real_game_worker, args=(session,),
                              kwargs=dict(url='http://fixture/', perception=Perception()), daemon=True)

    def wait(predicate):
        deadline = time.monotonic()+6
        while not predicate():
            assert time.monotonic() < deadline, session.status()
            time.sleep(.01)

    worker.start()
    try:
        wait(lambda: session.status()['state'] == 'ready')
        actual_source = 'physical' if source.startswith('physical') else source
        session.submit('game_start', game_request=dict(size=3, input_source=actual_source, opponent='human'))
        wait(lambda: not session.status()['busy'])
        for turn, (row, col) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1), (0, 2))):
            world.target = row, col
            mark = 'X' if turn % 2 == 0 else 'O'
            revision = session.status()['game']['revision']
            if actual_source == 'physical':
                world.cells[world.target] = frozenset((mark,))
                if turn == 4:
                    wait(lambda: session.status().get('reply_countdown') == 2)
                    assert not world.lines
                    if source == 'physical_stop':
                        session.request_stop()
                        wait(lambda: not session.status()['busy'])
                        assert not world.lines and session.status()['state'] == 'blocked'
                        return
            elif source == 'handwriting':
                u, v = (col+.5)/3, (row+.5)/3
                d = .04
                strokes = ([[[u-d, v-d], [u+d, v+d]], [[u-d, v+d], [u+d, v-d]]]
                           if mark == 'X' else [[[u+d*math.cos(i*math.pi/32),
                                                 v+d*math.sin(i*math.pi/32)] for i in range(65)]])
                session.submit('game_handwriting', strokes, dict(revision=revision))
            else:
                session.submit('game_vision_move', game_request=dict(row=row, col=col, revision=revision))
            wait(lambda: session.status()['game']['board'][row][col] == mark
                 and not session.status()['busy'])
            assert session.status()['state'] == 'ready', session.status()
        state = session.status()['game']
        assert state['phase'] == 'finished' and state['winning_line']['status'] == 'completed'
        assert state['winning_cells'] == [(0, 0), (0, 1), (0, 2)]
        assert len(world.lines) == 1
        saved = json.loads((tmp_path/'winning-line.json').read_text())
        assert saved['winning_line']['status'] == 'completed'
        time.sleep(.3)
        assert len(world.lines) == 1
    finally:
        session.shutdown.set()
        worker.join(timeout=3)


@pytest.mark.parametrize('line_status', ['completed', 'failed'])
def test_restored_terminal_line_is_display_only_and_never_replayed(monkeypatch, tmp_path, line_status):
    saved = tmp_path/'saved.json'
    saved.write_text(json.dumps({'game': dict(phase='finished', input_source='vision', size=3,
        board=[['X', 'X', 'X'], ['O', 'O', ''], ['', '', '']], winner='X',
        winning_line=dict(status=line_status, cells=[[0, 0], [0, 1], [0, 2]]))}))
    session = CanvasSession(tmp_path/'output', None, environment='real', vision_available=True)
    session.publish_camera(b'camera')
    class Client:
        def __init__(self, url, *args, **kwargs):
            self.url = url
    class HTTP:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, *args, **kwargs):
            raise RuntimeError('Fixture camera unavailable')
    monkeypatch.setattr(real_game, 'Workstation', Client)
    monkeypatch.setattr(real_game, 'RemoteDrawing', lambda *a, **k: object())
    monkeypatch.setattr(real_game.requests, 'Session', HTTP)
    perception = SimpleNamespace(detect_cells=lambda *a, **k: {})
    original_update = session.update
    def update(**changes):
        original_update(**changes)
        if changes.get('state') == 'ready':
            session.shutdown.set()
    session.update = update
    real_game.real_game_worker(session, url='http://fixture/', perception=perception, restore=saved)
    assert session.status()['game']['winning_line']['status'] == line_status
    assert session.status()['state'] == 'ready'
