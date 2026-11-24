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
        self.last_command_job = None
        self.last_command_kind = command['kind']
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
        self.last_command_job = job
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

    def recover_feedback(self, timeout=35.):
        """Wait for terminal execution and stationary fresh feedback; never replay a job."""
        deadline = time.monotonic()+timeout
        stopped_job = None
        while time.monotonic() < deadline:
            if self.cancelled():
                raise RuntimeError('Recovery cancelled; no new motion sent')
            state = self.get('status', timeout=3)
            incident = state.get('last_stop', {})
            if incident.get('source') != 'feedback_guard':
                raise RuntimeError('Only feedback-guard stops can recover automatically')
            if stopped_job is None:
                stopped_job = incident['job']
            if state['job'] != stopped_job or incident['job'] != stopped_job:
                raise RuntimeError('Another operator changed the recovery job')
            recovery = state.get('feedback_recovery') or {}
            if recovery.get('phase') == 'timeout':
                raise RuntimeError('Feedback recovery timed out; inspection is required')
            self.progress(dict(state, message='Waiting for fresh stationary feedback; preserving game progress'))
            if (not state['busy'] and state['fresh'] and state['state'] == 'recovering'
                    and recovery.get('phase') == 'confirmation'):
                origin = urlsplit(self.url)
                response = self.http.post(self.url+'api/command',
                    json={'kind':'acknowledge_recovery', 'job':stopped_job},
                    headers={'Origin':origin.scheme+'://'+origin.netloc,
                             'X-Workbench-Token':self.token}, timeout=10)
                response.raise_for_status()
                checked = self.get('status', timeout=3)
                if (checked['job'] != stopped_job or checked['busy'] or not checked['fresh']
                        or checked['state'] != 'ready' or checked.get('feedback_recovery')):
                    raise RuntimeError('Recovery acknowledgement was not verified')
                self.diagnostic('feedback_recovery_acknowledged', checked)
                return checked
            time.sleep(.2)
        raise TimeoutError('Feedback did not recover; no motion replayed')

    def park(self, name='clear'):
        getattr(self, 'timing', lambda *a, **k: None)('park_begin', name=name)
        for attempt in range(2):
            try:
                state = self.command(kind='preset', name=name, speed=1.)
                if not state.get('plan'):
                    raise RuntimeError('No verified preset plan')
                self.command(kind='execute')
                break
            except RuntimeError:
                if attempt:
                    raise
                state = self.get('status', timeout=3)
                incident = state.get('last_stop', {})
                if (incident.get('source') != 'feedback_guard'
                        or incident.get('job') != getattr(self, 'last_command_job', None)
                        or state['job'] != self.last_command_job):
                    raise
                recovered = self.recover_feedback()
                if not recovered.get('pose') or recovered['pose']['z'] < .2109:
                    raise RuntimeError('Preset recovery is below clearance; inspect and raise the pen first')
                # A new absolute preset plan starts at the actual recovered state.
                # The interrupted trajectory is never sent again.
                self.diagnostic('replanning_absolute_preset_after_feedback', state)
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

def draw_canvas_with_feedback_recovery(client, strokes, speed=.45, *, direct_from_zero=False):
    """Replan once only when feedback stopped the initial suspended approach."""
    command = dict(kind='canvas', strokes=strokes, speed=speed)
    if direct_from_zero:
        command['direct_from_zero'] = True
    try:
        return client.command(**command)
    except RuntimeError:
        state = client.get('status', timeout=3)
        incident = state.get('last_stop') or {}
        progress = state.get('drawing_progress') or {}
        pose = state.get('pose') or {}
        if (incident.get('source') != 'feedback_guard'
                or incident.get('job') != getattr(client, 'last_command_job', None)
                or state.get('job') != client.last_command_job
                or progress.get('source_stroke') != 1
                or progress.get('completed_input_strokes') != 0
                or progress.get('completed_parts') != 0
                or progress.get('total_input_strokes') != len(strokes)
                or progress.get('stage') not in
                    ('raise_before_transfer', 'approach', 'approach_hover', '1_transfer')
                or pose.get('z', 0) < .2109):
            raise
        recovered = client.recover_feedback()
        if not recovered.get('pose') or recovered['pose']['z'] < .2109:
            raise RuntimeError('Recovered approach is below clearance; inspect the pen')
        client.diagnostic('canvas_replanned_before_contact', recovered)
        # Fresh geometry planning, after terminal execution and stable feedback.
        # A second failure propagates; partially written strokes are never retried.
        return client.command(**command)


class RemoteDrawing:
    """Compose existing drawing geometry with the real workstation execution queue."""
    def __init__(self, client, *, direct_from_zero=False):
        import yaml
        from tictactoe_motion.canvas.board_canvas import BoardCanvas
        from tictactoe_motion.actions.drawing_actions import DrawingActions
        from ament_index_python.packages import get_package_share_directory
        root = Path(get_package_share_directory('tictactoe_motion'))
        self.geometry = DrawingActions(BoardCanvas(yaml.safe_load(
            (root/'config/board_real.yaml').read_text())))
        self.width, self.height = self.geometry.width, self.geometry.height
        self.client = client
        self.direct_from_zero = direct_from_zero

    def grid_strokes(self, *args, **kwargs):
        return self.geometry.grid_strokes(*args, **kwargs)

    def x_strokes(self, *args, **kwargs):
        return self.geometry.x_strokes(*args, **kwargs)

    def o_strokes(self, *args, **kwargs):
        return self.geometry.o_strokes(*args, **kwargs)

    def prepare_draw(self):
        """Use the workstation's direct approach when the real profile enables it."""
        if not (self.direct_from_zero
                or self.geometry.canvas.profile.get('allow_direct_zero_approach', False)):
            self.client.park('clear')

    def run_canvas(self, strokes):
        """Draw through the workbench using the configured approach."""
        return draw_canvas_with_feedback_recovery(
            self.client, strokes, speed=.45, direct_from_zero=self.direct_from_zero,
        )

    def draw(self, strokes, **options):
        self.prepare_draw()
        self.run_canvas(strokes)
        self.client.park('zero')
        return {'passed': True}

    def draw_grid(self, center, width, height, **options):
        return self.draw(self.geometry.grid_strokes(center, width, height,
                         rows=options['rows'], columns=options['columns']))

    def draw_x(self, center, size, **options):
        return self.draw(self.geometry.x_strokes(center, size))

    def draw_o(self, center, radius, **options):
        return self.draw(self.geometry.o_strokes(center, radius))

