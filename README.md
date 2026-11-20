# Play TicTacToe

## Package layout

- `tictactoe_game` defines board rules, scoring, and move selection.
- `tictactoe_coordinator` coordinates turns and dispatches drawing through the provided actions.
- `tictactoe_motion` handles MoveIt, feedback, pose records, and drawing.
- `tictactoe_perception` handles images and stable player-move confirmation.
- `tictactoe_gui` serves the workstation, freehand canvas, and game pages.



### Simultaneous XY planning

`/plan_xy` plans a straight base_link XY displacement from the current link6 pose.
Set writable `dx` and `dy` (meters); both default to zero. Z and orientation remain
fixed. Planning never executes automatically:

```bash
ros2 param set /motion_planner dx 0.01
ros2 param set /motion_planner dy 0.01
ros2 service call /plan_xy std_srvs/srv/Trigger '{}'
# Wait for "Complete Cartesian trajectory validated" before explicitly executing.
ros2 service call /execute_planned_trajectory std_srvs/srv/Trigger '{}'
```

`CartesianPlanner` uses the configured MoveIt Cartesian service with collision
checking. It rejects partial paths, large adjacent joint changes, stale feedback,
invalid timing and FK deviations from the requested path. FK checks cover returned
points and intermediate controller-spline samples; these are sampled checks, not a continuous
path proof. The existing execution start check, settle verification and
`/stop_motion` remain active. Stopping invalidates late service results.

Humble 2.5.9's Cartesian service times paths at native limits. We conservatively
stretch its time stamps and divide velocities/accelerations; the factor is at
least `1/velocity_scaling`, `1/sqrt(acceleration_scaling)` and the factor needed
for the configured average path speed. This does not promise constant tool speed.
Defaults: 1 mm interpolation, 5 mm/s average speed cap, 0.15 rad adjacent-joint
guard, 0.5 mm sampled path tolerance and 0.003 rad sampled orientation tolerance.
Collision protection depends on the supplied planning scene.

Gazebo-only acceptance: `test/verify_xy_motion.py --output <isolated-directory>`
with common.yaml + sim.yaml, a poses_file inside that directory and an isolated
ROS domain. It starts at SRDF clear, records the baseline, plans/executes
(+1 cm,+1 cm), measures independent FK and actual TF path errors, then replays
the baseline and deletes the temporary record. No hardware test is implied.

### Cloud simulation responsiveness

The measured rosject has 8 logical CPU cores, about 14.7 GiB RAM and no accelerated
GPU renderer (Mesa llvmpipe). An unlimited cgroup CPU quota means no additional
quota below the available cores, not infinite CPU capacity. Four orphaned
version-suffixed gzclient processes previously consumed CPU simultaneously.

For one managed session after sourcing Humble and the workspace overlay:

```bash
python3 tools/simulation_session.py --with-moveit --state-dir /tmp/tictactoe-session
```

This sets two software-rendering threads, refuses duplicate live Gazebo binaries,
and owns all child processes with a unique environment tag. Ctrl+C or creating
`/tmp/tictactoe-session/STOP` stops the session. It automatically ends after 900
seconds; `--duration` can change the bound up to 3600 seconds. It never commands
robot motion. Closing Gazebo's GUI may also terminate the original course launch;
the manager then cleans the rest of its own session. Reuse the existing session
rather than starting the original launch repeatedly. The manager does not kill
unmanaged user sessions or change physics, camera resolution or course assets.

The manager also disables Gazebo scene shadows after startup. This is a reversible
rendering change; use `--keep-shadows` to preserve the original appearance. On the
measured software-rendered cloud session, an on/off comparison of the GUI camera
update topic measured about 1.1–1.2 Hz with shadows and 4.5–5.7 Hz without them.
The physics real-time factor remained approximately 0.95–0.97. This improves visual
feedback but does not make the CPU renderer as smooth as a local GPU.

### Airborne X and O

`/plan_cross` uses `cross_size` (default 0.02 m) for two XY diagonals with an
explicit same-height transfer between them. `/plan_circle` uses `circle_radius`
(default 0.01 m), starting on the left rim and returning to that exact pose.
Both keep link6 Z and orientation fixed and require separate execution:

```bash
ros2 service call /plan_cross std_srvs/srv/Trigger '{}'
# After complete-path validation:
ros2 service call /execute_planned_trajectory std_srvs/srv/Trigger '{}'
# Return to the recorded baseline before a separate circle test.
ros2 service call /plan_circle std_srvs/srv/Trigger '{}'
ros2 service call /execute_planned_trajectory std_srvs/srv/Trigger '{}'
```

These are airborne gesture demonstrations. The X transfer is visible because
there is no pen lift in this task. Contact drawing will require separate stroke
and lift handling.

`drawing_paths.py` only generates poses; the shared `CartesianPlanner` performs
collision-aware planning, time stretching and geometric validation. Before a
trajectory becomes executable, FK samples cover quarter points of each controller
spline segment and check both deviation from the requested path and coverage of
its waypoints. Coverage matters for a closed O: returning to its start alone is
not evidence of traversing a circle. Linear/cubic/quintic interpolation follows
provided trajectory derivatives, as described in the
[ROS2 controller documentation](https://control.ros.org/humble/doc/ros2_controllers/joint_trajectory_controller/doc/trajectory.html).
The checks are sampled bounds, not a proof over every instant.

`test/verify_drawing_motion.py` exercises both gestures in Gazebo from clear,
checks an independent denser FK sample grid and measured TF coverage/deviation,
and returns to the recorded clear baseline after each gesture. Temporary records
are removed. Existing execution and software-stop interfaces are reused.

For an interactive development session that stays running:

```bash
python3 tools/simulation_session.py --with-moveit --duration 0 \
  --state-dir ~/ros2_ws/.play_tictactoe_simulation
```

`--duration 0` explicitly keeps the session alive until Ctrl+C or its `STOP` file.
Keep one browser and this simulator/MoveIt instance while rebuilding or restarting
only the application's nodes. Temporary test records can be deleted independently.
The manager waits for the owned Gazebo arm controller before starting MoveIt. If
the course loader strands an already loaded arm in `unconfigured` after its CLI
response timeout, a simulation-only helper waits a grace period, configures it,
then activates it. It requires a session-tagged gzserver and rejects hardware
bridge nodes. It sends no trajectory goals; unknown service results fail closed.

### Zero, coordinate, descent, retraction, zero

`PoseCycle` coordinates five verified driver primitives. The simulation driver
plans and executes each stage, waits for settling and checks the result before
continuing. A failure or software stop aborts the sequence without issuing a
recovery movement. Retraction uses the saved achieved upper position, rather than
adding distance to a potentially imperfect lower measurement.

`MotionPlanner.request_pose_plan()` supplies absolute base_link pose planning;
`CartesianPlanner.request_linear_position()` supplies a straight XYZ translation
while keeping the achieved orientation. Existing XY/X/O entry points still use
their fixed-height checks.

For the simulation demo, source the workspace/ROS environment and select its domain,
then run from the repository root against the already running simulator/MoveIt:

```bash
python3 tictactoe_motion/test/verify_pose_cycle.py --output /tmp/pose-cycle-check \
  --distance 0.01 --clearance 0.03 --ros-args \
  --params-file tictactoe_motion/config/common.yaml \
  --params-file tictactoe_motion/config/sim.yaml \
  -p poses_file:=/tmp/pose-cycle-check/poses_sim.json -p state_log_period:=0.0
```

The default target is computed from the currently running MoveIt SRDF `clear`
configuration by FK, then raised 3 cm in base_link Z. It visits `zero`, moves to
that pose, descends 1 cm, returns to the achieved upper pose, then returns to
`zero`. `--target X Y Z` instead supplies an absolute target in meters; the demo
retains the clear preset's orientation. Descent distance is limited to 5 cm.
The demo refuses non-simulation graphs and only runs as an explicit command; it
does not add an automatic startup movement, ROS sequence service or GUI button.

### X/O with explicit Z pen motion (simulation demo)

`StrokeDrawing` separates X into two strokes: lower, draw, lift, transfer at the
saved upper height, lower, draw, lift. O lowers once, traces a closed circle,
then lifts. Z is along `base_link`; link6 orientation is preserved. A failed or
cancelled stage prevents all subsequent motion requests; there is no automatic
recovery motion or physical-contact detection.

With the existing Gazebo and MoveIt running, use `tictactoe_motion/test/verify_stroke_drawing.py`
with `--output <temporary-directory>` and the common/sim ROS parameter files.
It approaches clear FK +3 cm Z, draws a 2 cm X and 1 cm radius O at 1 cm
below that upper plane, then returns to zero. These are airborne simulation
motions. This script is not a real-robot launch or a new ROS service.

### Bounded board canvas and virtual simulation ink

`config/board_sim.yaml` contains derived geometry from the installed course
world, SDF and material-separated board mesh. It is simulation-only and is not a
ROS parameter file. `tools/extract_sim_board.py` reproduces it from `--share`.
The black screen has rounded corners; the usable rectangle is inset by 5 mm.
The white Reset visual has no physical button sensor in the supplied model.

`BoardCanvas` maps normalized `[0,1]` drawing coordinates into a 0.5 mm implicit
grid. Outside inputs are rejected before snapping. `snap=False` retains curve
samples for circles/arcs: the grid is a positioning aid, not a requirement that
curves become staircase paths. Each stroke is limited to 500 waypoints and
0.3 m; split longer drawings at explicit pen-up boundaries. Camera orientation
is not used by this model-coordinate mapping.

`CanvasDrawing` approaches, lowers, traces and lifts each separately validated
stroke. The simulation uses link6 Z=0.22 m while raised and 0.21 m while drawing.
An earlier Z=0.25 m target at (0.1712,0.0283) required joint5 about1.251 rad,
beyond its configured1.22 rad limit; live limits were not relaxed. A 5x5 IK
sample at Z=0.22/0.21 m succeeded, but every requested path still needs planning
and verification. Geometry inside the board does not prove general reachability.

`SimulatedBoard` projects actual executed link6 XY samples onto the screen and
spawns one visual-only ribbon mesh per completed stroke. It does not render a
predefined X/O icon, infer pen contact, or calibrate a physical pen TCP. In this
first version ink appears after each stroke is verified, not continuously.
A downward virtual Reset gesture over the extracted button clears only this
renderer's owned ink models. Tests remove their ink entities and generated files.
The drawing/reference height is deliberately separate from the screen surface.

Simulation acceptance: `tictactoe_motion/test/verify_board_canvas.py --output <dir>`
with common/sim parameter files. It checks loaded board/base poses, draws a grid X,
a snapped O and a smooth O, verifies spawned entities, performs the virtual Reset,
checks deletion and returns to zero. It captures before/written/cleared camera
frames. A small Web drawing canvas is the next integration step.

For the faster simulation-only canvas profile, add
`--params-file tictactoe_motion/config/board_demo_sim.yaml` after the sim file.
This sets Cartesian speed to 20 mm/s and velocity/acceleration scaling to 0.3.
The real launch and conservative common/sim defaults stay unchanged. Add
`--test-stop` to the acceptance script to verify an explicit mid-line software
stop, fresh settled feedback, rejection of the old plan, and a newly planned
return to zero. The profile is optional; timing is not a hardware speed claim.

### Parameterized drawing actions and explicit-turn TicTacToe

`drawing_actions.py` contains `DrawingActions`. It receives a board canvas and an
existing motion driver; it does not create another node or own robot feedback.
Positions are normalized board-local `(u,v)` centers; dimensions are meters.

```python
actions = DrawingActions(canvas, driver, upper_z=0.22, depth=0.01)
actions.draw_grid(center=(0.5, 0.5), width=0.06, height=0.06)
actions.draw_x(center=(0.4, 0.4), size=0.012)
actions.draw_o(center=(0.6, 0.4), radius=0.005)
```

`size` is the X bounding-square edge, not the diagonal length. `grid_strokes`,
`x_strokes` and `o_strokes` produce validated preview geometry without motion.
Execution still requires explicit draw calls, planning, execution and settling.
The driver/geometry adapter, board calibration, actual tool TCP and verified
hardware-specific parameters are still required for a real-robot migration.
The supplied canvas/renderer and acceptance scripts remain simulation-only.

`tic_tac_toe.py` separately contains `TicTacToe`: explicit alternating X/O inputs,
occupied-cell rejection, win/draw detection and cell placement derived from the
selected grid center/width/height. A mark is committed only after verified drawing.
Failure blocks the game because a partial physical/virtual mark may exist; clear
with the existing Reset mechanism before constructing and starting a new game.
Optional CPU opponent suggestions use the confirmed game state. YOLO turn observation is a separate input to the game coordinator.

`test/verify_tictactoe_game.py` executes a 60x60 mm grid and five explicit moves
until X wins, captures the displayed board, triggers virtual Reset and returns
to zero. Use the common, sim and optional board_demo_sim parameter files as in
the canvas acceptance. This is the motion/game foundation for the future small
Web canvas, not a completed GUI.

### Larger grids and X/O five-in-a-row

`DrawingActions.draw_grid(..., rows=9, columns=9)` draws a 9x9 **cell** grid;
rows/columns are configurable from 2 to15 (up to28 internal lines, with lifted
transfers). The original3x3 default remains compatible. Width and height are
independent metric dimensions. Game symbols scale from
`cell_size = min(width / columns, height / rows)`:
X edge=0.55*cell_size, O radius=0.25*cell_size.

`GridGame` provides shared explicit-turn state. `TicTacToe` preserves three-in-a-row;
`Gomoku` defaults to9x9 cells and five-in-a-row. This airborne X/O variant uses
cell centers, permits overlines (five or more), and has no renju forbidden moves.
Winning runs cannot cross row boundaries or gaps. Failed
execution blocks further turns without committing a phantom mark.

`test/verify_gomoku_game.py` draws a90x90mm9x9 grid (10mm cells,5.5mm X edges,
2.5mm O radii), alternates nine specified moves to an X win, verifies30 measured
ink models, performs virtual Reset and returns tozero. Use the same common/sim/
board_demo_sim ROS parameter files and a temporary output/poses file. The larger
9cm lines use a0.75rad cumulative-excursion test envelope; the normal helper
remains0.5rad and the production per-sample jump, FK path, joint-limit, collision
and execution checks remain in force. This is one demonstrated configuration,
not runtime certification of all sizes or all board cells.

### CPU decision engines

Call `choose_move(board, player)` with a confirmed 3x3 or 9x9 matrix containing
empty strings, X, and O. X moves first. The return value is a zero-based
`(row, col)`, or `None` for a finished game. `game.suggest_move()` reads an
existing game's confirmed state and turn. The caller can then use `game.play()`.

The 3x3 engine uses Python Minimax. The 9x9 freestyle engine uses the
[Rapfi release](https://github.com/dotb1ue/rapfi/releases) as a separate Linux
process over standard input and output. Extract the release's configuration
and evaluation weights beside the Linux executable, then set
`TICTACTOE_RAPFI` to its absolute path. Choose a build supported by the CPU.
The adapter requests 500 ms per move by default and validates the returned
cell before handing it to the caller. A missing engine or protocol error fails
the suggestion without recording a move.

Pass `--decision` to either Gazebo game verification script to draw the final
move selected by its engine. The earlier scripted moves set up a winning position.

### Scalable illustration materials

`IllustrationDrawing` reuses `DrawingActions` and its existing motion driver.
The local material library is
[tictactoe_motion/tictactoe_motion/illustrations](tictactoe_motion/tictactoe_motion/illustrations/README.md):
chair centerlines, Docker outlines and a full smile with slightly offset double
strokes. JSON contains normalized pen paths and source attribution; SVG provides
a resolution-independent preview of the same paths.

```python
from tictactoe_motion.illustration_drawing import IllustrationDrawing

picture = IllustrationDrawing(actions)
paths = picture.strokes('chair', center=(0.5, 0.5), width=0.06, rotation=180)
picture.draw('chair', center=(0.5, 0.5), width=0.06, rotation=180)
picture.export_svg('chair', '/tmp/chair.svg')
```

Width is in meters and scaling preserves the physical aspect ratio. Center uses
board-local `(u,v)` and rotation is in the canvas plane. The 180-degree simulation
view choice is not camera calibration. All geometry batches are validated before
movement; acute reversals use separate lifted strokes. Identical consecutive
stroke endpoints do not require a zero-length hover transfer. The supplied canvas
and acceptance remain simulation-only; changing size or placement still requires
planning and execution checks.

`test/verify_illustration.py --shape chair|docker|smile --output <owned-run-dir>`
uses the existing common/sim/optional board_demo_sim parameter files, an owned
`poses_file`, and `cartesian_step:=0.0003`. It records actual TF, renders measured
ink, verifies virtual Reset, and returns to zero on normal completion. A complete
60mm-width local run passed for all three assets (82/12/12 lifted strokes).
The smile's outer face, eyes and mouth use two slightly offset paths, while the
simulated pen width remains 1mm. Rounded mesh joins/caps fill corner holes in the
rendered pen footprint; they do not change robot waypoints or pressure.

The chair is an approximate repaired raster trace rather than the original
vector artwork. Docker is an outline, without solid-region fill. The supplied
materials do not constitute a completed Web GUI or real-robot calibration.
## Local tablet canvas

See [tictactoe_gui/README.md](tictactoe_gui/README.md) for the local simulation-only Web tablet. Draw ordered strokes or load the chair/whale/smile previews, then explicitly execute; startup and asset selection never move the arm. The white Reset button clears the composite simulation ink in one operation.


### Real board drawing (measured profile)

`config/board_real.yaml` in `tictactoe_motion` stores a separate inward rectangle
(138.004 x 177.005 mm), writing link6 Z=0.206 m, hover Z=0.216 m.
Original four-corner pose/screenshot records are not overwritten. Screen-right maps
to base -X, screen-down to base +Y; this is not camera-to-base TF calibration.
The calibration assumes the same fixed board, pen mounting and clear orientation.

The real localization workbench now offers X, O and a 3x3 grid at the canvas center.
The dimension is the X square edge, O diameter, or grid total edge (8..60 mm).
The first physical checks should use 12 mm X/O; speed is limited to 10% (raised at the user request after the initial 5% tests).
Drawing executes immediately, preserves orientation, lifts before lateral transfer,
and finishes hovering. Move to the verified clear orientation first; a different
orientation is rejected before motion. Stop and feedback-loss handling stay active.
The API accepts `kind=draw`, `shape=x|o|grid`, metric `size`, `speed`, and optional
normalized `center=[u,v]`. Geometry is validated before any drawing movement.
`motion_completed` does not assert visible ink: `ink_confirmed` remains null.
Simulation retains its previous canvas, renderer and reset semantics; this real
workbench entry is rejected in simulation. A first physical 12 mm X/O run completed and both marks were visible. A subsequent reset-first 60 mm grid completed all 17 motion stages and four visible
lines. This is one physical verification, not an autonomous game or repeatability
certification. A later hovering camera-clearance jog stopped on a 1.027 s feedback
gap crossing the unchanged 1.0 s guard.


Before the next real drawing test, run the complete Reset action and visually
check that the board cleared (user instruction, 2026-11-16). Stops now retain
`last_stop` with job, source and first reason, also logged as `WORKBENCH_STOP`.
Later cleanup stop requests preserve the initial cause; feedback-loss thresholds
are unchanged. Earlier interrupted runs had no such audit and are not assigned a
root cause retrospectively.

Real drawing and normal jog controls now default to 10% speed scaling. Both the
request validator and board profile cap drawing at 10%; 5% remains selectable.
ResetAction retains its independent 5% cap. Feedback freshness remains 1.0 s.
