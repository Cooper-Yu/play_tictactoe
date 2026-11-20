"""Eight-move scoring rules and a score-aware Minimax for Tic-Tac-Toe."""

from functools import lru_cache

from tictactoe_motion.grid_game import GridGame


WEIGHTS = (2, 1, 2, 1, 3, 1, 2, 1, 2)
LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6),
         (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
ROUND_MOVES = 8
LINE_POINTS = 3


def score(board):
    """Return points and completed line counts by mark."""
    report = {}
    for mark in ("X", "O"):
        lines = sum(all(board[index] == mark for index in line) for line in LINES)
        tiles = sum(points for points, cell in zip(WEIGHTS, board) if cell == mark)
        report[mark] = {"points": tiles + LINE_POINTS * lines, "lines": lines}
    return report


def _moves(board, mark):
    for index, cell in enumerate(board):
        if not cell:
            yield index, board[:index] + (mark,) + board[index+1:]


@lru_cache(maxsize=20000)
def _value(board, turn):
    if board.count("") == 9 - ROUND_MOVES:
        points = score(board)
        return (points["X"]["points"] - points["O"]["points"],
                points["X"]["lines"] - points["O"]["lines"])
    other = "O" if turn == "X" else "X"
    select = max if turn == "X" else min
    return select(_value(next_board, other) for _, next_board in _moves(board, turn))


class ScoreTicTacToe(GridGame):
    """Keep playing after a line and decide the round by points after eight moves."""

    def __init__(self, actions, width, height, *, flip=False, swap_marks=False):
        super().__init__(actions, width=width, height=height, flip=flip, swap_marks=swap_marks)

    def outcome_after_move(self, symbol, row, col):
        if self.board.count("") != 9 - ROUND_MOVES:
            return None
        current = score(self.board)
        difference = current["X"]["points"] - current["O"]["points"]
        return "X" if difference > 0 else "O" if difference < 0 else "draw"

    def suggest_move(self):
        if self.phase == "finished":
            return None
        if self.phase != "playing":
            raise ValueError("Game is not accepting moves")
        board = tuple(self.board)
        other = "O" if self.turn == "X" else "X"
        select = max if self.turn == "X" else min
        index, _ = select(_moves(board, self.turn), key=lambda move: _value(move[1], other))
        return divmod(index, 3)
