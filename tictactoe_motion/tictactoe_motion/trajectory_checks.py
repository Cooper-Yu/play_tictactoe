"""Validate the joint trajectory before sending it for execution."""

import math


class JointExcursionError(ValueError):
    """A planned trajectory exceeds the allowed joint excursion."""


def check_trajectory(trajectory, limit=0.5):
    assert trajectory is not None, 'No accepted plan'
    joints = trajectory.joint_trajectory
    assert set(joints.joint_names) == {f'joint{i}' for i in range(1, 7)}
    assert joints.points
    maximum = max(abs(value - joints.points[0].positions[i])
                  for point in joints.points for i, value in enumerate(point.positions))
    if not math.isfinite(maximum) or maximum >= limit:
        raise JointExcursionError(f'Joint excursion {maximum:.6f} rad exceeds the limit {limit:.6f} rad')
    previous = -1.0
    for point in joints.points:
        assert len(point.positions) == len(joints.joint_names)
        assert all(math.isfinite(value) for value in point.positions)
        stamp = point.time_from_start.sec + point.time_from_start.nanosec * 1e-9
        assert stamp >= previous
        previous = stamp
    return {'max_joint_excursion_rad': maximum, 'points': len(joints.points), 'duration_s': previous}
