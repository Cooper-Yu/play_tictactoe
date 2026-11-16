"""Exercise workstation request boundaries, image enhancement and HTTP protection."""
import json
import threading
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
    assert validate_command(dict(kind='jog', axis='x', distance=.002, speed=.05), 'real')['distance'] == .002
    for command in [dict(kind='jog', axis='x', distance=.005), dict(kind='preset', name='clear', speed=.2)]:
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
            assert '机械臂定位工作台' in response.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
