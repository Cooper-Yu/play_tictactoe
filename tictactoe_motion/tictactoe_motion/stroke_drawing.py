"""Execute separate XY strokes with explicit base-frame Z lowering and lifting."""
import copy
import math

from tictactoe_motion.drawing_paths import circle_path, cross_path


class StrokeDrawing:
    """! @brief Draw X or O through verified driver motions, stopping on any failure.

    Start above the drawing plane. Transfers occur at this saved upper Z; each
    stroke descends along base_link -Z and retracts to the same upper plane.
    Driver primitives run outside ROS callbacks and verify execution/settling.
    This coordinator does not infer physical contact or board clearance.
    """

    def __init__(self, shape, size=.02, radius=.01, depth=.01):
        if shape not in ('cross', 'circle'):
            raise ValueError('Shape must be cross or circle')
        if not math.isfinite(depth) or not 0 < depth <= .05:
            raise ValueError('Depth must be finite and in (0, 0.05] meters')
        # Validate geometry before requesting any motion.
        if not math.isfinite(size) or not 0 < size <= .1:
            raise ValueError('Size must be finite and in (0, 0.1] meters')
        if not math.isfinite(radius) or not 0 < radius <= .04:
            raise ValueError('Radius must be finite and in (0, 0.04] meters')
        self.shape, self.size, self.radius, self.depth = shape, size, radius, depth
        self.results = []
        self.strokes = []

    def run(self, driver, cancelled=lambda: False, on_stage=lambda name: None):
        """! @brief Lower, trace, lift; transfer between strokes only after lifting."""
        self.results = []
        upper = copy.deepcopy(driver.current_pose())
        lower = copy.deepcopy(upper)
        lower.position.z -= self.depth
        if self.shape == 'cross':
            points = cross_path(lower, self.size)
            self.strokes = [points[:2], points[2:]]
        else:
            self.strokes = [circle_path(lower, self.radius)]

        def step(name, action):
            if cancelled():
                raise RuntimeError('Drawing cancelled; no further motion requested')
            on_stage(name)
            result = action()
            if not isinstance(result, dict) or result.get('passed') is not True:
                raise RuntimeError(f'Drawing stage {name} failed verification')
            self.results.append({'stage': name, 'result': copy.deepcopy(result)})

        for i, stroke in enumerate(self.strokes, 1):
            if i > 1:
                transfer = copy.deepcopy(stroke[0].position)
                transfer.z = upper.position.z
                step(f'{i}_transfer', lambda: driver.linear(transfer))
            # Lower vertically at the achieved start, avoiding lateral motion.
            start = copy.deepcopy(driver.current_pose().position)
            start.z = lower.position.z
            step(f'{i}_lower', lambda: driver.linear(start))
            step(f'{i}_draw', lambda: driver.path(stroke))
            lift = copy.deepcopy(driver.current_pose().position)
            lift.z = upper.position.z
            step(f'{i}_lift', lambda: driver.linear(lift))
        return copy.deepcopy(self.results)
