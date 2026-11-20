"""Prepare and request Cartesian trajectories."""

import copy


def linear(driver, target_position, *, speed):
    driver.check_motion_guard()
    assert driver.node.cartesian_planner.request_linear_position(target_position, speed=speed)
    driver.until(lambda: not driver.node.is_planning)


def path(driver, poses, *, speed):
    driver.check_motion_guard()
    start = driver.current_pose()
    waypoints = [copy.deepcopy(start)]
    for pose in poses[1:]:
        target = copy.deepcopy(start)
        target.position.x, target.position.y = pose.position.x, pose.position.y
        waypoints.append(target)
    assert driver.node.cartesian_planner.request_path(waypoints, speed=speed)
    driver.until(lambda: not driver.node.is_planning)
