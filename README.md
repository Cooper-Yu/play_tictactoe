# Play TicTacToe


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
