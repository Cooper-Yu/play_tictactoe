# Model ownership migration — 2026-11-22

The current default is `tictactoe_perception/models/xo_newest.pt`. This is a
rename of `tictactoe_gui/models/xo_real_nine_zero_candidate.pt`, with no retraining
or checkpoint modification. Both earlier weights remain under `models/archive/`.

| Asset | SHA-256 |
|---|---|
| xo_newest.pt | 1efa1bca908cb9efb8c2d1d10bf8676eb8026f44ed21fbfe7bcf179fab25b036 |
| archive/xo_real.pt | 83f4f856101527884a0309f7c6307cb1b8e25de083cae292e02c27cb691b3ef8 |
| archive/xo_real_nine.pt | 0f9b3d21602debf1772f743ac5073e8e84335750797aee49607c63ad8760d9da |

## Local verification

Environment: WSL Ubuntu-22.04, ROS 2 Humble. No cloud update or hardware motion.

- `colcon build --packages-select tictactoe_perception tictactoe_gui --symlink-install`: both passed.
- Both GUI launch files resolve their default weights through the installed
  `tictactoe_perception` package share directory. Actual canvas process arguments
  confirm `share/tictactoe_perception/models/xo_newest.pt`.
- Four relevant test files: 38 passed (`test_compare_real_models.py`,
  `test_real_board_perception.py`, `test_real_game_gui.py`, `test_game_handwriting.py`).
- Replayed 391 real images through each of the three relocated weights. All 1,173
  per-image scores/detections match the frozen pre-migration evaluation; no hash changed.
- Focused Python error checks and `git diff --check` passed.
- Local browser integration: actual mouse handwriting is drawn in Gazebo,
  recognized from camera frames, and committed to the correct cells. Passed 3x3 top-left X / center O and 9x9 right-edge X (1,9) / O (2,9);
  all four marks committed after camera confirmation.

Evidence on the Windows control side:
`outputs/model-migration-20261122/` (build/check logs, replay-comparison.json,
live-results.json, nine-results.json and browser screenshots).
WSL replay: `data/evaluations/model_migration_20261122/`.

## Simulation startup limitation

Cold Gazebo startup exceeded the original 30-second spawn-service timeout.
A separate readiness helper also exited after its first five-second discovery
poll. For this migration verification only, an owned headless fixture used a
90-second spawn timeout and shared the existing 60-second readiness deadline.
All four controllers became active before GUI motion tests.
These fixture changes are outside the source repository; this model migration
is not a claim that the general simulation cold-start issue is fixed.

An auxiliary session-test invocation initially failed: ROS was not sourced,
and the existing duplicate-start test expects a process-discovery message while
the managed-session lock rejects the duplicate earlier. Neither result concerns
model loading. No unrelated source changes are included in this migration.
