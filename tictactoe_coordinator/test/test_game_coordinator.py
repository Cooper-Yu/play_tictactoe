"""Verify that game state follows measured draw results."""

import pytest

from tictactoe_coordinator.game_coordinator import GameCoordinator


class Actions:
    width = .144
    height = .193

    def __init__(self, fail_o=False):
        self.fail_o = fail_o
        self.calls = []

    def grid_strokes(self, *args):
        return None

    x_strokes = o_strokes = grid_strokes

    def draw_grid(self, *args, **kwargs):
        return {"passed": True}

    def draw_x(self, center, *args, **kwargs):
        self.calls.append(("X", center))
        return {"passed": True}

    def draw_o(self, center, *args, **kwargs):
        self.calls.append(("O", center))
        return {"passed": not self.fail_o}


def test_human_and_ai_confirm_in_order_and_align_to_camera():
    actions = Actions()
    statuses = []
    game = GameCoordinator(actions, lambda **data: statuses.append(data), lambda: False)
    game.start(3, 1)
    game.move(0, 1, 2)
    phases = [status["game"] for status in statuses if "game" in status]
    assert [stage["phase"] for stage in phases] == [
        "preparing", "player", "drawing_x", "thinking", "drawing_o", "player"
    ]
    assert phases[2]["board"][0][1] == ""
    assert phases[3]["board"][0][1] == "X"
    assert phases[-1]["board"][0][0] == "O"
    assert [mark for mark, _ in actions.calls] == ["X", "O"]
    assert actions.calls[0][1][1] > .5
    assert actions.calls[1][1][0] > .5


def test_failed_ai_stroke_keeps_verified_human_move_and_pauses():
    actions = Actions(fail_o=True)
    statuses = []
    game = GameCoordinator(actions, lambda **data: statuses.append(data), lambda: False)
    game.start(3, 1)
    with pytest.raises(RuntimeError, match="Drawing not verified"):
        game.move(1, 1, 2)
    board = statuses[-1]["game"]
    assert board["phase"] == "blocked"
    assert board["board"][1][1] == "X"
    assert all("O" not in row for row in board["board"])
    with pytest.raises(ValueError, match="当前无法落子"):
        game.move(0, 0, 3)



def test_score_match_swaps_marks_and_resolves_an_exact_tie(monkeypatch):
    from tictactoe_game.score_tictactoe import score

    monkeypatch.setattr("tictactoe_coordinator.game_coordinator.secrets.choice", lambda sides: sides[0])
    snapshots = []
    actions = Actions()
    coordinator = GameCoordinator(actions, lambda **data: snapshots.append(data), lambda: False)
    coordinator.start(3, 1, mode="score")
    opening = coordinator.game.suggest_move()
    assert opening == (1, 1)
    for revision in range(2, 6):
        coordinator.move(*coordinator.game.suggest_move(), revision)
    first = snapshots[-1]["game"]
    assert first["phase"] == "between_rounds"
    assert sum(cell == "" for cell in coordinator.game.board) == 1
    assert first["totals"]["player"]["points"] - first["totals"]["ai"]["points"] == 2

    coordinator.next_round(6)
    second = snapshots[-1]["game"]
    assert second["human"] == "X" and second["round"] == 2 and second["first"] == "ai"
    assert second["board"][1][1] == "O" and actions.calls[8][0] == "O"
    for revision in range(7, 11):
        coordinator.move(*coordinator.game.suggest_move(), revision)
    result = snapshots[-1]["game"]
    assert result["phase"] == "finished" and len(result["rounds"]) == 2
    assert result["totals"]["player"] == result["totals"]["ai"]
    assert result["match_winner"] == "player" and result["decided_by"] == "coin"
    assert len(actions.calls) == 16
    assert score(["X", "", "", "", "X", "", "", "", "X"])["X"] == {"points": 10, "lines": 1}


def test_score_round_continues_after_a_three_in_a_row():
    from tictactoe_game.score_tictactoe import ScoreTicTacToe

    game = ScoreTicTacToe(Actions(), .14, .189)
    game.start()
    for row, col in ((0,0), (1,0), (0,1), (1,1), (0,2)):
        game.play(game.turn, row, col)
    assert game.outcome is None and game.phase == "playing"
    for row, col in ((2,0), (2,1), (2,2)):
        game.play(game.turn, row, col)
    assert game.phase == "finished" and game.suggest_move() is None

@pytest.mark.parametrize(("first", "initial_marks", "after_turn"), [
    ("player", [], ["O", "X"]),
    ("ai", ["X"], ["X", "O", "X"]),
])
def test_o_and_first_choice_are_independent(first, initial_marks, after_turn):
    snapshots = []
    actions = Actions()
    game = GameCoordinator(actions, lambda **data: snapshots.append(data), lambda: False)
    game.start(3, 1, mode="score", first=first, mark="O")
    assert [mark for mark, _ in actions.calls] == initial_marks
    assert snapshots[-1]["game"]["human"] == "O"
    assert snapshots[-1]["game"]["turn"] == "O"
    game.move(0, 0, 2)
    assert [mark for mark, _ in actions.calls] == after_turn
    assert snapshots[-1]["game"]["board"][0][0] == "O"


def test_four_mode_ends_at_four_without_rapfi(monkeypatch):
    monkeypatch.delenv("TICTACTOE_RAPFI", raising=False)
    snapshots = []
    actions = Actions()
    game = GameCoordinator(actions, lambda **data: snapshots.append(data), lambda: False)
    game.start(9, 1, mode="four", mark="O")
    assert snapshots[-1]["game"]["win_length"] == 4
    for revision, col in enumerate(range(3), start=2):
        monkeypatch.setattr(game.game, "suggest_move", lambda col=col: (8, col * 2))
        game.move(0, col, revision)
        assert snapshots[-1]["game"]["phase"] == "player"
    game.move(0, 3, 5)
    state = snapshots[-1]["game"]
    assert state["phase"] == "finished" and state["winner"] == "O"
    assert len(actions.calls) == 7


@pytest.mark.parametrize("mark, first", [("O", "player"), ("X", "ai")])
def test_fixed_three_stone_opening_respects_mark_and_o_turn(monkeypatch, mark, first):
    snapshots = []
    actions = Actions()
    coordinator = GameCoordinator(actions, lambda **data: snapshots.append(data), lambda: False)

    def suggest(game, **options):
        assert options == {"randomize_four_ties": True}
        return 0, 0

    monkeypatch.setattr("tictactoe_game.grid_game.GridGame.suggest_move", suggest)
    coordinator.start(9, 1, mode="four-three-stone", mark=mark)
    board = snapshots[-1]["game"]
    assert (board["turn"], board["human"], board["first"]) == (mark, mark, first)
    assert board["win_length"] == 4
    assert [board["board"][r][8] for r in (0, 1, 6)] == ["X", "O", "X"]
    assert board["board"][0][0] == ("O" if mark == "X" else "")
    assert [symbol for symbol, _ in actions.calls] == (
        ["X", "O", "X", "O"] if mark == "X" else ["X", "O", "X"]
    )
    with pytest.raises(ValueError, match="该格已经落子"):
        coordinator.move(0, 8, 2)


def test_fixed_three_stone_opening_keeps_only_verified_marks():
    snapshots = []
    actions = Actions(fail_o=True)
    coordinator = GameCoordinator(actions, lambda **data: snapshots.append(data), lambda: False)
    with pytest.raises(RuntimeError, match="Drawing not verified"):
        coordinator.start(9, 1, mode="four-three-stone", mark="O")
    board = snapshots[-1]["game"]
    assert board["phase"] == "blocked"
    assert [board["board"][r][8] for r in (0, 1, 6)] == ["X", "", ""]

def test_camera_move_records_existing_mark_and_draws_only_ai_reply():
    actions = Actions()
    statuses = []
    game = GameCoordinator(actions, lambda **data: statuses.append(data), lambda: False)
    game.start(3, 1)

    with pytest.raises(ValueError, match="符号"):
        game.register_observed_move(1, 2, "O", 2)
    assert game.game.board == [""] * 9 and not actions.calls

    game.register_observed_move(1, 2, "X", 2)
    phases = [value["game"] for value in statuses if "game" in value]
    assert [state["phase"] for state in phases] == [
        "preparing", "player", "thinking", "drawing_o", "player"
    ]
    assert phases[2]["board"][1][2] == "X"
    assert [mark for mark, _ in actions.calls] == ["O"]

    with pytest.raises(ValueError, match="已经落子"):
        game.register_observed_move(1, 2, "X", 2)
    assert [mark for mark, _ in actions.calls] == ["O"]


def test_real_camera_order_preserves_top_left():
    actions = Actions()
    game = GameCoordinator(actions, lambda **data: None, lambda: False, flip=False)
    game.start(3, 1)
    center = game.game.cell_center(0, 0)
    assert center[0] < .5
    assert center[1] < .5
