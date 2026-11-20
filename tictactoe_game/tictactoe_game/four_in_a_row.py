"""Time-bounded decision engine for free placement on a 9×9 four-in-a-row board."""

from secrets import choice
from time import monotonic


SIZE = 9
FULL_BOARD = (1 << (SIZE * SIZE)) - 1
WIN = 100_000
WINDOWS = tuple(
    sum(1 << ((row + offset * dr) * SIZE + col + offset * dc) for offset in range(4))
    for row in range(SIZE)
    for col in range(SIZE)
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1))
    if 0 <= row + 3 * dr < SIZE and 0 <= col + 3 * dc < SIZE
)
CELL_WINDOWS = tuple(tuple(window for window in WINDOWS if window & (1 << index))
                     for index in range(SIZE * SIZE))
CENTER_DISTANCE = tuple(sum(abs(axis - SIZE // 2) for axis in divmod(index, SIZE))
                        for index in range(SIZE * SIZE))
WEIGHTS = (0, 2, 16, 140)
MOVE_LIMIT = 12


class SearchTimeout(Exception):
    """The last completed search depth supplies the move when the budget expires."""


def cells(mask):
    """Yield individual square masks from least to most significant."""
    while mask:
        square = mask & -mask
        yield square
        mask ^= square


def threats_and_score(own, other):
    """Find immediate wins on both sides and score the remaining four-cell lines."""
    wins = losses = score = 0
    for window in WINDOWS:
        a, b = window & own, window & other
        if a and not b:
            count = a.bit_count()
            if count == 3:
                wins |= window ^ a
            elif count == 4:
                return wins, losses, WIN
            score += WEIGHTS[count]
        elif b and not a:
            count = b.bit_count()
            if count == 3:
                losses |= window ^ b
            elif count == 4:
                return wins, losses, -WIN
            score -= WEIGHTS[count]
    return wins, losses, score


def ordered_moves(own, other, empty):
    """Prefer moves that build useful lines or block the opponent's threats."""
    def priority(square):
        index = square.bit_length() - 1
        score = 0
        for window in CELL_WINDOWS[index]:
            a, b = window & own, window & other
            if not a:
                score += WEIGHTS[b.bit_count()]
            if not b:
                score += WEIGHTS[a.bit_count() + 1]
        return score, -CENTER_DISTANCE[index]

    return sorted(cells(empty), key=priority, reverse=True)[:MOVE_LIMIT]


def negamax(own, other, depth, alpha, beta, deadline, ply):
    """Search from the current player's perspective using Alpha-Beta pruning."""
    if monotonic() >= deadline:
        raise SearchTimeout
    empty = FULL_BOARD ^ (own | other)
    wins, losses, score = threats_and_score(own, other)
    if abs(score) == WIN:
        return score
    if not empty:
        return 0
    if wins:
        return WIN - ply - 1
    if losses.bit_count() > 1:
        return -WIN + ply + 2
    if depth == 0:
        return score
    moves = [losses] if losses else ordered_moves(own, other, empty)
    value = -WIN
    for square in moves:
        result = -negamax(other, own | square, depth - 1, -beta, -alpha, deadline, ply + 1)
        value = max(value, result)
        alpha = max(alpha, value)
        if alpha >= beta:
            break
    return value


def choose_four_move(state, player, move_time_ms, *, randomize_ties=False):
    """Return a legal (row, column) from an already validated 9×9 position."""
    if type(move_time_ms) is not int or move_time_ms < 1:
        raise ValueError("Four-in-a-row move time must be a positive integer in milliseconds")
    deadline = monotonic() + move_time_ms / 1000
    own = sum(1 << index for index, mark in enumerate(state) if mark == player)
    other = sum(1 << index for index, mark in enumerate(state) if mark and mark != player)
    empty = FULL_BOARD ^ (own | other)
    wins, losses, _ = threats_and_score(own, other)
    if wins or losses:
        candidates = cells(wins or losses)
        square = choice(tuple(candidates)) if randomize_ties else next(candidates)
        return divmod(square.bit_length() - 1, SIZE)
    if not own and not other:
        return SIZE // 2, SIZE // 2

    moves = ordered_moves(own, other, empty)
    best = [moves[0]]
    for depth in range(1, empty.bit_count() + 1):
        score = -WIN
        tied = []
        try:
            for square in [best[0], *(candidate for candidate in moves if candidate != best[0])]:
                # Keep equal scores inside the search window so a cutoff cannot masquerade as a tie.
                upper = min(WIN, -score + 1) if randomize_ties else -score
                value = -negamax(other, own | square, depth - 1, -WIN, upper, deadline, 1)
                if not tied or value > score:
                    score, tied = value, [square]
                elif randomize_ties and value == score:
                    tied.append(square)
        except SearchTimeout:
            break
        best = tied
        if abs(score) > WIN // 2:
            break
    square = choice(best) if randomize_ties else best[0]
    return divmod(square.bit_length() - 1, SIZE)
