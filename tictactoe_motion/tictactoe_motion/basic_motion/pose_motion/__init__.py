"""Motion to an absolute end-effector pose."""

from . import check_result, check_trajectory, execute, plan


class PoseMotion:
    """Reach and verify an absolute end-effector pose."""

    def __init__(self, driver):
        self.driver = driver

    def move(self, target, *, validate_plan=None, require_orientation=True):
        plan.request(self.driver, target)
        check_trajectory.verify(self.driver)
        if validate_plan is not None:
            try:
                validate_plan(self.driver.node.planned_trajectory)
            except Exception:
                self.driver.node.invalidate_plan()
                raise
        result = execute.run(self.driver)
        return check_result.verify(self.driver, result, require_orientation=require_orientation)
