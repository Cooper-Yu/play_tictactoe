# Tablet canvas GUI

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
