"""Exercise workstation request boundaries, image enhancement and HTTP protection."""
import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import cv2
import numpy as np
import pytest

from tictactoe_gui.workbench import WorkbenchSession, enhance_frame, make_handler, validate_command


@pytest.mark.parametrize('value', [0, .021, -.021, float('nan'), float('inf'), True, '0.001'])
def test_invalid_jog(value):
    with pytest.raises(ValueError):
        validate_command(dict(kind='jog', axis='x', distance=value))


@pytest.mark.parametrize('speed', [0, .31, float('nan'), True, '0.1'])
def test_invalid_speed(speed):
    with pytest.raises(ValueError):
        validate_command(dict(kind='preset', name='clear', speed=speed))


def test_jog_and_busy_stop(tmp_path):
    session = WorkbenchSession(tmp_path)
    session.update(state='ready')
    session.submit(dict(kind='jog', axis='z', distance=-.001))
    assert session.jobs.get_nowait()['distance'] == -.001
    with pytest.raises(RuntimeError):
        session.submit(dict(kind='record', name='Reset'))
    session.request_stop()
    assert session.stop.is_set()
    session.update(busy=False)
    with pytest.raises(RuntimeError):
        session.submit(dict(kind='record', name='Reset'))


def test_real_commands_retain_small_step_and_speed_limits(tmp_path):
    session = WorkbenchSession(tmp_path, environment='real')
    assert session.status()['environment'] == 'real'
    assert validate_command(dict(kind='jog', axis='x', distance=.05, speed=.1), 'real')['distance'] == .05
    for command in [dict(kind='jog', axis='z', distance=.05), dict(kind='jog', axis='x', distance=.051), dict(kind='preset', name='clear', speed=1.01)]:
        with pytest.raises(ValueError):
            validate_command(command, 'real')


def test_image_crop_and_brightness():
    raw = np.full((40, 60, 3), 100, np.uint8)
    _, encoded = cv2.imencode('.jpg', raw)
    result = enhance_frame(encoded.tobytes(), {'beta':['25'], 'roi':['0.25,0.25,0.5,0.5']})
    decoded = cv2.imdecode(np.frombuffer(result, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (20, 30, 3)
    assert abs(float(decoded.mean())-125) < 2
    result = enhance_frame(encoded.tobytes(), {'beta':['-255']})
    assert cv2.imdecode(np.frombuffer(result, np.uint8), cv2.IMREAD_COLOR).max() == 0
    for roi in ('0,0,0,0', '0.9,0,0.5,0.5', 'nan,0,1,1', '0,0,0.001,0.001'):
        with pytest.raises(ValueError):
            enhance_frame(encoded.tobytes(), {'beta':['0'], 'roi':[roi]})


def test_http_requires_token_and_preserves_ack_result_boundary(tmp_path):
    session = WorkbenchSession(tmp_path)
    session.update(state='ready')
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(session))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def post(token, origin=None):
        headers = {'Content-Type':'application/json', 'X-Workbench-Token':token}
        if origin:
            headers['Origin'] = origin
        return urlopen(Request(base+'/api/command', data=b'{"kind":"preset","name":"clear"}', headers=headers))
    try:
        for token, origin in [('', None), (session.token, 'http://other.invalid')]:
            with pytest.raises(HTTPError) as error:
                post(token, origin)
            assert error.value.code == 403
        with post(session.token) as response:
            assert response.status == 202
            assert json.load(response)['accepted']
        assert session.status()['busy']
        assert session.status()['comparison'] is None
        with urlopen(base+'/') as response:
            assert 'Robot calibration workbench' in response.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('shape', ['smile', 'docker', 'chair'])
def test_real_illustrations_keep_existing_motion_boundary(shape):
    command = dict(kind='draw', shape=shape, size=.05, center=[.5,.5], speed=.1)
    assert validate_command(command, 'real')['shape'] == shape
    with pytest.raises(ValueError): validate_command(command, 'sim')
    with pytest.raises(ValueError): validate_command(dict(command, size=.061), 'real')
    with pytest.raises(ValueError): validate_command(dict(command, speed=1.01), 'real')
    with pytest.raises(ValueError): validate_command(dict(command, shape='../chair'), 'real')


@pytest.mark.parametrize('skip', [True, -1, 256, 1.5, '6'])
def test_illustration_resume_rejects_invalid_index(skip):
    with pytest.raises(ValueError):
        validate_command(dict(kind='draw',shape='smile',skip_strokes=skip), 'real')


def test_explicit_resume_is_limited_to_named_illustrations():
    assert validate_command(dict(kind='draw',shape='smile',skip_strokes=6), 'real')['skip_strokes']==6
    with pytest.raises(ValueError):
        validate_command(dict(kind='draw',shape='x',skip_strokes=1), 'real')


def test_http_recovery_acknowledges_without_submitting_motion(tmp_path):
    session = WorkbenchSession(tmp_path, 'real')
    session.update(job=3, fresh=True, state='running', busy=True)
    session.request_stop('joint stream expired', 'feedback_guard')
    session.finish_stop()
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(session))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    headers = {'Origin': base, 'X-Workbench-Token': session.token,
               'Content-Type': 'application/json'}

    def post(command):
        return urlopen(Request(base+'/api/command', data=json.dumps(command).encode(),
                               headers=headers), timeout=2)

    def status():
        with urlopen(base+'/api/status', timeout=2) as response:
            return json.load(response)

    try:
        ack = {'kind': 'acknowledge_recovery', 'job': 3}
        with pytest.raises(HTTPError) as error:
            post(ack)
        assert error.value.code == 409
        assert status()['feedback_recovery']['phase'] == 'waiting'
        now = time.monotonic()
        for i in range(23):
            sample_time = now - 2.2 + i*.1
            sample = (sample_time, sample_time), (0.,)*6
            session.observe_recovery(sample_time, True, sample, .0001)
        assert status()['feedback_recovery']['phase'] == 'confirmation'
        with post(ack) as response:
            assert response.status == 202
            assert json.load(response)['job'] == 3
        assert status()['state'] == 'ready'
        assert status()['plan'] is None and session.jobs.empty()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
