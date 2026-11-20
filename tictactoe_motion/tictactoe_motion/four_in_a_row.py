"""Compatibility imports for the former motion-package path."""

from tictactoe_game.four_in_a_row import (
    SIZE,
    FULL_BOARD,
    WIN,
    WINDOWS,
    CELL_WINDOWS,
    CENTER_DISTANCE,
    WEIGHTS,
    MOVE_LIMIT,
    SearchTimeout,
    cells,
    threats_and_score,
    ordered_moves,
    negamax,
    choose_four_move,
)

__all__ = [
    "SIZE",
    "FULL_BOARD",
    "WIN",
    "WINDOWS",
    "CELL_WINDOWS",
    "CENTER_DISTANCE",
    "WEIGHTS",
    "MOVE_LIMIT",
    "SearchTimeout",
    "cells",
    "threats_and_score",
    "ordered_moves",
    "negamax",
    "choose_four_move",
]
