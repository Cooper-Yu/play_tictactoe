"""Asynchronous stopping with MoveIt cancellation and its manager-wide stop event."""

import json
import math
import time

from rclpy.clock import Clock, ClockType
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Trigger


class MotionStop:
    """!
    @brief Cancel this demo's execution and confirm a fresh stationary joint state.

    The stop event affects the configured MoveIt execution manager, so use this
    demo as its sole motion caller. A cancel acknowledgement is not a stopped
    verdict. Unknown terminal state or
    missing feedback keeps new motion blocked. This is not a hardware emergency stop.
    """

    def __init__(self, node, execution):
        self.node = node
        self.execution = execution
        self.active = False
        self.blocked = False
        self.cancel_pending = False
        self.generation = 0
        self.timer = None
        self.clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.status = {}
        self.event_generation = -1
        self.event_publisher = node.create_publisher(
            String, node.settings["stop_event_topic"], 1,
        )
        self.publisher = node.create_publisher(
            String, '/motion/status',
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        self.service = node.create_service(Trigger, '/stop_motion', self.callback)
        self.publish('idle', 'No stop request pending')

    def publish(self, state, message, **extra):
        """! @brief Publish the latest software-stop state for CLI and GUI callers."""
        self.status = {
            'state': state, 'message': message,
            'motion_blocked': self.execution.is_executing, **extra,
        }
        self.publisher.publish(String(data=json.dumps(self.status, allow_nan=False)))
        self.node.get_logger().info(f'Motion state {state}: {message}')

    def callback(self, request, response):
        response.success = self.request()
        response.message = self.status['message']
        return response

    def request(self):
        """! @brief Invalidate old work and begin or retry a bounded software stop."""
        self.node.cancel_planning()
        recording = getattr(self.node, 'pose_recording_demo', None)
        if recording is not None and self.node.is_recording:
            recording.cancel_callback(Trigger.Request(), Trigger.Response())
        if self.active and not self.blocked:
            return True
        if not self.execution.is_executing:
            self.publish('stopped', 'No owned execution is active; pending work cleared')
            return True
        self.active = True
        self.blocked = False
        self.generation += 1
        self.cancel_pending = False
        self.execution.is_executing = True
        settle_timer = getattr(self.execution, 'settle_timer', None)
        if settle_timer is not None:
            settle_timer.cancel()
        self.deadline = time.monotonic() + self.node.settings['stop_timeout']
        self.last_sequence = self.node.joint_state_sequence
        self.last_stamp = None
        self.previous = None
        self.stable_count = 0
        if self.timer is not None:
            self.node.destroy_timer(self.timer)
        self.timer = self.node.create_timer(
            self.node.settings['settle_period'], self.tick, clock=self.clock,
        )
        self.publish('stop_requested', 'Stop requested; waiting for terminal execution and settled feedback')
        self.cancel_available_goal()
        return True

    def cancel_available_goal(self):
        """! @brief Cancel once a goal handle is known, including a late acceptance."""
        handle = self.execution.execution_goal_handle
        if not self.active or self.cancel_pending or handle is None:
            return
        if self.execution.execution_terminal:
            return
        # Humble ExecuteTrajectory may not process cancellation while executing.
        # Use the same non-latched TEM event as MoveGroupInterface.stop().
        if self.event_generation != self.generation:
            self.event_publisher.publish(String(data='stop'))
            self.event_generation = self.generation
        try:
            self.cancel_pending = True
            self.cancel_future = handle.cancel_goal_async()
            generation = self.generation
            goal_id = bytes(handle.goal_id.uuid)
            self.cancel_future.add_done_callback(
                lambda future: self.cancel_response(future, generation, goal_id)
            )
        except Exception as error:
            self.cancel_pending = False
            self.fail(f'Failed to request cancellation: {error}')

    def cancel_response(self, future, generation, goal_id):
        if generation != self.generation:
            return
        self.cancel_pending = False
        if not self.active:
            return
        try:
            result = future.result()
            accepted = any(
                bytes(info.goal_id.uuid) == goal_id
                for info in result.goals_canceling
            )
            # This response may race with an already received terminal result.
            if self.execution.execution_terminal:
                return
            if accepted:
                self.publish('cancel_accepted', 'Cancellation accepted; robot stop is not yet confirmed')
            else:
                self.publish('cancel_rejected', 'Cancellation not accepted; still awaiting execution end',
                             return_code=result.return_code)
        except Exception as error:
            self.fail(f'Cancellation response unavailable: {error}')

    def terminal_received(self, status):
        """! @brief Require new feedback after an execution terminal result."""
        if not self.active:
            self.request()
        if self.blocked:
            return
        self.last_sequence = self.node.joint_state_sequence
        self.last_stamp = None
        self.previous = None
        self.stable_count = 0
        self.publish('stop_settling', 'Execution ended; checking fresh stationary feedback',
                     action_status=status)

    def fail(self, message):
        self.active = True
        self.blocked = True
        self.execution.is_executing = True
        if self.timer is not None:
            self.timer.cancel()
        self.publish('stop_blocked', message + '; new motion remains blocked')

    def tick(self):
        """! @brief Check steady-clock timeout and distinct, fresh, finite joint samples."""
        if time.monotonic() >= self.deadline:
            self.fail('Timed out confirming stop')
            return
        if not self.execution.execution_terminal or self.execution.execution_goal_pending:
            return
        if not self.node.feedback_is_fresh():
            self.previous = None
            self.stable_count = 0
            return
        if self.last_sequence == self.node.joint_state_sequence:
            return
        self.last_sequence = self.node.joint_state_sequence
        state = self.node.current_joint_state
        stamp = Time.from_msg(state.header.stamp).nanoseconds
        if self.last_stamp is not None and stamp <= self.last_stamp:
            self.previous = None
            self.stable_count = 0
            self.last_stamp = stamp
            return
        self.last_stamp = stamp
        try:
            if len(state.name) != len(state.position) or len(set(state.name)) != len(state.name):
                raise ValueError('Invalid feedback arrays')
            positions = dict(zip(state.name, state.position))
            current = [positions[f'joint{i}'] for i in range(1, 7)]
            if not all(math.isfinite(value) for value in current):
                raise ValueError('Non-finite joint feedback')
        except (KeyError, ValueError):
            self.previous = None
            self.stable_count = 0
            return
        if self.previous is not None:
            change = max(abs(a - b) for a, b in zip(current, self.previous))
            self.stable_count = (
                self.stable_count + 1
                if change <= self.node.settings['settle_joint_tolerance'] else 0
            )
        self.previous = current
        if self.stable_count < self.node.settings['settle_samples']:
            return
        self.timer.cancel()
        self.active = False
        self.blocked = False
        self.generation += 1
        self.cancel_pending = False
        self.execution.is_executing = False
        self.execution.execution_goal_handle = None
        self.node.invalidate_plan()
        self.publish('stopped', 'Execution ended and fresh joint feedback settled; replan before moving')

    def close(self):
        """! @brief Release the monitor timer before its node and context are destroyed."""
        if self.timer is not None:
            self.timer.cancel()
            self.node.destroy_timer(self.timer)
            self.timer = None
