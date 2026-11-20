"""Reuse the real workstation queue from local game and vision clients."""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
import requests

class Workstation:
    """Use verified workstation jobs and preserve every submitted operation."""
    def __init__(self, url, output, *, cancelled=lambda: False, progress=lambda state: None, timing=lambda event, **fields: None):
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
        self.timing = timing

    def get(self, route, *, timeout=15):
        r = self.http.get(self.url + 'api/' + route, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def diagnostic(self, stage, state=None, error=None):
        """Record readiness evidence without credentials or motion payloads."""
        record = dict(time=time.time(), stage=stage)
        if state is not None:
            record.update({key: state.get(key) for key in
                           ('state', 'busy', 'fresh', 'job', 'message', 'last_stop')})
        if error is not None:
            record['error'] = str(error)
        with (self.output/'connection_events.jsonl').open('a') as stream:
            stream.write(json.dumps(record, ensure_ascii=False)+'\n')

    def wait_ready(self, timeout=5.0):
        """Wait only for transient stale feedback before submitting a new command."""
        deadline = time.monotonic()+timeout
        initial_job = None
        while True:
            if self.cancelled():
                raise RuntimeError('Operation cancelled before submission')
            try:
                state = self.get('status', timeout=min(2.0, max(.1, deadline-time.monotonic())))
            except (requests.Timeout, requests.ConnectionError) as error:
                self.diagnostic('preflight_status_unavailable', error=error)
                if time.monotonic() >= deadline:
                    raise RuntimeError('Workstation status unavailable; no command sent') from error
                time.sleep(.25)
                continue
            if initial_job is None:
                initial_job = state['job']
            if state['busy'] or state['state'] != 'ready' or state['job'] != initial_job:
                self.diagnostic('preflight_rejected', state)
                raise RuntimeError('Workstation not ready: '+json.dumps(
                    {key:state.get(key) for key in ('state','busy','fresh','job','message')}))
            if state['fresh']:
                return state
            self.diagnostic('waiting_for_fresh_feedback', state)
            if time.monotonic() >= deadline:
                raise RuntimeError('Feedback remained stale before submission; no command sent')
            self.progress(dict(state, message='Waiting for fresh robot feedback before submission'))
            time.sleep(.25)

    def command(self, **command):
        if self.cancelled():
            raise RuntimeError('Operation cancelled')
        timing = getattr(self, 'timing', lambda event, **fields: None)
        started = time.monotonic()
        timing('command_begin', kind=command['kind'])
        self.wait_ready()
        timing('preflight_complete', kind=command['kind'])
        response = self.http.post(self.url + ('api/canvas' if command['kind'] == 'canvas' else 'api/command'), json=command,
                                  headers={'Origin': urlsplit(self.url).scheme + '://' + urlsplit(self.url).netloc,
                                           'X-Workbench-Token': self.token}, timeout=20)
        if response.status_code >= 400:
            raise RuntimeError(f'Workstation rejected command: {response.text}')
        job = response.json()['job']
        timing('command_accepted', job=job, kind=command['kind'])
        print('JOB', job, command['kind'], flush=True)
        previous_stage = None
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                state = self.get('status')
            except (requests.Timeout, requests.ConnectionError) as error:
                # The job was accepted: retry only status reads, never the POST.
                self.diagnostic('accepted_job_status_unavailable', error=error)
                if self.cancelled():
                    self.stop()
                    raise RuntimeError('Stop requested while status was unavailable')
                time.sleep(.5)
                continue
            self.progress(state)
            stage = state.get('message')
            if stage != previous_stage:
                timing('motion_stage', job=job, kind=command['kind'], stage=stage)
                previous_stage = stage
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
                timing('command_complete', job=job, kind=command['kind'], seconds=record['seconds'])
                print('DONE', job, round(record['seconds'], 2), state['message'], flush=True)
                return state
            time.sleep(.1)
        raise TimeoutError('Job did not finish within 300 seconds')

    def stop(self):
        origin = urlsplit(self.url)
        response = self.http.post(self.url+'api/stop', json={}, headers={
            'Origin': origin.scheme+'://'+origin.netloc, 'X-Workbench-Token': self.token}, timeout=10)
        response.raise_for_status()

    def park(self, name='clear'):
        getattr(self, 'timing', lambda *a, **k: None)('park_begin', name=name)
        state = self.command(kind='preset', name=name, speed=1.)
        if not state.get('plan'):
            raise RuntimeError('No verified preset plan')
        self.command(kind='execute')
        getattr(self, 'timing', lambda *a, **k: None)('park_complete', name=name)

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

