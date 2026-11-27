"""Coordinate a confirmed player turn, engine turn, and optional score match."""

import os
from pathlib import Path
import secrets

from tictactoe_game.grid_game import GridGame
from tictactoe_game.score_tictactoe import ScoreTicTacToe, WEIGHTS, score


THREE_STONE_MODE = "four-three-stone"
THREE_STONE_OPENING = (("X", 0, 8), ("O", 1, 8), ("X", 6, 8))
WIN_LENGTHS = {
    ("classic", 3): 3, ("classic", 9): 5, ("score", 3): 3,
    ("four", 9): 4, (THREE_STONE_MODE, 9): 4,
}


VISION_MODES = frozenset((("classic", 3), ("four", 9)))


class GameCoordinator:
    """Own the game on the worker thread and publish snapshots after verified marks."""

    def __init__(self, actions, publish, cancelled, *, flip=True, draw_winning_line=False):
        self.actions = actions
        self.flip = flip
        self.publish = publish
        self.cancelled = cancelled
        self.draw_winning_line = draw_winning_line
        self.winning_line = None
        self.game = None
        self.mode = "classic"
        self.input_source = "click"
        self.opponent = "ai"
        self.human = "X"
        self.player_mark = "X"
        self.round_number = 1
        self.rounds = []
        self.match_winner = None
        self.decided_by = None

    @property
    def active_mark(self):
        """Return the visible symbol expected from the current manual player."""
        return self._mark(self.game.turn) if self.opponent == "human" and self.game else self.player_mark

    def _mark(self, canonical):
        if canonical not in ("X", "O"):
            return canonical
        if canonical == self.human:
            return self.player_mark
        return "O" if self.player_mark == "X" else "X"

    def _update(self, phase, revision, **activity):
        game = self.game
        size = game.rows
        shown = [self._mark(cell) for cell in game.board]
        first_mark = "O" if self.mode == THREE_STONE_MODE else "X"
        state = dict(size=size, win_length=game.win_length, mode=self.mode, phase=phase, revision=revision,
                     turn=self._mark(game.turn), input_source=self.input_source, opponent=self.opponent,
                     human=self.player_mark, winner=self._mark(game.outcome),
                     first="player" if self.human == first_mark else "ai",
                     board=[shown[i:i+size] for i in range(0, len(shown), size)])
        state['winning_cells'] = game.winning_cells() if self.mode != 'score' else []
        state['winning_line'] = self.winning_line
        if self.mode == "score":
            current = self._player_scores()
            state.update(weights=WEIGHTS, round=self.round_number,
                         current_score=current, rounds=self.rounds.copy(),
                         totals=self._totals(), match_winner=self.match_winner,
                         decided_by=self.decided_by)
        self.publish(game=state, **activity)

    def _player_scores(self):
        scores = score(self.game.board)
        return dict(player=scores[self.human], ai=scores["O" if self.human == "X" else "X"])

    def _totals(self):
        return {side: {key: sum(round_score[side][key] for round_score in self.rounds)
                       for key in ("points", "lines")} for side in ("player", "ai")}

    def start(self, size, revision, *, mode="classic", first="player", mark="X",
              input_source="click", opponent="ai"):
        if not isinstance(mode, str) or (mode, size) not in WIN_LENGTHS:
            raise ValueError("Invalid game mode or board size")
        if opponent not in ("ai", "human"):
            raise ValueError("Unknown opponent mode")
        if opponent == "human" and ((mode, size) not in VISION_MODES or first != "player"):
            raise ValueError("Two players support 3x3 Tic-Tac-Toe or 9x9 four-in-a-row; choose the first symbol")
        if mode == "classic" and size == 9:
            engine = os.getenv("TICTACTOE_RAPFI")
            if not engine or not Path(engine).expanduser().is_file() or not os.access(
                Path(engine).expanduser(), os.X_OK
            ):
                raise RuntimeError("Configure an executable first TICTACTOE_RAPFI")
        if first not in ("player", "ai") or mark not in ("X", "O"):
            raise ValueError("Invalid turn order or symbol")
        if input_source not in ("click", "vision", "handwriting", "physical") or (
            input_source != "click" and (mode, size) not in VISION_MODES
        ):
            raise ValueError("Visual moves support classic 3×3 Tic-Tac-Toe or 9×9 four-in-a-row")
        self.input_source = input_source
        self.opponent = opponent
        self.mode = mode
        self.human = "X" if opponent == "human" else (
            mark if mode == THREE_STONE_MODE else ("X" if first == "player" else "O"))
        self.player_mark = mark
        self.round_number = 1
        self.rounds = []
        self.match_winner = None
        self.decided_by = None
        self._open_round(size, revision)

    def _open_round(self, size, revision):
        self.winning_line = None
        width, height = self.actions.width-.004, self.actions.height-.004
        swapped = self.human != self.player_mark
        if self.mode == "score":
            self.game = ScoreTicTacToe(self.actions, width, height, flip=self.flip, swap_marks=swapped)
        else:
            self.game = GridGame(self.actions, width=width, height=height, rows=size,
                                 columns=size, win_length=WIN_LENGTHS[self.mode, size], flip=self.flip,
                                 swap_marks=swapped)
        self._update("preparing", revision)
        try:
            self._check_cancelled()
            self.game.start(cancelled=self.cancelled)
            if self.mode == THREE_STONE_MODE:
                for mark, row, col in THREE_STONE_OPENING:
                    self._check_cancelled()
                    self.game.play(mark, row, col, **self._options())
                    self._update("preparing", revision)
            if self.opponent == "ai" and self.game.turn != self.human:
                self._ai_turn(revision)
        except Exception:
            self.block(revision)
            raise
        self._update("player", revision)

    def next_round(self, revision):
        if (self.mode != "score" or self.game is None
                or self.game.phase != "finished" or len(self.rounds) != 1):
            raise ValueError("Cannot start round two now")
        self.human = "O" if self.human == "X" else "X"
        self.round_number = 2
        self._open_round(3, revision)

    def block(self, revision):
        if self.game is not None:
            self.game.phase = "blocked"
            self._update("blocked", revision)

    def _check_cancelled(self):
        if self.cancelled():
            raise RuntimeError("Current action stopped")

    def _options(self):
        return dict(cancelled=self.cancelled, on_stage=lambda stage: self.publish(
            message={"lower": "Pen down", "draw": "Draw", "lift": "Pen up", "transfer": "Pen transfer"}.get(
                stage.rsplit("_", 1)[-1], "Move to mark position")))

    def _ai_turn(self, revision):
        self._check_cancelled()
        self._update("thinking", revision, decision="choosing")
        if self.mode == THREE_STONE_MODE:
            target = self.game.suggest_move(randomize_four_ties=True)
        else:
            target = self.game.suggest_move()
        self._check_cancelled()
        if target is None:
            raise RuntimeError("AI turn did not finish")
        mark = self.game.turn
        self._update("drawing_" + self._mark(mark).lower(), revision, decision="chosen")
        self.game.play(mark, *target, **self._options())

    def _complete_round(self):
        self.rounds.append(self._player_scores())
        if len(self.rounds) == 1:
            return "between_rounds"
        total = self._totals()
        for criterion in ("points", "lines"):
            player, ai = total["player"][criterion], total["ai"][criterion]
            if player != ai:
                self.match_winner = "player" if player > ai else "ai"
                self.decided_by = criterion
                break
        else:
            self.match_winner = secrets.choice(("player", "ai"))
            self.decided_by = "coin"
        return "finished"

    def _draw_winning_line(self, revision):
        """Draw a terminal decoration once; an uncertain/failed stroke is never replayed."""
        if (not self.draw_winning_line or self.mode == 'score'
                or self.winning_line is not None):
            return
        cells = self.game.winning_cells()
        if not cells:
            return
        points = [self.game.cell_center(*cells[0]), self.game.cell_center(*cells[-1])]
        self.winning_line = dict(status='pending', cells=cells, points=points)
        self._update('drawing_win_line', revision)
        try:
            self._check_cancelled()
            self.winning_line = dict(self.winning_line, status='drawing')
            self._update('drawing_win_line', revision, message='Drawing the winning line')
            result = self.actions.draw([points], **self._options())
            if not isinstance(result, dict) or result.get('passed') is not True:
                raise RuntimeError('Winning line drawing was not verified')
            self._check_cancelled()
        except Exception as error:
            self.winning_line = dict(self.winning_line, status='failed', error=str(error))
            self._update('finished', revision)
            raise
        self.winning_line = dict(self.winning_line, status='completed')

    def move(self, row, col, revision):
        self._player_move(row, col, revision, observed=False)

    def register_observed_move(self, row, col, mark, revision):
        '''Register an already-drawn player mark in a supported visual game.'''
        if self.game is None or (self.mode, self.game.rows) not in VISION_MODES:
            raise ValueError("Unsupported board for visual move registration")
        if mark != self.active_mark:
            raise ValueError("Detected symbol does not match the current player symbol")
        self._player_move(row, col, revision, observed=True)

    def _player_move(self, row, col, revision, *, observed):
        game = self.game
        if game is None or game.phase != "playing" or (
                self.opponent == "ai" and game.turn != self.human):
            raise ValueError("Cannot place a mark now")
        game.cell_center(row, col)
        if game.board[row*game.columns+col]:
            raise ValueError("This cell is occupied")
        try:
            self._check_cancelled()
            if observed:
                game.record_observed_move(game.turn, row, col)
            else:
                self._update("drawing_" + self.active_mark.lower(), revision)
                game.play(game.turn, row, col, **self._options())
            if not game.outcome and self.opponent == "ai":
                self._ai_turn(revision)
        except Exception:
            self.block(revision)
            raise
        if not game.outcome:
            phase = "player"
        else:
            phase = self._complete_round() if self.mode == "score" else "finished"
            self._draw_winning_line(revision)
        self._update(phase, revision)
