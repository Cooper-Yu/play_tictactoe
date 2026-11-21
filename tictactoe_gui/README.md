# Robot localization workstation and tablet canvas

This package owns the web pages and launch entry points for the localization
workstation, freehand canvas, and game. Game turns are owned by the
`tictactoe_coordinator` package.

The localization workstation is the current main GUI. It follows the original
light/teal calibration reference: camera overview and enhanced ROI above,
base-frame jogging, measured pose and named records below, without page tabs.

```bash
cd ~/ros2_ws
colcon build --packages-up-to tictactoe_gui --symlink-install
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
Real XY steps are limited to 50mm and Z steps to 20mm; motion velocity scaling offers 5% increments up to 100%, with 10% selected initially. Reset remains capped at 10%. Larger steps require checking clearance first.
Physical records use data/localization_real/poses_real.json and separate screenshots.
For The Construct, use the HTTPS webpage gateway below in a separate browser tab.
The ROS backend stays loopback-only; the gateway exposes only workstation routes through the platform. Hardware operation requires explicit authorization.

## Separate tablet canvas

Local, simulation-only tablet UI for freehand strokes and the bundled chair,
Docker outline and smile illustrations. Drawing never starts on page load.
Choose an illustration or draw with a mouse/stylus, then press **执行绘图**.

```bash
cd ~/ros2_ws
colcon build --packages-up-to tictactoe_gui --symlink-install
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
  `board_real.yaml`. Drawing scaling is selectable from 5% to 100% in 5% increments. The default is 10%.
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

### Local robot game

With Gazebo/MoveIt running in an isolated local ROS domain, launch
`canvas_sim.launch.py` and open `http://127.0.0.1:8765/game`.
The canvas home also links there. Use `port:=8768` if launching on that port.

- Choose 3×3 Minimax or 9×9 Rapfi. Set `TICTACTOE_RAPFI` before launch for Rapfi.
- Starting a game creates the calibrated 140×189 mm grid in Gazebo. Click an
  empty cell to ask the arm to draw X. The AI selects O after X is verified.
- Each mark uses measured arm motion, and the board updates only when the mark
  is verified. The displayed Gazebo image refreshes after the round.
- Stop pauses the round. Start a new game to clear the virtual ink and recover
  the board after partial drawing. Clear and exit uses the simulated Reset
  motion. This page requires the existing local Gazebo worker.
The score-based 3×3 mode plays two rounds with reversed first turns. Each
player places four marks per round. The center is worth 3 points, corners 2,
and edge cells 1. Each completed line adds 3 points. Score Minimax searches all
remaining turns. Match rank uses total points and then total lines. An exact
tie is decided randomly and labeled explicitly in the result. The player
can choose the opening side and their mark independently. Round two switches the opening side and keeps both marks.

### 对弈页感知预览

展开相机旁的「感知预览」可查看仿真棋盘的透视校正、Canny 边缘和 YOLO 识别叠加。
识别叠加显示标定格线、识别框及格子的行列编号。9×9 棋盘使用四个重叠区域推理，
同格同时出现 X/O 时显示冲突。预览可以独立查看。

使用默认 Final Project Gazebo 场景启动。校正使用该场景的固定相机参数及对局绘制范围。
校正与边缘无需模型。识别叠加需在同一 Python 环境安装 Ultralytics，并在启动时指定
训练好的权重和设备，例如：

```bash
ros2 launch tictactoe_gui canvas_sim.launch.py \
  preview_weights:="$HOME/ros2_ws/src/play_tictactoe/tictactoe_gui/models/xo_real_nine_zero_candidate.pt" \
  preview_device:=0
```

### 仿真视觉落子

给本地仿真页面配置 YOLO 权重后，普通 3×3 井字棋可以在开局前选择「模拟书写 · 相机识别」。点击空格让仿真机械臂代写玩家符号。机械臂回到 `zero` 后，程序从实时相机取帧，连续三帧确认原有棋子一致、只有一个新增玩家符号时，才把识别出的格位登记到对局并启动 AI 回合。每个回合单独验证，确认失败时暂停对局。

默认落子方式是「网页点格」。视觉模式下，网页格位只供仿真代写使用，识别提交由仿真后台完成。

### Real robot vision game GUI

The existing `/game` page can connect to the real workstation through a local
vision service. It shows the coordinator board, raw camera and YOLO overlay
side by side. A clicked cell only requests a proxy-player drawing. Three distinct
camera frames must confirm one new mark before the coordinator registers it.
A visible physical player mark can also be confirmed while the worker is idle.

```bash
python3 -m tictactoe_gui.real_game \
  --workstation-url "<current webpage_address>" \
  --weights "<real validated best.pt>" \
  --grid-points "<four real internal grid intersections.json>" \
  --output "<game evidence directory>" --port 8775
```

Open `http://localhost:8775/game`. `--device` defaults to CPU. Use `--device 0`
for local GPU inference. The four grid intersections must match the current
camera and physical playing area. New games clear the board and draw the grid
using the calibrated real canvas. Only classic 3x3 vision games are supported.
`--restore-game <finished game.json>` displays a completed game and checks it
against the camera after connecting. While the workstation is unavailable,
the page labels its retained photo and detection overlay as saved images and
disables movement. Update the workstation URL on service launch if the cloud
session changes. Startup and restoring the completed display issue no motion.

### Cloud-only real-robot GUIs

All three GUIs and YOLO inference can run inside the rosject. Local Python,
WSL servers and a local GPU are not required by this deployment.

The robot bridge, camera and the real MoveGroup must already be running.
Install the additional Python packages into the repository-local directory,
not the system Python environment:

```bash
cd ~/ros2_ws/src/play_tictactoe
python3 -m pip install --target .cloud-python --no-deps \
  -r tictactoe_gui/config/cloud-requirements.txt
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --base-paths src/play_tictactoe --packages-up-to tictactoe_gui
source install/setup.bash
ros2 launch tictactoe_gui robot_games_real.launch.py \
  public_url:="$(webpage_address)"
```

This reuses the cloud's installed CPU PyTorch and OpenCV. NumPy 1.26 is pinned
for the ROS Humble cv_bridge binary; the isolated directory avoids changing
other cloud applications. The launch applies this directory to its children.

Open the URL printed by `webpage_address`:

- Root: calibration workbench.
- `canvas`: free drawing canvas.
- `game/`: real-robot Tic-Tac-Toe with camera-confirmed player moves.

One gateway listens on `0.0.0.0:7000`; internal workbench and game servers use
loopback ports 8765 and 8775. Do not start separate copies on those ports.
The launch preserves real localization records under `data/localization_real`
and stores game evidence under `data/cloud_gui`. Startup does not move the arm.
YOLO warms up before the game reports readiness, using CPU with two threads.
The bundled `models/xo_real_nine_zero_candidate.pt` is the user-selected shared test model; older real-camera models remain available for rollback.

`grid_points` accepts a JSON file containing four internal 3x3 grid intersections
in raw-image pixels, ordered top-left, top-right, bottom-right, bottom-left.
Verify alignment after any camera or board change; the bundled calibration is
an existing real setup reference, not automatic calibration.

```bash
ros2 launch tictactoe_gui robot_games_real.launch.py \
  public_url:="$(webpage_address)" grid_points:=/absolute/path/grid_points.json
```

Browser resume refreshes state, camera frames and session tokens without
replaying motion requests. A frozen or disconnected page cannot render live
updates; the cloud worker continues the accepted job. On returning, wait for
synchronization before issuing another command. Real feedback-loss and stop
checks remain active independently of page polling.


## Two-player camera-confirmed games

The game page offers **Players → Two players** for 3×3 Tic-Tac-Toe and
9×9 Four-in-a-Row. **First symbol** selects X or O; each accepted turn then
alternates symbols. Player-vs-AI remains the default. The scoreboard and turn
messages identify Player X / Player O in two-player games.

On real hardware both players use **Robot proxy drawing · Camera confirmation**:
click an empty cell, draw only the current player's mark, return to zero, then
wait for three consistent fresh camera frames before committing a cell and
changing turns. The clicked coordinates are drawing intent, not board-state
truth. No decision engine or automatic opponent reply is called. Physical
camera observations can also be accepted while waiting for the current player.
An unconfirmed, conflicting or failed stroke does not grant the next turn;
inspect the retained board and explicitly reset after a blocked operation.
Existing winner detection, occupied-cell checks, revision checks, stop and
serialized motion guards remain active. Unsupported score/opening/Gomoku
variants keep their existing AI modes.

The simulation worker supports the same opponent setting for local validation.
Frontend and mocked real-worker tests do not replace live camera/robot checks.
Next real session: alternate X/O across the top and right edges and corners;
repeat with the first symbol swapped, retaining snapshots and failed detections.


### Freehand game input (simulation)

Choose **Player input → Freehand writing · Camera confirmation (simulation)**
before starting a supported 3×3 or 9×9 game. Both Player vs AI and Two players
are supported. Draw one symbol directly on the game board, use Undo stroke or
Clear draft if needed, then press Draw and confirm. Multiple strokes preserve
their order. Pointer locations are normalized against the playable grid.

The request includes strokes and the game revision, never a proposed cell.
The simulation arm executes the actual strokes and returns to zero. Three fresh,
consistent camera observations must identify exactly one new expected symbol
while preserving every existing symbol. Only the observed cell is committed;
then the other player or AI acts. Cross-cell ink also blocks registration even
when only one fragment is detected. Wrong, missing, ambiguous, or duplicate
occupied-cell marks pause the game without changing its board state.

Ink already executed cannot be undone by editing the browser draft. Inspect the
physical/simulated board and explicitly clear/start a new game after failure.
This first implementation is simulation-only; the real server rejects freehand
requests until the hardware integration is separately validated. Direct human
writing on a physical tablet remains a separate future input integration.


### Shared detector selected for the next tests

The default real-game launch and simulation canvas launch load
`models/xo_real_nine_zero_candidate.pt` for both 3x3 and 9x9. The original
`xo_real.pt` and `xo_real_nine.pt` remain bundled for comparison and rollback.
Use real-launch `weights:=...` or simulation `preview_weights:=...` to override.
This user-selected test default does not imply it outperforms every older model.
