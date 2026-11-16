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