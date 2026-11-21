"""Check board-size-aware visual move confirmation."""
from tictactoe_perception.stable_player_move import StablePlayerMove

def test_nine_by_nine_outer_cell_requires_three_frames():
    gate = StablePlayerMove([["" for _ in range(9)] for _ in range(9)], "X")
    cells = {(8, 8): frozenset(("X",))}
    assert gate.observe(1, cells) is None
    assert gate.observe(2, cells) is None
    assert gate.observe(3, cells) == (8, 8, "X")
    assert gate.observe(4, cells) is None

def test_outside_board_is_not_a_move():
    gate = StablePlayerMove([["", "", ""] for _ in range(3)], "X")
    for sequence in range(1, 5):
        assert gate.observe(sequence, {(8, 8): frozenset(("X",))}) is None
