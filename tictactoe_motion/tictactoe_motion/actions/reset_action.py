"""Recorded two-point Reset sequence over existing planning and execution APIs."""
import copy
import math
import time


class ResetAction:
    """! @brief Align at hover height, press vertically, and return to the hover record.

    Motion completion does not prove that the board was cleared. Any failure or
    cancellation stops the sequence; no automatic retreat follows a stop request.
    """
    _ALIGNMENT_TOLERANCE_M = .0005
    _PRELIFT_EPSILON_M = .00001
    _MAX_REAL_OFFSET_M = .003

    def __init__(self, driver, progress=None):
        self.driver = driver
        self.progress = progress or (lambda stage: None)

    def _stage(self, stage):
        self.driver.check_motion_guard()
        self.progress(stage)

    @classmethod
    def validate_pair(cls, hover, press):
        """! @brief Reject mismatched records before requesting any movement."""
        for record in (hover, press):
            if record['tip_link'] != 'link6' or record['pose_stamped']['header']['frame_id'] != 'base_link':
                raise ValueError('Reset records must use base_link / link6')
        if hover['environment'] != press['environment']:
            raise ValueError('Reset records belong to different environments')
        a, b = [r['pose_stamped']['pose'] for r in (hover, press)]
        values = [p['position'][axis] for p in (a, b) for axis in ('x', 'y', 'z')]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Reset record positions must be finite')
        max_offset = (cls._MAX_REAL_OFFSET_M if hover['environment'] == 'real'
                      else cls._ALIGNMENT_TOLERANCE_M)
        if math.hypot(a['position']['x']-b['position']['x'],
                      a['position']['y']-b['position']['y']) > max_offset:
            raise ValueError('Reset points exceed the horizontal alignment limit')
        clearance = a['position']['z']-b['position']['z']
        if not .001 <= clearance <= .02:
            raise ValueError('Reset vertical clearance must be 1 to 20 mm')
        quaternions = [[p['orientation'][key] for key in ('x', 'y', 'z', 'w')] for p in (a, b)]
        for q in quaternions:
            if not all(math.isfinite(v) for v in q) or abs(sum(v*v for v in q)-1) > .01:
                raise ValueError('Invalid Reset orientation')
        dot = abs(sum(x*y for x, y in zip(*quaternions)))
        if 2*math.acos(min(1., dot)) > .01:
            raise ValueError('Reset orientations must match within 0.01 rad')
        return clearance

    def run(self, speed=.05, hover_name='Reset hover', press_name='Reset', *, direct_native=False):
        """! @brief Execute a bounded cycle; return with optical clearing unconfirmed."""
        if not math.isfinite(speed) or not .01 <= speed <= .1:
            raise ValueError('Reset speed must be 0.01 to 0.1')
        d = self.driver
        self._stage('Check Reset two recorded poses')
        d.recording._reload()
        hover = copy.deepcopy(d.recording.recorder.get_pose(hover_name))
        press = copy.deepcopy(d.recording.recorder.get_pose(press_name))
        clearance = self.validate_pair(hover, press)
        if direct_native:
            hover_pose, press_pose = [r['pose_stamped']['pose']['position'] for r in (hover, press)]
            if (hover['environment'] != 'real' or abs(hover_pose['z']-.216) > .00025
                    or abs(press_pose['z']-.2069714381) > .00025
                    or math.hypot(hover_pose['x']-press_pose['x'],
                                  hover_pose['y']-press_pose['y']) > self._ALIGNMENT_TOLERANCE_M):
                raise ValueError('Direct Reset requires the verified 216 mm and 206.97 mm pair')
        if hover['environment'] != d.recording.environment:
            raise ValueError('Reset records do not match the active environment')
        hover_position = hover['pose_stamped']['pose']['position']
        press_position = press['pose_stamped']['pose']['position']
        hover_z = hover_position['z']
        align_at_hover = math.hypot(hover_position['x'] - press_position['x'],
                                    hover_position['y'] - press_position['y']) > self._ALIGNMENT_TOLERANCE_M
        d.parameters(velocity_scaling=speed, acceleration_scaling=speed)
        current = d.current_pose()
        # TF rounding near the hover height must not request a sub-resolution
        # Cartesian trajectory. The recorded hover is still planned and verified.
        if current.position.z < hover_z - self._PRELIFT_EPSILON_M:
            self._stage('Raise to clearance height first')
            target = copy.deepcopy(current.position)
            target.z = hover_z
            d.linear(target)
        self._stage('Move to Reset clearance pose')
        d.parameters(record_name=hover_name)
        d.call('load_pose')
        d.call('plan_return')
        d.until(lambda: not d.node.is_planning, 25)
        d.guard(2.)
        result = d.execute()
        if not result.get('passed', False):
            raise RuntimeError('Reset hover pose verification failed')
        d.parameters(velocity_scaling=min(speed, .05), acceleration_scaling=min(speed, .05))
        def button_leg(position):
            if not direct_native:
                d.linear(position)
                return
            planner = d.node.cartesian_planner
            d.parameters(velocity_scaling=1.0, acceleration_scaling=1.0)
            planner.canvas_native_timing = True
            try:
                d.linear(position)
            finally:
                planner.canvas_native_timing = False
                d.parameters(velocity_scaling=min(speed,.05), acceleration_scaling=min(speed,.05))
        if align_at_hover:
            self._stage('Align at clearance height Reset press pose')
            target = copy.deepcopy(d.current_pose().position)
            if target.z < hover_z - .0001:
                raise RuntimeError('Reset alignment requires hover height')
            target.x, target.y = press_position['x'], press_position['y']
            d.linear(target)
            reached = d.current_pose().position
            if (math.hypot(reached.x - target.x, reached.y - target.y) > self._ALIGNMENT_TOLERANCE_M
                    or reached.z < hover_z - .0001):
                raise RuntimeError('Reset horizontal alignment verification failed')
        self._stage('Press vertically Reset')
        target = copy.deepcopy(d.current_pose().position)
        target.z = press_position['z']
        button_leg(target)
        self._stage('Brief dwell')
        until = time.monotonic()+.3
        d.until(lambda: time.monotonic() >= until, 1.)
        self._stage('Retract vertically to clearance pose')
        target = copy.deepcopy(d.current_pose().position)
        target.z = hover_z
        button_leg(target)
        if align_at_hover:
            self._stage('Return to the original approach point at clearance height')
            target = copy.deepcopy(d.current_pose().position)
            if target.z < hover_z - .0001:
                raise RuntimeError('Reset return requires hover height')
            target.x, target.y = hover_position['x'], hover_position['y']
            d.linear(target)
        self._stage('Button action completed, Confirm that the board is clear')
        return {'motion_completed': True, 'clear_confirmed': None,
                'hover_record': hover_name, 'press_record': press_name,
                'vertical_distance_m': clearance, 'direct_native': direct_native}