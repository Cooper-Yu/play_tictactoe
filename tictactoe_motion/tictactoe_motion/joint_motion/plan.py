"""Request plans for joint targets and saved records."""


def request(driver, joints, target_pose, name):
    driver.check_motion_guard()
    assert driver.node.request_joint_plan(joints, target_pose, name)
    driver.until(lambda: not driver.node.is_planning)


def replay(driver, name):
    driver.parameters(record_name=name)
    driver.recording.recorder.poses = {}
    driver.call('load_pose')
    driver.call('plan_return')
    driver.until(lambda: not driver.node.is_planning)
