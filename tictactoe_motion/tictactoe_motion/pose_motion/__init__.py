"""Motion to an absolute end-effector pose."""

from . import check_result, check_trajectory, execute, plan


class PoseMotion:
    """Reach and verify an absolute end-effector pose."""

    def __init__(self, driver):
        self.driver = driver

    def move(self, target):
        plan.request(self.driver, target)
        check_trajectory.verify(self.driver)
        result = execute.run(self.driver)
        return check_result.verify(self.driver, result)
