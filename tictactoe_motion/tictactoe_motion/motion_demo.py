import rclpy
from tictactoe_motion.motion_planner import MotionPlanner
import math
from std_srvs.srv import Trigger
from tictactoe_motion.drawing_paths import cross_path, circle_path
from tictactoe_motion.pose_recording_demo import PoseRecordingDemo


class MotionDemo:
    """!
    @brief Coordinate the motion planning and execution demo.
    """

    def __init__(self, node):
        self.node = node
        self.execution_service = self.node.create_service(
            Trigger, "/execute_planned_trajectory", self.execution_trigger_callback
        )
        period = self.node.settings["state_log_period"]
        self.state_timer = (
            self.node.create_timer(period, self.report_current_state) if period > 0 else None
        )
        self.planning_service = self.node.create_service(
            Trigger,
            "/plan_step",
            self.planning_trigger_callback
        )

        self.xy_service = node.create_service(Trigger, '/plan_xy', self.xy_callback)
        node.declare_parameter('cross_size', 0.02)
        node.declare_parameter('circle_radius', 0.01)
        self.cross_service = node.create_service(Trigger, '/plan_cross', lambda req, res: self.drawing_callback(res, 'cross'))
        self.circle_service = node.create_service(Trigger, '/plan_circle', lambda req, res: self.drawing_callback(res, 'circle'))

    def drawing_callback(self, response, shape):
        try:
            start = self.node.cartesian_planner.start_pose()
            if shape == 'cross':
                poses = cross_path(start, self.node.get_parameter('cross_size').value)
            else:
                poses = circle_path(start, self.node.get_parameter('circle_radius').value)
            response.success = self.node.cartesian_planner.request_path(poses)
        except (ValueError, TypeError) as error:
            self.node.get_logger().warning(str(error))
            if not self.node.is_planning and not self.node.is_recording and not self.node.trajectory_executor.is_executing:
                self.node.invalidate_plan()
            response.success = False
        response.message = 'Drawing plan requested; result pending' if response.success else 'Drawing request rejected; check node logs'
        return response

    def xy_callback(self, request, response):
        response.success = self.node.cartesian_planner.request_xy(
            self.node.get_parameter('dx').value, self.node.get_parameter('dy').value)
        response.message = 'Cartesian planning requested; result pending' if response.success else 'Cartesian request rejected; check node logs'
        return response

    def run_planning_demo(self):
        axis = self.node.get_parameter("axis").value
        distance = self.node.get_parameter("distance").value
        if axis not in ("x", "y", "z"):
            self.node.get_logger().warning("Invalid axis: expected 'x', 'y', or 'z'")
            return False
        if not math.isfinite(distance):
            self.node.get_logger().warning("Distance must be finite")
            return False
        if distance == 0.0:
            self.node.get_logger().info("Distance is zero, skipping planning")
            return False
        return self.node.request_plan(axis, distance)

    def execution_trigger_callback(self, request, response):
        response.success = self.node.trajectory_executor.execute_planned_trajectory(
            self.node.planned_trajectory, self.node.planned_target_pose,
            self.node.planned_target_joints, self.node.planned_record_name,
        )
        if response.success:
            response.message = "Execution requested; final result pending"
        else:
            response.message = "Execution request not sent; check node logs"
        return response

    def report_current_state(self):
        if self.node.current_joint_state is None:
            self.node.get_logger().info("Waiting for joint states")
            return
        joint_position = dict(
            zip(
                self.node.current_joint_state.name,
                self.node.current_joint_state.position,
            )
        )
        required_joints = [f"joint{i}" for i in range(1, 7)]
        if any(name not in joint_position for name in required_joints):
            self.node.get_logger().warning("Joint states are incomplete")
            return
        joint_summary = ", ".join(
            f"{name}={joint_position[name]:.4f}" for name in required_joints
        )
        self.node.get_logger().info(f"Joint positions (rad): {joint_summary}")
        transform = self.node.get_current_pose()
        if transform is None:
            return

        translation = transform.transform.translation
        orientation = transform.transform.rotation

        self.node.get_logger().info(
            f"link6 position (m): "
            f"x={translation.x:.4f}, "
            f"y={translation.y:.4f}, "
            f"z={translation.z:.4f}"
        )

        self.node.get_logger().info(
            f"link6 orientation (quaternion xyzw): "
            f"x={orientation.x:.4f}, "
            f"y={orientation.y:.4f}, "
            f"z={orientation.z:.4f}, "
            f"w={orientation.w:.4f}"
        )

    def planning_trigger_callback(self, request, response):
        response.success = self.run_planning_demo()
        if response.success:
            response.message = "Planning requested; final result pending"
        else:
            response.message = "Planning request not sent; check node logs"
        return response


def main(args=None):
    rclpy.init(args=args)
    node = MotionPlanner()
    recording_demo = None
    try:
        _motion_demo = MotionDemo(node)
        recording_demo = PoseRecordingDemo(node)
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if recording_demo is not None:
            recording_demo.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
