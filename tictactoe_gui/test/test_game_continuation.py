"""Preserve an interrupted physical turn without replaying its drawing request."""
import json
import threading
import time
from types import SimpleNamespace

import pytest
from tictactoe_gui import real_game
from tictactoe_gui.server import CanvasSession
from tictactoe_gui.workstation_client import Workstation


@pytest.mark.parametrize('visible', [False, True])
def test_inspected_resume_preserves_turn_and_never_replays_canvas(monkeypatch, tmp_path, visible):
    world = SimpleNamespace(sequence=0, cells={}, canvas_calls=0, parks=[])
    class Response:
        content = b'camera'
        def raise_for_status(self): pass
        def json(self):
            world.sequence += 1
            return dict(camera=dict(sequence=world.sequence, fresh=True, age_s=0), fresh=True)
    class HTTP:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs): return Response()
    class Client:
        def __init__(self, *args, **kwargs): self.url = 'http://test/'
        def park(self, name): world.parks.append(name)
        def command(self, **command):
            if command['kind'] == 'canvas':
                world.canvas_calls += 1
                if visible: world.cells[(0, 0)] = frozenset(('X',))
                raise RuntimeError('Interrupted physical drawing')
        def get(self, *args, **kwargs):
            return dict(state='ready', busy=False, fresh=True, pose={'z': .216}, job=2)
    class Actions:
        width, height = .144, .193
        def __init__(self, client): self.client = client
        def prepare_draw(self): self.client.park('clear')
        def grid_strokes(self, *args): pass
        x_strokes = o_strokes = grid_strokes
        def draw_grid(self, *args, **kwargs): return {'passed': True}
    class Perception:
        def detect_cells(self, *args, **kwargs): return dict(world.cells)
    monkeypatch.setattr(real_game.requests, 'Session', HTTP)
    monkeypatch.setattr(real_game, 'Workstation', Client)
    monkeypatch.setattr(real_game, 'RemoteDrawing', Actions)
    session = CanvasSession(tmp_path, None, environment='real', vision_available=True)
    thread = threading.Thread(target=real_game.real_game_worker, args=(session,),
        kwargs=dict(url='http://test/', perception=Perception()), daemon=True)
    def wait(predicate):
        until = time.monotonic()+5
        while not predicate():
            assert time.monotonic() < until, session.status()
            time.sleep(.01)
    thread.start()
    try:
        wait(lambda: session.status()['state'] == 'ready')
        session.submit('game_start', game_request=dict(size=3, mode='classic',
            input_source='handwriting', opponent='human'))
        wait(lambda: not session.status()['busy'])
        strokes = [[[.1,.1],[.23,.23]], [[.23,.1],[.1,.23]]]
        session.submit('game_handwriting', strokes,
                       dict(revision=session.status()['game']['revision']))
        wait(lambda: session.status()['state'] == 'blocked')
        before = session.status()
        assert before['game']['board'][0][0] == ''
        assert before['continuation']['stage'] == 'drawing'
        assert before['continuation']['available']
        assert json.loads((tmp_path/'turn-recovery.json').read_text())['original_job'] == 2
        request = dict(revision=before['game']['revision'], original_job=2, inspected=True)
        with pytest.raises(RuntimeError):
            session.submit('game_resume', game_request=dict(request, original_job=1))
        with pytest.raises(RuntimeError):
            session.submit('game_resume', game_request=dict(request, inspected=False))
        session.submit('game_resume', game_request=request)
        wait(lambda: session.status()['state'] == 'ready' and not session.status()['busy'])
        if visible:
            wait(lambda: session.status()['game']['board'][0][0] == 'X')
            assert session.status()['game']['turn'] == 'O'
        else:
            assert session.status()['game']['turn'] == 'X'
            assert session.status()['game']['board'][0][0] == ''
        assert world.canvas_calls == 1
        assert world.parks[-1] == 'zero'
        assert session.status()['continuation'] is None
        with pytest.raises(RuntimeError):
            session.submit('game_resume', game_request=request)
    finally:
        session.shutdown.set()
        thread.join(timeout=3)


@pytest.mark.parametrize('low_clearance', [False, True])
def test_preset_feedback_recovery_replans_instead_of_replaying(low_clearance, tmp_path):
    client = Workstation.__new__(Workstation)
    client.output = tmp_path
    calls = []
    def command(**value):
        calls.append(value['kind'])
        client.last_command_job = len(calls)
        if len(calls) == 2: raise RuntimeError('Feedback interrupted')
        return dict(plan={'verified':True})
    client.command = command
    client.get = lambda *a, **k: dict(job=2, last_stop=dict(job=2, source='feedback_guard'))
    client.recover_feedback = lambda: dict(pose={'z':.206 if low_clearance else .216})
    if low_clearance:
        with pytest.raises(RuntimeError, match='below clearance'): client.park('zero')
        assert calls == ['preset', 'execute']
    else:
        client.park('zero')
        assert calls == ['preset', 'execute', 'preset', 'execute']


def test_old_feedback_stop_cannot_authorize_retry_of_new_failure(tmp_path):
    client = Workstation.__new__(Workstation)
    client.output = tmp_path
    client.last_command_job = 4
    client.command = lambda **kw: (_ for _ in ()).throw(RuntimeError('New planning failure'))
    client.get = lambda *a, **k: dict(job=4, last_stop=dict(job=2, source='feedback_guard'))
    client.recover_feedback = lambda: pytest.fail('Reused an unrelated old stop')
    with pytest.raises(RuntimeError, match='New planning failure'): client.park('zero')


def test_feedback_ack_requires_matching_terminal_stationary_job(tmp_path):
    client = Workstation.__new__(Workstation)
    client.output, client.url, client.token = tmp_path, 'http://localhost/', 'test'
    client.cancelled = lambda: False
    client.progress = lambda state: None
    stopped = dict(job=8, state='recovering', busy=False, fresh=True,
        last_stop=dict(job=8, source='feedback_guard'), feedback_recovery=dict(phase='confirmation'))
    ready = dict(stopped, state='ready', feedback_recovery=None)
    states = iter([stopped, ready])
    client.get = lambda *a, **k: next(states)
    posts = []
    def post(*a, **k):
        posts.append(k['json'])
        return SimpleNamespace(raise_for_status=lambda: None)
    client.http = SimpleNamespace(post=post)
    assert client.recover_feedback()['state'] == 'ready'
    assert posts == [dict(kind='acknowledge_recovery', job=8)]


@pytest.mark.parametrize('source,job', [('caller', 8), ('feedback_guard', 9)])
def test_unrelated_stop_or_job_change_never_acknowledged(tmp_path, monkeypatch, source, job):
    client = Workstation.__new__(Workstation)
    client.output = tmp_path
    client.cancelled = lambda: False
    client.progress = lambda state: None
    state = dict(job=job, last_stop=dict(job=8, source=source))
    client.get = lambda *a, **k: state
    client.http = SimpleNamespace(post=lambda *a, **k: pytest.fail('Unsafe acknowledgement'))
    with pytest.raises(RuntimeError): client.recover_feedback()
