"""Check cloud proxy routing and preserve the workstation request protections."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from tictactoe_gui.cloud_gateway import make_gateway
from tictactoe_gui.workbench import WorkbenchSession, make_handler


def test_cloud_gateway_keeps_origin_token_and_readiness_checks(tmp_path):
    session = WorkbenchSession(tmp_path, 'real')
    backend = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(session))
    origin = 'https://test.robotigniteacademy.com'
    gateway = ThreadingHTTPServer(('127.0.0.1', 0),
        make_gateway(origin+'/slot/webpage/', backend.server_port))
    threads = [threading.Thread(target=s.serve_forever, daemon=True)
               for s in (backend, gateway)]
    for thread in threads:
        thread.start()
    base = f'http://127.0.0.1:{gateway.server_port}'
    def post(path, token, source):
        return urlopen(Request(base+path, data=b'{}', headers={
            'Origin':source, 'X-Workbench-Token':token}))
    try:
        with urlopen(base+'/api/status') as response:
            assert json.load(response)['environment'] == 'real'
        with urlopen(base+'/') as response:
            html = response.read().decode()
            assert 'src="workbench.js"' in html
        for token, source in [('', origin), (session.token, 'https://evil.invalid')]:
            with pytest.raises(HTTPError) as error:
                post('/api/stop', token, source)
            assert error.value.code == 403
        assert not session.stop.is_set()
        with post('/api/stop', session.token, origin) as response:
            assert response.status == 202
        assert session.stop.is_set()
        with pytest.raises(HTTPError) as error:
            urlopen(base+'/../../private')
        assert error.value.code == 404
    finally:
        for server in (gateway, backend):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()


@pytest.mark.parametrize('url', ['http://test.robotigniteacademy.com/slot/webpage/',
    'https://evil.invalid/slot/webpage/', 'https://test.robotigniteacademy.com/',
    'https://test.robotigniteacademy.com/slot/webpage/?token=x'])
def test_gateway_rejects_unexpected_public_url(url):
    with pytest.raises(ValueError):
        make_gateway(url)

def test_cloud_game_namespace_keeps_workbench_and_game_separate(tmp_path):
    from tictactoe_gui.server import CanvasSession, make_handler as game_handler
    work = WorkbenchSession(tmp_path/'work', 'real')
    game = CanvasSession(tmp_path/'game', None, environment='real', vision_available=True)
    game.update(state='ready')
    game.workstation_url = 'http://127.0.0.1:8765/'
    game.width_mm, game.height_mm = 140, 189
    backend = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(work))
    games = ThreadingHTTPServer(('127.0.0.1', 0), game_handler(game))
    origin = 'https://test.robotigniteacademy.com'
    gateway = ThreadingHTTPServer(('127.0.0.1', 0),
        make_gateway(origin+'/slot/webpage/', backend.server_port, games.server_port))
    servers = [backend, games, gateway]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    base = f'http://127.0.0.1:{gateway.server_port}'
    try:
        with urlopen(base+'/game/') as response:
            assert b'Robot board games' in response.read()
        with urlopen(base+'/game/game.js') as response:
            assert b'gameMount' in response.read()
        with urlopen(base+'/game/api/config') as response:
            config = json.load(response)
            assert config['workstation_url'] == origin+'/slot/webpage/'
        with urlopen(base+'/api/config') as response:
            assert json.load(response)['token'] == work.token
        game.update(state='ready', game=dict(size=3,phase='player',revision=7,
                    input_source='handwriting',board=[['']*3 for _ in range(3)]))
        points=[[.1+i*.0002,.1+i*.0002] for i in range(500)]
        body=json.dumps({'revision':7,'strokes':[points]}).encode()
        assert len(body)>4096
        headers={'Origin':origin,'X-Canvas-Token':game.token}
        with urlopen(Request(base+'/game/api/game/handwriting',data=body,headers=headers)) as response:
            assert response.status==202
        queued=game.jobs.get_nowait()
        assert queued['kind']=='game_handwriting' and queued['strokes']==[points]
        assert not any(any(row) for row in game.status()['game']['board'])
        game.update(busy=True)
        headers = {'Origin':origin, 'X-Canvas-Token':game.token}
        with urlopen(Request(base+'/game/api/stop', data=b'{}', headers=headers)) as response:
            assert response.status == 202
        assert game.stop.is_set()
        assert not work.stop.is_set()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base+'/game/api/stop', data=b'{}',
                    headers={'Origin':'https://evil.invalid', 'X-Canvas-Token':game.token}))
        assert error.value.code == 403
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()