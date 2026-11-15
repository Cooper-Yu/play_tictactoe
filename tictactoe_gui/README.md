# Robot localization workstation and tablet canvas

The localization workstation is the current main GUI. It follows the original
light/teal calibration reference: camera overview and enhanced ROI above,
base-frame jogging, measured pose and named records below, without page tabs.

```bash
cd ~/ros2_ws
colcon build --packages-select tictactoe_gui --symlink-install
source install/setup.bash
export ROS_DOMAIN_ID=186 ROS_LOCALHOST_ONLY=1
ros2 launch tictactoe_gui localization_sim.launch.py
```

Open **http://localhost:8765/**. Reuse the already-running Gazebo/MoveIt in the
same domain. Run only one GUI/motion demo against that instance at a time.
Startup never moves the robot. The existing canvas remains available through
`canvas_sim.launch.py`; it uses the same default port, so stop the idle helper
before switching interfaces, or specify another port for a separate simulation.

- The camera selector lists `sensor_msgs/msg/Image` topics; `cv_bridge` converts
  incoming frames to BGR. Select a rectangle with the mouse to enhance the same
  image coordinates in subsequent frames. Invalid/tiny selections keep the last
  valid region; selecting the full image clears the ROI. Topic changes clear ROI.
- Python `ImageEnhancer` applies brightness beta from -255 to +255. The original
  remains unchanged; the ROI preview preserves aspect ratio with padding.
  Enlarging a region does not recover missing source detail.
- Camera reception age and observed frame rate remain visible. A delayed camera
  retains its previous image, clearly marked, rather than flashing blank.
  Delay detection uses a bounded 5–10 second window based on received frame rate.
  Screenshot recording still requires a camera/pose timestamp difference <=0.5s.
- X/Y/Z buttons move one selected step (0.5–20mm) in `base_link`, keeping the
  current `link6` orientation. Speed is MoveIt **velocity/acceleration scaling**
  (5/10/20/30%), not a guaranteed Cartesian mm/s speed. Planning failure or a
  failed actual-position comparison reports an error.
- `zero`, `clear`, `clear2` and recorded-point returns are **plan first**, then
  **execute explicitly**. Execution rechecks the actual starting joints. Software
  stop clears queued/pending work and uses the existing bounded stop/settling
  mechanism. It is not a hardware emergency stop.
- Named records save actual joint1–joint6 angles and time-matched `link6` pose in
  `base_link`, after settling, plus a matched full camera screenshot. Custom names,
  explicit overwrite, deletion, startup reload and planned return are supported.
  Default labels are Reset and four board corners; naming a record does not infer
  that it is a calibrated board/contact point.
- Data defaults to `~/ros2_ws/src/play_tictactoe/data/localization_sim/`:
  `poses_sim.json`, `screenshots.json`, `screenshots/*.jpg`. Use
  `output_dir:=/persistent/path` to change it. Runtime data is excluded from Git;
  back it up separately. The Construct must use a persistent rosject directory.

This first workstation has **simulation-only** launch/preflight, with no real-arm
launch or automatic hardware migration. A later real adapter must select real
configuration and verify the actual robot/control/calibration environment.

## Separate tablet canvas

Local, simulation-only tablet UI for freehand strokes and the bundled chair,
Docker outline and smile illustrations. Drawing never starts on page load.
Choose an illustration or draw with a mouse/stylus, then press **执行绘图**.

```bash
cd ~/ros2_ws
colcon build --packages-select tictactoe_motion tictactoe_gui --symlink-install
source install/setup.bash
export ROS_DOMAIN_ID=186 ROS_LOCALHOST_ONLY=1
export GAZEBO_MASTER_URI=http://127.0.0.1:11605
ros2 launch tictactoe_gui canvas_sim.launch.py
```

Reuse the existing Piper Gazebo and MoveIt instance. Their ROS domain must match
this process. Open **http://localhost:8765/** on the same computer. Optional
launch arguments: `port:=8765`, `output_dir:=/absolute/path/to/session`.

The HTTP listener binds only to loopback. ROS remains on a single serialized
worker while HTTP status and stop requests stay responsive. Requests require
a per-session header and a same-origin host. No third-party server or npm
dependency is required. This package intentionally has no real-robot launch.

- Each pointer-down/up gesture creates one ordered stroke. Undo removes the
  last draft stroke; clearing the draft does not clear Gazebo.
- All strokes are checked before movement: 1–32 input strokes, at most 8000
  total input points, 2000 per stroke, finite normalized coordinates.
- The current board profile maps the portrait screen with a 180-degree rotation
  and 1mm centerline inset for the fixed-width pen. No camera TF is assumed.
- Long strokes and sharp reversals are split into lifted segments; source order
  and line geometry are preserved. MoveIt still validates each trajectory.
- Each segment executes elevated approach → lower → trace → lift. The existing
  motion driver checks actual feedback and settling; completion returns to zero.
- Software stop cancels the active sequence, confirms fresh settled feedback,
  and skips the remaining strokes. It never automatically resumes or returns
  to zero after a stop. A new explicit command replans from the achieved state.
- The white tablet button performs the existing virtual Reset gesture, then
  clears one composite ink entity. It does not erase separate strokes in turn.
- Simulation ink is based on measured link6 XY feedback and appears after each
  completed segment. The physical arm stays above the board; this is not pen
  contact or pressure control. Filled shapes and automatic photo tracing are
  outside this initial GUI.

Illustration buttons load editable previews at 60mm width; they never execute
automatically. The preview's inverse map is regression-tested against the
existing illustration library used by previous local/cloud motion tests.

Per-job JSON contains submitted strokes, validated segments, stage order,
observed feedback, execution comparisons and final status. Successful jobs
also save a simulation camera PNG. Existing job numbers are not overwritten
when restarting against the same output directory.

Runtime code:

- `tictactoe_gui/server.py`: local HTTP endpoints and serialized session state.
- `tictactoe_gui/geometry.py`: input, edge footprint and illustration mapping.
- `tictactoe_gui/sim_worker.py`: existing motion/stop/renderer integration.
- `tictactoe_gui/web/`: dependency-free tablet frontend.
- Motion package `simulation_driver.py` / `simulation_scene.py`: the previously
  verified simulation driver promoted from test helpers; old helpers retain
  compatibility imports. No planning/controller limits were relaxed.
