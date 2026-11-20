"""Request a trajectory to an absolute end-effector pose."""


def request(driver, target):
    driver.check_motion_guard()
    assert driver.node.request_pose_plan(target, orientation_tolerance=.001)
    driver.until(lambda: not driver.node.is_planning)
