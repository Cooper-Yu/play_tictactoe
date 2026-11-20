"""Post-execution joint settling and target verification."""

import math
import time

from rclpy.time import Time


class TrajectoryResultChecker:
    """Wait for a settled robot state and compare it with the motion target."""

    def __init__(self, node, on_settled, on_timeout):
        self.node = node
        self.settings = node.settings
        self.on_settled = on_settled
        self.on_timeout = on_timeout
        self.timer = None
        self.active = False

    def start(self):
        """Wait for new joint samples after a successful execution."""
        if self.timer is not None:
            self.node.destroy_timer(self.timer)
        self.last_settle_sequence = self.node.joint_state_sequence
        self.previous_settle_positions = None
        self.stable_sample_count = 0
        self.settle_deadline = time.monotonic() + self.settings["settle_timeout"]
        self.active = True
        self.timer = self.node.create_timer(self.settings["settle_period"], self.check_settled_state)

    def cancel(self):
        self.active = False
        if self.timer is not None:
            self.timer.cancel()

    def check_settled_state(self):
        if not self.active:
            return
        if time.monotonic() >= self.settle_deadline:
            self.cancel()
            self.on_timeout("Timed out waiting for settled state")
            return
        if self.node.joint_state_sequence == self.last_settle_sequence:
            return

        self.last_settle_sequence = self.node.joint_state_sequence

        current_positions = dict(
            zip(
                self.node.current_joint_state.name,
                self.node.current_joint_state.position,
            )
        )

        required_joints = [f"joint{i}" for i in range(1, 7)]
        if any(name not in current_positions for name in required_joints):
            self.previous_settle_positions = None
            self.stable_sample_count = 0
            return

        positions = [current_positions[name] for name in required_joints]

        if self.previous_settle_positions is None:
            self.previous_settle_positions = positions
            return

        max_change = max(
            abs(current - previous)
            for current, previous in zip(positions, self.previous_settle_positions)
        )
        self.previous_settle_positions = positions

        if max_change <= self.settings["settle_joint_tolerance"]:
            self.stable_sample_count += 1
        else:
            self.stable_sample_count = 0

        if self.stable_sample_count < self.settings["settle_samples"]:
            return

        if self.stable_sample_count == self.settings["settle_samples"]:
            self.settled_joint_stamp = self.node.current_joint_state.header.stamp

        actual_transform = self.node.get_current_pose()
        if actual_transform is None:
            return

        tf_time = Time.from_msg(actual_transform.header.stamp).nanoseconds
        stable_time = Time.from_msg(self.settled_joint_stamp).nanoseconds

        if tf_time < stable_time:
            return

        self.cancel()
        self.node.get_logger().info(
            "Joint feedback settled; comparing execution result"
        )
        self.on_settled(actual_transform)

    def compare(self, actual_transform, start_transform, target_pose, target_joints):
        start = start_transform.transform.translation
        actual = actual_transform.transform.translation
        target = target_pose.position
        displacement = (actual.x - start.x, actual.y - start.y, actual.z - start.z)
        position_error = math.dist(
            (actual.x, actual.y, actual.z), (target.x, target.y, target.z)
        )

        qa = actual_transform.transform.rotation
        qt = target_pose.orientation
        a = (qa.x, qa.y, qa.z, qa.w)
        t = (qt.x, qt.y, qt.z, qt.w)
        norm_a = math.sqrt(sum(v * v for v in a))
        norm_t = math.sqrt(sum(v * v for v in t))
        if norm_a == 0.0 or norm_t == 0.0:
            self.node.get_logger().warning("Invalid quaternion")
            return
        dot = abs(sum(av * tv for av, tv in zip(a, t)))
        cosine = min(1.0, max(0.0, dot / (norm_a * norm_t)))
        angle_error = 2.0 * math.acos(cosine)

        self.node.get_logger().info(f"Actual displacement (m): {displacement}")
        self.node.get_logger().info(
            f"Position error={position_error:.6f} m, "
            f"orientation error={angle_error:.6f} rad"
        )
        comparison = {
            "position_error_m": position_error,
            "orientation_error_rad": angle_error,
            "displacement_m": list(displacement),
        }
        if target_joints is not None:
            state = self.node.current_joint_state
            actual_joints = dict(zip(state.name, state.position))
            joint_errors = {
                name: abs(actual_joints[name] - target)
                for name, target in target_joints.items()
            }
            max_error = max(joint_errors.values())
            passed = (
                max_error <= self.settings["return_joint_tolerance"]
                and position_error <= self.settings["return_position_tolerance"]
                and angle_error <= self.settings["return_orientation_tolerance"]
            )
            comparison.update(
                joint_errors_rad=joint_errors,
                max_joint_error_rad=max_error,
                passed=passed,
            )
            self.node.get_logger().info(
                f"Return verification {'PASSED' if passed else 'FAILED'}: "
                f"max joint error={max_error:.6f} rad"
            )
        return comparison
