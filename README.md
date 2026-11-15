
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
points and their joint-space midpoints; these are sampled checks, not a continuous
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
