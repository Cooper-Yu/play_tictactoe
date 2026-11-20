"""Verify real GUI vision turns without sending robot commands."""
import threading
import time
from types import SimpleNamespace

import pytest
from tictactoe_gui.server import CanvasSession
from tictactoe_gui import real_game


def test_real_session_rejects_direct_state_move(tmp_path):
    s = CanvasSession(tmp_path, None, vision_available=True, environment='real')
    s.update(state='ready')
    with pytest.raises(ValueError):
        s.submit('game_move', game_request={'row':0, 'col':0, 'revision':1})
    with pytest.raises(ValueError):
        s.submit('game_start', game_request={'size':3, 'input_source':'click'})


def test_proxy_turn_is_committed_only_after_three_camera_frames(monkeypatch, tmp_path):
    world = SimpleNamespace(cells={}, sequence=0, moves=[], detection_sequences=[])
    class Response:
        content = b'camera'
        def raise_for_status(self):
            pass
        def json(self):
            world.sequence += 1
            return {'camera': {'sequence':world.sequence, 'fresh':True, 'age_s':0}, 'fresh':True}
    class HTTP:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, *args, **kwargs):
            return Response()
    class Client:
        def __init__(self, url, output, **kwargs):
            self.url = url
        def command(self, **kwargs):
            world.moves.append(kwargs['kind'])
        def park(self, *args):
            pass
    class Actions:
        width, height = .144, .193
        def __init__(self, client):
            pass
        def grid_strokes(self, *args):
            pass
        x_strokes = o_strokes = grid_strokes
        def draw_grid(self, *args, **kwargs):
            return {'passed':True}
        def draw_x(self, *args, **kwargs):
            world.cells[(0,0)] = frozenset(('X',))
            return {'passed':True}
        def draw_o(self, *args, **kwargs):
            assert len(set(world.detection_sequences)) >= 3
            world.moves.append('O')
            return {'passed':True}
    class Perception:
        def detect_cells(self, image):
            if world.cells:
                world.detection_sequences.append(world.sequence)
            return dict(world.cells)
    monkeypatch.setattr(real_game.requests, 'Session', HTTP)
    monkeypatch.setattr(real_game, 'Workstation', Client)
    monkeypatch.setattr(real_game, 'RemoteDrawing', Actions)
    s = CanvasSession(tmp_path, None, vision_available=True, environment='real')
    thread = threading.Thread(target=real_game.real_game_worker,
        args=(s,), kwargs={'url':'http://test/', 'perception':Perception()}, daemon=True)
    thread.start()
    def wait(predicate):
        deadline=time.monotonic()+5
        while not predicate():
            assert time.monotonic()<deadline
            time.sleep(.02)
    try:
        wait(lambda:s.status()['state']=='ready')
        s.submit('game_start', game_request={'size':3,'input_source':'vision'})
        wait(lambda:not s.status()['busy'])
        revision=s.status()['game']['revision']
        s.submit('game_vision_move', game_request={'row':0,'col':0,'revision':revision})
        wait(lambda:not s.status()['busy'])
        assert s.status()['state']=='ready', s.status()
        assert s.status()['game']['board'][0][0]=='X'
        assert sum(mark=='O' for row in s.status()['game']['board'] for mark in row)==1
        assert world.moves==['reset','O']
        assert s.status()['vision']['consecutive']==3
    finally:
        s.shutdown.set()
        thread.join(timeout=3)


def test_offline_startup_retains_finished_board_without_motion(monkeypatch, tmp_path):
    import json
    saved = tmp_path/'game.json'
    board = [['X','O','X'],['','O',''],['','O','X']]
    saved.write_text(json.dumps({'game':{'phase':'finished','input_source':'vision','board':board,'size':3}}))
    (tmp_path/'finished.jpg').write_bytes(b'saved-camera')
    s = CanvasSession(tmp_path/'output', None, vision_available=True, environment='real')
    def unavailable(*args, **kwargs):
        s.shutdown.set()
        raise real_game.requests.ConnectionError('offline')
    monkeypatch.setattr(real_game, 'Workstation', unavailable)
    real_game.real_game_worker(s, url='http://test/', perception=None, restore=saved)
    assert s.status()['frame_source']=='saved'
    assert s.status()['game']['board']==board
    assert s.camera_image()==b'saved-camera'
    assert s.status()['state']=='offline'
