"""Verify the achieved end-effector pose after pose motion."""


def verify(driver, result):
    return driver.verified_pose_result(result)
