"""CPU decision engines for three-in-a-row and four-in-a-row and freestyle nine-by-nine Gomoku."""

from functools import lru_cache
import os
from pathlib import Path
import re
from selectors import DefaultSelector, EVENT_READ
import subprocess
import time


def _winner(state, size, length):
    for index, player in enumerate(state):
        if not player:
            continue
        row, col = divmod(index, size)
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            end_row = row + (length - 1) * dr
            end_col = col + (length - 1) * dc
            if 0 <= end_row < size and 0 <= end_col < size and all(
                state[(row + step * dr) * size + col + step * dc] == player
                for step in range(1, length)
            ):
                return player
    return None


def _other(player):
    return "O" if player == "X" else "X"


def _moves(state, player):
    for index, value in enumerate(state):
        if not value:
            yield index, state[:index] + (player,) + state[index + 1:]


@lru_cache(maxsize=20000)
def _minimax(state, player):
    if _winner(state, 3, 3):
        return -(1 + state.count(""))
    return max((-_minimax(next_state, _other(player))
                for _, next_state in _moves(state, player)), default=0)


def _rapfi_move(state, player, executable, move_time_ms):
    if not executable:
        raise RuntimeError("Set TICTACTOE_RAPFI to the Rapfi executable path")
    binary = Path(executable).expanduser().resolve()
    if not isinstance(move_time_ms, int) or isinstance(move_time_ms, bool) or move_time_ms < 1:
        raise ValueError("Rapfi move time must be a positive integer in milliseconds")

    # Rapfi loads config.toml and its evaluation weights from the engine directory.
    with subprocess.Popen([str(binary)], cwd=binary.parent, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            with DefaultSelector() as selector:
                selector.register(process.stdout, EVENT_READ)
                pending = bytearray()

                def read_until(accept, timeout):
                    deadline = time.monotonic() + timeout
                    while True:
                        while b"\n" in pending:
                            raw, tail = pending.split(b"\n", 1)
                            pending[:] = tail
                            line = raw.decode("utf-8", errors="replace").strip()
                            if line.startswith(("ERROR", "UNKNOWN")):
                                raise RuntimeError(f"Rapfi: {line}")
                            if accept(line):
                                return line
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise TimeoutError("Rapfi did not reply before the deadline")
                        data = os.read(process.stdout.fileno(), 4096)
                        if not data:
                            raise RuntimeError("Rapfi exited before replying")
                        pending.extend(data)

                process.stdin.write(b"START 9\n")
                process.stdin.flush()
                read_until(lambda line: line == "OK", 5.0)
                commands = ["INFO rule 0", f"INFO timeout_turn {move_time_ms}"]
                stones = []
                for index, symbol in enumerate(state):
                    if symbol:
                        row, col = divmod(index, 9)
                        stones.append(f"{col},{row},{1 if symbol == player else 2}")
                commands.extend(["BOARD", *stones, "DONE"] if stones else ["BEGIN"])
                process.stdin.write(("\n".join(commands) + "\n").encode("ascii"))
                process.stdin.flush()
                move = read_until(lambda line: re.fullmatch(r"\d+,\d+", line) is not None,
                                  5.0 + move_time_ms / 1000)
                col, row = map(int, move.split(","))
                return row, col
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()


def choose_move(board, player, *, win_length=None, rapfi_path=None, move_time_ms=500,
                randomize_four_ties=False):
    """! @brief Return the next zero-based (row, col) for a confirmed X/O board.

    Empty cells contain an empty string. X plays first. Return None for a finished
    position. Five-in-a-row uses a Rapfi executable on Linux.
    """
    size = len(board)
    if size not in (3, 9) or any(len(row) != size for row in board):
        raise ValueError("Expected a square 3x3 or 9x9 board")
    if win_length is None:
        win_length = 3 if size == 3 else 5
    if (size, win_length) not in ((3, 3), (9, 4), (9, 5)):
        raise ValueError("Expected 3×3 three-in-a-row, or 9×9 with four or five in a row")
    state = tuple(cell for row in board for cell in row)
    if any(cell not in ("", "X", "O") for cell in state) or player not in ("X", "O"):
        raise ValueError("Board cells must be empty, X, or O; player must be X or O")
    balance = state.count("X") - state.count("O")
    if balance not in (0, 1):
        raise ValueError("Invalid X/O move counts")
    if _winner(state, size, win_length) or all(state):
        return None
    if player != ("X" if balance == 0 else "O"):
        raise ValueError("Player does not match the current turn")
    if size == 3:
        best_index, _ = max(_moves(state, player),
                            key=lambda move: -_minimax(move[1], _other(player)))
        return divmod(best_index, 3)

    if win_length == 4:
        from tictactoe_motion.four_in_a_row import choose_four_move

        return choose_four_move(state, player, move_time_ms, randomize_ties=randomize_four_ties)

    row, col = _rapfi_move(state, player, rapfi_path or os.getenv("TICTACTOE_RAPFI"),
                           move_time_ms)
    if not (0 <= row < size and 0 <= col < size) or state[row * size + col]:
        raise RuntimeError(f"Rapfi returned an illegal cell ({row}, {col})")
    return row, col

