from pathlib import Path
import copy
import math
import json
import tempfile
from sensor_msgs.msg import JointState
from geometry_msgs.msg import PoseStamped


class PoseRecorder:
    """!
    @brief Save and load named robot poses and joint configurations.
    """

    def __init__(self, poses_file):
        self.poses_file = Path(poses_file).expanduser()
        self.poses = {}

    def record_pose(
        self, name, joint_state, pose_stamped, environment, overwrite=False
    ):
        """!
        @brief Add a named pose and joint configuration to memory.

        @param name Unique record name.
        @param joint_state Actual joint feedback as JointState.
        @param pose_stamped Link6 pose in base_link as PoseStamped.
        @param environment Recording environment: sim or real.
        @param overwrite Whether to replace an existing named record.
        """

        if not isinstance(name, str) or not name.strip():
            raise ValueError("Record name must be a non-empty string")
        name = name.strip()

        if name in self.poses and not overwrite:
            raise ValueError(f"Record already exists: {name}")

        if environment not in ("sim", "real"):
            raise ValueError("Environment must be 'sim' or 'real'")

        if len(joint_state.name) != len(joint_state.position):
            raise ValueError("Joint names and positions must have equal lengths")

        if len(set(joint_state.name)) != len(joint_state.name):
            raise ValueError("Joint names must be unique")

        joint_positions = dict(zip(joint_state.name, joint_state.position))

        required_joints = [f"joint{i}" for i in range(1, 7)]

        if any(joint not in joint_positions for joint in required_joints):
            raise ValueError("Joint states must contain joint1 through joint6")

        arm_joint_positions = {
            joint: joint_positions[joint] for joint in required_joints
        }

        if not all(math.isfinite(angle) for angle in arm_joint_positions.values()):
            raise ValueError("Joint positions must be finite")

        if pose_stamped.header.frame_id != "base_link":
            raise ValueError("Pose frame must be 'base_link'")

        position = pose_stamped.pose.position
        orientation = pose_stamped.pose.orientation

        pose_values = (
            position.x,
            position.y,
            position.z,
            orientation.x,
            orientation.y,
            orientation.z,
            orientation.w,
        )

        if not all(math.isfinite(value) for value in pose_values):
            raise ValueError("Pose values must be finite")

        quaternion_norm = math.hypot(
            orientation.x,
            orientation.y,
            orientation.z,
            orientation.w,
        )

        if abs(quaternion_norm - 1.0) > 0.001:
            raise ValueError("Orientation quaternion must have unit length")

        record = {
            "name": name,
            "environment": environment,
            "tip_link": "link6",
            "joint_state": {
                "stamp": {
                    "sec": joint_state.header.stamp.sec,
                    "nanosec": joint_state.header.stamp.nanosec,
                },
                "positions": arm_joint_positions,
            },
            "pose_stamped": {
                "header": {
                    "stamp": {
                        "sec": pose_stamped.header.stamp.sec,
                        "nanosec": pose_stamped.header.stamp.nanosec,
                    },
                    "frame_id": pose_stamped.header.frame_id,
                },
                "pose": {
                    "position": {
                        "x": position.x,
                        "y": position.y,
                        "z": position.z,
                    },
                    "orientation": {
                        "x": orientation.x,
                        "y": orientation.y,
                        "z": orientation.z,
                        "w": orientation.w,
                    },
                },
            },
        }

        self.poses[name] = record

    def save_to_file(self):
        """!
        @brief Save all named records to the configured JSON file.
        """
        self.poses_file.parent.mkdir(parents=True, exist_ok=True)

        json_text = json.dumps(
            self.poses,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.poses_file.parent,
                prefix=f".{self.poses_file.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(json_text)

            temp_path.replace(self.poses_file)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def load_from_file(self, environment):
        """!
        @brief Load and validate records for the current environment.

        @param environment Expected environment: sim or real.
        """
        if environment not in ("sim", "real"):
            raise ValueError("Environment must be 'sim' or 'real'")

        json_text = self.poses_file.read_text(encoding="utf-8")

        records = json.loads(json_text)

        if not isinstance(records, dict):
            raise TypeError("Pose file must contain a JSON object")

        validated_recorder = PoseRecorder(self.poses_file)

        for name, record in records.items():
            if not isinstance(record, dict):
                raise TypeError(f"Record {name!r} must be a JSON object")

            if record.get("environment") != environment:
                raise ValueError(
                    f"Record {name!r} does not match environment {environment!r}"
                )

            if not name or name != name.strip():
                raise ValueError("Record names must be non-empty and trimmed")

            if record.get("name") != name:
                raise ValueError(f"Record name does not match key {name!r}")

            if record.get("tip_link") != "link6":
                raise ValueError(f"Record {name!r} must describe link6")

            joint_data = record.get("joint_state")
            if not isinstance(joint_data, dict):
                raise TypeError(f"Record {name!r} has invalid joint_state")

            positions_data = joint_data.get("positions")
            if not isinstance(positions_data, dict):
                raise TypeError(f"Record {name!r} has invalid joint positions")

            if not all(
                isinstance(angle, (int, float)) and not isinstance(angle, bool)
                for angle in positions_data.values()
            ):
                raise TypeError(f"Record {name!r} has non-numeric joint positions")

            joint_state = JointState()
            joint_state.name = list(positions_data.keys())
            joint_state.position = [
                float(angle) for angle in positions_data.values()
            ]

            stamp_data = joint_data.get("stamp")
            if not isinstance(stamp_data, dict):
                raise TypeError(f"Record {name!r} has invalid joint timestamp")

            sec = stamp_data.get("sec")
            nanosec = stamp_data.get("nanosec")

            if any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in (sec, nanosec)
            ):
                raise TypeError("Timestamp fields must be integers")

            if not -(2**31) <= sec < 2**31:
                raise ValueError("Timestamp seconds are out of range")

            if not 0 <= nanosec < 1_000_000_000:
                raise ValueError("Timestamp nanoseconds are out of range")

            joint_state.header.stamp.sec = sec
            joint_state.header.stamp.nanosec = nanosec

            pose_stamped_data = record.get("pose_stamped")
            if not isinstance(pose_stamped_data, dict):
                raise TypeError(f"Record {name!r} has invalid pose_stamped")

            header_data = pose_stamped_data.get("header")
            pose_data = pose_stamped_data.get("pose")

            if not isinstance(header_data, dict):
                raise TypeError(f"Record {name!r} has invalid pose header")

            if not isinstance(pose_data, dict):
                raise TypeError(f"Record {name!r} has invalid pose data")

            frame_id = header_data.get("frame_id")
            if not isinstance(frame_id, str):
                raise TypeError(f"Record {name!r} has invalid frame_id")

            pose_stamped = PoseStamped()
            pose_stamped.header.frame_id = frame_id

            stamp_data = header_data.get("stamp")
            if not isinstance(stamp_data, dict):
                raise TypeError(f"Record {name!r} has invalid pose timestamp")

            sec = stamp_data.get("sec")
            nanosec = stamp_data.get("nanosec")

            if any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in (sec, nanosec)
            ):
                raise TypeError("Timestamp fields must be integers")

            if not -(2**31) <= sec < 2**31:
                raise ValueError("Timestamp seconds are out of range")

            if not 0 <= nanosec < 1_000_000_000:
                raise ValueError("Timestamp nanoseconds are out of range")

            pose_stamped.header.stamp.sec = sec
            pose_stamped.header.stamp.nanosec = nanosec

            position_data = pose_data.get("position")
            orientation_data = pose_data.get("orientation")

            if not isinstance(position_data, dict):
                raise TypeError(f"Record {name!r} has invalid position")

            if not isinstance(orientation_data, dict):
                raise TypeError(f"Record {name!r} has invalid orientation")

            position_values = [
                position_data.get(axis) for axis in ("x", "y", "z")
            ]
            orientation_values = [
                orientation_data.get(axis) for axis in ("x", "y", "z", "w")
            ]

            if not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in position_values + orientation_values
            ):
                raise TypeError(f"Record {name!r} has non-numeric pose values")

            pose_stamped.pose.position.x = float(position_values[0])
            pose_stamped.pose.position.y = float(position_values[1])
            pose_stamped.pose.position.z = float(position_values[2])

            pose_stamped.pose.orientation.x = float(orientation_values[0])
            pose_stamped.pose.orientation.y = float(orientation_values[1])
            pose_stamped.pose.orientation.z = float(orientation_values[2])
            pose_stamped.pose.orientation.w = float(orientation_values[3])

            validated_recorder.record_pose(
                name, joint_state, pose_stamped, environment
            )

        self.poses = validated_recorder.poses

    def delete_pose(self, name):
        """!
        @brief Delete a named record from memory.

        @param name Name of the record to delete.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Record name must be a non-empty string")

        name = name.strip()

        if name not in self.poses:
            raise KeyError(f"Record does not exist: {name}")

        del self.poses[name]

    def get_pose(self, name):
        """!
        @brief Return an independent copy of a named record.

        @param name Name of the record to retrieve.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Record name must be a non-empty string")
        name = name.strip()
        if name not in self.poses:
            raise KeyError(f"Record does not exist: {name}")
        return copy.deepcopy(self.poses[name])
