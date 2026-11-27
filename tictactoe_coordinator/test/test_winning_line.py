"""Exercise terminal-line geometry and one-shot execution without ROS or hardware."""
import pytest

from tictactoe_coordinator.game_coordinator import GameCoordinator
from tictactoe_game.grid_game import GridGame


class Actions:
    width, height = .144, .193

    def __init__(self):
        self.lines = []
        self.failure = None

    def grid_strokes(self, *args):
        pass

    x_strokes = o_strokes = grid_strokes

    def draw_grid(self, *args, **kwargs):
        return {'passed': True}

    draw_x = draw_o = draw_grid

    def draw(self, strokes, **kwargs):
        self.lines.append(strokes)
        if self.failure:
            raise RuntimeError(self.failure)
        return {'passed': True}


@pytest.mark.parametrize('size,length', [(3, 3), (9, 4), (9, 5)])
@pytest.mark.parametrize('dr,dc', [(0, 1), (1, 0), (1, 1), (1, -1)])
def test_winning_cells_follow_each_axis_and_ignore_other_marks(size, length, dr, dc):
    game = GridGame(Actions(), rows=size, columns=size, win_length=length)
    row, col = 0, size-1 if dc < 0 else 0
    cells = [(row+i*dr, col+i*dc) for i in range(length)]
    for r, c in cells:
        game.board[r*size+c] = 'O'
    game.outcome = 'O'
    assert game.winning_cells() == cells


def test_maximal_run_and_draw_geometry():
    game = GridGame(Actions(), rows=9, columns=9, win_length=4)
    game.board[:6] = ['X']*6
    game.outcome = 'X'
    assert game.winning_cells() == [(0, i) for i in range(6)]
    game.outcome = 'draw'
    assert game.winning_cells() == []


def finishing_game(source='click', *, flip=False, mark='X', failure=None, cancelled=lambda: False):
    actions, states = Actions(), []
    actions.failure = failure
    coordinator = GameCoordinator(actions, lambda **s: states.append(s), cancelled,
                                  flip=flip, draw_winning_line=True)
    coordinator.start(3, 1, input_source=source, opponent='human', mark=mark)
    # Canonical X wins; visible symbols may be swapped.
    coordinator.game.board = ['X', 'O', '', 'O', 'X', '', '', '', '']
    coordinator.game.turn = 'X'
    return coordinator, actions, states


@pytest.mark.parametrize('source', ['click', 'vision', 'handwriting', 'physical'])
@pytest.mark.parametrize('flip', [False, True])
@pytest.mark.parametrize('mark', ['X', 'O'])
def test_all_inputs_draw_once_using_calibrated_centers(source, flip, mark):
    coordinator, actions, states = finishing_game(source, flip=flip, mark=mark)
    if source == 'click':
        coordinator.move(2, 2, 2)
    else:
        coordinator.register_observed_move(2, 2, mark, 2)
    expected = [[coordinator.game.cell_center(0, 0), coordinator.game.cell_center(2, 2)]]
    assert actions.lines == [expected]
    assert states[-1]['game']['winner'] == mark
    assert states[-1]['game']['winning_cells'] == [(0, 0), (1, 1), (2, 2)]
    assert states[-1]['game']['winning_line']['status'] == 'completed'
    assert states[-1]['game']['phase'] == 'finished'
    assert all(s['game']['winner'] == mark for s in states
               if s['game']['phase'] == 'drawing_win_line')
    coordinator._draw_winning_line(3)
    assert len(actions.lines) == 1
    with pytest.raises(ValueError):
        coordinator.move(0, 2, 3)


def test_ai_win_uses_same_terminal_line(monkeypatch):
    coordinator, actions, states = finishing_game()
    coordinator.opponent = 'ai'
    coordinator.game.board = ['X', '', 'X', 'O', 'O', '', '', '', '']
    monkeypatch.setattr(coordinator.game, 'suggest_move', lambda: (1, 2))
    coordinator.move(2, 0, 2)
    assert coordinator.game.outcome == 'O'
    assert actions.lines == [[[coordinator.game.cell_center(1, 0),
                               coordinator.game.cell_center(1, 2)]]]


@pytest.mark.parametrize('failure', ['feedback lost after pen contact', None])
def test_failure_or_cancellation_retains_outcome_and_never_retries(failure):
    stop = [False]
    coordinator, actions, states = finishing_game(failure=failure, cancelled=lambda: stop[0])
    if failure is None:
        original_publish = coordinator.publish
        def publish(**s):
            original_publish(**s)
            if (s.get('game', {}).get('winning_line') or {}).get('status') == 'pending':
                stop[0] = True
        coordinator.publish = publish
    with pytest.raises(RuntimeError):
        coordinator.move(2, 2, 2)
    assert coordinator.game.outcome == 'X'
    assert coordinator.winning_line['status'] == 'failed'
    attempted = len(actions.lines)
    stop[0] = False
    coordinator._draw_winning_line(3)
    assert len(actions.lines) == attempted == (1 if failure else 0)


def test_draw_and_default_coordinator_do_not_draw_decoration():
    coordinator, actions, _ = finishing_game()
    coordinator.game.board = ['X', 'O', 'X', 'X', 'O', 'O', 'O', 'X', '']
    coordinator.move(2, 2, 2)
    assert coordinator.game.outcome == 'draw' and not actions.lines
    coordinator, actions, _ = finishing_game()
    coordinator.draw_winning_line = False
    coordinator.move(2, 2, 2)
    assert not actions.lines


def test_new_game_clears_one_shot_record():
    coordinator, actions, _ = finishing_game()
    coordinator.move(2, 2, 2)
    coordinator.start(3, 3, opponent='human')
    assert coordinator.winning_line is None and coordinator.game.winning_cells() == []
