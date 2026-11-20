"""Regression coverage for the free-placement four-in-a-row decision route."""

import pytest

from tictactoe_game.decision import choose_move


def board_with(x_cells, o_cells):
    board = [[""] * 9 for _ in range(9)]
    for mark, coordinates in (("X", x_cells), ("O", o_cells)):
        for row, col in coordinates:
            board[row][col] = mark
    return board


@pytest.mark.parametrize("dr,dc", [(0, 1), (1, 0), (1, 1), (1, -1)])
def test_four_wins_in_all_directions(dr, dc):
    stones = [(3 + j * dr, 3 + j * dc) for j in range(3)]
    board = board_with(stones, [(7, 0), (7, 2), (7, 4)])
    winning_move = choose_move(board, "X", win_length=4, move_time_ms=1)
    assert winning_move in [(3 - dr, 3 - dc), (3 + 3 * dr, 3 + 3 * dc)]
    row, col = winning_move
    board[row][col] = "X"
    assert choose_move(board, "O", win_length=4) is None


def test_four_blocks_an_immediate_win():
    board = board_with([(2, 0), (7, 4), (8, 4)], [(2, 1), (2, 2), (2, 3)])
    assert choose_move(board, "X", win_length=4, move_time_ms=1) == (2, 4)


def test_four_prefers_winning_to_blocking():
    board = board_with([(2, 1), (2, 2), (2, 3)], [(3, 1), (3, 2), (3, 3)])
    assert choose_move(board, "X", win_length=4) in [(2, 0), (2, 4)]


def test_four_creates_a_double_threat():
    board = board_with([(4, 4), (4, 5)], [(0, 0), (0, 2)])
    assert choose_move(board, "X", win_length=4) in [(4, 3), (4, 6)]
