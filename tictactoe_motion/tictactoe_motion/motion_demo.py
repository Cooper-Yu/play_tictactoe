import rclpy
from tictactoe_motion.motion_planner import MotionPlanner
import math
from std_srvs.srv import Trigger

class MotionDemo:
    """!
    @brief Coordinate the motion planning and execution demo.
    """

    def __init__(self, node):
        self.node = node
        self.demo_timer = self.node.create_timer(3.0, self.run_planning_demo)
        self.execution_service = self.node.create_service(
            Trigger,
            "/execute_planned_trajectory",
            self.execution_trigger_callback
        )
        self.state_timer = self.node.create_timer(1.0, self.report_current_state)

    def run_planning_demo(self):
        self.demo_timer.cancel()
        axis = self.node.get_parameter("axis").value
        distance = self.node.get_parameter("distance").value
        if axis not in ("x", "y", "z"):
            self.node.get_logger().warning("Invalid axis: expected 'x', 'y', or 'z'")
            return
        if not math.isfinite(distance):
            self.node.get_logger().warning("Distance must be finite")
            return
        if distance == 0.0:
            self.node.get_logger().info("Distance is zero, skipping planning")
            return
        self.node.request_plan(axis, distance)

    def execution_trigger_callback(self, request, response):
        response.success = self.node.trajectory_executor.execute_planned_trajectory(
            self.node.planned_trajectory, self.node.planned_target_pose
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
            zip(self.node.current_joint_state.name, self.node.current_joint_state.position)
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

def main(args=None):
    rclpy.init(args=args)
    node = MotionPlanner()
    demo = MotionDemo(node)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
