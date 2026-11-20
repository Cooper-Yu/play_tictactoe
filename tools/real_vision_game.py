"""Run a real 3x3 vision game through the existing serialized workstation."""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from tictactoe_gui.workstation_client import Workstation, RemoteDrawing



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
