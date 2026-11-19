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

        return self.run_strokes(driver, self.strokes, upper, cancelled, on_stage)

    def run_strokes(self, driver, strokes, upper, cancelled, on_stage, fallback=None):
        """! @brief Execute prepared strokes after an explicit elevated approach."""
        self.strokes = copy.deepcopy(strokes)
        def step(name, action):
            if cancelled():
                raise RuntimeError('Drawing cancelled; no further motion requested')
            on_stage(name)
            result = action()
            if not isinstance(result, dict) or result.get('passed') is not True:
                raise RuntimeError(f'Drawing stage {name} failed verification')
            self.results.append({'stage': name, 'result': copy.deepcopy(result)})

        def vertical(name, z):
            target = copy.deepcopy(driver.current_pose().position)
            target.z = z
            step(name, lambda: driver.linear(target))

        fallback = fallback or {}
        for i, stroke in enumerate(self.strokes, 1):
            previous_end = self.strokes[i-2][-1].position if i > 1 else None
            same_start = previous_end is not None and all(
                abs(getattr(previous_end, axis)-getattr(stroke[0].position, axis)) < 1e-9
                for axis in ('x', 'y', 'z'))
            if i > 1 and not same_start:
                transfer = copy.deepcopy(stroke[0].position)
                transfer.z = upper.position.z
                step(f'{i}_transfer', lambda: driver.linear(transfer))
            # Lower vertically at the achieved start, avoiding lateral motion.
            depth_z = stroke[0].position.z
            vertical(f'{i}_lower', depth_z)
            if i in fallback:
                def draw():
                    result = driver.path(stroke, allow_plan_retry=True)
                    if result is None:
                        return {'passed': True, 'planned_only': True, 'fallback': True}
                    return result

                step(f'{i}_draw', draw)
                if self.results[-1]['result'].get('fallback'):
                    for part, path in enumerate(fallback[i], 1):
                        if part > 1:
                            vertical(f'{i}_fallback_{part}_lower', depth_z)
                        step(f'{i}_fallback_{part}_draw', lambda: driver.path(path))
                        vertical(f'{i}_fallback_{part}_lift', upper.position.z)
                    continue
            else:
                step(f'{i}_draw', lambda: driver.path(stroke))
            vertical(f'{i}_lift', upper.position.z)
        return copy.deepcopy(self.results)
