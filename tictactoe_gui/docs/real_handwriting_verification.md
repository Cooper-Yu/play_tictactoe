# Real freehand games and GUI acceptance

Date: 2026-11-22. Target: real Piper arm, The Construct rosject 1063805.
This is integration/runtime evidence, not a course-learning PASS or a guarantee
of continuous operation. Camera and MoveGroup were supplied by the user.

## Fixed configuration

- All board writing: base_link Z=206 mm. The proposed 205.9-mm test was declined;
  it was not performed. In-board hover 211 mm, transfer height 216 mm.
- Contact velocity and acceleration scaling 45%; existing pen/transfer motions
  100%. Reset retains the calibrated 206.97-mm/216-mm pair.
- /joint_states remains the control source. No migration to single-state topics,
  controller change, timeout relaxation or threshold/model tuning was performed.
- xo_newest.pt from tictactoe_perception, SHA256
  `1efa1bca908cb9efb8c2d1d10bf8676eb8026f44ed21fbfe7bcf179fab25b036`.
  CPU inference in the cloud, confidence .25, IoU .70, end2end=False; native
  four-quadrant processing for 9x9. No local inference server is required.

## Implemented integration

Real game freehand requests carry ordered strokes and the active revision;
they do not supply a proposed row/column. The real canvas map preserves the
camera/grid orientation and compensates for its separate inset. After drawing,
the arm returns to zero; three distinct consistent camera frames are required
before player registration. Two-player turns never invoke an AI engine.
The cloud gateway authenticates/forwards the handwriting route and supports its
larger bounded payload. Drawing orientation is established before board entry.

## Completed 3x3 games and negative cases

| Case | Actual result |
| --- | --- |
| Two players, initial session jobs 8-13 | Five camera-confirmed moves; X won the top row; arm at zero |
| Player vs AI, post-fix jobs 4-7 | X proxy strokes were camera-confirmed before AI responses; O won the middle column after six physical marks; arm at zero |
| Occupied-cell overwrite, initial job 39 | O written over existing X; blocked without changing the logical X or turn |
| Triangle, initial job 42 | No accepted new mark; blocked with empty logical board. The live rejection was the camera gate, not evidence that the polygon veto ran |
| Stop, initial job 45 and post-fix job 2 | Stop button interrupted an active suspended transfer, preserved the empty board, and required replanning |
| Post-fix stop -> clear -> new game | Clear completed, then a full AI game ran without another service restart |

## 9x9 position checks

Rows and columns below are one-based and follow the camera-aligned game page.
These are sparse-board examples, not exhaustive accuracy or per-cell repeatability
statistics. Interrupted drawings do not count as recognition failures.

| Row | Column | Symbol | Result | Blocking reason, if any |
| --- | --- | --- | --- | --- |
| 1 | 1 | X | Confirmed |  |
| 1 | 2 | X | Confirmed |  |
| 1 | 3 | O | Confirmed |  |
| 1 | 4 | X | Confirmed |  |
| 1 | 5 | O | Confirmed |  |
| 1 | 6 | O | Confirmed |  |
| 1 | 7 | X | Confirmed |  |
| 1 | 8 | O | Not confirmed | Camera has not confirmed one unique new mark, Inspect the board before continuing |
| 1 | 8 | X | Confirmed |  |
| 1 | 9 | O | Not confirmed | Camera has not confirmed one unique new mark, Inspect the board before continuing; Joint feedback interrupted, Waiting for execution to stop and feedback to recover |
| 1 | 9 | X | Not confirmed | Camera has not confirmed one unique new mark, Inspect the board before continuing |
| 2 | 9 | O | Not confirmed | Camera has not confirmed one unique new mark, Inspect the board before continuing |
| 3 | 4 | O | Confirmed |  |
| 3 | 5 | O | Confirmed |  |
| 3 | 6 | O | Confirmed |  |
| 3 | 9 | X | Confirmed |  |
| 4 | 9 | X | Confirmed |  |
| 5 | 1 | O | Confirmed |  |
| 5 | 4 | X | Confirmed |  |
| 5 | 5 | X | Confirmed |  |
| 5 | 6 | O | Confirmed |  |
| 5 | 6 | X | Confirmed |  |
| 5 | 8 | X | Confirmed |  |
| 5 | 9 | O | Confirmed |  |
| 5 | 9 | X | Confirmed |  |
| 6 | 9 | O | Confirmed |  |
| 7 | 9 | X | Confirmed |  |
| 8 | 9 | O | Confirmed |  |
| 9 | 1 | O | Confirmed |  |
| 9 | 5 | X | Confirmed |  |
| 9 | 9 | O | Confirmed |  |
| 9 | 9 | X | Confirmed |  |

The top-right X was not confirmed at two sizes, and the top-right O also failed
after a completed drawing. Raw ink there was extremely faint. An offline check
of the first tiny-mark frame at 640/1280 and lower confidence found no raw
candidates, so this was not explained by cell ownership/NMS filtering alone.
Contact force was not measured; faint appearance alone does not establish a
pressure, lighting, hardware or model root cause. Height remains unchanged.
An earlier top-right O attempt was interrupted before drawing by feedback loss
and is recorded separately.

## GUI and recovery evidence

- Native pointer strokes, buttons and camera-detection switch were exercised.
  Rectified, edge and detection views rendered 420x567 images without POSTing
  motion. Workbench ROI selection/restoration, brightness +1/reset and cyan
  enhancement selection also produced no motion POSTs.
- Freezing the game page for 15 s left the server camera sequence advancing;
  resuming retained the same finished job/board without replay. Reload during
  9x9 preparation continued the original job.
- A browser response-body protocol error occurred after submitting one X. After
  explicit user-authorized unlock, the original job was confirmed as completed;
  it was not resent. Test helpers now wait for an HTTP response and query task
  state, rather than reading an already-consumed response body or treating an
  old ready state as the newly submitted result.
- Paused-but-connected games now have an explicit connection label. The pending
  camera phase also receives an explicit waiting message rather than the last
  workstation's generic completion message.

## Diagnosed Reset failure and repair

After the first intentional stop, Clear failed with `No accepted plan`.
Recorded hover Z was 0.2160004662952249 m; current Z was
0.21600013100619986 m: a requested prelift of only 3.352890250440943e-7 m.
MoveIt returned an unusable short Cartesian trajectory. Reset now skips only
prelift differences below 0.01 mm, and still plans/verifies the recorded hover
before pressing. A 0.1-mm gap still produces a real lift. No trajectory-shape,
collision, joint-change or final-result check was disabled.

The measured-difference regression failed before the repair, passed afterward,
and the same near-hover real starting position then completed Reset. A second
intentional stop -> clear -> new game passed without another restart.

## Feedback incidents and timing

Initial work jobs 31 and 145 stopped on >1-s feedback loss. Each recovered only
after fresh settled feedback and explicit acknowledgement; partial strokes were
not replayed. The independent ROS subscriber recorded a 3.83-s receipt gap near
the second incident, proving a gap outside the GUI alone. The first incident
predated that subscriber. This does not identify the robot/network/cloud root
cause. The original protection remains enabled.

For the first two AI turns, cloud monotonic timings were respectively:
player motion+return 25.461/25.510 s, camera confirmation .785/.725 s,
post-confirmation AI work 20.847/20.413 s. Local poll-to-poll durations include
observation overhead; prefer the cloud timeline for latency attribution.

## Checks and evidence

- Python GUI/coordinator/perception: 208 passed, 3 deselected.
- Motion/driver after Reset repair: 245 passed, 1 skipped, 3 deselected.
- Native headless Chrome: two-player controls, freehand input, resume/no replay
  and workbench polling passed. Two existing fixtures required repair: waiting
  for the actual new board rather than an already-visible canvas, and using the
  separate drawing-speed selector instead of the travel-speed selector.
- Local Humble colcon build: tictactoe_motion and tictactoe_gui passed. Cloud
  regular colcon build and latest-model hash were rechecked at 4c2526d.
- Git whitespace checks passed. No mass formatting or new editor configuration.
- Cloud evidence: data/real_acceptance_20261122/game (initial),
  post_reset_fix/game, incident JSON, latency.jsonl, feedback-monitor/gap logs.
  Initial and restarted-session job numbers must not be conflated.
- Local evidence: outputs/real-acceptance-20261122 under the Windows Masterclass
  workspace, including move-results.csv, operation history and native screenshots.

Git, pytest, colcon, actual browser controls, ROS feedback and camera/job logs
were used. Additional debugger sessions, PlotJuggler, rosbag, coverage and
generated Doxygen output were deferred; no controller or trajectory algorithm
was replaced. Full invalid-handwriting coverage, uninterrupted operation under
transport outages and universal 9x9 recognition are not claimed.


## Final live checks and booking closeout

- Further top-row tests confirmed O at (1,3), (1,5), (1,6) and X at
  (1,7), (1,8). O at (1,8) was not confirmed; an offline diagnostic found
  confidence .106, below the unchanged production .25 threshold.
- Further right-edge examples passed at rows 3 through 9. The O at (2,9)
  did not produce a unique accepted board change; existing cells also showed
  conflicting X/O detections. It is not classified as an isolated new-O miss.
- During active job 25, a 15-second page freeze left the same server job running
  and camera sequence advancing from 9929 to 10020. The task later blocked on
  recognition, independently of the page suspension.
- The center-only two-player 9x9 test confirmed six physical marks: X at
  (5,4), (5,5), (5,6), and O at (3,4), (3,5), (3,6). The seventh move was
  not submitted. This is not a completed four-in-a-row game.
- The Construct main page unexpectedly changed to /closed while reading the
  sixth move. Unlock could not pass the exact-target check until the user
  restored the project. No unknown stroke was replayed and Chrome was retained.
- After restoration, game job 33 was ready with all six marks and X to move.
  The scheduled closeout had returned the robot to zero: work job 189, ready,
  idle, fresh feedback; position (0.05614219, 0.00000540, 0.21322609) m.
  The raw camera frame was fresh (age .102 s) and saved as nine-center-final.jpg.
  No further motion was submitted. The physical board was intentionally retained.
- Final workbench record/return/delete and free-canvas execution smoke tests
  were not performed before closeout. No temporary pose record was created.
- The final camera-wait message and this report are a local follow-up to cloud
  revision 4c2526d. The restored project did not expose a unique terminal #3,
  so final cloud synchronization/restart was not verified this session.
