# Unified detector configuration and simulation verification

2026-11-22, WSL Ubuntu-22.04 / ROS2 Humble. User-selected test default:
`xo_real_nine_zero_candidate.pt`, SHA256
`1efa1bca908cb9efb8c2d1d10bf8676eb8026f44ed21fbfe7bcf179fab25b036`.

## Configuration change

- `robot_games_real.launch.py`: shared configurable `weights` argument defaults
  to the candidate; no separate 9x9 override is passed. RealBoardPerception uses
  the same model for 3x3 and its existing four-zone 9x9 inference path.
- `canvas_sim.launch.py`: default preview_weights is the installed candidate.
- setup.py now installs the candidate as well as xo_real.pt and xo_real_nine.pt.
- All three source/installed model hashes were checked; older files are unchanged.
- Standalone CLI model arguments and launch overrides remain available for rollback.

Selecting this default is an explicit experiment choice, not evidence that the
candidate is uniformly better. The historical 3x3 regression warning in the model
README remains valid evidence. No weights were retrained or thresholds changed.

## Checks actually performed

- `colcon build --packages-select tictactoe_coordinator tictactoe_gui --symlink-install`: 2 packages built.
- `ros2 launch tictactoe_gui robot_games_real.launch.py --show-args`: installed candidate path confirmed without starting real services.
- Focused Ruff E9/F63/F7/F82 checks on changed launch/setup files, JS/page-resume checks and Git whitespace check passed.
- `python3 -m pytest -q tictactoe_gui/test/test_real_board_perception.py tictactoe_gui/test/test_real_game_gui.py tictactoe_gui/test/test_game_handwriting.py --disable-warnings`: 33 passed.

## Actual simulation

Reused the existing single managed Gazebo/MoveIt session in ROS domain 187,
master port 11605. Restarted only the simulation GUI backend with no model-path
override; the actual process command confirms the installed candidate was loaded.
The robot executed mouse-drawn strokes and the rendered ink came from measured
feedback. Camera recognition, not requested row/column, committed each move.

| Job | Board | Observed result |
| --- | --- | --- |
| 1 | 3x3 | Start two-player freehand game |
| 2 | 3x3 | X confirmed at row 1 column 1 in three fresh frames |
| 3 | 3x3 | O confirmed at row 2 column 2 in three fresh frames |
| 4 | 9x9 | Start two-player freehand game |
| 5 | 9x9 | X confirmed at row 1 column 9 in three fresh frames |
| 6 | 9x9 | O confirmed at row 2 column 9 in three fresh frames |

Actual job/camera evidence: `/home/cooper/ros2_ws/unified_model_test_20261122/gui/`.
Compact job-summary.json, runtime-config.json and browser screenshots/scripts:
`C:/Users/Administrator/Documents/Robot_Developer_Masterclass/outputs/unified-model-20261122/`.

CPU replay using this same candidate on the final job-3 and job-6 camera PNGs
also recovered exactly the two expected symbols and cells for each image.
The 3x3 call took 1.159 s including first model load; warm 9x9 call took .135 s
with two Torch threads. These are local CPU observations, not cloud latency
claims or an apples-to-apples speed comparison between board sizes.

## Boundary

This is a four-positive-mark runtime smoke test, not a new accuracy benchmark.
It does not supersede held-out metrics or verify every edge/dense layout.
No cloud synchronization or real-robot motion was performed in this slice.
The next real test should use the same installed shared default for both sizes,
retain raw frames, and check upper/right-edge recognition and failure recovery.

Tests/build/logs/actual camera feedback and Git were relevant here. Additional
controller debugging, rosbag, PlotJuggler, coverage and Doxygen generation were
not needed for this model-path/package-data change. Existing model history and
other tracks' learning progress were preserved.
