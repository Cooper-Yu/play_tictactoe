"""Motion to a joint configuration or saved record."""

from . import check_result, check_trajectory, execute, plan


class JointMotion:
    """Reach joint targets for named poses and saved records."""

    def __init__(self, driver):
        self.driver = driver

    def named(self, name):
        joints, target = self.driver.named_target(name)
        return self.move(joints, target, name)

    def move(self, joints, target_pose, name=None):
        """Execute a joint target with its expected end-effector pose."""
        plan.request(self.driver, joints, target_pose, name)
        return self._execute_plan()

    def replay(self, name):
        plan.replay(self.driver, name)
        return self._execute_plan()

    def _execute_plan(self):
        check_trajectory.verify(self.driver)
        result = execute.run(self.driver)
        return check_result.verify(result)
