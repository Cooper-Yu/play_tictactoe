"""Check transient feedback recovery without replaying robot commands."""
from types import SimpleNamespace
import requests
import pytest
from tictactoe_gui.workstation_client import Workstation


def client(tmp_path, monkeypatch, states):
    c = Workstation.__new__(Workstation)
    c.output = tmp_path
    c.url = 'http://localhost/'
    c.token = 'test'
    c.cancelled = lambda: False
    c.progress = lambda state: None
    values = iter(states)
    def get(route, **kwargs):
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return value
    c.get = get
    c.posts = []
    def post(*args, **kwargs):
        c.posts.append((args, kwargs))
        return SimpleNamespace(status_code=202, json=lambda: {'job': 1})
    c.http = SimpleNamespace(post=post)
    monkeypatch.setattr('tictactoe_gui.workstation_client.time.sleep', lambda _: None)
    return c


def status(*, fresh=True, busy=False, job=0):
    return dict(state='ready', fresh=fresh, busy=busy, job=job,
                message='Operation completed')


def test_stale_feedback_recovers_before_single_submission(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch,
               [status(fresh=False), status(), status(job=1)])
    c.command(kind='execute')
    assert len(c.posts) == 1
    assert 'waiting_for_fresh_feedback' in (tmp_path/'connection_events.jsonl').read_text()


@pytest.mark.parametrize('returned', [True, False])
def test_canvas_completion_requires_return_to_clear(tmp_path, monkeypatch, returned):
    final = dict(status(job=1),
                 message='Drawing completed; returned to clear. Check the actual ink.',
                 drawing_result=dict(motion_completed=True, returned_to_clear=returned))
    c = client(tmp_path, monkeypatch, [status(), final])
    if returned:
        assert c.command(kind='canvas', strokes=[], speed=.45) is final
    else:
        with pytest.raises(RuntimeError, match='return to clear must both complete'):
            c.command(kind='canvas', strokes=[], speed=.45)
    assert len(c.posts) == 1


def test_persistent_stale_feedback_sends_nothing(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, [status(fresh=False)])
    with pytest.raises(RuntimeError, match='no command sent'):
        c.wait_ready(timeout=0)
    assert not c.posts


def test_other_operator_or_busy_state_is_not_retried(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, [status(busy=True)])
    with pytest.raises(RuntimeError, match='"busy": true'):
        c.command(kind='execute')
    assert not c.posts


def test_accepted_job_status_timeout_never_replays_post(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch,
               [status(), requests.Timeout('temporary read timeout'), status(job=1)])
    c.command(kind='execute')
    assert len(c.posts) == 1
    assert 'accepted_job_status_unavailable' in (tmp_path/'connection_events.jsonl').read_text()


def test_unknown_post_result_is_not_retried(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, [status()])
    def post(*args, **kwargs):
        c.posts.append(args)
        raise requests.Timeout('unknown submission outcome')
    c.http.post = post
    with pytest.raises(requests.Timeout):
        c.command(kind='execute')
    assert len(c.posts) == 1

def test_preflight_read_timeout_can_recover_without_motion_replay(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch,
               [requests.Timeout('temporary read timeout'), status(), status(job=1)])
    c.command(kind='execute')
    assert len(c.posts) == 1
    assert 'preflight_status_unavailable' in (tmp_path/'connection_events.jsonl').read_text()
