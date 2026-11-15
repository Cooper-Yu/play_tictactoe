from pathlib import Path
import math
import json
import tempfile

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

