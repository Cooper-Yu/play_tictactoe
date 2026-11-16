"""Recorded two-point Reset sequence over existing planning and execution APIs."""
import copy
import math
import time


class ResetAction:
    """! @brief Approach above Reset, press vertically, and retreat vertically.

    Motion completion does not prove that the board was cleared. Any failure or
    cancellation stops the sequence; no automatic retreat follows a stop request.
    """
    def __init__(self, driver, progress=None):
        self.driver = driver
        self.progress = progress or (lambda stage: None)

    def _stage(self, stage):
        self.driver.check_motion_guard()
        self.progress(stage)

    @staticmethod
    def validate_pair(hover, press):
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
        if math.hypot(a['position']['x']-b['position']['x'], a['position']['y']-b['position']['y']) > .0005:
            raise ValueError('Reset points must align vertically within 0.5 mm')
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

    def run(self, speed=.05, hover_name='reset悬空预备', press_name='Reset'):
        """! @brief Execute a bounded cycle; return with optical clearing unconfirmed."""
        if not math.isfinite(speed) or not .01 <= speed <= .1:
            raise ValueError('Reset speed must be 0.01 to 0.1')
        d = self.driver
        self._stage('检查 Reset 两点记录')
        d.recording._reload()
        hover = copy.deepcopy(d.recording.recorder.get_pose(hover_name))
        press = copy.deepcopy(d.recording.recorder.get_pose(press_name))
        clearance = self.validate_pair(hover, press)
        if hover['environment'] != d.recording.environment:
            raise ValueError('Reset records do not match the active environment')
        hover_z = hover['pose_stamped']['pose']['position']['z']
        d.parameters(velocity_scaling=speed, acceleration_scaling=speed)
        current = d.current_pose()
        if current.position.z < hover_z:
            self._stage('先抬起到悬空高度')
            target = copy.deepcopy(current.position)
            target.z = hover_z
            d.linear(target)
        self._stage('到达 Reset 悬空点')
        d.parameters(record_name=hover_name)
        d.call('load_pose')
        d.call('plan_return')
        d.until(lambda: not d.node.is_planning, 25)
        d.guard(2.)
        result = d.execute()
        if not result.get('passed', False):
            raise RuntimeError('Reset hover pose verification failed')
        self._stage('低速竖直按下 Reset')
        d.parameters(velocity_scaling=min(speed, .05), acceleration_scaling=min(speed, .05))
        target = copy.deepcopy(d.current_pose().position)
        target.z = press['pose_stamped']['pose']['position']['z']
        d.linear(target)
        self._stage('短暂停留')
        until = time.monotonic()+.3
        d.until(lambda: time.monotonic() >= until, 1.)
        self._stage('竖直返回悬空点')
        target = copy.deepcopy(d.current_pose().position)
        target.z = hover_z
        d.linear(target)
        self._stage('按键动作完成，请确认黑板已清空')
        return {'motion_completed': True, 'clear_confirmed': None,
                'hover_record': hover_name, 'press_record': press_name,
                'vertical_distance_m': clearance}