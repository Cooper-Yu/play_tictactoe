# Real game continuity after an interruption

The workstation still stops on stale joint feedback. This change does not relax
the feedback timeout, settling checks, collision checks, or trajectory validation.

## Absolute suspended transfers

`Workstation.park` can recover once from a feedback-guard stop belonging to its
own accepted command. It waits up to 35 seconds for terminal execution and the
existing two-second fresh stationary confirmation, acknowledges that exact job,
then requests a new absolute preset plan from the actual state. It never resends
the interrupted trajectory. Recovery below 211 mm, a caller stop, a changed job,
an unknown POST outcome, or repeated failure remains blocked.

## Interrupted player turns

The real game stores `turn-recovery.json` atomically, including original job,
uncommitted board, original strokes, phase, error and available workstation
progress/pose/stop evidence. A stopped player turn can expose **Resume turn after
inspection** instead of requiring a new game and Reset.

The operator must inspect the physical board and pen. The resume request includes
the current revision and original job; stale, duplicate or uninspected requests
are rejected. Fresh idle workstation state and at least 211 mm clearance are
required before a verified return to zero. Original strokes are never replayed.
The same player can then complete a missing mark, or the existing physical mark
can be registered after three fresh consistent camera frames. Shape and cell
checks remain active for the saved handwriting. No row/column is forced into
the logical board.

This first version does not automatically reconstruct a partially drawn stroke,
resume a partially executed AI turn, or restore a live game after process restart.
The persisted checkpoint is evidence, not permission for unattended restart.

## Verification before real deployment

2026-11-22, WSL Ubuntu-22.04 / ROS2 Humble: GUI, coordinator and perception
functional regression: 216 passed, 3 linter tests deselected. Existing broad
flake8/pep257 checks report repository-wide style debt; no mass formatting was
performed. New tests cover interrupted visible/absent marks, unchanged turns,
exact-job confirmation, low-clearance rejection and refusal to reuse an old stop.
Native headless Chrome tests passed for inspected resume, handwriting, two-player
controls and page suspension/no replay. These are local tests; real recovery
evidence must be recorded separately.
