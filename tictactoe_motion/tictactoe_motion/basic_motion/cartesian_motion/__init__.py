"""Straight Cartesian moves and XY strokes."""

import math

from . import check_result, check_trajectory, execute, plan


class CartesianMotion:
    """Plan and execute Cartesian moves with the current tool orientation."""

    def __init__(self, driver):
        self.driver = driver

    def linear(self, target_position, *, speed=None, allow_excursion_retry=False,
               excursion_limit=.5):
        if (isinstance(excursion_limit, bool)
                or not isinstance(excursion_limit, (int, float))
                or not math.isfinite(excursion_limit) or not .5 <= excursion_limit <= .7):
            raise ValueError("Linear joint excursion must be in [0.5, 0.7] rad")
        plan.linear(self.driver, target_position, speed=speed)
        if not check_trajectory.accept_linear(
            self.driver, allow_retry=allow_excursion_retry, limit=excursion_limit
        ):
            return None
        result = execute.run(self.driver)
        return check_result.verify(self.driver, result)

    def path(self, poses, excursion_limit=0.5, *, speed=None, allow_plan_retry=False):
        """Execute one XY stroke at the achieved drawing height and orientation."""
        plan.path(self.driver, poses, speed=speed)
        if not check_trajectory.accept_path(
            self.driver, excursion_limit, allow_retry=allow_plan_retry
        ):
            return None
        result = execute.run(self.driver)
        return check_result.verify(self.driver, result)
