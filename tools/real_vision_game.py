"""Run a real 3x3 vision game through the existing serialized workstation."""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests


class Workstation:
    """Use verified workstation jobs and preserve every submitted operation."""
    def __init__(self, url, output):
        self.url = url.rstrip('/') + '/'
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.http = requests.Session()
        config = self.get('config')
        if config['environment'] != 'real':
            raise ValueError('Expected real workstation')
        self.token = config['token']

    def get(self, route):
        r = self.http.get(self.url + 'api/' + route, timeout=15)
        r.raise_for_status()
        return r.json()

    def command(self, **command):
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
            if state['job'] != job:
                raise RuntimeError('Another operator changed the active job')
            if not state['busy']:
                record = dict(command=command, seconds=time.monotonic()-started, state=state)
                (self.output/f'job-{job}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
                if state['state'] != 'ready' or state.get('last_stop', {}).get('job') == job:
                    raise RuntimeError(state['message'])
                expected = {'canvas': '绘图运动完成，已抬笔；请检查实际笔迹',
                            'preset': '操作完成', 'execute': '操作完成',
                            'reset': 'Reset 按键动作完成，已回悬空点；请确认清屏'}
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--play', action='store_true')
    parser.add_argument('--resume-one-x', action='store_true')
    parser.add_argument('--weights')
    parser.add_argument('--grid-points', help='JSON file with four internal grid intersections')
    args = parser.parse_args()
    client = Workstation(args.url, args.output)
    if args.prepare:
        client.command(kind='reset', speed=.1)
        client.park()
        client.frame('cleared.jpg')
        prepare_grid(client)
    if args.play:
        play_game(client, args.weights, json.loads(Path(args.grid_points).read_text()), resume_one_x=args.resume_one_x)




class RemoteDrawing:
    """Compose existing drawing geometry with the real workstation execution queue."""
    def __init__(self, client):
        import yaml
        from tictactoe_motion.canvas.board_canvas import BoardCanvas
        from tictactoe_motion.actions.drawing_actions import DrawingActions
        root = Path(__file__).resolve().parents[1]
        self.geometry = DrawingActions(BoardCanvas(yaml.safe_load(
            (root/'tictactoe_motion/config/board_real.yaml').read_text())))
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


def prepare_grid(client):
    client.park('clear')
    actions = RemoteDrawing(client)
    actions.draw_grid((.5, .5), actions.width-.004, actions.height-.004,
                      rows=3, columns=3)
    client.frame('grid.jpg')


def play_game(client, weights, points, *, resume_one_x=False):
    import cv2
    from tictactoe_gui.real_board_perception import RealBoardPerception
    from tictactoe_perception.stable_player_move import StablePlayerMove
    from tictactoe_coordinator.game_coordinator import GameCoordinator
    perception = RealBoardPerception(weights, points, device='0')
    actions = RemoteDrawing(client)
    # The preparation phase already drew and photographed the empty grid.
    actions.draw_grid = lambda *args, **kwargs: {'passed': True}
    def publish(**state):
        (client.output/'game.json').write_text(json.dumps(state, ensure_ascii=False, indent=2))
        if 'game' in state:
            print('GAME', state['game']['phase'], state['game']['board'], flush=True)
    game = GameCoordinator(actions, publish, lambda: False, flip=False)
    initial, _ = client.frame('baseline.jpg')
    initial_cells = perception.detect_cells(initial.read_bytes())
    if resume_one_x:
        if len(initial_cells) != 1 or next(iter(initial_cells.values())) != {'X'}:
            raise RuntimeError('Resume requires exactly one visible X and no O')
    elif initial_cells:
        raise RuntimeError('Initial board is not empty')
    game.start(3, 0, input_source='vision')
    turn = 0
    while not game.game.outcome:
        turn += 1
        # This path only writes a proxy-player mark. No coordinate is submitted.
        candidates = (0, 4, 8, 2, 6, 1, 3, 5, 7)
        cell = next(i for i in candidates if not game.game.board[i])
        row, col = divmod(cell, 3)
        if not (resume_one_x and turn == 1):
            actions.draw_x(game.game.cell_center(row, col), game.game.cell_size*.55)
        gate = StablePlayerMove([game.game.board[i:i+3] for i in (0, 3, 6)], 'X')
        observations = []
        found = None
        for attempt in range(15):
            time.sleep(.4)
            path, sequence = client.frame(f'turn-{turn}-frame-{attempt}.jpg')
            image = path.read_bytes()
            cells = perception.detect_cells(image)
            result = perception.render(image, sequence, 3, 'detections')
            if result:
                (client.output/f'turn-{turn}-detection-{attempt}.jpg').write_bytes(result)
            observations.append(dict(sequence=sequence, cells={f'{r},{c}':sorted(m) for (r,c),m in cells.items()}))
            print('OBSERVE', sequence, observations[-1]['cells'], flush=True)
            found = gate.observe(sequence, cells)
            if found:
                break
        (client.output/f'turn-{turn}-observations.json').write_text(json.dumps(observations, indent=2))
        if found is None:
            raise RuntimeError('No stable unique player move confirmed')
        print('VISION_CONFIRMED', found, flush=True)
        game.register_observed_move(*found, turn)
        client.frame(f'turn-{turn}-after-ai.jpg')
    client.park('zero')
    client.frame('finished.jpg')
    print('FINISHED', game.game.outcome, flush=True)

if __name__ == '__main__':
    main()
