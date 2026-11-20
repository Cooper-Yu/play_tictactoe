"""A verified zero -> target -> descend -> retract -> zero sequence."""
import copy
import math


class PoseCycle:
    """! @brief Coordinate verified driver primitives; abort without an automatic recovery move.

    The driver provides named(), pose(), linear() and current_pose(). Each motion
    primitive returns a dict with passed=True only after execution and settling.
    The synchronous runner belongs outside a ROS callback; a driver may pump its
    executor while waiting. It does not create a ROS action server or GUI button.
    """

    def __init__(self, target_pose, distance):
        p, q = target_pose.position, target_pose.orientation
        if not all(math.isfinite(v) for v in (p.x,p.y,p.z,q.x,q.y,q.z,q.w)) or sum(v*v for v in (q.x,q.y,q.z,q.w)) < 1e-12:
            raise ValueError('Target pose must be finite with a valid quaternion')
        if not math.isfinite(distance) or not 0 < distance <= .05:
            raise ValueError('Descent distance must be finite and in (0, 0.05] meters')
        self.target = copy.deepcopy(target_pose)
        self.distance = float(distance)
        self.results = []
        self.upper = None
        self.lower = None

    def run(self, driver, cancelled=lambda: False, on_stage=lambda name: None):
        """! @brief Execute each stage only after the preceding stage was verified."""
        self.results = []
        def step(name, action):
            if cancelled():
                raise RuntimeError('Pose cycle cancelled; no further motion requested')
            on_stage(name)
            result = action()
            if not isinstance(result, dict) or result.get('passed') is not True:
                raise RuntimeError(f'Pose cycle stage {name} failed verification')
            self.results.append({'stage': name, 'result': copy.deepcopy(result)})
        step('zero_start', lambda: driver.named('zero'))
        step('target', lambda: driver.pose(self.target))
        self.upper = copy.deepcopy(driver.current_pose())
        self.lower = copy.deepcopy(self.upper)
        self.lower.position.z -= self.distance
        step('descend', lambda: driver.linear(self.lower.position))
        step('retract', lambda: driver.linear(self.upper.position))
        step('zero_finish', lambda: driver.named('zero'))
        return copy.deepcopy(self.results)
