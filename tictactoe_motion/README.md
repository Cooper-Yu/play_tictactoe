# Named pose recording and return demo

The demo uses the existing MoveIt configuration, `base_link`, `link6`, and
`joint1` through `joint6`. Capturing or loading a record never moves the arm.
The operator must confirm that a recorded preparation pose is clear of the board.
Contact poses and automatic approach/retreat paths are not implemented here.

## Build and start

In the same ROS environment/domain as the local Gazebo and MoveIt simulation:

```bash
cd ~/ros2_ws
colcon build --packages-select tictactoe_motion --symlink-install
source install/setup.bash
ros2 launch tictactoe_motion motion_demo.launch.py environment:=sim
```

The default environment is `real`, with `~/ros2_ws/src/play_tictactoe/data/poses_real.json`.
The explicit `environment:=sim` example above selects `poses_sim.json` instead.
Override it using `poses_file:=/absolute/path/poses_sim.json`. `environment` and
`poses_file` are fixed for one run. Use a separate real record file with
`environment:=real`; changing the label does not connect or start real hardware.
Download cloud records or explicitly commit/push them to the private repository;
placing files in a cloud workspace alone does not guarantee persistence.

## Record, load, delete and list

```bash
ros2 param set /motion_planner record_name A
ros2 service call /record_pose std_srvs/srv/Trigger '{}'
ros2 topic echo /pose_recording/status
```

`/record_pose` acknowledges the capture request, not its final success. Wait for
`"state": "saved"` on `/pose_recording/status`. Capture waits up to five seconds
for three stable comparisons of distinct joint timestamps at 0.1-second sampling
and an exact-time `base_link -> link6` transform. The joint change threshold is
0.0001 rad; reception age must be at most one second. These are demo defaults,
not established real-robot accuracy specifications.

```bash
ros2 service call /list_poses std_srvs/srv/Trigger '{}'
ros2 service call /load_pose std_srvs/srv/Trigger '{}'
ros2 service call /delete_pose std_srvs/srv/Trigger '{}'
ros2 service call /cancel_recording std_srvs/srv/Trigger '{}'
```

`record_name` selects the name for record/load/delete. `/load_pose` returns a JSON
copy of the record and selects it as the return target. `/delete_pose` persists
the deletion. Saving, loading or deleting invalidates pending return plans.
An existing name is rejected unless explicitly enabled:

```bash
ros2 param set /motion_planner overwrite true
# Capture the selected record again, then restore the default.
ros2 service call /record_pose std_srvs/srv/Trigger '{}'
ros2 param set /motion_planner overwrite false
```

## Plan and explicitly execute a return

```bash
ros2 param set /motion_planner record_name A
ros2 service call /load_pose std_srvs/srv/Trigger '{}'
ros2 service call /plan_return std_srvs/srv/Trigger '{}'
# Wait for Planning succeeded and inspect the RViz trajectory preview.
ros2 service call /execute_planned_trajectory std_srvs/srv/Trigger '{}'
```

Return goals use recorded joint angles. Execution remains separate and checks
that current feedback matches the planned start. After confirmed settling, the
demo compares the six joint angles and link6 pose with the record. Return
verification requires maximum joint error <= 0.001 rad, position error <= 0.3 mm,
and orientation error <= 0.003 rad. These are configurable-in-code demo criteria.
The final comparison is published on `/pose_recording/status`.

Planning, execution and capture are mutually exclusive. Lost/uncertain execution
responses or settling timeout keep motion blocked; cancellation of capture does
not cancel arm motion. Software stop/cancel controls are provided below; Web GUI integration
is separate follow-up work. This demo does not certify collision-free contact
or compensate for the missing board/table collision scene.

## Checks

```bash
cd ~/ros2_ws/src/play_tictactoe
python3 -m pytest tictactoe_motion/test/test_pose_recording_demo.py -q
```

Runtime record files are user data, not automatically staged or committed.

### Local validation: 2026-11-15

Validated in WSL Ubuntu-22.04 with ROS2 Humble and the local Piper Gazebo/MoveIt
simulation. The package built successfully; all 17 recording-demo tests and 87
existing recorder checks passed.

The runtime check captured A with matching joint/TF timestamps, recreated the
node, loaded A from disk, executed an X+ 1 cm step, planned and explicitly executed
a joint-space return to A, then verified settling and deleted the test record.
The measured return position error was 0.0283 mm, orientation error was
0.0000569 rad, and maximum joint error was 0.0000802 rad. These are results of one
simulation run and do not establish real-hardware precision. Temporary test
nodes were destroyed and the simulated arm was returned to the recorded pose.

## Environment configuration

Both packages load `config/common.yaml`, then `config/real.yaml` (the default)
or `config/sim.yaml`, then explicit launch arguments. Shared settings describe
planning, capture and verification; environment files select the clock and
separate record files. Real thresholds currently retain the demo values and
require hardware validation. Loading `real` configuration never starts a driver
or sends a motion goal. Gazebo, drivers and MoveIt are started separately.

```bash
# Default: real settings; no planning or execution on startup.
ros2 launch tictactoe_motion motion_demo.launch.py
# Local Gazebo/MoveIt, using /clock.
ros2 launch tictactoe_motion motion_demo.launch.py environment:=sim
# Override an environment value or a shared command parameter.
ros2 launch tictactoe_motion motion_demo.launch.py environment:=sim \
  distance:=0.005 velocity_scaling:=0.1 poses_file:=/tmp/poses_sim.json
```

Motion settings use meters, radians and seconds. Startup-only settings are
read-only parameters: joint topic/action names, planning group/time/attempts,
position/orientation/joint goal tolerances, server and feedback timeouts,
execution start tolerance, settling period/count/threshold/timeout, recording
timeout and return verification tolerances. Set `state_log_period: 0.0` to disable
periodic console output. The command parameters `axis`, `distance`,
`velocity_scaling`, `acceleration_scaling`, `record_name` and `overwrite` remain
writable through `ros2 param set`. Keep positive finite timeouts and tolerances;
counts must be positive integers. Invalid startup settings fail before creating
motion interfaces. Model identity remains `base_link`, `link6`, joint1..joint6;
the existing Piper MoveIt package owns the robot model and controller setup.

Use launch for YAML loading; bare `ros2 run` uses code defaults unless passed
`--ros-args --params-file ...`. Rebuild after adding config files; with
`--symlink-install`, editing an already installed YAML applies on the next launch.
Configuration changes do not hot-reload an active node.

Configuration tests (no arm motion):

```bash
cd ~/ros2_ws/src/play_tictactoe
python3 -m pytest tictactoe_motion/test/test_configuration.py \
  tictactoe_motion/test/test_pose_recording_demo.py \
  tictactoe_perception/test/test_perception_configuration.py -q
# Use an isolated ROS domain and ROS_LOCALHOST_ONLY=1 for this launch check.
python3 tictactoe_motion/test/verify_launch_configuration.py
```

The launch check starts/stops temporary processes, reads parameter services, and
publishes synthetic RGB frames. It selects the system OpenCV with
`PYTHONNOUSERSITE=1` and Qt offscreen mode to avoid opening desktop windows.
It does not validate real camera transport, robot execution or interactive GUI use.


## Active software stop

```bash
ros2 service call /stop_motion std_srvs/srv/Trigger '{}'
ros2 topic echo /motion/status
```

The Trigger response acknowledges the stop request. Wait for `state: stopped`
in the JSON status; `cancel_accepted` is not proof that the arm has stopped.
`stop_blocked` means the system cannot confirm stopping and keeps planning,
execution and pose capture blocked. A repeated request is idempotent while a
stop is pending. After a blocked timeout, an explicit stop request can retry
confirmation; only a terminal execution result plus fresh stable feedback can
release the block. There is no force-unlock service.

The stop entry cancels pose capture, invalidates pending plans, cancels a known
plan-only goal, and discards late planning responses. During execution it sends
both the goal-specific cancel request and a non-latched `stop` event to
`stop_event_topic` (default `/trajectory_execution_event`). It also handles a
stop received before the execution goal is accepted. This compatibility route
is necessary in the locally tested Humble MoveIt 2.5.9 environment: action-only
cancellation did not interrupt an eight-second test trajectory. The MoveIt
[execution manager stop-event implementation](https://moveit.picknik.ai/humble/api/html/moveit__ros_2planning_2trajectory__execution__manager_2src_2trajectory__execution__manager_8cpp_source.html)
processes the `stop` event by stopping trajectory execution.

The event stops executions managed by the configured MoveIt instance; it is not
restricted to one action UUID. Use this demo as the sole motion caller for that
MoveIt instance, including avoiding concurrent RViz execution. No stop event is
sent when the demo has no active accepted execution handle. It does not stop
independent driver commands or other MoveIt instances and does not replace a
hardware emergency stop. Hardware operation has not been validated here.

The timeout uses a steady clock and remains active even if simulated `/clock`
pauses. `stop_timeout` defaults to five seconds. Settling uses `settle_period`,
`settle_samples`, `settle_joint_tolerance` and `feedback_max_age` from common.yaml.
Samples must have distinct increasing timestamps, valid joint1..joint6 values,
and fresh reception times. Cancel rejection or missing responses never by
themselves release the block. Interrupted execution is not compared with the
original endpoint as a successful move. After stopping, an explicit new plan
and execution request are required; the canceled trajectory cannot resume.

Validated locally on 2026-11-15: 19 stop tests, 7 configuration tests, 17 recording
tests and 5 perception tests passed. An intermediate repeated-node test hit a
native rclpy segmentation fault. Explicit action-client, TF-listener and stop-timer
cleanup was added before node/context destruction. The complete 48-test suite
then passed in one process with aggressive Python garbage collection enabled;
this bounded check does not establish the full native failure mechanism.

Gazebo validation: an eight-second X+1cm trajectory was stopped after actual
progress exceeded 2mm, MoveIt returned ABORTED/PREEMPTED, joint feedback settled,
and replay of the old trajectory was rejected. An explicitly replanned return
to the saved starting joint configuration passed joint and pose checks.
The first action-only attempt and its recovery are retained in validation records.
