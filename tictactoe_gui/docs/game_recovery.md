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

Grid preparation has a separate conservative continuation: only a stop before
the active unsegmented line begins (transfer/lowering stage) permits drawing
the unstarted suffix. Completed source strokes are omitted. A stop during drawing
or an inconsistent/mismatched progress record does not enable grid replay.

Live camera observation records numeric class confidence and the rectified
polygon per cell alongside the exact observed frame sequence. This adds evidence;
it does not change inference thresholds or accepted board states.

## Verification before real deployment

2026-11-22, WSL Ubuntu-22.04 / ROS2 Humble: GUI, coordinator and perception
functional regression: 216 passed, 3 linter tests deselected. Existing broad
flake8/pep257 checks report repository-wide style debt; no mass formatting was
performed. New tests cover interrupted visible/absent marks, unchanged turns,
exact-job confirmation, low-clearance rejection and refusal to reuse an old stop.
Native headless Chrome tests passed for inspected resume, handwriting, two-player
controls and page suspension/no replay. These are local tests; real recovery
evidence must be recorded separately.

## Initial suspended approach recovery

A feedback-only interruption before the first input stroke has begun can replan
once automatically. The accepted job must match, input/part completion must be
zero, and the recorded stage and actual pose must show suspended clearance of
at least 211 mm. Existing terminal-action and stationary-feedback confirmation
is still required. The replacement command plans fresh geometry; it does not
resume an old trajectory. Contact, partial ink, caller stops, another job, and
unknown HTTP submission outcomes are not retried automatically.

2026-11-22 local functional regression: 233 passed, 3 linter tests deselected.
The seven added cases verify eligible initial approach, contact/partial progress,
caller stop, job mismatch, and refusal to retry an unknown transport outcome.
Real evidence for this automatic path is recorded separately from the successful
inspected player-turn and remaining-grid-strokes recovery tests.