"""Regression checks for the shared decision API."""

import os

import pytest

from tictactoe_motion.decision import choose_move


@pytest.mark.parametrize(("board", "player", "expected"), [
    (["XX ", "OO ", "   "], "X", (0, 2)),
    (["XX ", " O ", "   "], "O", (0, 2)),
    (["XXX", "OO ", "   "], "O", None),
    (["XOX", "XOO", "OXX"], "O", None),
])
def test_minimax(board, player, expected):
    board = [["" if cell == " " else cell for cell in row] for row in board]
    original = [row.copy() for row in board]
    assert choose_move(board, player) == expected
    assert board == original


def test_wrong_turn():
    with pytest.raises(ValueError, match="current turn"):
        choose_move([[""] * 3 for _ in range(3)], "O")


@pytest.mark.skipif(not os.getenv("TICTACTOE_RAPFI"), reason="Local Rapfi executable required")
def test_rapfi_blocks_open_end_of_four():
    board = [[""] * 9 for _ in range(9)]
    for col in range(4):
        board[2][col] = "O"
    for row, col in ((0, 6), (1, 8), (5, 6), (8, 8)):
        board[row][col] = "X"
    assert choose_move(board, "X") == (2, 4)

