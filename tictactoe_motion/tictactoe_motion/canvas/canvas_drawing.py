"""Execute normalized canvas polylines with explicit virtual pen-up/down motion."""
import copy
import math
from geometry_msgs.msg import Pose
from tictactoe_motion.actions.stroke_drawing import StrokeDrawing


class CanvasDrawing(StrokeDrawing):
    """! @brief Validate all canvas strokes before approaching their first start."""
    def __init__(self, canvas, strokes, upper_z=.22, depth=.01, snap=True, *,
                 transfer_z=None, exit_to_transfer=False, fallback=None):
        super().__init__('cross',depth=depth)
        self.canvas = canvas
        profile_hover = canvas.profile.get('canvas_hover_link6_z_m' if transfer_z is not None
                                         else 'hover_link6_z_m', upper_z)
        if canvas.environment == 'real' and (
                abs(upper_z-profile_hover) > 1e-9
                or abs(upper_z-depth-canvas.z) > 1e-9):
            raise ValueError('Real drawing heights must match the calibrated board profile')
        if not 1<=len(strokes)<=32:raise ValueError('Require 1..32 separate strokes')
        length_options = {'max_length': .5} if canvas.environment == 'real' and transfer_z is not None else {}
        self.paths=[canvas.stroke(points,snap=snap, **length_options) for points in strokes]
        self.fallback = {i: [canvas.stroke(points, snap=snap, **length_options) for points in parts]
                         for i, parts in (fallback or {}).items()}
        self.transfer_excursion_limit = canvas.profile.get('transfer_joint_excursion_rad', .5)
        self.continuous_excursion_limit = canvas.profile.get('continuous_stroke_joint_excursion_rad', .5)
        if not .5 <= self.continuous_excursion_limit <= 1.:
            raise ValueError('Continuous stroke joint excursion must be in [0.5, 1.0] rad')
        self.upper_z=upper_z
        self.transfer_z = transfer_z
        self.exit_to_transfer = exit_to_transfer
        if transfer_z is not None and (
                canvas.environment != 'real' or not math.isfinite(transfer_z)
                or not .001 <= transfer_z - upper_z <= .02):
            raise ValueError('Invalid elevated canvas transfer height')
        if not .20<=upper_z-depth<upper_z<=.30:
            raise ValueError('Simulation hover height outside validated range')

    def run(self, driver, cancelled=lambda:False, on_stage=lambda name:None):
        if self.canvas.environment != 'real':
            return self._run(driver, cancelled, on_stage)
        if getattr(getattr(driver, 'recording', None), 'environment', None) != 'real':
            raise ValueError('Real canvas requires a real motion driver')
        planner = driver.node.cartesian_planner
        previous_limit = getattr(planner, 'canvas_max_length', None)
        planner.canvas_max_length = .5
        requested = {key: driver.node.get_parameter(key).value
                     for key in ('velocity_scaling', 'acceleration_scaling')}

        def progress(name):
            # Only the contact path uses the requested drawing scaling.
            if name.endswith('_draw'):
                scaling = requested
            elif name in ('approach_from_zero', 'adjust_hover_orientation'):
                value = min(.1, self.canvas.profile.get('travel_velocity_scaling', 1.0))
                scaling = dict(velocity_scaling=value, acceleration_scaling=value)
            else:
                key = ('pen_vertical_velocity_scaling'
                       if name.endswith(('_lower', '_lift')) and name != 'exit_lift'
                       else 'travel_velocity_scaling')
                value = self.canvas.profile.get(key, 1.0)
                scaling = dict(velocity_scaling=value, acceleration_scaling=value)
            driver.parameters(**scaling)
            planner.canvas_native_timing = True
            on_stage(name)

        try:
            stages = self._run(driver, cancelled, progress)
            if self.transfer_z is not None and self.exit_to_transfer:
                if cancelled():
                    raise RuntimeError('Drawing cancelled before exit lift')
                progress('exit_lift')
                lift = copy.deepcopy(driver.current_pose().position)
                lift.z = self.transfer_z
                result = driver.linear(lift)
                if not isinstance(result, dict) or not result.get('passed'):
                    raise RuntimeError('Canvas exit lift failed')
                self.results.append(dict(stage='exit_lift', result=copy.deepcopy(result)))
                return copy.deepcopy(self.results)
            return stages
        finally:
            planner.canvas_native_timing = False
            planner.canvas_max_length = previous_limit
            driver.parameters(**requested)

    @staticmethod
    def real_approach(driver, start, destination, cancelled, *, excursion_limit=.5):
        """Try one verified move, then split a rejected horizontal joint excursion."""
        if cancelled():
            raise RuntimeError('Drawing cancelled before canvas approach')
        options = {'allow_excursion_retry': True}
        if excursion_limit != .5:
            if abs(destination.z-start.z) > .0001:
                raise ValueError('Relaxed excursion requires horizontal pen-up travel')
            options['excursion_limit'] = excursion_limit
        result = driver.linear(destination, **options)
        if result is not None:
            return result
        distance = math.hypot(destination.x-start.x, destination.y-start.y)
        if distance <= .06 or abs(destination.z-start.z) > .0001:
            raise RuntimeError('Canvas approach exceeds the joint excursion limit')
        count = math.ceil(distance/.06)
        for index in range(1, count+1):
            if cancelled():
                raise RuntimeError('Drawing cancelled during canvas approach')
            target = copy.deepcopy(destination)
            target.x = start.x + (destination.x-start.x)*index/count
            target.y = start.y + (destination.y-start.y)*index/count
            result = driver.linear(target)
            if not isinstance(result, dict) or result.get('passed') is not True:
                raise RuntimeError('Canvas approach segment failed verification')
        return dict(result, approach_segments=count)

    def _drawing_orientation_matches(self, orientation):
        actual = [orientation.x, orientation.y, orientation.z, orientation.w]
        norm = math.sqrt(sum(value * value for value in actual))
        if not math.isfinite(norm) or abs(norm - 1) > .001:
            raise ValueError('Invalid current drawing orientation')
        expected = self.canvas.profile['required_orientation_xyzw']
        dot = abs(sum(a * b for a, b in zip(actual, expected))) / norm
        error = 2 * math.acos(min(1., dot))
        return error <= self.canvas.profile['orientation_tolerance_rad']

    def verify_direct_approach(self, trajectory, fk, clearance, cancelled):
        """Check that the planned flange stays above the board clearance."""
        joint_path = trajectory.joint_trajectory
        previous = joint_path.points[0].positions
        over_board = False
        margin = .005
        for point in joint_path.points:
            end = point.positions
            count = max(1, math.ceil(max(abs(b - a) for a, b in zip(previous, end)) / .025))
            for step in range(1, count + 1):
                if cancelled():
                    raise RuntimeError('Drawing cancelled during direct approach verification')
                ratio = step / count
                joints = {name: a + ratio * (b - a)
                          for name, a, b in zip(joint_path.joint_names, previous, end)}
                pose = fk(joints)
                p = pose.position
                if not all(math.isfinite(value) for value in (p.x, p.y, p.z)):
                    raise RuntimeError('Direct approach has invalid pose feedback')
                if (self.canvas.x0 - margin <= p.x <= self.canvas.x1 + margin
                        and self.canvas.y0 - margin <= p.y <= self.canvas.y1 + margin):
                    over_board = True
                    if p.z < clearance:
                        raise RuntimeError('Direct approach drops below board clearance')
            previous = end
        if not over_board:
            raise RuntimeError('Direct approach did not reach the drawing area')

    def _approach_from_zero(self, driver, upper, clearance, cancelled, on_stage):
        if not self.canvas.profile.get('allow_direct_zero_approach', False):
            raise ValueError('Move to clear drawing orientation before drawing')
        zero, _ = driver.named_target('zero')
        if not driver.node.feedback_is_fresh():
            raise RuntimeError('Fresh joint feedback required for direct drawing approach')
        state = driver.node.current_joint_state
        measured = dict(zip(state.name, state.position))
        if not all(abs(measured.get(name, math.inf) - angle) <= .03
                   for name, angle in zero.items()):
            raise ValueError('Start at zero or move to clear drawing orientation')
        if cancelled():
            raise RuntimeError('Drawing cancelled before direct approach')
        target = copy.deepcopy(upper)
        target.position.x, target.position.y, _ = self.paths[0][0]
        target.position.z = clearance + .005
        (target.orientation.x, target.orientation.y, target.orientation.z,
         target.orientation.w) = self.canvas.profile['required_orientation_xyzw']
        on_stage('approach_from_zero')
        upper = self._verified_hover(driver, target, clearance, cancelled, 'approach_from_zero')
        if not self._drawing_orientation_matches(upper.orientation):
            if cancelled():
                raise RuntimeError('Drawing cancelled before hover orientation adjustment')
            on_stage('adjust_hover_orientation')
            upper = self._verified_hover(
                driver, target, clearance, cancelled, 'adjust_hover_orientation',
            )
            if not self._drawing_orientation_matches(upper.orientation):
                raise RuntimeError('Correct drawing orientation was not reached at hover')
        return upper

    def _verified_hover(self, driver, target, clearance, cancelled, stage):
        result = driver.pose(
            target,
            validate_plan=lambda trajectory: self.verify_direct_approach(
                trajectory, driver.fk, clearance, cancelled
            ),
            require_orientation=stage != 'approach_from_zero',
        )
        if not isinstance(result, dict) or result.get('passed') is not True:
            raise RuntimeError(f'{stage} failed')
        upper = driver.current_pose()
        p, goal = upper.position, target.position
        error = math.dist((p.x, p.y, p.z), (goal.x, goal.y, goal.z))
        if not (p.z >= clearance and error <= .001):
            raise RuntimeError(f'{stage} did not reach the verified drawing hover position')
        self.results.append({'stage': stage, 'result': copy.deepcopy(result)})
        return upper

    def _run(self, driver, cancelled, on_stage):
        self.results=[]
        if cancelled():raise RuntimeError('Drawing cancelled')
        upper=driver.current_pose()
        reached_direct_hover = False
        if self.canvas.environment == 'real':
            if getattr(getattr(driver, 'recording', None), 'environment', None) != 'real':
                raise ValueError('Real canvas requires a real motion driver')
            clearance = self.transfer_z or self.upper_z
            if not self._drawing_orientation_matches(upper.orientation):
                upper = self._approach_from_zero(driver, upper, clearance, cancelled, on_stage)
                reached_direct_hover = True
            if upper.position.z < clearance-0.0001:
                on_stage('raise_before_transfer')
                lift = copy.deepcopy(upper.position); lift.z = clearance
                result = driver.linear(lift)
                if not isinstance(result, dict) or result.get('passed') is not True:
                    raise RuntimeError('Canvas initial lift failed')
                self.results.append({'stage':'raise_before_transfer','result':copy.deepcopy(result)})
                if cancelled():raise RuntimeError('Drawing cancelled')
                upper = driver.current_pose()
                if self.transfer_z is not None and upper.position.z < clearance-.0001:
                    raise RuntimeError('Canvas transfer clearance not reached')
        if not reached_direct_hover:
            upper.position.x,upper.position.y,_=self.paths[0][0]
        transfer_z = max(upper.position.z, self.upper_z) if self.canvas.environment == 'real' else self.upper_z
        upper.position.z=transfer_z
        on_stage('approach')
        actual = driver.current_pose().position
        distance = math.dist((actual.x,actual.y,actual.z),
                             (upper.position.x,upper.position.y,upper.position.z))
        if reached_direct_hover:
            # The verified pose approach already reached the XY target within tolerance.
            result = dict(passed=True, skipped=True, reason='verified_direct_hover')
        elif self.canvas.environment == 'real' and distance <= 0.00001:
            # A <=10 micrometer approach is already satisfied; do not execute a zero-length plan.
            result = dict(passed=True, skipped=True, reason='already_at_approach',
                          position_error_m=distance, orientation_error_rad=0.)
        elif self.canvas.environment == 'real':
            result = self.real_approach(driver, actual, upper.position, cancelled,
                                        excursion_limit=self.transfer_excursion_limit)
        else:
            result = driver.pose(upper)
        if not isinstance(result,dict) or result.get('passed') is not True:raise RuntimeError('Canvas approach failed')
        self.results.append({'stage':'approach','result':copy.deepcopy(result)})
        if self.canvas.environment == 'real' and transfer_z > self.upper_z+0.0001:
            if cancelled():raise RuntimeError('Drawing cancelled')
            upper.position.z = self.upper_z
            on_stage('approach_hover')
            result = driver.linear(upper.position)
            if not isinstance(result, dict) or result.get('passed') is not True:
                raise RuntimeError('Canvas hover approach failed')
            self.results.append({'stage':'approach_hover','result':copy.deepcopy(result)})
        upper.position.z = self.upper_z
        def poses(path):
            result = []
            for x, y, _ in path:
                pose = Pose()
                pose.position.x, pose.position.y, pose.position.z = x, y, self.upper_z-self.depth
                pose.orientation = copy.deepcopy(upper.orientation)
                result.append(pose)
            return result

        strokes = [poses(path) for path in self.paths]
        fallback = {i: [poses(path) for path in parts] for i, parts in self.fallback.items()}
        def transfer(target):
            start = driver.current_pose().position
            if min(start.z, target.z) < self.upper_z-.0001:
                raise RuntimeError('Pen-up clearance not reached before transfer')
            return self.real_approach(driver, start, target, cancelled,
                                      excursion_limit=self.transfer_excursion_limit)

        return self.run_strokes(driver, strokes, upper, cancelled, on_stage, fallback,
                                candidate_excursion_limit=self.continuous_excursion_limit,
                                transfer_action=transfer if self.canvas.environment == 'real' else None)
