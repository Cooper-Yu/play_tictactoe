"""Service-based capture of named poses using settled joint feedback and TF."""

import copy
import json
import math
import time
from pathlib import Path

from geometry_msgs.msg import PoseStamped
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import TransformException

from tictactoe_motion.pose_recorder import PoseRecorder


class PoseRecordingDemo:
    """!
    @brief Capture, persist, select and return to named robot poses.

    Capture never moves the robot. Return planning requires a separate execution
    request. Contact with a board or button must be confirmed by the operator.
    """

    def __init__(self, node):
        self.node = node
        node.declare_parameter("environment", "sim", ParameterDescriptor(read_only=True))
        self.environment = node.get_parameter("environment").value
        if self.environment not in ("sim", "real"):
            raise ValueError("Environment must be 'sim' or 'real'")
        default_file = (
            Path.home() / "ros2_ws/src/play_tictactoe/data"
            / f"poses_{self.environment}.json"
        )
        node.declare_parameter(
            "poses_file", str(default_file), ParameterDescriptor(read_only=True)
        )
        node.declare_parameter("record_name", "A")
        node.declare_parameter("overwrite", False)
        self.recorder = PoseRecorder(node.get_parameter("poses_file").value)
        self.loaded_pose = None
        self.capture_timer = None
        self.last_status = {}
        node.trajectory_executor.on_verification = self._return_verified
        self.status_publisher = node.create_publisher(
            String, "/pose_recording/status",
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        callbacks = {
            "/record_pose": self.record_callback,
            "/cancel_recording": self.cancel_callback,
            "/load_pose": self.load_callback,
            "/list_poses": self.list_callback,
            "/delete_pose": self.delete_callback,
            "/plan_return": self.return_callback,
        }
        self.services = [
            node.create_service(Trigger, name, callback)
            for name, callback in callbacks.items()
        ]
        try:
            self._reload()
        except (OSError, ValueError, TypeError, OverflowError) as error:
            self._publish("load", "failed", str(error))

    def _name(self):
        name = self.node.get_parameter("record_name").value
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Record name must be a non-empty string")
        return name.strip()

    def _publish(self, operation, state, message, **extra):
        self.last_status = {
            "operation": operation, "state": state, "message": message,
            "environment": self.environment,
            "poses_file": str(self.recorder.poses_file), **extra,
        }
        msg = String()
        msg.data = json.dumps(self.last_status, ensure_ascii=False, allow_nan=False)
        self.status_publisher.publish(msg)
        logger = self.node.get_logger()
        if state in ("failed", "blocked"):
            logger.warning(message)
        else:
            logger.info(message)

    def _require_idle(self):
        if self.node.is_recording:
            raise ValueError("Pose recording is already in progress")
        if self.node.is_planning or self.node.trajectory_executor.is_executing:
            raise ValueError("Planning, execution or settling is in progress")

    def _reload(self):
        candidate = PoseRecorder(self.recorder.poses_file)
        if candidate.poses_file.exists():
            candidate.load_from_file(self.environment)
        self.recorder = candidate

    def record_callback(self, request, response):
        """! @brief Start a bounded stationary capture; completion is published."""
        try:
            self._require_idle()
            name = self._name()
            self._reload()
            overwrite = self.node.get_parameter("overwrite").value
            if name in self.recorder.poses and not overwrite:
                raise ValueError(f"Record already exists: {name}")
            self.capture_name = name
            self.capture_overwrite = overwrite
            self.capture_deadline = time.monotonic() + 5.0
            self.last_sequence = self.node.joint_state_sequence
            self.last_stamp = None
            self.previous_positions = None
            self.stable_count = 0
            self.snapshot = None
            self.node.is_recording = True
            self.capture_timer = self.node.create_timer(0.1, self._capture_tick)
            self._publish("record", "waiting", "Waiting for settled feedback", name=name)
            response.success = True
            response.message = "Recording requested; final result on /pose_recording/status"
        except (OSError, ValueError, TypeError, OverflowError) as error:
            response.success = False
            response.message = str(error)
        return response

    def _stop_capture(self):
        if self.capture_timer is not None:
            self.capture_timer.cancel()
            self.node.destroy_timer(self.capture_timer)
            self.capture_timer = None
        self.node.is_recording = False

    def _observe_feedback(self):
        state = self.node.current_joint_state
        if state is None or self.node.joint_state_sequence == self.last_sequence:
            return
        self.last_sequence = self.node.joint_state_sequence
        stamp = Time.from_msg(state.header.stamp).nanoseconds
        if self.last_stamp is not None and stamp <= self.last_stamp:
            if stamp < self.last_stamp:
                self.previous_positions = None
                self.stable_count = 0
                self.snapshot = None
            self.last_stamp = stamp
            return
        self.last_stamp = stamp
        if len(state.name) != len(state.position) or len(set(state.name)) != len(state.name):
            raise ValueError("Invalid joint feedback arrays")
        positions = dict(zip(state.name, state.position))
        values = [positions[f"joint{i}"] for i in range(1, 7)]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Joint feedback must be finite")
        if self.previous_positions is not None:
            change = max(abs(a - b) for a, b in zip(values, self.previous_positions))
            if change <= 0.0001:
                self.stable_count += 1
            else:
                self.stable_count = 0
                self.snapshot = None
        self.previous_positions = values
        if self.stable_count >= 3 and self.snapshot is None:
            self.snapshot = copy.deepcopy(state)

    def _capture_tick(self):
        try:
            if time.monotonic() >= self.capture_deadline:
                raise TimeoutError("Timed out waiting for settled, time-matched feedback")
            if not self.node.feedback_is_fresh():
                self.previous_positions = None
                self.snapshot = None
                self.stable_count = 0
                return
            self._observe_feedback()
            if self.snapshot is None:
                return
            try:
                transform = self.node.tf_buffer.lookup_transform(
                    "base_link", "link6", Time.from_msg(self.snapshot.header.stamp)
                )
            except TransformException:
                return
            pose = PoseStamped()
            pose.header = copy.deepcopy(transform.header)
            pose.pose.position.x = transform.transform.translation.x
            pose.pose.position.y = transform.transform.translation.y
            pose.pose.position.z = transform.transform.translation.z
            pose.pose.orientation = copy.deepcopy(transform.transform.rotation)
            previous = copy.deepcopy(self.recorder.poses)
            try:
                self.recorder.record_pose(
                    self.capture_name, self.snapshot, pose, self.environment,
                    overwrite=self.capture_overwrite,
                )
                self.recorder.save_to_file()
            except Exception:
                self.recorder.poses = previous
                raise
            self.loaded_pose = None
            self.node.invalidate_plan()
            self._stop_capture()
            self._publish("record", "saved", "Pose saved to file", name=self.capture_name)
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
            self._stop_capture()
            self._publish("record", "failed", str(error), name=self.capture_name)

    def cancel_callback(self, request, response):
        """! @brief Cancel capture without changing the file or moving the arm."""
        response.success = self.node.is_recording
        response.message = "Recording canceled" if response.success else "No recording in progress"
        if response.success:
            self._stop_capture()
            self._publish("record", "canceled", response.message)
        return response

    def load_callback(self, request, response):
        """! @brief Load and select a named pose without planning or execution."""
        try:
            self._require_idle()
            self.loaded_pose = None
            self.node.invalidate_plan()
            self._reload()
            name = self._name()
            self.loaded_pose = self.recorder.get_pose(name)
            response.success = True
            response.message = json.dumps(self.loaded_pose, ensure_ascii=False)
            self._publish("load", "loaded", "Pose loaded; no motion requested", record=self.loaded_pose)
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
            response.success = False
            response.message = str(error)
        return response

    def list_callback(self, request, response):
        """! @brief List the currently loaded record names."""
        response.success = True
        response.message = json.dumps(sorted(self.recorder.poses), ensure_ascii=False)
        return response

    def delete_callback(self, request, response):
        """! @brief Delete and persist one record; invalidate pending return targets."""
        try:
            self._require_idle()
            self._reload()
            name = self._name()
            previous = copy.deepcopy(self.recorder.poses)
            try:
                self.recorder.delete_pose(name)
                self.recorder.save_to_file()
            except Exception:
                self.recorder.poses = previous
                raise
            self.loaded_pose = None
            self.node.invalidate_plan()
            response.success = True
            response.message = f"Deleted record: {name}"
            self._publish("delete", "deleted", response.message, name=name)
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
            response.success = False
            response.message = str(error)
        return response

    def return_callback(self, request, response):
        """! @brief Plan a joint-space return; a separate execution request is required."""
        try:
            self._require_idle()
            if self.loaded_pose is None:
                raise ValueError("Load a named pose before requesting return planning")
            record = self.loaded_pose
            data = record["pose_stamped"]["pose"]
            pose = PoseStamped()
            for axis in ("x", "y", "z"):
                setattr(pose.pose.position, axis, data["position"][axis])
            for axis in ("x", "y", "z", "w"):
                setattr(pose.pose.orientation, axis, data["orientation"][axis])
            response.success = self.node.request_joint_plan(
                record["joint_state"]["positions"], pose.pose, record["name"]
            )
            response.message = (
                "Return planning requested; execution remains separate" if response.success
                else "Return planning request not sent; check node logs"
            )
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
            response.success = False
            response.message = str(error)
        return response

    def _return_verified(self, name, result):
        if name is not None:
            passed = result is not None and result.get("passed", False)
            self._publish(
                "return", "verified" if passed else "failed",
                "Return verification passed" if passed else "Return verification failed",
                name=name, comparison=result,
            )

    def close(self):
        """! @brief Release a pending capture when the demo shuts down."""
        self._stop_capture()
