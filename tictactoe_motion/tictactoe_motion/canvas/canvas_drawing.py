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

    def _run(self, driver, cancelled, on_stage):
        self.results=[]
        if cancelled():raise RuntimeError('Drawing cancelled')
        upper=driver.current_pose()
        if self.canvas.environment == 'real':
            if getattr(getattr(driver, 'recording', None), 'environment', None) != 'real':
                raise ValueError('Real canvas requires a real motion driver')
            q = upper.orientation
            actual = [q.x, q.y, q.z, q.w]
            expected = self.canvas.profile['required_orientation_xyzw']
            norm = math.sqrt(sum(v*v for v in actual))
            if not math.isfinite(norm) or abs(norm-1) > .001:
                raise ValueError('Invalid current drawing orientation')
            error = 2*math.acos(min(1., abs(sum(a*b for a,b in zip(actual,expected))/norm)))
            if error > self.canvas.profile['orientation_tolerance_rad']:
                raise ValueError('Move to clear drawing orientation before drawing')
            clearance = self.transfer_z or self.upper_z
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
        upper.position.x,upper.position.y,_=self.paths[0][0]
        transfer_z = max(upper.position.z, self.upper_z) if self.canvas.environment == 'real' else self.upper_z
        upper.position.z=transfer_z
        on_stage('approach')
        actual = driver.current_pose().position
        distance = math.dist((actual.x,actual.y,actual.z),
                             (upper.position.x,upper.position.y,upper.position.z))
        if self.canvas.environment == 'real' and distance <= 0.00001:
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
