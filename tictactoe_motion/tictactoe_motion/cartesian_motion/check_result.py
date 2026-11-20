"""Verify the achieved end-effector pose after Cartesian motion."""

from tictactoe_motion.pose_motion.check_result import verify_pose_result


def verify(driver, result):
    return verify_pose_result(result, driver.node.settings)
