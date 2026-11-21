# Freehand game input: local simulation verification

Date: 2026-11-22. Environment: WSL Ubuntu-22.04, ROS2 Humble, local original Piper/Gazebo assets, isolated ROS_DOMAIN_ID=187, Gazebo master port 11605. No real robot or cloud commands were sent.

## Implemented behavior

The game page offers freehand input for 3x3 Tic-Tac-Toe and 9x9 Four-in-a-Row,
with either two players or Player vs AI. Pointer strokes retain their order,
can be undone/cleared before submission, and are sent with the active revision.
There is no proposed row or column in a freehand request.

The simulation executes these strokes using the existing CanvasDrawing path,
paints measured robot feedback, returns to zero, and obtains three fresh
consistent camera observations. Only the observed new mark is committed.
An invalid revision, busy worker, unsupported board or real environment rejects
the request. Ambiguous/wrong/duplicate occupied-cell ink pauses progression;
physical/simulated ink is not erased merely by reverting a logical move.
Cross-cell ink and obvious single-stroke closed convex triangles/quadrilaterals
receive additional geometric vetoes before registration.

## Actual Gazebo and browser evidence

| Jobs | Result |
| --- | --- |
| 1-3 | Two players: handwrite X in row 1 column 1, then O in row 2 column 2; both camera-confirmed and turn changed |
| 4 | Repeated occupied-cell O: blocked, existing two marks retained |
| 5-6 | Player vs AI: handwritten X confirmed before AI drew O |
| 7-8 | Negative test exposed a bug: YOLO called a triangle X in three frames and it was committed |
| 9-10 | After the fix: normal handwritten X still confirmed before AI reply |
| 11-12 | Same triangle after fix: polygon veto blocked registration; board stayed empty |
| 13-15 | 9x9: handwritten X at row 1 column 9 and O at row 2 column 9 confirmed from camera |
| 16 | 9x9 repeated occupied-cell O: blocked with both prior marks retained |
| 17-18 | 9x9 cross-cell X: no unique valid camera change; blocked with empty logical board |
| 19 | Final clean 3x3 two-player handwriting board, ready for manual use |

Camera acceptance for each successful manual move is recorded as three distinct
sequence numbers in job JSON. The renderer uses measured motion feedback;
this was not an image-only fixture. Detailed evidence remains at
`/home/cooper/ros2_ws/handwriting_test_20261122/gui/job-*.json` and job PNGs.
Windows screenshots, browser scripts, compact results and job-summary.json are
under `C:/Users/Administrator/Documents/Robot_Developer_Masterclass/outputs/game-handwriting-20261122/`.

The simulation used yolo26n_sim_v1_baseline_20261118/weights/best.pt, SHA256
`24d0660ece8f3e722b2e7b2fa766b38f1e5b0df4fc7d0e8b4dd37f36c74ca7d7`.
No model weights or trained thresholds changed.

## Checks

- `python3 -m pytest -q tictactoe_coordinator/test tictactoe_gui/test tictactoe_perception/test -m "not linter" --disable-warnings`: 204 passed, 3 deselected.
- Headless Chrome `test_handwriting_page.cjs`: 3x3/9x9 pointer capture, undo, clear, draft retention during poll/resume, no command replay, cell-free payload and delayed state commitment passed.
- Headless Chrome `test_two_player_page.cjs`: first-symbol controls, both turns, winner labels, AI-mode preservation passed.
- Existing page-resume regression passed.
- Focused Ruff E9/F63/F7/F82 checks on changed logic and new Python tests passed; JavaScript syntax and Git whitespace checks passed.
- `colcon build --packages-select tictactoe_coordinator tictactoe_gui --symlink-install`: both packages built.

The first simulator launch failed because its archived Gazebo environment was
not sourced. Sourcing the existing support/environment.bash repaired the launch;
failed owned processes were cleaned, and only one managed simulator was started.
Template repository-wide style checks are outside this functional run; no mass
formatting or new editor/linter configuration was introduced.

## Limits and next acceptance

The polygon veto addresses the observed false positive; it is not a universal
shape recognizer and does not repair YOLO itself. Multi-stroke polygons and
other unfamiliar scribbles can still be misclassified. Add hard negatives and
independent evaluation before claiming broad invalid-symbol rejection.

Wrong/absent/multiple marks, stale revisions, cross-cell and occupied-cell cases
also have isolated regression tests. The actual cross-cell run was rejected by
the camera gate, while the extra single-detected-fragment veto has unit evidence.
No full game or exhaustive freehand robustness claim is made.

Hardware freehand execution remains disabled pending explicit real integration
and validation. Direct human writing on a physical board without GUI proxy is
not implemented by this slice. No ROS planner/controller or model was replaced.

Tool boundary: pytest, browser tests, colcon, ROS camera/motion feedback, logs and
Git diff were used. Additional debugger sessions, PlotJuggler, rosbag recording,
coverage and generated Doxygen output were deferred because no controller or
trajectory algorithm changed and the behavior has endpoint/job/camera evidence.
No course-learning PASS or other track progress was changed.
