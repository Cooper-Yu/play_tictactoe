"""Reuse the real workstation queue from local game and vision clients."""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
import requests

class Workstation:
    """Use verified workstation jobs and preserve every submitted operation."""
    def __init__(self, url, output, *, cancelled=lambda: False, progress=lambda state: None):
        self.url = url.rstrip('/') + '/'
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.http = requests.Session()
        config = self.get('config')
        if config['environment'] != 'real':
            raise ValueError('Expected real workstation')
        self.token = config['token']
        self.cancelled = cancelled
        self.progress = progress

    def get(self, route):
        r = self.http.get(self.url + 'api/' + route, timeout=15)
        r.raise_for_status()
        return r.json()

    def command(self, **command):
        if self.cancelled():
            raise RuntimeError('Operation cancelled')
        state = self.get('status')
        if state['busy'] or not state['fresh'] or state['state'] != 'ready':
            raise RuntimeError('Workstation not ready: ' + state['message'])
        started = time.monotonic()
        response = self.http.post(self.url + ('api/canvas' if command['kind'] == 'canvas' else 'api/command'), json=command,
                                  headers={'Origin': urlsplit(self.url).scheme + '://' + urlsplit(self.url).netloc,
                                           'X-Workbench-Token': self.token}, timeout=20)
        if response.status_code >= 400:
            raise RuntimeError(f'Workstation rejected command: {response.text}')
        job = response.json()['job']
        print('JOB', job, command['kind'], flush=True)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            state = self.get('status')
            self.progress(state)
            if self.cancelled():
                self.stop()
                raise RuntimeError('Stop requested; check workstation settling state')
            if state['job'] != job:
                raise RuntimeError('Another operator changed the active job')
            if not state['busy']:
                record = dict(command=command, seconds=time.monotonic()-started, state=state)
                (self.output/f'job-{job}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
                if state['state'] != 'ready' or state.get('last_stop', {}).get('job') == job:
                    raise RuntimeError(state['message'])
                expected = {'canvas': 'Drawing motion completed; pen raised. Check the actual ink.',
                            'preset': 'Operation completed', 'execute': 'Operation completed',
                            'reset': 'Reset completed; returned to clearance pose. Confirm that the board is clear.'}
                if state['message'] != expected[command['kind']]:
                    raise RuntimeError(state['message'])
                if command['kind'] == 'canvas' and not state.get('drawing_result', {}).get('motion_completed'):
                    raise RuntimeError(state['message'])
                if command['kind'] == 'preset' and not state.get('plan'):
                    raise RuntimeError(state['message'])
                print('DONE', job, round(record['seconds'], 2), state['message'], flush=True)
                return state
            time.sleep(.5)
        raise TimeoutError('Job did not finish within 300 seconds')

    def stop(self):
        origin = urlsplit(self.url)
        response = self.http.post(self.url+'api/stop', json={}, headers={
            'Origin': origin.scheme+'://'+origin.netloc, 'X-Workbench-Token': self.token}, timeout=10)
        response.raise_for_status()

    def park(self, name='clear'):
        state = self.command(kind='preset', name=name, speed=1.)
        if not state.get('plan'):
            raise RuntimeError('No verified preset plan')
        self.command(kind='execute')

    def frame(self, name):
        state = self.get('status')
        if not state['camera'].get('fresh'):
            raise RuntimeError('Camera is stale')
        response = self.http.get(self.url+'api/frame', timeout=15)
        response.raise_for_status()
        path = self.output/name
        path.write_bytes(response.content)
        return path, state['camera']['sequence']

class RemoteDrawing:
    """Compose existing drawing geometry with the real workstation execution queue."""
    def __init__(self, client):
        import yaml
        from tictactoe_motion.canvas.board_canvas import BoardCanvas
        from tictactoe_motion.actions.drawing_actions import DrawingActions
        from ament_index_python.packages import get_package_share_directory
        root = Path(get_package_share_directory('tictactoe_motion'))
        self.geometry = DrawingActions(BoardCanvas(yaml.safe_load(
            (root/'config/board_real.yaml').read_text())))
        self.width, self.height = self.geometry.width, self.geometry.height
        self.client = client

    def grid_strokes(self, *args, **kwargs):
        return self.geometry.grid_strokes(*args, **kwargs)

    def x_strokes(self, *args, **kwargs):
        return self.geometry.x_strokes(*args, **kwargs)

    def o_strokes(self, *args, **kwargs):
        return self.geometry.o_strokes(*args, **kwargs)

    def draw(self, strokes, **options):
        self.client.command(kind='canvas', strokes=strokes, speed=1.)
        self.client.park()
        return {'passed': True}

    def draw_grid(self, center, width, height, **options):
        return self.draw(self.geometry.grid_strokes(center, width, height,
                         rows=options['rows'], columns=options['columns']))

    def draw_x(self, center, size, **options):
        return self.draw(self.geometry.x_strokes(center, size))

    def draw_o(self, center, radius, **options):
        return self.draw(self.geometry.o_strokes(center, radius))

