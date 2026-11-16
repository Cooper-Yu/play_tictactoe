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

The explicit hardware entry is `ros2 launch tictactoe_gui localization_real.launch.py`.
It requires the connected physical Piper bridge and official MoveIt server in the same ROS domain.
It checks fresh joint/TF feedback, controller mapping and unique motion owners. Startup does not move or enable hardware.
Real XY steps are limited to 50mm and Z steps to 20mm; velocity scaling stays at 10% maximum, with 5% selected initially. Larger steps require checking clearance first.
Physical records use data/localization_real/poses_real.json and separate screenshots.
For The Construct, use the HTTPS webpage gateway below in a separate browser tab.
The ROS backend stays loopback-only; the gateway exposes only workstation routes through the platform. Hardware operation requires explicit authorization.

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

### The Construct: open the workstation in a browser tab

Keep the workstation backend on localhost:8765. In a second cloud terminal:

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/.play_tictactoe_runtime/install/setup.bash
python3 -m tictactoe_gui.cloud_gateway --public-url "$(webpage_address)"
```

The gateway listens on port 7000, which the platform exposes at the HTTPS URL
printed by `webpage_address`. Open that URL in a separate browser tab. The page
uses relative asset/API paths so the platform's `/webpage/` prefix is retained.
The gateway accepts POST requests only from that exact public origin; the backend
still checks its per-session token, robot readiness and motion limits. No Firefox
or graphical desktop is required. Restart this gateway with the new URL after a
platform slot changes. Keep the ROS backend and MoveIt running independently.
Status polling permits only one outstanding request, with a 3-second timeout. Command acknowledgement does not wait for a status refresh; the server busy state still blocks overlapping robot commands. Read timeouts do not trigger command replay.

### Recorded Reset button cycle

The `Reset／清屏完整动作` button uses records `reset悬空预备` and `Reset`.
Both must belong to the active environment and base_link/link6, align in XY
within 0.5mm, have matching orientation within 0.01rad, and differ by 1–20mm
in Z. Save and verify these two records before enabling the action.

The cycle lifts at the current XY if below the approach height, approaches the
hover record using the existing return planner, descends vertically at no more
than 5% scaling, dwells for 0.3s, and returns vertically to the hover height.
The regular Stop button cancels the cycle; a canceled or failed cycle does not
continue or automatically retreat. A separate user confirmation precedes the
complete cycle. Motion completion is reported separately from actual screen
clearing: automatic visual clear confirmation is not implemented.
### Cyan/blue ink observation mode

Select `青蓝色笔迹增强`, then manually crop a rectangular region inside the black
writing surface, excluding the cyan frame. Until an ROI is selected, only the
original preview is displayed. Strength (0–100) adjusts selective HSV brightness
and saturation; color tolerance (5–45) widens hue selection around cyan/blue.
Positive local brightness contrast suppresses uniformly blue-tinted background.
No stroke dilation, line completion or image reconstruction is performed. The
source image and saved original screenshots remain unchanged. This is a viewing
aid, not a pressure measurement or a certified stroke-detection result.

### Real calibrated drawing canvas

Open `/canvas` from the running localization workstation (or append `canvas` to
its public `/webpage/` URL). The header links back to the localization page.
This is a second view of the same serialized workstation, not another ROS
node or another motion driver. Keep the existing real launch and gateway.

Draw with the mouse/touch pen; releasing finishes a stroke. Undo and Clear Draft
only edit the draft. Execute submits the complete ordered draft explicitly.
The white tablet button performs the real recorded Reset cycle; Stop uses the
same cancellation boundary as the localization workstation. No request is
replayed automatically after a timeout or connection loss.

- Actual calibrated area: about 138.004 by 177.005 mm, with a further 1 mm
  footprint margin. Screen right maps to base -X and down to +Y.
- Drawing Z206 mm, hover Z216 mm and the clear orientation come from
  `board_real.yaml`. Speeds are 5% or 10%; feedback protection is unchanged.
- Up to 32 source strokes / 8000 points; geometry is checked before any motion.
  Long strokes (>60 mm), dense paths or sharp reversals are lifted and split
  while preserving the source order. The backend does not smooth the drawing.
- Chair, whale and smile buttons load editable 60-mm previews; they never start
  motion. Live camera, source-stroke progress and execution segments appear on
  the same page. Motion completion does not claim visual ink confirmation.
- Per-job input, prepared paths, stage evidence and failure/completion reports
  are saved under the active localization data directory's `canvas/` subfolder.
  A stopped drawing is not automatically resumed.

The original standalone simulation canvas and its 180-degree mapping remain
separate. Do not launch that simulation driver against a real arm.
