"""Confirm a player move from consecutive board observations."""


class StablePlayerMove:
    """Require the same exact one-mark change in three distinct camera frames."""

    def __init__(self, board, player_mark):
        self.rows = len(board)
        self.columns = len(board[0]) if board else 0
        if not self.rows or not self.columns or any(len(row) != self.columns for row in board):
            raise ValueError("Expected a non-empty rectangular board")
        self.baseline = {(row, col): frozenset((mark,))
                         for row, cells in enumerate(board) for col, mark in enumerate(cells)
                         if mark}
        self.player_mark = player_mark
        self.last_sequence = None
        self.candidate = None
        self.count = 0
        self.submitted = False

    def observe(self, sequence, cells):
        if self.submitted or (self.last_sequence is not None and sequence <= self.last_sequence):
            return None
        self.last_sequence = sequence
        added = cells.keys() - self.baseline.keys()
        candidate = None
        if len(added) == 1 and all(cells.get(key) == mark for key, mark in self.baseline.items()):
            row, col = next(iter(added))
            if 0 <= row < self.rows and 0 <= col < self.columns and cells[(row, col)] == {self.player_mark}:
                candidate = (row, col, self.player_mark)
        self.count = self.count + 1 if candidate == self.candidate and candidate else int(candidate is not None)
        self.candidate = candidate
        if self.count >= 3:
            self.submitted = True
            return candidate
        return None
