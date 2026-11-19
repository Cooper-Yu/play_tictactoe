"""Bounded verification of fresh, stationary feedback after a software stop."""
import math


class FeedbackRecovery:
    """! @brief Confirm observation readiness without queuing any motion."""

    timeout = 30.
    stable_duration = 2.
    max_gap = .35
    messages = {
        'waiting': '关节反馈中断，正在等待执行结束和反馈恢复',
        'confirmation': '可恢复，待确认。请检查笔尖和板面再重新规划',
        'timeout': '恢复检查超时，运动保持暂停，请检查真机和反馈链路',
    }

    def __init__(self, now, incident):
        self.incident = incident
        self.phase = 'waiting'
        self.deadline = now + self.timeout
        self.first_sample = self.last_sample = self.anchor = None
        self.stamps = self.last_advancing_sample = None

    def snapshot(self):
        return dict(self.incident, phase=self.phase, deadline_s=self.deadline)

    def observe(self, now, stopped, sample, tolerance):
        if self.phase == 'timeout':
            return
        if self.phase == 'waiting' and now >= self.deadline:
            self.phase = 'timeout'
            return
        stamps, positions = sample if sample is not None else (None, None)
        valid = (stopped and sample is not None
                 and (self.last_sample is None or now - self.last_sample <= self.max_gap)
                 and (self.anchor is None
                      or max(abs(a-b) for a, b in zip(self.anchor, positions)) <= tolerance))
        if valid and self.stamps is not None:
            valid = all(a >= b for a, b in zip(stamps, self.stamps))
            if valid and all(a > b for a, b in zip(stamps, self.stamps)):
                self.last_advancing_sample = now
                self.stamps = stamps
            elif valid:
                valid = now - self.last_advancing_sample <= self.max_gap
        if not valid:
            if self.phase == 'confirmation':
                self.deadline = now + self.timeout
            self.phase = 'waiting'
            self.first_sample = self.last_sample = self.anchor = None
            self.stamps = self.last_advancing_sample = None
            return
        if self.first_sample is None:
            self.first_sample, self.anchor = now, positions
            self.stamps, self.last_advancing_sample = stamps, now
        self.last_sample = now
        if (now - self.first_sample >= self.stable_duration
                and self.last_advancing_sample == now):
            self.phase = 'confirmation'

    def can_acknowledge(self, now):
        return (self.phase == 'confirmation'
                and now - self.last_advancing_sample <= self.max_gap)


def recovery_sample(now, ros_now, state, transform, receipt_time, receipt_limit):
    """! @brief Require complete joint feedback and current base-to-link6 TF."""
    if state is None or transform is None or receipt_time is None:
        return None
    if not 0 <= now-receipt_time <= min(receipt_limit, FeedbackRecovery.max_gap):
        return None
    headers = state.header, transform.header
    stamps = tuple(h.stamp.sec + h.stamp.nanosec*1e-9 for h in headers)
    if any(stamp <= 0 or not -.2 <= ros_now-stamp <= receipt_limit for stamp in stamps):
        return None
    positions = dict(zip(state.name, state.position))
    if len(positions) != len(state.name) or len(state.name) != len(state.position):
        return None
    arm = tuple(positions.get(f'joint{i}', math.nan) for i in range(1, 7))
    p, q = transform.transform.translation, transform.transform.rotation
    rotation = (q.x, q.y, q.z, q.w)
    if (not all(math.isfinite(value) for value in (*arm, p.x, p.y, p.z, *rotation))
            or not .99 <= math.hypot(*rotation) <= 1.01):
        return None
    return stamps, arm
